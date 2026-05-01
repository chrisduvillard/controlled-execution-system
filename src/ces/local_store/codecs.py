"""Row-to-record conversion helpers for the local SQLite store."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from ces.brownfield.records import LegacyBehaviorRecord
from ces.control.models.audit_entry_record import AuditEntryRecord
from ces.local_store.records import (
    LocalApprovalRecord,
    LocalBuilderBriefRecord,
    LocalBuilderSessionRecord,
    LocalManifestRow,
    LocalRuntimeExecutionRecord,
)


def row_to_manifest_record(row: sqlite3.Row) -> LocalManifestRow:
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


def row_to_builder_brief(row: sqlite3.Row) -> LocalBuilderBriefRecord:
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


def row_to_builder_session(row: sqlite3.Row) -> LocalBuilderSessionRecord:
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


def row_to_runtime_execution(row: sqlite3.Row) -> LocalRuntimeExecutionRecord:
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


def row_to_approval(row: sqlite3.Row) -> LocalApprovalRecord:
    return LocalApprovalRecord(
        manifest_id=row["manifest_id"],
        decision=row["decision"],
        rationale=row["rationale"],
        created_at=row["created_at"],
    )


def row_to_legacy_behavior(row: sqlite3.Row) -> LegacyBehaviorRecord:
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


def row_to_audit_entry(row: sqlite3.Row) -> AuditEntryRecord:
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
