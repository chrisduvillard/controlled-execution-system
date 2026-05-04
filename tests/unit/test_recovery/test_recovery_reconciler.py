"""Tests for stale builder session reconciliation."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ces.local_store import LocalProjectStore
from ces.recovery.reconciler import reconcile_stale_builder_session, write_builder_runtime_lock


def _seed_session(
    tmp_path: Path, *, stage: str, updated_at: datetime | None = None
) -> tuple[LocalProjectStore, Path, str]:
    project_root = tmp_path
    (project_root / ".ces").mkdir(exist_ok=True)
    store = LocalProjectStore(project_root / ".ces" / "state.db", project_id="proj")
    brief_id = store.save_builder_brief(
        request="Build MiniLog",
        project_mode="greenfield",
        constraints=[],
        acceptance_criteria=["CLI works"],
        must_not_break=[],
        open_questions={},
        manifest_id="M-123",
    )
    session_id = store.save_builder_session(
        brief_id=brief_id,
        request="Build MiniLog",
        project_mode="greenfield",
        stage=stage,
        next_action="review_evidence",
        last_action="execution_started",
        manifest_id="M-123",
        runtime_manifest_id="M-123",
    )
    if updated_at is not None:
        with store._connect() as conn:
            conn.execute(
                "UPDATE builder_sessions SET updated_at = ? WHERE session_id = ?",
                (updated_at.isoformat(), session_id),
            )
    return store, project_root, session_id


def test_reconcile_marks_stale_running_session_blocked(tmp_path: Path) -> None:
    stale_at = datetime.now(timezone.utc) - timedelta(hours=2)
    store, project_root, session_id = _seed_session(tmp_path, stage="running", updated_at=stale_at)

    result = reconcile_stale_builder_session(project_root=project_root, local_store=store, stale_after_seconds=60)

    assert result.changed is True
    assert result.session_id == session_id
    session = store.get_builder_session(session_id)
    assert session is not None
    assert session.stage == "blocked"
    assert session.next_action == "retry_runtime"
    assert session.last_action == "runtime_interrupted"
    assert session.recovery_reason == "runtime_interrupted"
    assert session.last_error is not None
    assert "stale" in session.last_error.lower() or "interrupted" in session.last_error.lower()


def test_reconcile_leaves_fresh_running_session_unchanged(tmp_path: Path) -> None:
    store, project_root, session_id = _seed_session(tmp_path, stage="running", updated_at=datetime.now(timezone.utc))

    result = reconcile_stale_builder_session(project_root=project_root, local_store=store, stale_after_seconds=3600)

    assert result.changed is False
    session = store.get_builder_session(session_id)
    assert session is not None
    assert session.stage == "running"
    assert session.next_action == "review_evidence"


def test_reconcile_leaves_completed_session_unchanged(tmp_path: Path) -> None:
    stale_at = datetime.now(timezone.utc) - timedelta(hours=2)
    store, project_root, session_id = _seed_session(tmp_path, stage="completed", updated_at=stale_at)

    result = reconcile_stale_builder_session(project_root=project_root, local_store=store, stale_after_seconds=60)

    assert result.changed is False
    session = store.get_builder_session(session_id)
    assert session is not None
    assert session.stage == "completed"


def test_reconcile_does_not_block_live_runtime_lock(tmp_path: Path) -> None:
    stale_at = datetime.now(timezone.utc) - timedelta(hours=2)
    store, project_root, session_id = _seed_session(tmp_path, stage="running", updated_at=stale_at)
    write_builder_runtime_lock(project_root=project_root, session_id=session_id, manifest_id="M-123")

    result = reconcile_stale_builder_session(project_root=project_root, local_store=store, stale_after_seconds=60)

    assert result.changed is False
    assert result.active_runtime is True
    session = store.get_builder_session(session_id)
    assert session is not None
    assert session.stage == "running"


def test_reconcile_blocks_dead_runtime_lock_immediately(tmp_path: Path) -> None:
    store, project_root, session_id = _seed_session(tmp_path, stage="running", updated_at=datetime.now(timezone.utc))
    (project_root / ".ces" / "builder-runtime.lock").write_text(
        f'{{"pid": {os.getpid() + 10_000_000}, "session_id": "{session_id}", "manifest_id": "M-123"}}',
        encoding="utf-8",
    )

    result = reconcile_stale_builder_session(project_root=project_root, local_store=store, stale_after_seconds=3600)

    assert result.changed is True
    assert result.stale is True
    session = store.get_builder_session(session_id)
    assert session is not None
    assert session.stage == "blocked"


def test_reconcile_can_report_stale_without_mutating(tmp_path: Path) -> None:
    stale_at = datetime.now(timezone.utc) - timedelta(hours=2)
    store, project_root, session_id = _seed_session(tmp_path, stage="running", updated_at=stale_at)

    result = reconcile_stale_builder_session(
        project_root=project_root,
        local_store=store,
        stale_after_seconds=60,
        mutate=False,
    )

    assert result.changed is False
    assert result.stale is True
    session = store.get_builder_session(session_id)
    assert session is not None
    assert session.stage == "running"
