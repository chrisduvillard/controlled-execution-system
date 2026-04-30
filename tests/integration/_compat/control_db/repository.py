"""Data access repositories for CES control plane tables.

Each repository wraps an AsyncSession and provides typed methods
for common access patterns. Repositories do NOT own session lifecycle --
callers are responsible for commit/rollback.

CRITICAL: AuditRepository has NO update() or delete() methods.
This is the application-layer enforcement of D-07 (append-only audit ledger).
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ces.brownfield.records import LegacyBehaviorRecord
from ces.control.models.audit_entry_record import AuditEntryRecord
from ces.control.models.kill_switch_state import ActivityClass
from ces.control.models.manifest import TaskManifest
from tests.integration._compat.control_db.tables import (
    AuditEntryRow,
    HarnessProfileRow,
    IntakeSessionRow,
    KillSwitchStateRow,
    LegacyBehaviorRow,
    ManifestRow,
    TrustEventRow,
    TruthArtifactRow,
    VaultNoteRow,
)


class TruthArtifactRepository:
    """Data access for truth artifacts.

    Supports full CRUD since truth artifacts go through
    draft -> approved lifecycle transitions.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, row: TruthArtifactRow) -> TruthArtifactRow:
        """Insert or merge a truth artifact row."""
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_by_id(self, artifact_id: str) -> TruthArtifactRow | None:
        """Retrieve a truth artifact by its ID."""
        result = await self.session.execute(select(TruthArtifactRow).where(TruthArtifactRow.id == artifact_id))
        return result.scalar_one_or_none()

    async def get_by_type(self, artifact_type: str, project_id: str | None = None) -> list[TruthArtifactRow]:
        """Retrieve all truth artifacts of a given type."""
        stmt = select(TruthArtifactRow).where(TruthArtifactRow.type == artifact_type)
        if project_id is not None:
            stmt = stmt.where(TruthArtifactRow.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_approved(self, project_id: str | None = None) -> list[TruthArtifactRow]:
        """Retrieve all approved truth artifacts."""
        stmt = select(TruthArtifactRow).where(TruthArtifactRow.status == "approved")
        if project_id is not None:
            stmt = stmt.where(TruthArtifactRow.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, row: TruthArtifactRow) -> TruthArtifactRow:
        """Update an existing truth artifact (e.g., status promotion)."""
        merged = await self.session.merge(row)
        await self.session.flush()
        return merged

    async def delete(self, artifact_id: str) -> bool:
        """Delete a truth artifact by ID. Returns True if found."""
        row = await self.get_by_id(artifact_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True


_DEFAULT_PROJECT_ID = "default"


def _manifest_to_row(manifest: TaskManifest) -> ManifestRow:
    """Convert a runtime TaskManifest to the SQLAlchemy ORM row."""
    return ManifestRow(
        manifest_id=manifest.manifest_id,
        description=manifest.description,
        risk_tier=manifest.risk_tier.value,
        behavior_confidence=manifest.behavior_confidence.value,
        change_class=manifest.change_class.value,
        content=manifest.model_dump(mode="json"),
        content_hash=manifest.content_hash or "",
        signature=manifest.signature,
        status=manifest.status.value,
        expires_at=manifest.expires_at,
        classifier_id=manifest.classifier_id,
        implementer_id=manifest.implementer_id,
        project_id=_DEFAULT_PROJECT_ID,
        created_at=manifest.created_at,
        updated_at=datetime.now(timezone.utc),
    )


class ManifestRepository:
    """Data access for task manifests.

    Supports full CRUD for manifest lifecycle management.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, row: ManifestRow | TaskManifest) -> ManifestRow:
        """Insert or merge a manifest row.

        Accepts either the runtime ``TaskManifest`` domain model (used by
        ``ManifestManager``) or the SQLAlchemy ``ManifestRow`` (used by
        legacy compatibility tests). The domain model is converted internally.
        """
        if isinstance(row, TaskManifest):
            row = _manifest_to_row(row)
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_by_id(self, manifest_id: str) -> ManifestRow | None:
        """Retrieve a manifest by its ID."""
        result = await self.session.execute(select(ManifestRow).where(ManifestRow.manifest_id == manifest_id))
        return result.scalar_one_or_none()

    async def get_active(self, project_id: str | None = None) -> list[ManifestRow]:
        """Retrieve all manifests with non-terminal status."""
        stmt = select(ManifestRow).where(ManifestRow.status.in_(["draft", "approved", "in_flight"]))
        if project_id is not None:
            stmt = stmt.where(ManifestRow.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_all(self, project_id: str | None = None) -> list[ManifestRow]:
        """Retrieve every manifest regardless of status or workflow state.

        Unlike ``get_active``, this includes terminal manifests (merged,
        deployed, rejected, expired, failed, cancelled). Used by the spec
        lookup path so ``ces spec reconcile`` can see already-shipped stories.
        """
        stmt = select(ManifestRow)
        if project_id is not None:
            stmt = stmt.where(ManifestRow.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, row: ManifestRow) -> ManifestRow:
        """Update an existing manifest."""
        merged = await self.session.merge(row)
        await self.session.flush()
        return merged

    async def delete(self, manifest_id: str) -> bool:
        """Delete a manifest by ID. Returns True if found."""
        row = await self.get_by_id(manifest_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True


class AuditRepository:
    """Data access for the append-only audit ledger.

    CRITICAL: This repository intentionally has NO update() or delete()
    methods. The audit ledger is append-only per D-07. This is enforced
    at three levels:
    1. DB trigger: prevents UPDATE/DELETE on the table
    2. This repository: only exposes append() and read methods
    3. Hash chain: prev_hash links entries for tamper detection

    To correct an erroneous entry, append a new correction entry
    referencing the original.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(self, row: AuditEntryRecord | AuditEntryRow) -> AuditEntryRow:
        """Append a new audit entry. This is the only write operation.

        Accepts either the runtime ``AuditEntryRecord`` dataclass (used by
        ``AuditLedgerService``) or the SQLAlchemy ``AuditEntryRow`` (used by
        legacy compatibility tests). The dataclass is converted to the ORM
        row in-place.
        """
        if isinstance(row, AuditEntryRecord):
            row = AuditEntryRow(**asdict(row))
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_latest(self, limit: int = 50, project_id: str | None = None) -> list[AuditEntryRow]:
        """Retrieve the most recent audit entries, ordered by sequence."""
        stmt = select(AuditEntryRow).order_by(AuditEntryRow.sequence_num.desc()).limit(limit)
        if project_id is not None:
            stmt = stmt.where(AuditEntryRow.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_event_type(self, event_type: str, project_id: str | None = None) -> list[AuditEntryRow]:
        """Retrieve all audit entries of a given event type."""
        stmt = select(AuditEntryRow).where(AuditEntryRow.event_type == event_type)
        if project_id is not None:
            stmt = stmt.where(AuditEntryRow.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_actor(self, actor: str, project_id: str | None = None) -> list[AuditEntryRow]:
        """Retrieve all audit entries by a specific actor."""
        stmt = select(AuditEntryRow).where(AuditEntryRow.actor == actor)
        if project_id is not None:
            stmt = stmt.where(AuditEntryRow.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_time_range(
        self, start: datetime, end: datetime, project_id: str | None = None
    ) -> list[AuditEntryRow]:
        """Retrieve audit entries within a time range."""
        stmt = select(AuditEntryRow).where(
            AuditEntryRow.timestamp >= start,
            AuditEntryRow.timestamp <= end,
        )
        if project_id is not None:
            stmt = stmt.where(AuditEntryRow.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_last_entry(self, project_id: str | None = None) -> AuditEntryRow | None:
        """Get the most recent entry for hash chain continuation."""
        stmt = select(AuditEntryRow).order_by(AuditEntryRow.sequence_num.desc()).limit(1)
        if project_id is not None:
            stmt = stmt.where(AuditEntryRow.project_id == project_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, entry_id: str) -> AuditEntryRow | None:
        """Retrieve a specific audit entry by ID."""
        result = await self.session.execute(select(AuditEntryRow).where(AuditEntryRow.entry_id == entry_id))
        return result.scalar_one_or_none()


class KillSwitchRepository:
    """Data access for kill switch state per activity class.

    Manages the control.kill_switch_state table which has one row
    per activity class (7 total). Supports upsert for activate/recover
    operations and bulk initialization of defaults.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_all(self) -> list[KillSwitchStateRow]:
        """Retrieve all kill switch state rows."""
        result = await self.session.execute(select(KillSwitchStateRow))
        return list(result.scalars().all())

    async def get_by_activity_class(self, activity_class: str) -> KillSwitchStateRow | None:
        """Retrieve kill switch state for a specific activity class."""
        result = await self.session.execute(
            select(KillSwitchStateRow).where(KillSwitchStateRow.activity_class == activity_class)
        )
        return result.scalar_one_or_none()

    async def upsert(self, row: KillSwitchStateRow) -> KillSwitchStateRow:
        """Insert or update a kill switch state row (merge operation)."""
        merged = await self.session.merge(row)
        await self.session.flush()
        return merged

    async def initialize_defaults(self) -> None:
        """Create one row per activity class with halted=False if not exists.

        Called at startup to ensure all 7 activity classes have rows.
        Uses merge to avoid conflicts with existing rows.
        """
        for ac in ActivityClass:
            existing = await self.get_by_activity_class(ac.value)
            if existing is None:
                row = KillSwitchStateRow(
                    activity_class=ac.value,
                    halted=False,
                )
                self.session.add(row)
        await self.session.flush()


class HarnessProfileRepository:
    """Data access for agent harness profiles.

    Supports read and write operations for harness profile persistence.
    Profiles track agent trust status and are queried by the calibrate
    command for hidden check pass rate computation.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_all(self, project_id: str | None = None) -> list[HarnessProfileRow]:
        """Retrieve all harness profiles."""
        stmt = select(HarnessProfileRow)
        if project_id is not None:
            stmt = stmt.where(HarnessProfileRow.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, profile_id: str) -> HarnessProfileRow | None:
        """Retrieve a harness profile by its ID."""
        result = await self.session.execute(select(HarnessProfileRow).where(HarnessProfileRow.profile_id == profile_id))
        return result.scalar_one_or_none()

    async def save(self, row: HarnessProfileRow) -> HarnessProfileRow:
        """Insert or merge a harness profile row."""
        self.session.add(row)
        await self.session.flush()
        return row


class TrustEventRepository:
    """Data access for trust lifecycle events.

    Records trust status transitions (promotion, contraction, recovery)
    for harness profiles. Append-and-read pattern -- trust events are
    historical records that should not be modified.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, row: TrustEventRow) -> TrustEventRow:
        """Insert a new trust event row."""
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_by_profile(self, profile_id: str, limit: int = 50) -> list[TrustEventRow]:
        """Retrieve trust events for a profile, ordered by most recent first."""
        result = await self.session.execute(
            select(TrustEventRow)
            .where(TrustEventRow.profile_id == profile_id)
            .order_by(TrustEventRow.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Knowledge plane repositories
# ---------------------------------------------------------------------------


class VaultRepository:
    """Data access for knowledge vault notes.

    Supports full CRUD plus category/trust-level filtering and
    JSONB tag search. The knowledge vault is informational only.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, row: VaultNoteRow) -> VaultNoteRow:
        """Insert a new vault note row."""
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_by_id(self, note_id: str) -> VaultNoteRow | None:
        """Retrieve a vault note by its ID."""
        result = await self.session.execute(select(VaultNoteRow).where(VaultNoteRow.note_id == note_id))
        return result.scalar_one_or_none()

    async def get_by_category(self, category: str, project_id: str | None = None) -> list[VaultNoteRow]:
        """Retrieve all vault notes in a given category."""
        stmt = select(VaultNoteRow).where(VaultNoteRow.category == category)
        if project_id is not None:
            stmt = stmt.where((VaultNoteRow.project_id == project_id) | (VaultNoteRow.project_id.is_(None)))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_trust_level(self, trust_level: str, project_id: str | None = None) -> list[VaultNoteRow]:
        """Retrieve all vault notes with a given trust level."""
        stmt = select(VaultNoteRow).where(VaultNoteRow.trust_level == trust_level)
        if project_id is not None:
            stmt = stmt.where((VaultNoteRow.project_id == project_id) | (VaultNoteRow.project_id.is_(None)))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_trust_level(self, note_id: str, new_level: str) -> VaultNoteRow | None:
        """Update the trust level of a vault note."""
        row = await self.get_by_id(note_id)
        if row is None:
            return None
        row.trust_level = new_level
        await self.session.flush()
        return row

    async def search_by_tags(self, tags: list[str]) -> list[VaultNoteRow]:
        """Search vault notes by JSONB tags using the ?| operator."""
        result = await self.session.execute(select(VaultNoteRow).where(VaultNoteRow.tags.op("?|")(tags)))
        return list(result.scalars().all())

    async def delete(self, note_id: str) -> bool:
        """Delete a vault note by ID. Returns True if found."""
        row = await self.get_by_id(note_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True


class IntakeRepository:
    """Data access for intake interview sessions.

    Supports CRUD plus project-based filtering and
    stage/answers update operations.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, row: IntakeSessionRow) -> IntakeSessionRow:
        """Insert a new intake session row."""
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_by_id(self, session_id: str) -> IntakeSessionRow | None:
        """Retrieve an intake session by its ID."""
        result = await self.session.execute(select(IntakeSessionRow).where(IntakeSessionRow.session_id == session_id))
        return result.scalar_one_or_none()

    async def get_by_project(self, project_id: str) -> list[IntakeSessionRow]:
        """Retrieve all intake sessions for a project."""
        result = await self.session.execute(select(IntakeSessionRow).where(IntakeSessionRow.project_id == project_id))
        return list(result.scalars().all())

    async def update_stage(self, session_id: str, new_stage: str) -> IntakeSessionRow | None:
        """Update the current stage of an intake session."""
        row = await self.get_by_id(session_id)
        if row is None:
            return None
        row.current_stage = new_stage
        await self.session.flush()
        return row

    async def update_answers(self, session_id: str, answers: dict) -> IntakeSessionRow | None:
        """Update the answers JSONB of an intake session."""
        row = await self.get_by_id(session_id)
        if row is None:
            return None
        row.answers = answers
        await self.session.flush()
        return row


class LegacyBehaviorRepository:
    """Data access for observed legacy behavior entries.

    Supports CRUD plus system-based filtering, pending-entry
    retrieval, and disposition/promotion workflows.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, row: LegacyBehaviorRecord | LegacyBehaviorRow) -> LegacyBehaviorRow:
        """Insert a new legacy behavior entry.

        Accepts either the runtime ``LegacyBehaviorRecord`` dataclass (used by
        ``LegacyBehaviorService``) or the SQLAlchemy ``LegacyBehaviorRow``.
        """
        if isinstance(row, LegacyBehaviorRecord):
            row = LegacyBehaviorRow(**asdict(row))
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_by_id(self, entry_id: str) -> LegacyBehaviorRow | None:
        """Retrieve a legacy behavior entry by its ID."""
        result = await self.session.execute(select(LegacyBehaviorRow).where(LegacyBehaviorRow.entry_id == entry_id))
        return result.scalar_one_or_none()

    async def get_by_system(self, system: str, project_id: str | None = None) -> list[LegacyBehaviorRow]:
        """Retrieve all legacy behavior entries for a system."""
        stmt = select(LegacyBehaviorRow).where(LegacyBehaviorRow.system == system)
        if project_id is not None:
            stmt = stmt.where(LegacyBehaviorRow.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_pending(self, project_id: str | None = None) -> list[LegacyBehaviorRow]:
        """Retrieve entries with no disposition and not discarded."""
        stmt = select(LegacyBehaviorRow).where(
            LegacyBehaviorRow.disposition.is_(None),
            LegacyBehaviorRow.discarded == False,  # noqa: E712
        )
        if project_id is not None:
            stmt = stmt.where(LegacyBehaviorRow.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_disposition(
        self,
        entry_id: str,
        disposition: str,
        reviewed_by: str,
        reviewed_at: datetime,
    ) -> LegacyBehaviorRow | None:
        """Set disposition and reviewer info for an entry."""
        row = await self.get_by_id(entry_id)
        if row is None:
            return None
        row.disposition = disposition
        row.reviewed_by = reviewed_by
        row.reviewed_at = reviewed_at
        await self.session.flush()
        return row

    async def mark_promoted(self, entry_id: str, prl_id: str) -> LegacyBehaviorRow | None:
        """Mark an entry as promoted to a PRL item."""
        row = await self.get_by_id(entry_id)
        if row is None:
            return None
        row.promoted_to_prl_id = prl_id
        await self.session.flush()
        return row
