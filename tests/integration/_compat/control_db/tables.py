"""SQLAlchemy 2.0 ORM table definitions for CES control, harness, and knowledge planes.

Tables use per-plane PostgreSQL schema separation:
- control: truth_artifacts, manifests, audit_entries, workflow_states
- harness: harness_profiles, trust_events
- knowledge: vault_notes, intake_sessions, legacy_behaviors

All tables use Mapped[] annotations (SQLAlchemy 2.0 style).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Sequence,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tests.integration._compat.control_db.base import Base

# ---------------------------------------------------------------------------
# Control plane tables
# ---------------------------------------------------------------------------


class TruthArtifactRow(Base):
    """Polymorphic JSONB truth artifact storage (per D-06).

    All 9 truth artifact types are stored in a single table with
    type-discriminated JSONB content. GIN index on content enables
    efficient querying of nested JSONB fields.
    """

    __tablename__ = "truth_artifacts"
    __table_args__ = (
        Index(
            "ix_truth_artifacts_content",
            "content",
            postgresql_using="gin",
        ),
        {"schema": "control"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(50), index=True)
    version: Mapped[int]
    status: Mapped[str] = mapped_column(String(20), index=True)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64))
    owner: Mapped[str] = mapped_column(String(100))
    project_id: Mapped[str] = mapped_column(String(100), index=True, server_default="default")
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ManifestRow(Base):
    """Task manifest persistence (control plane).

    Stores the full manifest as JSONB for flexible querying,
    with indexed columns for common access patterns.
    """

    __tablename__ = "manifests"
    __table_args__ = ({"schema": "control"},)

    manifest_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    description: Mapped[str] = mapped_column(Text)
    risk_tier: Mapped[str] = mapped_column(String(5))
    behavior_confidence: Mapped[str] = mapped_column(String(5))
    change_class: Mapped[str] = mapped_column(String(10))
    content: Mapped[dict] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    classifier_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    implementer_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True, server_default="default")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class AuditEntryRow(Base):
    """Append-only audit ledger entry (per D-07, D-16).

    Enforced at three levels:
    1. DB trigger: prevents UPDATE/DELETE on the table
    2. Repository: AuditRepository exposes only append() and read methods
    3. Hash chain: prev_hash links entries for tamper detection

    The sequence_num column provides a total ordering guarantee
    independent of timestamps.
    """

    __tablename__ = "audit_entries"
    __table_args__ = ({"schema": "control"},)

    audit_seq = Sequence("audit_entries_seq", schema="control")

    entry_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sequence_num: Mapped[int] = mapped_column(
        BigInteger,
        audit_seq,
        server_default=audit_seq.next_value(),
        unique=True,
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    event_type: Mapped[str] = mapped_column(String(30), index=True)
    actor: Mapped[str] = mapped_column(String(100), index=True)
    actor_type: Mapped[str] = mapped_column(String(20))
    scope: Mapped[dict] = mapped_column(JSONB)
    action_summary: Mapped[str] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    metadata_extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True, server_default="default")
    prev_hash: Mapped[str] = mapped_column(String(64), default="GENESIS")
    entry_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class WorkflowStateRow(Base):
    """Current workflow state for a manifest (per D-11).

    Provides fast lookup of manifest workflow status without
    scanning the full audit ledger.
    """

    __tablename__ = "workflow_states"
    __table_args__ = ({"schema": "control"},)

    manifest_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("control.manifests.manifest_id"),
        primary_key=True,
    )
    current_state: Mapped[str] = mapped_column(String(20), index=True)
    sub_state: Mapped[str | None] = mapped_column(String(30), nullable=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True, server_default="default")
    retry_count: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class KillSwitchStateRow(Base):
    """Kill switch state per activity class (per D-05).

    One row per activity class (7 total). Primary key is the activity
    class string value, so there's exactly one row per class.

    State changes are made via KillSwitchService which logs all
    activations/recoveries to the audit ledger (T-02-08, T-02-10).
    """

    __tablename__ = "kill_switch_state"
    __table_args__ = ({"schema": "control"},)

    activity_class: Mapped[str] = mapped_column(String(30), primary_key=True)
    halted: Mapped[bool] = mapped_column(Boolean, default=False)
    halted_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    halted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


# ---------------------------------------------------------------------------
# Harness plane tables
# ---------------------------------------------------------------------------


class TrustEventRow(Base):
    """Trust lifecycle event history for harness profiles.

    Records every trust status transition (promotion, contraction, recovery)
    with trigger reason and metadata for audit purposes.
    """

    __tablename__ = "trust_events"
    __table_args__ = ({"schema": "harness"},)

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True, server_default="default")
    old_status: Mapped[str] = mapped_column(String(20))
    new_status: Mapped[str] = mapped_column(String(20))
    trigger: Mapped[str] = mapped_column(String(50))
    metadata_extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class HarnessProfileRow(Base):
    """Agent harness profile persistence.

    Stores the full profile as JSONB with indexed columns
    for agent lookup and trust filtering.
    """

    __tablename__ = "harness_profiles"
    __table_args__ = ({"schema": "harness"},)

    profile_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(100), index=True, unique=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True, server_default="default")
    trust_status: Mapped[str] = mapped_column(String(20))
    profile_data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


# ---------------------------------------------------------------------------
# Knowledge plane tables
# ---------------------------------------------------------------------------


class VaultNoteRow(Base):
    """Knowledge vault note persistence (Zettelkasten).

    Stores notes across 9 categories with trust levels.
    GIN index on metadata enables efficient JSONB querying.
    Composite index on (category, trust_level) for common filters.

    The knowledge vault is informational only -- it must NEVER answer
    requirement, policy, or risk-acceptance questions.
    """

    __tablename__ = "vault_notes"
    __table_args__ = (
        Index(
            "ix_vault_notes_note_metadata",
            "note_metadata",
            postgresql_using="gin",
        ),
        Index(
            "ix_vault_notes_category_trust",
            "category",
            "trust_level",
        ),
        {"schema": "knowledge"},
    )

    note_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    category: Mapped[str] = mapped_column(String(30), index=True)
    trust_level: Mapped[str] = mapped_column(String(20), index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(255))
    project_id: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    note_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    related_artifacts: Mapped[list] = mapped_column(JSONB, default=list)
    invalidation_trigger: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class IntakeSessionRow(Base):
    """Intake interview session persistence.

    Stores the state of intake interview sessions including
    answers (append-only JSONB), assumptions, and blocked questions.
    """

    __tablename__ = "intake_sessions"
    __table_args__ = ({"schema": "knowledge"},)

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    phase: Mapped[int] = mapped_column(Integer)
    current_stage: Mapped[str] = mapped_column(String(20))
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    answers: Mapped[dict] = mapped_column(JSONB, default=dict)
    assumptions: Mapped[dict] = mapped_column(JSONB, default=dict)
    blocked_questions: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class LegacyBehaviorRow(Base):
    """Observed legacy behavior persistence for brownfield projects.

    Tracks behaviors discovered by agents in legacy systems.
    Supports the disposition flow: pending -> reviewed -> promoted.
    """

    __tablename__ = "legacy_behaviors"
    __table_args__ = ({"schema": "knowledge"},)

    entry_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    system: Mapped[str] = mapped_column(String(255), index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True, server_default="default")
    behavior_description: Mapped[str] = mapped_column(Text)
    inferred_by: Mapped[str] = mapped_column(String(100))
    inferred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[float] = mapped_column(Float)
    disposition: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    promoted_to_prl_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    discarded: Mapped[bool] = mapped_column(Boolean, default=False)
    source_manifest_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
