"""Focused tests for local-store row codecs."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ces.local_store.codecs import row_to_builder_session, row_to_manifest_record


def _manifest_row(tmp_path: Path) -> sqlite3.Row:
    conn = sqlite3.connect(tmp_path / "rows.db")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE manifests (
            manifest_id TEXT, description TEXT, risk_tier TEXT,
            behavior_confidence TEXT, change_class TEXT, workflow_state TEXT,
            content TEXT, status TEXT, expires_at TEXT, created_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO manifests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "M-1",
            "Ship local state",
            "B",
            "BC2",
            "class_2",
            "in_flight",
            '{"manifest_id": "M-1"}',
            "draft",
            "2026-01-01T01:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
        ),
    )
    row = conn.execute("SELECT * FROM manifests").fetchone()
    conn.close()
    return row


def _builder_session_row(tmp_path: Path) -> sqlite3.Row:
    conn = sqlite3.connect(tmp_path / "rows.db")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE builder_sessions (
            session_id TEXT, brief_id TEXT, request TEXT, project_mode TEXT,
            stage TEXT, next_action TEXT, last_action TEXT, recovery_reason TEXT,
            last_error TEXT, attempt_count INTEGER, manifest_id TEXT,
            runtime_manifest_id TEXT, evidence_packet_id TEXT, approval_manifest_id TEXT,
            source_of_truth TEXT, critical_flows TEXT, brownfield_review_state TEXT,
            brownfield_entry_ids TEXT, brownfield_reviewed_count INTEGER,
            brownfield_remaining_count INTEGER, created_at TEXT, updated_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO builder_sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "BS-1",
            None,
            "Review legacy billing",
            "brownfield",
            "awaiting_review",
            "review_brownfield",
            "brownfield_review_in_progress",
            None,
            None,
            2,
            "M-1",
            "M-1",
            "EP-1",
            None,
            "README",
            '["Billing export"]',
            '{"group_index": 1}',
            '["OLB-1"]',
            1,
            3,
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:01:00+00:00",
        ),
    )
    row = conn.execute("SELECT * FROM builder_sessions").fetchone()
    conn.close()
    return row


def test_row_to_manifest_record_decodes_json_and_datetimes(tmp_path: Path) -> None:
    row = _manifest_row(tmp_path)

    record = row_to_manifest_record(row)

    assert record.manifest_id == "M-1"
    assert record.content == {"manifest_id": "M-1"}
    assert record.expires_at.isoformat() == "2026-01-01T01:00:00+00:00"


def test_row_to_builder_session_decodes_optional_brownfield_json(tmp_path: Path) -> None:
    row = _builder_session_row(tmp_path)

    record = row_to_builder_session(row)

    assert record.session_id == "BS-1"
    assert record.critical_flows == ["Billing export"]
    assert record.brownfield_review_state == {"group_index": 1}
    assert record.brownfield_entry_ids == ["OLB-1"]
