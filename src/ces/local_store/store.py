"""LocalProjectStore — SQLite persistence for local-first CES projects.

The store owns the on-disk schema, runs in-app migrations on startup, and
exposes typed query helpers consumed by the repository adapters in
:mod:`ces.local_store.repositories`. Higher-level services depend on the
adapters, not on the store directly.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

try:  # pragma: no cover - Windows fallback is exercised by the no-op branch.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

from ces.brownfield.records import LegacyBehaviorRecord
from ces.control.models.audit_entry_record import AuditEntryRecord
from ces.control.services.evidence_integrity import compute_reviewed_evidence_hash
from ces.execution.secrets import scrub_secrets_from_text
from ces.harness_evolution.manifest_io import manifest_to_stable_json
from ces.harness_evolution.memory import HarnessMemoryLesson
from ces.harness_evolution.models import HarnessChangeManifest, HarnessChangeVerdict
from ces.intent_gate.models import IntentGatePreflight, SpecificationLedger
from ces.local_store.codecs import (
    row_to_approval,
    row_to_audit_entry,
    row_to_builder_brief,
    row_to_builder_session,
    row_to_legacy_behavior,
    row_to_manifest_record,
    row_to_runtime_execution,
)
from ces.local_store.queries import (
    fetch_active_manifests,
    fetch_all_manifests,
    fetch_approval,
    fetch_audit,
    fetch_builder_brief,
    fetch_builder_session,
    fetch_evidence_by_manifest,
    fetch_evidence_by_packet,
    fetch_latest_builder_brief,
    fetch_latest_builder_session,
    fetch_latest_evidence_packet,
    fetch_legacy_behavior,
    fetch_legacy_behaviors_by_system,
    fetch_manifest,
    fetch_pending_legacy_behaviors,
    fetch_promoted_prl_items,
    fetch_runtime_execution,
)
from ces.local_store.records import (
    LocalApprovalRecord,
    LocalBrownfieldSessionSummary,
    LocalBuilderBriefRecord,
    LocalBuilderSessionRecord,
    LocalBuilderSessionSnapshot,
    LocalHarnessChangeRecord,
    LocalHarnessChangeVerdictRecord,
    LocalHarnessMemoryLessonRecord,
    LocalIntentGatePreflightRecord,
    LocalManifestRow,
    LocalRuntimeExecutionRecord,
)
from ces.local_store.schema import initialize_schema
from ces.local_store.writes import (
    insert_builder_session,
    update_builder_session,
)

if TYPE_CHECKING:
    from ces.control.models.manifest import TaskManifest
    from ces.harness.services.findings_aggregator import AggregatedReview

_UNSET = object()
SQLITE_BUSY_TIMEOUT_MS = 30_000
LOCAL_STORE_LOCK_FILENAME = "state.db.lock"


def _configure_sqlite_connection(conn: sqlite3.Connection) -> None:
    """Apply local-first concurrency settings to every store connection."""
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    # journal_mode=WAL can transiently need an exclusive lock while several
    # CLI-style processes open the same fresh DB at once. Retry explicitly so
    # latest dependency/SQLite builds do not fail before busy_timeout applies.
    last_error: sqlite3.OperationalError | None = None
    for _attempt in range(20):
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            last_error = None
            break
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower():
                raise
            last_error = exc
            time.sleep(0.05)
    if last_error is not None:
        raise last_error
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")


def _row_to_harness_change(row: sqlite3.Row) -> LocalHarnessChangeRecord:
    manifest = HarnessChangeManifest.model_validate(json.loads(row["manifest_json"]))
    return LocalHarnessChangeRecord(
        change_id=row["change_id"],
        component_type=row["component_type"],
        title=row["title"],
        status=row["status"],
        manifest=manifest,
        manifest_hash=row["manifest_hash"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_harness_change_verdict(row: sqlite3.Row) -> LocalHarnessChangeVerdictRecord:
    verdict = HarnessChangeVerdict.model_validate(json.loads(row["verdict_json"]))
    return LocalHarnessChangeVerdictRecord(
        id=row["id"],
        change_id=row["change_id"],
        verdict=row["verdict"],
        verdict_payload=verdict,
        created_at=row["created_at"],
    )


def _row_to_harness_memory_lesson(row: sqlite3.Row) -> LocalHarnessMemoryLessonRecord:
    lesson = HarnessMemoryLesson.model_validate(json.loads(row["lesson_json"]))
    return LocalHarnessMemoryLessonRecord(
        lesson_id=row["lesson_id"],
        kind=row["kind"],
        title=row["title"],
        status=row["status"],
        lesson=lesson,
        content_hash=row["content_hash"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_intent_gate_preflight(row: sqlite3.Row) -> LocalIntentGatePreflightRecord:
    ledger = SpecificationLedger.model_validate_json(row["ledger_json"])
    created_at = datetime.fromisoformat(row["created_at"])
    preflight = IntentGatePreflight(
        preflight_id=row["preflight_id"],
        decision=row["decision"],
        safe_next_step=row["safe_next_step"],
        created_at=created_at,
        content_hash=row["content_hash"],
        ledger=ledger,
    )
    return LocalIntentGatePreflightRecord(
        record_id=row["id"],
        preflight=preflight,
        request=row["request"],
        brief_id=row["brief_id"],
        session_id=row["session_id"],
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return str(value)


class LocalProjectStore:
    """Persist CES state in `.ces/state.db` for local-first projects."""

    def __init__(self, db_path: Path, project_id: str = "default") -> None:
        self._db_path = Path(db_path)
        self._lock_path = self._db_path.with_name(LOCAL_STORE_LOCK_FILENAME)
        self._project_id = project_id
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        # One pooled connection per store instance. CES CLI invocations are
        # single-threaded; opening per-call would pay journal-init latency on
        # every read. ``check_same_thread=False`` is intentional — the
        # connection is owned exclusively by this instance and access patterns
        # are sequential within the async event loop.
        self._conn = sqlite3.connect(
            self._db_path,
            timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        _configure_sqlite_connection(self._conn)
        self.initialize()
        # Tighten file perms after SQLite has created the file. Wrapped in
        # try/except so Windows (which doesn't honour POSIX bits the same way)
        # and unusual filesystems don't break local projects.
        try:
            os.chmod(self._db_path.parent, 0o700)
            if self._db_path.exists():
                os.chmod(self._db_path, 0o600)
            if self._lock_path.exists():
                os.chmod(self._lock_path, 0o600)
        except OSError:
            pass

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # ``with self._conn:`` invokes sqlite3's transaction-context-manager
        # protocol — auto-commits on clean exit, rolls back on exception. The
        # connection itself is reused across calls for cache-warmth.
        with self._process_lock(), self._conn:
            yield self._conn

    @contextmanager
    def _process_lock(self) -> Iterator[None]:
        """Serialize local store transactions across concurrent CES processes."""
        if fcntl is None:
            yield
            return
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                with suppress(OSError):
                    os.chmod(self._lock_path, 0o600)
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def close(self) -> None:
        """Close the pooled SQLite connection. Safe to call multiple times."""
        try:
            self._conn.close()
        except sqlite3.ProgrammingError:
            # Already closed — no-op for idempotence.
            pass

    def __enter__(self) -> LocalProjectStore:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()

    def __del__(self) -> None:
        with suppress(Exception):
            self.close()

    def initialize(self) -> None:
        with self._connect() as conn:
            initialize_schema(conn)

    def save_project_settings(self, settings: dict[str, Any]) -> None:
        with self._connect() as conn:
            for key, value in settings.items():
                conn.execute(
                    "INSERT OR REPLACE INTO project_settings(key, value) VALUES(?, ?)",
                    (key, json.dumps(value)),
                )

    def get_project_settings(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM project_settings").fetchall()
        return {row["key"]: json.loads(row["value"]) for row in rows}

    def save_intent_gate_preflight(
        self,
        preflight: IntentGatePreflight,
        *,
        brief_id: str | None = None,
        session_id: str | None = None,
        request: str | None = None,
    ) -> LocalIntentGatePreflightRecord:
        ledger_json = json.dumps(preflight.ledger.model_dump(mode="json"), sort_keys=True)
        record_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO intent_gate_preflights(
                    id, preflight_id, project_id, decision, safe_next_step, content_hash,
                    created_at, ledger_json, request, brief_id, session_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    preflight.preflight_id,
                    self._project_id,
                    preflight.decision,
                    preflight.safe_next_step,
                    preflight.content_hash,
                    preflight.created_at.isoformat(),
                    ledger_json,
                    request,
                    brief_id,
                    session_id,
                ),
            )
        record = self._get_intent_gate_preflight_record(record_id)
        if record is None:
            raise RuntimeError("failed to persist Intent Gate preflight")
        return record

    def _get_intent_gate_preflight_record(self, record_id: str) -> LocalIntentGatePreflightRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, preflight_id, decision, safe_next_step, content_hash, created_at,
                       ledger_json, request, brief_id, session_id
                FROM intent_gate_preflights
                WHERE project_id = ? AND id = ?
                """,
                (self._project_id, record_id),
            ).fetchone()
        return _row_to_intent_gate_preflight(row) if row else None

    def get_intent_gate_preflight(self, preflight_id: str) -> LocalIntentGatePreflightRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, preflight_id, decision, safe_next_step, content_hash, created_at,
                       ledger_json, request, brief_id, session_id
                FROM intent_gate_preflights
                WHERE project_id = ? AND preflight_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (self._project_id, preflight_id),
            ).fetchone()
        return _row_to_intent_gate_preflight(row) if row else None

    def get_latest_intent_gate_preflight(self) -> LocalIntentGatePreflightRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, preflight_id, decision, safe_next_step, content_hash, created_at,
                       ledger_json, request, brief_id, session_id
                FROM intent_gate_preflights
                WHERE project_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (self._project_id,),
            ).fetchone()
        return _row_to_intent_gate_preflight(row) if row else None

    def get_intent_gate_preflight_for_brief(self, brief_id: str) -> LocalIntentGatePreflightRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, preflight_id, decision, safe_next_step, content_hash, created_at,
                       ledger_json, request, brief_id, session_id
                FROM intent_gate_preflights
                WHERE project_id = ? AND brief_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (self._project_id, brief_id),
            ).fetchone()
        return _row_to_intent_gate_preflight(row) if row else None

    def get_intent_gate_preflight_for_session(self, session_id: str) -> LocalIntentGatePreflightRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, preflight_id, decision, safe_next_step, content_hash, created_at,
                       ledger_json, request, brief_id, session_id
                FROM intent_gate_preflights
                WHERE project_id = ? AND session_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (self._project_id, session_id),
            ).fetchone()
        return _row_to_intent_gate_preflight(row) if row else None

    def save_harness_change(self, manifest: HarnessChangeManifest) -> LocalHarnessChangeRecord:
        """Persist or update a local harness change manifest."""

        manifest_json = manifest_to_stable_json(manifest)
        manifest_hash = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        created_at = manifest.created_at.isoformat()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT created_at FROM harness_changes WHERE project_id = ? AND change_id = ?",
                (self._project_id, manifest.change_id),
            ).fetchone()
            conn.execute(
                """
                INSERT OR REPLACE INTO harness_changes(
                    change_id, project_id, component_type, title, status,
                    manifest_json, manifest_hash, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest.change_id,
                    self._project_id,
                    manifest.component_type.value,
                    manifest.title,
                    manifest.status,
                    manifest_json,
                    manifest_hash,
                    existing["created_at"] if existing else created_at,
                    now,
                ),
            )
        record = self.get_harness_change(manifest.change_id)
        if record is None:
            raise RuntimeError("failed to persist harness change")
        return record

    def get_harness_change(self, change_id: str) -> LocalHarnessChangeRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT change_id, component_type, title, status, manifest_json,
                       manifest_hash, created_at, updated_at
                FROM harness_changes
                WHERE project_id = ? AND change_id = ?
                """,
                (self._project_id, change_id),
            ).fetchone()
        return _row_to_harness_change(row) if row else None

    def list_harness_changes(self, *, status: str | None = None) -> list[LocalHarnessChangeRecord]:
        with self._connect() as conn:
            if status is None:
                rows = conn.execute(
                    """
                    SELECT change_id, component_type, title, status, manifest_json,
                           manifest_hash, created_at, updated_at
                    FROM harness_changes
                    WHERE project_id = ?
                    ORDER BY updated_at DESC, change_id ASC
                    """,
                    (self._project_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT change_id, component_type, title, status, manifest_json,
                           manifest_hash, created_at, updated_at
                    FROM harness_changes
                    WHERE project_id = ? AND status = ?
                    ORDER BY updated_at DESC, change_id ASC
                    """,
                    (self._project_id, status),
                ).fetchall()
        return [_row_to_harness_change(row) for row in rows]

    def save_harness_change_verdict(self, verdict: HarnessChangeVerdict) -> LocalHarnessChangeVerdictRecord:
        if self.get_harness_change(verdict.change_id) is None:
            raise ValueError(f"unknown harness change: {verdict.change_id}")
        verdict_json = json.dumps(verdict.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        verdict_id = f"hcv-{uuid.uuid4().hex[:12]}"
        created_at = verdict.created_at.isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO harness_change_verdicts(
                    id, project_id, change_id, verdict, verdict_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (verdict_id, self._project_id, verdict.change_id, verdict.verdict, verdict_json, created_at),
            )
            row = conn.execute(
                """
                SELECT id, change_id, verdict, verdict_json, created_at
                FROM harness_change_verdicts
                WHERE project_id = ? AND id = ?
                """,
                (self._project_id, verdict_id),
            ).fetchone()
        if row is None:
            raise RuntimeError("failed to persist harness change verdict")
        return _row_to_harness_change_verdict(row)

    def list_harness_change_verdicts(self, change_id: str) -> list[LocalHarnessChangeVerdictRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, change_id, verdict, verdict_json, created_at
                FROM harness_change_verdicts
                WHERE project_id = ? AND change_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (self._project_id, change_id),
            ).fetchall()
        return [_row_to_harness_change_verdict(row) for row in rows]

    def save_harness_memory_lesson(self, lesson: HarnessMemoryLesson) -> LocalHarnessMemoryLessonRecord:
        """Persist or update a local harness memory lesson."""

        now = datetime.now(timezone.utc).isoformat()
        created_at = lesson.created_at.isoformat()
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT created_at, status
                FROM harness_memory_lessons
                WHERE project_id = ? AND lesson_id = ?
                """,
                (self._project_id, lesson.lesson_id),
            ).fetchone()
            persisted_lesson = lesson
            if existing is not None and existing["status"] == "active" and lesson.status == "draft":
                persisted_lesson = lesson.model_copy(update={"status": "active"})
            lesson_json = json.dumps(persisted_lesson.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
            conn.execute(
                """
                INSERT OR REPLACE INTO harness_memory_lessons(
                    lesson_id, project_id, kind, title, status, lesson_json,
                    content_hash, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    persisted_lesson.lesson_id,
                    self._project_id,
                    persisted_lesson.kind,
                    persisted_lesson.title,
                    persisted_lesson.status,
                    lesson_json,
                    persisted_lesson.content_hash,
                    existing["created_at"] if existing else created_at,
                    now,
                ),
            )
        record = self.get_harness_memory_lesson(str(lesson.lesson_id))
        if record is None:
            raise RuntimeError("failed to persist harness memory lesson")
        return record

    def get_harness_memory_lesson(self, lesson_id: str) -> LocalHarnessMemoryLessonRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT lesson_id, kind, title, status, lesson_json, content_hash, created_at, updated_at
                FROM harness_memory_lessons
                WHERE project_id = ? AND lesson_id = ?
                """,
                (self._project_id, lesson_id),
            ).fetchone()
        return _row_to_harness_memory_lesson(row) if row else None

    def list_harness_memory_lessons(self, *, status: str | None = None) -> list[LocalHarnessMemoryLessonRecord]:
        with self._connect() as conn:
            if status is None:
                rows = conn.execute(
                    """
                    SELECT lesson_id, kind, title, status, lesson_json, content_hash, created_at, updated_at
                    FROM harness_memory_lessons
                    WHERE project_id = ?
                    ORDER BY updated_at DESC, lesson_id ASC
                    """,
                    (self._project_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT lesson_id, kind, title, status, lesson_json, content_hash, created_at, updated_at
                    FROM harness_memory_lessons
                    WHERE project_id = ? AND status = ?
                    ORDER BY updated_at DESC, lesson_id ASC
                    """,
                    (self._project_id, status),
                ).fetchall()
        return [_row_to_harness_memory_lesson(row) for row in rows]

    def activate_harness_memory_lesson(self, lesson_id: str) -> LocalHarnessMemoryLessonRecord | None:
        record = self.get_harness_memory_lesson(lesson_id)
        if record is None:
            return None
        lesson = record.lesson.model_copy(update={"status": "active"})
        return self.save_harness_memory_lesson(lesson)

    def archive_harness_memory_lesson(self, lesson_id: str) -> LocalHarnessMemoryLessonRecord | None:
        record = self.get_harness_memory_lesson(lesson_id)
        if record is None:
            return None
        lesson = record.lesson.model_copy(update={"status": "archived"})
        return self.save_harness_memory_lesson(lesson)

    def save_builder_brief(
        self,
        *,
        request: str,
        project_mode: str,
        constraints: list[str],
        acceptance_criteria: list[str],
        must_not_break: list[str],
        open_questions: dict[str, Any],
        source_of_truth: str = "",
        critical_flows: list[str] | None = None,
        manifest_id: str | None = None,
        evidence_packet_id: str | None = None,
        prl_draft_path: str | None = None,
    ) -> str:
        brief_id = f"BB-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO builder_briefs(
                    brief_id, project_id, request, project_mode, constraints,
                    acceptance_criteria, must_not_break, open_questions,
                    source_of_truth, critical_flows, manifest_id, evidence_packet_id,
                    prl_draft_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    brief_id,
                    self._project_id,
                    request,
                    project_mode,
                    json.dumps(constraints),
                    json.dumps(acceptance_criteria),
                    json.dumps(must_not_break),
                    json.dumps(open_questions),
                    source_of_truth,
                    json.dumps(critical_flows or []),
                    manifest_id,
                    evidence_packet_id,
                    prl_draft_path,
                    now,
                    now,
                ),
            )
        return brief_id

    def update_builder_brief_artifacts(
        self,
        brief_id: str,
        *,
        manifest_id: str | None = None,
        evidence_packet_id: str | None = None,
        prl_draft_path: str | None = None,
    ) -> None:
        current = self.get_builder_brief(brief_id)
        if current is None:
            return
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE builder_briefs
                SET manifest_id = ?, evidence_packet_id = ?, prl_draft_path = ?, updated_at = ?
                WHERE brief_id = ? AND project_id = ?
                """,
                (
                    manifest_id or current.manifest_id,
                    evidence_packet_id or current.evidence_packet_id,
                    prl_draft_path or current.prl_draft_path,
                    datetime.now(timezone.utc).isoformat(),
                    brief_id,
                    self._project_id,
                ),
            )

    def get_builder_brief(self, brief_id: str) -> LocalBuilderBriefRecord | None:
        with self._connect() as conn:
            row = fetch_builder_brief(conn, self._project_id, brief_id)
        return row_to_builder_brief(row) if row else None

    def get_latest_builder_brief(self) -> LocalBuilderBriefRecord | None:
        with self._connect() as conn:
            row = fetch_latest_builder_brief(conn, self._project_id)
        return row_to_builder_brief(row) if row else None

    def save_builder_session(
        self,
        *,
        brief_id: str | None,
        request: str,
        project_mode: str,
        stage: str,
        next_action: str,
        last_action: str,
        recovery_reason: str | None = None,
        last_error: str | None = None,
        attempt_count: int = 0,
        manifest_id: str | None = None,
        runtime_manifest_id: str | None = None,
        evidence_packet_id: str | None = None,
        approval_manifest_id: str | None = None,
        source_of_truth: str = "",
        critical_flows: list[str] | None = None,
        brownfield_review_state: dict[str, Any] | None = None,
        brownfield_entry_ids: list[str] | None = None,
        brownfield_reviewed_count: int = 0,
        brownfield_remaining_count: int = 0,
    ) -> str:
        session_id = f"BS-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            insert_builder_session(
                conn,
                project_id=self._project_id,
                session_id=session_id,
                brief_id=brief_id,
                request=request,
                project_mode=project_mode,
                stage=stage,
                next_action=next_action,
                last_action=last_action,
                recovery_reason=recovery_reason,
                last_error=last_error,
                attempt_count=attempt_count,
                manifest_id=manifest_id,
                runtime_manifest_id=runtime_manifest_id,
                evidence_packet_id=evidence_packet_id,
                approval_manifest_id=approval_manifest_id,
                source_of_truth=source_of_truth,
                critical_flows=critical_flows,
                brownfield_review_state=brownfield_review_state,
                brownfield_entry_ids=brownfield_entry_ids,
                brownfield_reviewed_count=brownfield_reviewed_count,
                brownfield_remaining_count=brownfield_remaining_count,
                now=now,
            )
        return session_id

    def update_builder_session(
        self,
        session_id: str,
        *,
        stage: str | object = _UNSET,
        next_action: str | None | object = _UNSET,
        last_action: str | None | object = _UNSET,
        recovery_reason: str | None | object = _UNSET,
        last_error: str | None | object = _UNSET,
        attempt_count: int | object = _UNSET,
        manifest_id: str | None | object = _UNSET,
        runtime_manifest_id: str | None | object = _UNSET,
        evidence_packet_id: str | None | object = _UNSET,
        approval_manifest_id: str | None | object = _UNSET,
        brownfield_review_state: dict[str, Any] | None | object = _UNSET,
        brownfield_entry_ids: list[str] | None | object = _UNSET,
        brownfield_reviewed_count: int | object = _UNSET,
        brownfield_remaining_count: int | object = _UNSET,
    ) -> LocalBuilderSessionRecord | None:
        current = self.get_builder_session(session_id)
        if current is None:
            return None
        with self._connect() as conn:
            update_builder_session(
                conn,
                project_id=self._project_id,
                session_id=session_id,
                stage=current.stage if stage is _UNSET else stage,
                next_action=current.next_action if next_action is _UNSET else next_action,
                last_action=current.last_action if last_action is _UNSET else last_action,
                recovery_reason=current.recovery_reason if recovery_reason is _UNSET else recovery_reason,
                last_error=current.last_error if last_error is _UNSET else last_error,
                attempt_count=current.attempt_count if attempt_count is _UNSET else attempt_count,
                manifest_id=current.manifest_id if manifest_id is _UNSET else manifest_id,
                runtime_manifest_id=(
                    current.runtime_manifest_id if runtime_manifest_id is _UNSET else runtime_manifest_id
                ),
                evidence_packet_id=(current.evidence_packet_id if evidence_packet_id is _UNSET else evidence_packet_id),
                approval_manifest_id=(
                    current.approval_manifest_id if approval_manifest_id is _UNSET else approval_manifest_id
                ),
                brownfield_review_state=(
                    current.brownfield_review_state if brownfield_review_state is _UNSET else brownfield_review_state
                ),
                brownfield_entry_ids=(
                    current.brownfield_entry_ids if brownfield_entry_ids is _UNSET else brownfield_entry_ids
                ),
                brownfield_reviewed_count=(
                    current.brownfield_reviewed_count
                    if brownfield_reviewed_count is _UNSET
                    else brownfield_reviewed_count
                ),
                brownfield_remaining_count=(
                    current.brownfield_remaining_count
                    if brownfield_remaining_count is _UNSET
                    else brownfield_remaining_count
                ),
                now=datetime.now(timezone.utc).isoformat(),
            )
        return self.get_builder_session(session_id)

    def get_builder_session(self, session_id: str) -> LocalBuilderSessionRecord | None:
        with self._connect() as conn:
            row = fetch_builder_session(conn, self._project_id, session_id)
        return row_to_builder_session(row) if row else None

    def get_latest_builder_session(self) -> LocalBuilderSessionRecord | None:
        with self._connect() as conn:
            row = fetch_latest_builder_session(conn, self._project_id)
        return row_to_builder_session(row) if row else None

    def ensure_latest_builder_session(self) -> LocalBuilderSessionRecord | None:
        latest = self.get_latest_builder_session()
        if latest is not None:
            return latest
        brief = self.get_latest_builder_brief()
        if brief is None:
            return None
        stage = "awaiting_review" if brief.evidence_packet_id else "ready_to_run"
        next_action = "review_evidence" if brief.evidence_packet_id else "run_continue"
        session_id = self.save_builder_session(
            brief_id=brief.brief_id,
            request=brief.request,
            project_mode=brief.project_mode,
            stage=stage,
            next_action=next_action,
            last_action="legacy_brief_backfill",
            manifest_id=brief.manifest_id,
            runtime_manifest_id=brief.manifest_id,
            evidence_packet_id=brief.evidence_packet_id,
            source_of_truth=brief.source_of_truth,
            critical_flows=brief.critical_flows,
            brownfield_review_state=None,
            brownfield_entry_ids=[],
            brownfield_reviewed_count=0,
            brownfield_remaining_count=0,
        )
        return self.get_builder_session(session_id)

    def save_manifest(self, manifest: TaskManifest) -> None:
        now = datetime.now(timezone.utc).isoformat()
        content = manifest.model_dump(mode="json")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO manifests(
                    manifest_id, project_id, description, risk_tier,
                    behavior_confidence, change_class, status, workflow_state,
                    content_hash, expires_at, created_at, updated_at, content
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest.manifest_id,
                    self._project_id,
                    manifest.description,
                    manifest.risk_tier.value,
                    manifest.behavior_confidence.value,
                    manifest.change_class.value,
                    manifest.status.value,
                    manifest.workflow_state.value,
                    manifest.content_hash,
                    manifest.expires_at.isoformat(),
                    manifest.created_at.isoformat(),
                    now,
                    json.dumps(content, default=_json_default),
                ),
            )

    def get_manifest_row(self, manifest_id: str) -> LocalManifestRow | None:
        with self._connect() as conn:
            row = fetch_manifest(conn, self._project_id, manifest_id)
        if row is None:
            return None
        return row_to_manifest_record(row)

    def get_active_manifest_rows(self) -> list[LocalManifestRow]:
        with self._connect() as conn:
            rows = fetch_active_manifests(conn, self._project_id)
        return [row_to_manifest_record(row) for row in rows]

    def get_all_manifest_rows(self) -> list[LocalManifestRow]:
        """Return every stored manifest row regardless of workflow state.

        Unlike ``get_active_manifest_rows``, this includes terminal states
        (merged / deployed / rejected / expired / failed / cancelled). Callers
        that need full history — notably spec tree rendering and
        ``ces spec reconcile`` — must not filter out terminal manifests, or
        they misclassify already-shipped stories as "added" on the next run.
        """
        with self._connect() as conn:
            rows = fetch_all_manifests(conn, self._project_id)
        return [row_to_manifest_record(row) for row in rows]

    def update_manifest_workflow_state(self, manifest_id: str, workflow_state: str) -> LocalManifestRow | None:
        """Update only a manifest workflow state, preserving full manifest content."""
        current = self.get_manifest_row(manifest_id)
        if current is None:
            return None
        content = dict(current.content or {})
        content["workflow_state"] = workflow_state
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE manifests
                SET workflow_state = ?, content = ?, updated_at = ?
                WHERE manifest_id = ? AND project_id = ?
                """,
                (
                    workflow_state,
                    json.dumps(content, default=_json_default),
                    datetime.now(timezone.utc).isoformat(),
                    manifest_id,
                    self._project_id,
                ),
            )
        return self.get_manifest_row(manifest_id)

    def save_runtime_execution(self, manifest_id: str, execution: dict[str, Any]) -> None:
        # Scrub any stray secrets (API keys, env assignments) out of subprocess
        # output before persisting. Without this, an agent that reads `.env` or
        # `~/.aws/credentials` and echoes it ends up with those secrets stored
        # in `.ces/state.db` and subsequently shared in evidence packets.
        scrubbed_stdout = scrub_secrets_from_text(execution["stdout"])
        scrubbed_stderr = scrub_secrets_from_text(execution["stderr"])
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO runtime_executions(
                    manifest_id, project_id, runtime_name, runtime_version,
                    reported_model, invocation_ref, exit_code, stdout, stderr,
                    duration_seconds, transcript_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest_id,
                    self._project_id,
                    execution["runtime_name"],
                    execution["runtime_version"],
                    execution.get("reported_model"),
                    execution["invocation_ref"],
                    execution["exit_code"],
                    scrubbed_stdout,
                    scrubbed_stderr,
                    execution["duration_seconds"],
                    execution.get("transcript_path"),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def get_runtime_execution(self, manifest_id: str) -> LocalRuntimeExecutionRecord | None:
        with self._connect() as conn:
            row = fetch_runtime_execution(conn, self._project_id, manifest_id)
        if row is None:
            return None
        return row_to_runtime_execution(row)

    def save_evidence(
        self,
        manifest_id: str,
        *,
        packet_id: str,
        summary: str,
        challenge: str,
        triage_color: str,
        content: dict[str, Any],
    ) -> None:
        persisted_content = dict(content)
        persisted_content.setdefault("manifest_id", manifest_id)
        persisted_content.setdefault("packet_id", packet_id)
        persisted_content.setdefault("summary", summary)
        persisted_content.setdefault("challenge", challenge)
        persisted_content.setdefault("triage_color", triage_color)
        # Hash the exact JSON-compatible payload we persist. This keeps merge-time
        # evidence integrity stable after SQLite JSON round-trips convert enums,
        # paths, datetimes, and Pydantic models into primitive values.
        persisted_content = json.loads(json.dumps(persisted_content, default=_json_default))
        persisted_content["reviewed_evidence_hash"] = compute_reviewed_evidence_hash(persisted_content)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO evidence_packets(
                    manifest_id, project_id, packet_id, summary, challenge,
                    triage_color, content, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest_id,
                    self._project_id,
                    packet_id,
                    summary,
                    challenge,
                    triage_color,
                    json.dumps(persisted_content, default=_json_default),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def get_evidence(self, manifest_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = fetch_evidence_by_manifest(conn, self._project_id, manifest_id)
        if row is None:
            return None
        data = json.loads(row["content"])
        data.update(
            {
                "packet_id": row["packet_id"],
                "summary": row["summary"],
                "challenge": row["challenge"],
                "triage_color": row["triage_color"],
            }
        )
        return data

    def get_evidence_by_packet_id(self, packet_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = fetch_evidence_by_packet(conn, self._project_id, packet_id)
        if row is None:
            return None
        data = json.loads(row["content"])
        data.update(
            {
                "manifest_id": row["manifest_id"],
                "packet_id": row["packet_id"],
                "summary": row["summary"],
                "challenge": row["challenge"],
                "triage_color": row["triage_color"],
            }
        )
        return data

    def get_latest_evidence_packet(self) -> dict[str, Any] | None:
        """Return the latest persisted evidence packet for this project."""
        with self._connect() as conn:
            row = fetch_latest_evidence_packet(conn, self._project_id)
        if row is None:
            return None
        data = json.loads(row["content"])
        data.update(
            {
                "manifest_id": row["manifest_id"],
                "packet_id": row["packet_id"],
                "summary": row["summary"],
                "challenge": row["challenge"],
                "triage_color": row["triage_color"],
            }
        )
        return data

    def save_review_findings(
        self,
        manifest_id: str,
        aggregated_review: AggregatedReview,
    ) -> None:
        """Persist AggregatedReview findings and metadata.

        Args:
            manifest_id: Manifest the review is for.
            aggregated_review: AggregatedReview from FindingsAggregator.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            # Delete previous findings for this manifest (re-review)
            conn.execute(
                "DELETE FROM review_findings WHERE manifest_id = ? AND project_id = ?",
                (manifest_id, self._project_id),
            )
            # Save each individual finding
            for finding in aggregated_review.all_findings:
                conn.execute(
                    """
                    INSERT INTO review_findings(
                        finding_id, manifest_id, project_id, reviewer_role,
                        severity, category, file_path, line_number, title,
                        description, recommendation, confidence, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        finding.finding_id,
                        manifest_id,
                        self._project_id,
                        finding.reviewer_role.value,
                        finding.severity.value,
                        finding.category,
                        finding.file_path,
                        finding.line_number,
                        finding.title,
                        finding.description,
                        finding.recommendation,
                        finding.confidence,
                        now,
                    ),
                )
            # Save aggregated metadata
            conn.execute(
                """
                INSERT OR REPLACE INTO review_aggregates(
                    manifest_id, project_id, critical_count, high_count,
                    disagreements, unanimous_zero_findings, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest_id,
                    self._project_id,
                    aggregated_review.critical_count,
                    aggregated_review.high_count,
                    json.dumps(list(aggregated_review.disagreements)),
                    1 if aggregated_review.unanimous_zero_findings else 0,
                    now,
                ),
            )

    def get_review_findings(self, manifest_id: str) -> dict[str, Any] | None:
        """Load persisted review findings for a manifest.

        Returns:
            Dict with keys: findings (list of dicts), critical_count, high_count,
            disagreements, unanimous_zero_findings. None if no review exists.
        """
        with self._connect() as conn:
            meta_row = conn.execute(
                "SELECT * FROM review_aggregates WHERE manifest_id = ? AND project_id = ?",
                (manifest_id, self._project_id),
            ).fetchone()
            if meta_row is None:
                return None
            finding_rows = conn.execute(
                """
                SELECT * FROM review_findings
                WHERE manifest_id = ? AND project_id = ?
                ORDER BY severity, confidence DESC
                """,
                (manifest_id, self._project_id),
            ).fetchall()
        return {
            "findings": [
                {
                    "finding_id": row["finding_id"],
                    "reviewer_role": row["reviewer_role"],
                    "severity": row["severity"],
                    "category": row["category"],
                    "file_path": row["file_path"],
                    "line_number": row["line_number"],
                    "title": row["title"],
                    "description": row["description"],
                    "recommendation": row["recommendation"],
                    "confidence": row["confidence"],
                }
                for row in finding_rows
            ],
            "critical_count": meta_row["critical_count"],
            "high_count": meta_row["high_count"],
            "disagreements": json.loads(meta_row["disagreements"]),
            "unanimous_zero_findings": bool(meta_row["unanimous_zero_findings"]),
        }

    def save_approval(self, manifest_id: str, *, decision: str, rationale: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO approvals(
                    manifest_id, project_id, decision, rationale, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    manifest_id,
                    self._project_id,
                    decision,
                    rationale,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def get_approval(self, manifest_id: str) -> LocalApprovalRecord | None:
        with self._connect() as conn:
            row = fetch_approval(conn, self._project_id, manifest_id)
        if row is None:
            return None
        return row_to_approval(row)

    def get_builder_session_snapshot(self, session_id: str) -> LocalBuilderSessionSnapshot | None:
        session = self.get_builder_session(session_id)
        if session is None:
            return None
        return self._resolve_builder_session_snapshot(session)

    def get_latest_builder_session_snapshot(self) -> LocalBuilderSessionSnapshot | None:
        session = self.ensure_latest_builder_session()
        if session is None:
            return None
        return self._resolve_builder_session_snapshot(session)

    def _resolve_builder_session_snapshot(self, session: LocalBuilderSessionRecord) -> LocalBuilderSessionSnapshot:
        brief = (
            self.get_builder_brief(session.brief_id)
            if session.brief_id is not None
            else self.get_latest_builder_brief()
        )
        manifest_id = session.manifest_id or session.runtime_manifest_id or getattr(brief, "manifest_id", None)
        manifest = self.get_manifest_row(manifest_id) if manifest_id else None
        runtime_execution = (
            self.get_runtime_execution(session.runtime_manifest_id or manifest_id)
            if (session.runtime_manifest_id or manifest_id)
            else None
        )
        evidence = (
            self.get_evidence(session.runtime_manifest_id or manifest_id)
            if (session.runtime_manifest_id or manifest_id)
            else None
        )
        approval = (
            self.get_approval(session.approval_manifest_id or manifest_id)
            if (session.approval_manifest_id or manifest_id)
            else None
        )
        project_mode = session.project_mode or getattr(brief, "project_mode", "unknown")
        request = session.request or getattr(brief, "request", "")
        latest_artifact = "session"
        if brief is not None:
            latest_artifact = "brief"
        if manifest is not None:
            latest_artifact = "manifest"
        if runtime_execution is not None:
            latest_artifact = "runtime_execution"
        if evidence is not None:
            latest_artifact = "evidence"
        if approval is not None:
            latest_artifact = "approval"
        brownfield = None
        if project_mode == "brownfield":
            brownfield = LocalBrownfieldSessionSummary(
                entry_ids=list(session.brownfield_entry_ids or []),
                reviewed_count=session.brownfield_reviewed_count or 0,
                remaining_count=session.brownfield_remaining_count or 0,
                checkpoint=session.brownfield_review_state,
            )
        intent_gate_preflight = None
        if session.session_id:
            intent_gate_preflight = self.get_intent_gate_preflight_for_session(session.session_id)
        if intent_gate_preflight is None and session.brief_id:
            intent_gate_preflight = self.get_intent_gate_preflight_for_brief(session.brief_id)
        return LocalBuilderSessionSnapshot(
            request=request,
            project_mode=project_mode,
            stage=session.stage,
            next_action=session.next_action,
            next_step=self._describe_snapshot_next_step(session),
            latest_activity=self._describe_snapshot_activity(session),
            latest_artifact=latest_artifact,
            is_chain_complete=all(
                (
                    brief is not None,
                    manifest is not None,
                    runtime_execution is not None,
                    evidence is not None,
                    approval is not None,
                )
            ),
            brief_only_fallback=session.last_action == "legacy_brief_backfill",
            session=session,
            brief=brief,
            manifest=manifest,
            runtime_execution=runtime_execution,
            evidence=evidence,
            approval=approval,
            brownfield=brownfield,
            intent_gate_preflight=intent_gate_preflight,
        )

    @staticmethod
    def _describe_snapshot_activity(session: LocalBuilderSessionRecord) -> str:
        mapping = {
            "brief_captured": "CES captured the builder brief and is ready to continue.",
            "execution_started": "CES started the local runtime execution.",
            "brownfield_review_in_progress": "CES paused during grouped brownfield review.",
            "brownfield_review_completed": "CES finished grouped brownfield review and returned to the main flow.",
            "evidence_ready": "CES gathered runtime evidence and synthesized a review summary.",
            "runtime_missing": "CES could not find a supported local runtime.",
            "runtime_failed": "The last runtime execution failed before CES could finish the flow.",
            "approval_recorded": "CES recorded the latest review decision.",
            "approval_rejected": "CES recorded that the last review did not pass.",
            "legacy_brief_backfill": "CES reconstructed a builder session from an older saved brief.",
        }
        return mapping.get(session.last_action, "CES has saved builder progress for this request.")

    @staticmethod
    def _describe_snapshot_next_step(session: LocalBuilderSessionRecord) -> str:
        mapping = {
            "run_continue": "Run `ces continue` to start the next execution pass.",
            "install_runtime": "Install and authenticate `codex` or `claude`, then run `ces continue`.",
            "retry_runtime": "Retry the last runtime execution with `ces continue`.",
            "review_evidence": "Review the evidence and decide whether to ship the change.",
            "review_brownfield": "Run `ces continue` to resume grouped brownfield review.",
            "answer_builder_questions": "Answer the remaining builder questions so CES can continue.",
            "start_new_session": "Start a new task with `ces build` when you're ready for the next request.",
        }
        return mapping.get(session.next_action, "Run `ces continue` to move this builder session forward.")

    def save_legacy_behavior_row(self, row: Any) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO legacy_behaviors(
                    entry_id, project_id, system, behavior_description, inferred_by,
                    inferred_at, confidence, disposition, reviewed_by, reviewed_at,
                    promoted_to_prl_id, discarded, source_manifest_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.entry_id,
                    getattr(row, "project_id", None) or self._project_id,
                    row.system,
                    row.behavior_description,
                    row.inferred_by,
                    row.inferred_at.isoformat() if hasattr(row.inferred_at, "isoformat") else str(row.inferred_at),
                    row.confidence,
                    getattr(row, "disposition", None),
                    getattr(row, "reviewed_by", None),
                    row.reviewed_at.isoformat() if getattr(row, "reviewed_at", None) else None,
                    getattr(row, "promoted_to_prl_id", None),
                    1 if getattr(row, "discarded", False) else 0,
                    getattr(row, "source_manifest_id", None),
                    getattr(row, "created_at", None) or now,
                    now,
                ),
            )

    def get_pending_legacy_behavior_rows(self) -> list[LegacyBehaviorRecord]:
        with self._connect() as conn:
            rows = fetch_pending_legacy_behaviors(conn, self._project_id)
        return [row_to_legacy_behavior(row) for row in rows]

    def get_legacy_behavior_rows_by_system(self, system: str) -> list[LegacyBehaviorRecord]:
        with self._connect() as conn:
            rows = fetch_legacy_behaviors_by_system(conn, self._project_id, system)
        return [row_to_legacy_behavior(row) for row in rows]

    def get_legacy_behavior_row(self, entry_id: str) -> LegacyBehaviorRecord | None:
        with self._connect() as conn:
            row = fetch_legacy_behavior(conn, self._project_id, entry_id)
        return row_to_legacy_behavior(row) if row else None

    def update_legacy_behavior_disposition(
        self,
        *,
        entry_id: str,
        disposition: str,
        reviewed_by: str,
        reviewed_at: datetime,
    ) -> LegacyBehaviorRecord | None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE legacy_behaviors
                SET disposition = ?, reviewed_by = ?, reviewed_at = ?, updated_at = ?
                WHERE entry_id = ? AND project_id = ?
                """,
                (
                    disposition,
                    reviewed_by,
                    reviewed_at.isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                    entry_id,
                    self._project_id,
                ),
            )
        return self.get_legacy_behavior_row(entry_id)

    def mark_legacy_behavior_promoted(
        self,
        *,
        entry_id: str,
        prl_id: str,
    ) -> LegacyBehaviorRecord | None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE legacy_behaviors
                SET promoted_to_prl_id = ?, updated_at = ?
                WHERE entry_id = ? AND project_id = ?
                """,
                (
                    prl_id,
                    datetime.now(timezone.utc).isoformat(),
                    entry_id,
                    self._project_id,
                ),
            )
        return self.get_legacy_behavior_row(entry_id)

    def save_prl_item(self, prl_item: Any) -> None:
        content = prl_item.model_dump(mode="json") if hasattr(prl_item, "model_dump") else dict(prl_item)
        prl_id = content["prl_id"]
        statement = content["statement"]
        created_at = content.get("created_at") or datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO prl_items(
                    prl_id, project_id, statement, content, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    prl_id,
                    self._project_id,
                    statement,
                    json.dumps(content, default=_json_default),
                    created_at,
                ),
            )

    def get_promoted_prl_items(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = fetch_promoted_prl_items(conn, self._project_id, limit)
        return [json.loads(row["content"]) for row in rows]

    def append_audit_entry(self, row: Any) -> None:
        metadata = getattr(row, "metadata_extra", None)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_entries(
                    entry_id, project_id, timestamp, event_type, actor, actor_type,
                    action_summary, decision, rationale, scope, metadata_extra,
                    prev_hash, entry_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.entry_id,
                    getattr(row, "project_id", self._project_id),
                    row.timestamp.isoformat(),
                    row.event_type,
                    row.actor,
                    row.actor_type,
                    row.action_summary,
                    row.decision,
                    row.rationale,
                    json.dumps(row.scope),
                    json.dumps(metadata) if metadata is not None else None,
                    row.prev_hash,
                    row.entry_hash,
                ),
            )

    def get_last_audit_entry(self, project_id: str | None = None) -> AuditEntryRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM audit_entries WHERE project_id = ? ORDER BY timestamp DESC LIMIT 1",
                (project_id or self._project_id,),
            ).fetchone()
        return row_to_audit_entry(row) if row else None

    def get_audit_by_event_type(self, event_type: str, project_id: str | None = None) -> list[AuditEntryRecord]:
        return self._fetch_audit(
            "SELECT * FROM audit_entries WHERE event_type = ? AND project_id = ? ORDER BY timestamp DESC",
            (event_type, project_id or self._project_id),
        )

    def get_audit_by_actor(self, actor: str, project_id: str | None = None) -> list[AuditEntryRecord]:
        return self._fetch_audit(
            "SELECT * FROM audit_entries WHERE actor = ? AND project_id = ? ORDER BY timestamp DESC",
            (actor, project_id or self._project_id),
        )

    def get_audit_by_time_range(
        self, start: datetime, end: datetime, project_id: str | None = None
    ) -> list[AuditEntryRecord]:
        return self._fetch_audit(
            "SELECT * FROM audit_entries WHERE timestamp >= ? AND timestamp <= ? AND project_id = ? ORDER BY timestamp DESC",
            (start.isoformat(), end.isoformat(), project_id or self._project_id),
        )

    def get_latest_audit(self, limit: int = 1000, project_id: str | None = None) -> list[AuditEntryRecord]:
        return self._fetch_audit(
            "SELECT * FROM audit_entries WHERE project_id = ? ORDER BY timestamp DESC LIMIT ?",
            (project_id or self._project_id, limit),
        )

    def _fetch_audit(self, query: str, params: tuple[Any, ...]) -> list[AuditEntryRecord]:
        with self._connect() as conn:
            rows = fetch_audit(conn, query, params)
        return [row_to_audit_entry(row) for row in rows]
