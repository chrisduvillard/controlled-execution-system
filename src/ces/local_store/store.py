"""LocalProjectStore — SQLite persistence for local-first CES projects.

The store owns the on-disk schema, runs in-app migrations on startup, and
exposes typed query helpers consumed by the repository adapters in
:mod:`ces.local_store.repositories`. Higher-level services depend on the
adapters, not on the store directly.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

from ces.brownfield.records import LegacyBehaviorRecord
from ces.control.models.audit_entry_record import AuditEntryRecord
from ces.execution.sandbox import scrub_secrets_from_text
from ces.local_store.records import (
    LocalApprovalRecord,
    LocalBrownfieldSessionSummary,
    LocalBuilderBriefRecord,
    LocalBuilderSessionRecord,
    LocalBuilderSessionSnapshot,
    LocalManifestRow,
    LocalRuntimeExecutionRecord,
)

if TYPE_CHECKING:
    from ces.control.models.manifest import TaskManifest
    from ces.harness.services.findings_aggregator import AggregatedReview

_UNSET = object()


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


class LocalProjectStore:
    """Persist CES state in `.ces/state.db` for local-first projects."""

    def __init__(self, db_path: Path, project_id: str = "default") -> None:
        self._db_path = Path(db_path)
        self._project_id = project_id
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        # One pooled connection per store instance. CES CLI invocations are
        # single-threaded; opening per-call would pay journal-init latency on
        # every read. ``check_same_thread=False`` is intentional — the
        # connection is owned exclusively by this instance and access patterns
        # are sequential within the async event loop.
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.initialize()
        # Tighten file perms after SQLite has created the file. Wrapped in
        # try/except so Windows (which doesn't honour POSIX bits the same way)
        # and unusual filesystems don't break local projects.
        try:
            os.chmod(self._db_path.parent, 0o700)
            if self._db_path.exists():
                os.chmod(self._db_path, 0o600)
        except OSError:
            pass

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # ``with self._conn:`` invokes sqlite3's transaction-context-manager
        # protocol — auto-commits on clean exit, rolls back on exception. The
        # connection itself is reused across calls for cache-warmth.
        with self._conn:
            yield self._conn

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
            # Defensive recovery: if a previous initialize() was interrupted
            # mid-migration (process kill, disk full, power loss), a temp
            # `review_findings_new` table can strand. Reconcile based on
            # which side of the rename completed:
            #   - both tables exist  → crash before DROP; main is the source
            #     of truth, drop the temp.
            #   - only temp exists   → crash after DROP, before RENAME; the
            #     temp holds the data and just needs renaming.
            # Doing this BEFORE the CREATE-IF-NOT-EXISTS below matters: that
            # statement would otherwise create a fresh empty `review_findings`
            # in the temp-only case and silently abandon the user's data.
            has_temp = bool(
                conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='review_findings_new'"
                ).fetchone()
            )
            if has_temp:
                has_main = bool(
                    conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='review_findings'"
                    ).fetchone()
                )
                if has_main:
                    conn.execute("DROP TABLE review_findings_new")
                else:
                    conn.execute("ALTER TABLE review_findings_new RENAME TO review_findings")

            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS project_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS manifests (
                    manifest_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    description TEXT NOT NULL,
                    risk_tier TEXT NOT NULL,
                    behavior_confidence TEXT NOT NULL,
                    change_class TEXT NOT NULL,
                    status TEXT NOT NULL,
                    workflow_state TEXT NOT NULL,
                    content_hash TEXT,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    content TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_entries (
                    entry_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    actor_type TEXT NOT NULL,
                    action_summary TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    metadata_extra TEXT,
                    prev_hash TEXT NOT NULL,
                    entry_hash TEXT
                );
                CREATE TRIGGER IF NOT EXISTS audit_entries_no_update
                    BEFORE UPDATE ON audit_entries
                    BEGIN
                        SELECT RAISE(ABORT, 'audit_entries are append-only');
                    END;
                CREATE TRIGGER IF NOT EXISTS audit_entries_no_delete
                    BEFORE DELETE ON audit_entries
                    BEGIN
                        SELECT RAISE(ABORT, 'audit_entries are append-only');
                    END;
                CREATE TABLE IF NOT EXISTS runtime_executions (
                    manifest_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    runtime_name TEXT NOT NULL,
                    runtime_version TEXT NOT NULL,
                    reported_model TEXT,
                    invocation_ref TEXT NOT NULL,
                    exit_code INTEGER NOT NULL,
                    stdout TEXT NOT NULL,
                    stderr TEXT NOT NULL,
                    duration_seconds REAL NOT NULL,
                    transcript_path TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evidence_packets (
                    manifest_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    packet_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    challenge TEXT NOT NULL,
                    triage_color TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    manifest_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS builder_briefs (
                    brief_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    request TEXT NOT NULL,
                    project_mode TEXT NOT NULL,
                    constraints TEXT NOT NULL,
                    acceptance_criteria TEXT NOT NULL,
                    must_not_break TEXT NOT NULL,
                    open_questions TEXT NOT NULL,
                    source_of_truth TEXT NOT NULL,
                    critical_flows TEXT NOT NULL,
                    manifest_id TEXT,
                    evidence_packet_id TEXT,
                    prl_draft_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS builder_sessions (
                    session_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    brief_id TEXT,
                    request TEXT NOT NULL,
                    project_mode TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    next_action TEXT NOT NULL,
                    last_action TEXT NOT NULL,
                    recovery_reason TEXT,
                    last_error TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    manifest_id TEXT,
                    runtime_manifest_id TEXT,
                    evidence_packet_id TEXT,
                    approval_manifest_id TEXT,
                    source_of_truth TEXT NOT NULL,
                    critical_flows TEXT NOT NULL,
                    brownfield_review_state TEXT,
                    brownfield_entry_ids TEXT,
                    brownfield_reviewed_count INTEGER NOT NULL DEFAULT 0,
                    brownfield_remaining_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS legacy_behaviors (
                    entry_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    system TEXT NOT NULL,
                    behavior_description TEXT NOT NULL,
                    inferred_by TEXT NOT NULL,
                    inferred_at TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    disposition TEXT,
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    promoted_to_prl_id TEXT,
                    discarded INTEGER NOT NULL DEFAULT 0,
                    source_manifest_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS prl_items (
                    prl_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    statement TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_findings (
                    id INTEGER PRIMARY KEY,
                    finding_id TEXT NOT NULL,
                    manifest_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    reviewer_role TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    category TEXT NOT NULL,
                    file_path TEXT,
                    line_number INTEGER,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    recommendation TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_review_findings_manifest
                    ON review_findings (manifest_id);
                CREATE TABLE IF NOT EXISTS review_aggregates (
                    manifest_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    critical_count INTEGER NOT NULL DEFAULT 0,
                    high_count INTEGER NOT NULL DEFAULT 0,
                    disagreements TEXT NOT NULL DEFAULT '[]',
                    unanimous_zero_findings INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                """
            )
            # Migration: review_findings should have a synthetic INTEGER PK,
            # not a uniqueness constraint on finding_id. Earlier schemas
            # promoted finding_id (a free-form label the reviewer attaches)
            # to the actual primary key — first as `finding_id PRIMARY KEY`
            # alone, briefly as `(manifest_id, finding_id)` composite. Both
            # caused IntegrityError when reviewers hard-coded duplicate IDs
            # (across manifests, or — for the composite version — across
            # reviewers within a single Tier A triad). The fresh-DB CREATE
            # above already uses the synthetic PK. This block detects either
            # legacy shape and rebuilds the table, preserving every row.
            #
            # Atomicity: every statement runs as conn.execute() inside the
            # surrounding `with conn:` block, so the whole migration commits
            # as a single transaction. (executescript() would commit
            # mid-migration and could leave the table half-renamed on error.)
            existing_columns = [row["name"] for row in conn.execute("PRAGMA table_info(review_findings)").fetchall()]
            needs_migration = existing_columns and "id" not in existing_columns
            if needs_migration:
                conn.execute(
                    """
                    CREATE TABLE review_findings_new (
                        id INTEGER PRIMARY KEY,
                        finding_id TEXT NOT NULL,
                        manifest_id TEXT NOT NULL,
                        project_id TEXT NOT NULL,
                        reviewer_role TEXT NOT NULL,
                        severity TEXT NOT NULL,
                        category TEXT NOT NULL,
                        file_path TEXT,
                        line_number INTEGER,
                        title TEXT NOT NULL,
                        description TEXT NOT NULL,
                        recommendation TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO review_findings_new (
                        finding_id, manifest_id, project_id, reviewer_role,
                        severity, category, file_path, line_number, title,
                        description, recommendation, confidence, created_at
                    )
                    SELECT
                        finding_id, manifest_id, project_id, reviewer_role,
                        severity, category, file_path, line_number, title,
                        description, recommendation, confidence, created_at
                    FROM review_findings
                    """
                )
                conn.execute("DROP TABLE review_findings")
                conn.execute("ALTER TABLE review_findings_new RENAME TO review_findings")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_review_findings_manifest ON review_findings (manifest_id)")

            builder_session_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(builder_sessions)").fetchall()
            }
            if "brownfield_review_state" not in builder_session_columns:
                conn.execute("ALTER TABLE builder_sessions ADD COLUMN brownfield_review_state TEXT")
            if "brownfield_entry_ids" not in builder_session_columns:
                conn.execute("ALTER TABLE builder_sessions ADD COLUMN brownfield_entry_ids TEXT")
            if "brownfield_reviewed_count" not in builder_session_columns:
                conn.execute(
                    "ALTER TABLE builder_sessions ADD COLUMN brownfield_reviewed_count INTEGER NOT NULL DEFAULT 0"
                )
            if "brownfield_remaining_count" not in builder_session_columns:
                conn.execute(
                    "ALTER TABLE builder_sessions ADD COLUMN brownfield_remaining_count INTEGER NOT NULL DEFAULT 0"
                )

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
            row = conn.execute(
                "SELECT * FROM builder_briefs WHERE brief_id = ? AND project_id = ?",
                (brief_id, self._project_id),
            ).fetchone()
        return self._row_to_builder_brief(row) if row else None

    def get_latest_builder_brief(self) -> LocalBuilderBriefRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM builder_briefs WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
                (self._project_id,),
            ).fetchone()
        return self._row_to_builder_brief(row) if row else None

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
            conn.execute(
                """
                INSERT INTO builder_sessions(
                    session_id, project_id, brief_id, request, project_mode, stage,
                    next_action, last_action, recovery_reason, last_error, attempt_count,
                    manifest_id, runtime_manifest_id, evidence_packet_id, approval_manifest_id,
                    source_of_truth, critical_flows, brownfield_review_state,
                    brownfield_entry_ids, brownfield_reviewed_count, brownfield_remaining_count,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    self._project_id,
                    brief_id,
                    request,
                    project_mode,
                    stage,
                    next_action,
                    last_action,
                    recovery_reason,
                    last_error,
                    attempt_count,
                    manifest_id,
                    runtime_manifest_id,
                    evidence_packet_id,
                    approval_manifest_id,
                    source_of_truth,
                    json.dumps(critical_flows or []),
                    json.dumps(brownfield_review_state) if brownfield_review_state is not None else None,
                    json.dumps(brownfield_entry_ids or []),
                    brownfield_reviewed_count,
                    brownfield_remaining_count,
                    now,
                    now,
                ),
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
            conn.execute(
                """
                UPDATE builder_sessions
                SET stage = ?, next_action = ?, last_action = ?, recovery_reason = ?,
                    last_error = ?, attempt_count = ?, manifest_id = ?,
                    runtime_manifest_id = ?, evidence_packet_id = ?,
                    approval_manifest_id = ?, brownfield_review_state = ?,
                    brownfield_entry_ids = ?, brownfield_reviewed_count = ?,
                    brownfield_remaining_count = ?, updated_at = ?
                WHERE session_id = ? AND project_id = ?
                """,
                (
                    current.stage if stage is _UNSET else stage,
                    current.next_action if next_action is _UNSET else next_action,
                    current.last_action if last_action is _UNSET else last_action,
                    current.recovery_reason if recovery_reason is _UNSET else recovery_reason,
                    current.last_error if last_error is _UNSET else last_error,
                    current.attempt_count if attempt_count is _UNSET else attempt_count,
                    current.manifest_id if manifest_id is _UNSET else manifest_id,
                    current.runtime_manifest_id if runtime_manifest_id is _UNSET else runtime_manifest_id,
                    current.evidence_packet_id if evidence_packet_id is _UNSET else evidence_packet_id,
                    current.approval_manifest_id if approval_manifest_id is _UNSET else approval_manifest_id,
                    (
                        json.dumps(current.brownfield_review_state)
                        if brownfield_review_state is _UNSET
                        else (json.dumps(brownfield_review_state) if brownfield_review_state is not None else None)
                    ),
                    (
                        json.dumps(current.brownfield_entry_ids or [])
                        if brownfield_entry_ids is _UNSET
                        else json.dumps(brownfield_entry_ids or [])
                    ),
                    (
                        current.brownfield_reviewed_count
                        if brownfield_reviewed_count is _UNSET
                        else brownfield_reviewed_count
                    ),
                    (
                        current.brownfield_remaining_count
                        if brownfield_remaining_count is _UNSET
                        else brownfield_remaining_count
                    ),
                    datetime.now(timezone.utc).isoformat(),
                    session_id,
                    self._project_id,
                ),
            )
        return self.get_builder_session(session_id)

    def get_builder_session(self, session_id: str) -> LocalBuilderSessionRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM builder_sessions WHERE session_id = ? AND project_id = ?",
                (session_id, self._project_id),
            ).fetchone()
        return self._row_to_builder_session(row) if row else None

    def get_latest_builder_session(self) -> LocalBuilderSessionRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM builder_sessions WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
                (self._project_id,),
            ).fetchone()
        return self._row_to_builder_session(row) if row else None

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
            row = conn.execute(
                "SELECT * FROM manifests WHERE manifest_id = ? AND project_id = ?",
                (manifest_id, self._project_id),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_manifest_namespace(row)

    def get_active_manifest_rows(self) -> list[LocalManifestRow]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM manifests
                WHERE project_id = ?
                  AND workflow_state NOT IN ('merged', 'deployed', 'expired', 'rejected')
                ORDER BY created_at DESC
                """,
                (self._project_id,),
            ).fetchall()
        return [self._row_to_manifest_namespace(row) for row in rows]

    def get_all_manifest_rows(self) -> list[LocalManifestRow]:
        """Return every stored manifest row regardless of workflow state.

        Unlike ``get_active_manifest_rows``, this includes terminal states
        (merged / deployed / rejected / expired / failed / cancelled). Callers
        that need full history — notably spec tree rendering and
        ``ces spec reconcile`` — must not filter out terminal manifests, or
        they misclassify already-shipped stories as "added" on the next run.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM manifests WHERE project_id = ? ORDER BY created_at DESC",
                (self._project_id,),
            ).fetchall()
        return [self._row_to_manifest_namespace(row) for row in rows]

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
            row = conn.execute(
                "SELECT * FROM runtime_executions WHERE manifest_id = ? AND project_id = ?",
                (manifest_id, self._project_id),
            ).fetchone()
        if row is None:
            return None
        return LocalRuntimeExecutionRecord(
            manifest_id=row["manifest_id"],
            runtime_name=row["runtime_name"],
            runtime_version=row["runtime_version"],
            reported_model=row["reported_model"],
            invocation_ref=row["invocation_ref"],
            exit_code=row["exit_code"],
            stdout=row["stdout"],
            stderr=row["stderr"],
            duration_seconds=row["duration_seconds"],
            transcript_path=row["transcript_path"],
        )

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
                    json.dumps(content, default=_json_default),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def get_evidence(self, manifest_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM evidence_packets WHERE manifest_id = ? AND project_id = ?",
                (manifest_id, self._project_id),
            ).fetchone()
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
            row = conn.execute(
                "SELECT * FROM evidence_packets WHERE packet_id = ? AND project_id = ?",
                (packet_id, self._project_id),
            ).fetchone()
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
            row = conn.execute(
                "SELECT * FROM approvals WHERE manifest_id = ? AND project_id = ?",
                (manifest_id, self._project_id),
            ).fetchone()
        if row is None:
            return None
        return LocalApprovalRecord(
            manifest_id=row["manifest_id"],
            decision=row["decision"],
            rationale=row["rationale"],
            created_at=row["created_at"],
        )

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
            rows = conn.execute(
                """
                SELECT * FROM legacy_behaviors
                WHERE project_id = ? AND disposition IS NULL AND discarded = 0
                ORDER BY created_at DESC
                """,
                (self._project_id,),
            ).fetchall()
        return [self._row_to_legacy_behavior_namespace(row) for row in rows]

    def get_legacy_behavior_rows_by_system(self, system: str) -> list[LegacyBehaviorRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM legacy_behaviors
                WHERE system = ? AND project_id = ?
                ORDER BY created_at DESC
                """,
                (system, self._project_id),
            ).fetchall()
        return [self._row_to_legacy_behavior_namespace(row) for row in rows]

    def get_legacy_behavior_row(self, entry_id: str) -> LegacyBehaviorRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM legacy_behaviors WHERE entry_id = ? AND project_id = ?",
                (entry_id, self._project_id),
            ).fetchone()
        return self._row_to_legacy_behavior_namespace(row) if row else None

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
            rows = conn.execute(
                """
                SELECT content FROM prl_items
                WHERE project_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (self._project_id, limit),
            ).fetchall()
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
        return self._row_to_audit_namespace(row) if row else None

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
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_audit_namespace(row) for row in rows]

    @staticmethod
    def _row_to_manifest_namespace(row: sqlite3.Row) -> LocalManifestRow:
        return LocalManifestRow(
            manifest_id=row["manifest_id"],
            description=row["description"],
            risk_tier=row["risk_tier"],
            behavior_confidence=row["behavior_confidence"],
            change_class=row["change_class"],
            workflow_state=row["workflow_state"],
            content=json.loads(row["content"]),
            status=row["status"],
            expires_at=datetime.fromisoformat(row["expires_at"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _row_to_builder_brief(row: sqlite3.Row) -> LocalBuilderBriefRecord:
        return LocalBuilderBriefRecord(
            brief_id=row["brief_id"],
            request=row["request"],
            project_mode=row["project_mode"],
            constraints=json.loads(row["constraints"]),
            acceptance_criteria=json.loads(row["acceptance_criteria"]),
            must_not_break=json.loads(row["must_not_break"]),
            open_questions=json.loads(row["open_questions"]),
            source_of_truth=row["source_of_truth"],
            critical_flows=json.loads(row["critical_flows"]),
            manifest_id=row["manifest_id"],
            evidence_packet_id=row["evidence_packet_id"],
            prl_draft_path=row["prl_draft_path"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_builder_session(row: sqlite3.Row) -> LocalBuilderSessionRecord:
        return LocalBuilderSessionRecord(
            session_id=row["session_id"],
            brief_id=row["brief_id"],
            request=row["request"],
            project_mode=row["project_mode"],
            stage=row["stage"],
            next_action=row["next_action"],
            last_action=row["last_action"],
            recovery_reason=row["recovery_reason"],
            last_error=row["last_error"],
            attempt_count=row["attempt_count"],
            manifest_id=row["manifest_id"],
            runtime_manifest_id=row["runtime_manifest_id"],
            evidence_packet_id=row["evidence_packet_id"],
            approval_manifest_id=row["approval_manifest_id"],
            source_of_truth=row["source_of_truth"],
            critical_flows=json.loads(row["critical_flows"]),
            brownfield_review_state=(
                json.loads(row["brownfield_review_state"]) if row["brownfield_review_state"] else None
            ),
            brownfield_entry_ids=(json.loads(row["brownfield_entry_ids"]) if row["brownfield_entry_ids"] else []),
            brownfield_reviewed_count=row["brownfield_reviewed_count"],
            brownfield_remaining_count=row["brownfield_remaining_count"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_legacy_behavior_namespace(row: sqlite3.Row) -> LegacyBehaviorRecord:
        return LegacyBehaviorRecord(
            entry_id=row["entry_id"],
            system=row["system"],
            project_id=row["project_id"],
            behavior_description=row["behavior_description"],
            inferred_by=row["inferred_by"],
            inferred_at=datetime.fromisoformat(row["inferred_at"]),
            confidence=row["confidence"],
            disposition=row["disposition"],
            reviewed_by=row["reviewed_by"],
            reviewed_at=(datetime.fromisoformat(row["reviewed_at"]) if row["reviewed_at"] else None),
            promoted_to_prl_id=row["promoted_to_prl_id"],
            discarded=bool(row["discarded"]),
            source_manifest_id=row["source_manifest_id"],
        )

    @staticmethod
    def _row_to_audit_namespace(row: sqlite3.Row) -> AuditEntryRecord:
        return AuditEntryRecord(
            entry_id=row["entry_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            event_type=row["event_type"],
            actor=row["actor"],
            actor_type=row["actor_type"],
            scope=json.loads(row["scope"]),
            action_summary=row["action_summary"],
            decision=row["decision"],
            rationale=row["rationale"],
            metadata_extra=json.loads(row["metadata_extra"]) if row["metadata_extra"] else {},
            project_id=row["project_id"],
            prev_hash=row["prev_hash"],
            entry_hash=row["entry_hash"],
        )
