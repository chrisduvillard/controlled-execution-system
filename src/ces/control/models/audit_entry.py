"""Audit Ledger Entry model (PRD Part IV SS2.9).

Records every governance event in an append-only ledger with HMAC chain
integrity (D-16). Entries capture event type, actor, scope, decision,
rationale, and optional metadata fields.
"""

from __future__ import annotations

from datetime import date, datetime

from ces.shared.base import CESBaseModel
from ces.shared.enums import ActorType, EventType, InvalidationSeverity


class AuditScope(CESBaseModel):
    """Scope of artifacts, tasks, and manifests affected by the audit event."""

    affected_artifacts: tuple[str, ...] = ()
    affected_tasks: tuple[str, ...] = ()
    affected_manifests: tuple[str, ...] = ()


class CostImpact(CESBaseModel):
    """Economic cost impact of the event."""

    tokens_consumed: int = 0
    tasks_invalidated: int = 0
    rework_estimated_hours: float = 0.0


class AuditEntry(CESBaseModel):
    """Audit Ledger Entry (PRD SS2.9).

    Records a single governance event. Append-only -- entries may not be
    modified or deleted. HMAC chain fields (prev_hash, entry_hash) are
    populated by the audit ledger service, not on creation.
    """

    entry_id: str
    timestamp: datetime
    event_type: EventType
    actor: str
    actor_type: ActorType
    scope: AuditScope
    action_summary: str
    decision: str
    rationale: str
    evidence_refs: tuple[str, ...] = ()

    # Optional fields (PRD SS2.9 optional_fields)
    exception_type: str | None = None
    exception_expiry: datetime | None = None
    override_owner: str | None = None
    override_scope: str | None = None
    retrospective_review_date: date | None = None
    previous_state: str | None = None
    new_state: str | None = None
    invalidation_severity: InvalidationSeverity | None = None
    invalidation_downstream_count: int | None = None
    model_version: str | None = None
    cost_impact: CostImpact | None = None

    # Multi-project support (v1.2 MULTI-04)
    project_id: str | None = None

    # HMAC chain fields (D-16) -- populated by audit ledger service
    prev_hash: str = "GENESIS"
    entry_hash: str | None = None
