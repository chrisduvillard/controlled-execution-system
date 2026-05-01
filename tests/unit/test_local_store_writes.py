"""Focused tests for local-store write helpers."""

from __future__ import annotations

from pathlib import Path

from ces.local_store import LocalProjectStore
from ces.local_store.writes import insert_builder_session, update_builder_session


def test_insert_builder_session_persists_compatible_string_values(tmp_path: Path) -> None:
    store = LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj")

    with store._connect() as conn:
        insert_builder_session(
            conn,
            project_id="proj",
            session_id="BS-direct",
            brief_id=None,
            request="Build direct helper",
            project_mode="greenfield",
            stage="ready_to_run",
            next_action="run_continue",
            last_action="brief_captured",
            recovery_reason=None,
            last_error=None,
            attempt_count=0,
            manifest_id=None,
            runtime_manifest_id=None,
            evidence_packet_id=None,
            approval_manifest_id=None,
            source_of_truth="README",
            critical_flows=["First run"],
            brownfield_review_state=None,
            brownfield_entry_ids=[],
            brownfield_reviewed_count=0,
            brownfield_remaining_count=0,
            now="2026-01-01T00:00:00+00:00",
        )
        row = conn.execute("SELECT * FROM builder_sessions WHERE session_id = 'BS-direct'").fetchone()

    assert row["stage"] == "ready_to_run"
    assert row["next_action"] == "run_continue"
    assert row["last_action"] == "brief_captured"
    assert row["critical_flows"] == '["First run"]'
    store.close()


def test_update_builder_session_persists_same_string_values(tmp_path: Path) -> None:
    store = LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj")
    session_id = store.save_builder_session(
        brief_id=None,
        request="Build direct helper",
        project_mode="greenfield",
        stage="ready_to_run",
        next_action="run_continue",
        last_action="brief_captured",
    )

    with store._connect() as conn:
        update_builder_session(
            conn,
            project_id="proj",
            session_id=session_id,
            stage="awaiting_review",
            next_action="review_evidence",
            last_action="evidence_ready",
            recovery_reason=None,
            last_error=None,
            attempt_count=1,
            manifest_id="M-1",
            runtime_manifest_id="M-1",
            evidence_packet_id="EP-1",
            approval_manifest_id=None,
            brownfield_review_state={"checkpoint": "kept"},
            brownfield_entry_ids=["OLB-1"],
            brownfield_reviewed_count=1,
            brownfield_remaining_count=0,
            now="2026-01-01T00:01:00+00:00",
        )
        row = conn.execute("SELECT * FROM builder_sessions WHERE session_id = ?", (session_id,)).fetchone()

    assert row["stage"] == "awaiting_review"
    assert row["next_action"] == "review_evidence"
    assert row["last_action"] == "evidence_ready"
    assert row["brownfield_review_state"] == '{"checkpoint": "kept"}'
    assert row["brownfield_entry_ids"] == '["OLB-1"]'
    store.close()
