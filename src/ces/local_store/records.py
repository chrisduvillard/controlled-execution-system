"""Frozen dataclasses describing rows read out of ``.ces/state.db``.

Each record mirrors a SQLite table (``manifests``, ``builder_briefs``,
``builder_sessions``, ``runtime_executions``, ``approvals``) or a derived
view (``LocalBrownfieldSessionSummary``, ``LocalBuilderSessionSnapshot``).
The records are exposed by :mod:`ces.local_store.repositories` and consumed
by the runtime services in ``src/ces/control/services``,
``src/ces/brownfield/services``, and the CLI status helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ces.harness_evolution.memory import HarnessMemoryLesson
from ces.harness_evolution.models import HarnessChangeManifest, HarnessChangeVerdict


@dataclass(frozen=True)
class LocalRuntimeExecutionRecord:
    manifest_id: str
    runtime_name: str
    runtime_version: str
    reported_model: str | None
    invocation_ref: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    transcript_path: str | None = None


@dataclass(frozen=True)
class LocalHarnessChangeRecord:
    change_id: str
    component_type: str
    title: str
    status: str
    manifest: HarnessChangeManifest
    manifest_hash: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class LocalHarnessChangeVerdictRecord:
    id: str
    change_id: str
    verdict: str
    verdict_payload: HarnessChangeVerdict
    created_at: str


@dataclass(frozen=True)
class LocalHarnessMemoryLessonRecord:
    lesson_id: str
    kind: str
    title: str
    status: str
    lesson: HarnessMemoryLesson
    content_hash: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class LocalBuilderBriefRecord:
    brief_id: str
    request: str
    project_mode: str
    constraints: list[str]
    acceptance_criteria: list[str]
    must_not_break: list[str]
    open_questions: dict[str, Any]
    source_of_truth: str
    critical_flows: list[str]
    manifest_id: str | None = None
    evidence_packet_id: str | None = None
    prl_draft_path: str | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class LocalBuilderSessionRecord:
    session_id: str
    brief_id: str | None
    request: str
    project_mode: str
    stage: str
    next_action: str
    last_action: str
    recovery_reason: str | None = None
    last_error: str | None = None
    attempt_count: int = 0
    manifest_id: str | None = None
    runtime_manifest_id: str | None = None
    evidence_packet_id: str | None = None
    approval_manifest_id: str | None = None
    source_of_truth: str = ""
    critical_flows: list[str] | None = None
    brownfield_review_state: dict[str, Any] | None = None
    brownfield_entry_ids: list[str] | None = None
    brownfield_reviewed_count: int = 0
    brownfield_remaining_count: int = 0
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class LocalManifestRow:
    """Row-shaped manifest read back from ``.ces/state.db``.

    Mirrors the columns in the ``manifests`` table plus the deserialised
    ``content`` blob. ``ManifestManager._row_to_manifest`` reconstructs a full
    ``TaskManifest`` from this record.
    """

    manifest_id: str
    description: str
    risk_tier: str
    behavior_confidence: str
    change_class: str
    workflow_state: str
    content: dict[str, Any]
    status: str
    expires_at: datetime
    created_at: datetime


@dataclass(frozen=True)
class LocalApprovalRecord:
    manifest_id: str
    decision: str
    rationale: str
    created_at: str | None = None


@dataclass(frozen=True)
class LocalBrownfieldSessionSummary:
    entry_ids: list[str]
    reviewed_count: int
    remaining_count: int
    checkpoint: dict[str, Any] | None = None


@dataclass(frozen=True)
class LocalBuilderSessionSnapshot:
    request: str
    project_mode: str
    stage: str
    next_action: str
    next_step: str
    latest_activity: str
    latest_artifact: str
    is_chain_complete: bool
    brief_only_fallback: bool
    session: LocalBuilderSessionRecord | None
    brief: LocalBuilderBriefRecord | None
    manifest: LocalManifestRow | None
    runtime_execution: LocalRuntimeExecutionRecord | None
    evidence: dict[str, Any] | None
    approval: LocalApprovalRecord | None
    brownfield: LocalBrownfieldSessionSummary | None
