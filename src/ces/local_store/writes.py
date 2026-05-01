"""Table-specific write helpers for the local SQLite store."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def insert_builder_session(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    session_id: str,
    brief_id: str | None,
    request: str,
    project_mode: str,
    stage: str,
    next_action: str,
    last_action: str,
    recovery_reason: str | None,
    last_error: str | None,
    attempt_count: int,
    manifest_id: str | None,
    runtime_manifest_id: str | None,
    evidence_packet_id: str | None,
    approval_manifest_id: str | None,
    source_of_truth: str,
    critical_flows: list[str] | None,
    brownfield_review_state: dict[str, Any] | None,
    brownfield_entry_ids: list[str] | None,
    brownfield_reviewed_count: int,
    brownfield_remaining_count: int,
    now: str,
) -> None:
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
            project_id,
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


def update_builder_session(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    session_id: str,
    stage: str,
    next_action: str | None,
    last_action: str | None,
    recovery_reason: str | None,
    last_error: str | None,
    attempt_count: int,
    manifest_id: str | None,
    runtime_manifest_id: str | None,
    evidence_packet_id: str | None,
    approval_manifest_id: str | None,
    brownfield_review_state: dict[str, Any] | None,
    brownfield_entry_ids: list[str] | None,
    brownfield_reviewed_count: int,
    brownfield_remaining_count: int,
    now: str,
) -> None:
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
            json.dumps(brownfield_review_state) if brownfield_review_state is not None else None,
            json.dumps(brownfield_entry_ids or []),
            brownfield_reviewed_count,
            brownfield_remaining_count,
            now,
            session_id,
            project_id,
        ),
    )
