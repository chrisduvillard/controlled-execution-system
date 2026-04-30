"""Legacy behavior register service (BROWN-01, BROWN-02, BROWN-03).

Manages the Observed Legacy Behavior Register for brownfield projects.
Key invariants:
- BROWN-01: Stores inferred behaviors with confidence scores
- BROWN-02: register_behavior() NEVER creates a PRLItem directly.
  Legacy behaviors go to the register, NOT the PRL, until human disposition.
- BROWN-03: Copy-on-promote creates a NEW PRLItem with back-reference
  to the register entry. The original entry is PRESERVED (not deleted).

Threat mitigations:
- T-05-15: promote_to_prl requires approver string; DispositionWorkflow
  state machine prevents skipping the review step.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from ces.brownfield.records import LegacyBehaviorRecord
from ces.brownfield.services.disposition_workflow import DispositionWorkflow
from ces.control.models.prl_item import AcceptanceCriterion, PRLItem
from ces.harness.models.observed_legacy import ObservedLegacyBehavior
from ces.shared.enums import (
    ActorType,
    ArtifactStatus,
    EventType,
    LegacyDisposition,
    Priority,
    PRLItemType,
    VerificationMethod,
)


class LegacyBehaviorService:
    """Service managing the Observed Legacy Behavior Register.

    Implements BROWN-01 (register), BROWN-02 (separate from PRL),
    and BROWN-03 (disposition workflow with copy-on-promote).
    """

    def __init__(
        self,
        repository: object | None = None,
        audit_ledger: object | None = None,
    ) -> None:
        """Initialize with optional repository and audit ledger.

        Args:
            repository: LegacyBehaviorRepository for DB persistence.
            audit_ledger: Any object with append_event method for auditing.
        """
        self._repository = repository
        self._audit_ledger = audit_ledger

    async def register_behavior(
        self,
        *,
        system: str,
        behavior_description: str,
        inferred_by: str,
        confidence: float,
        source_manifest_id: str | None = None,
    ) -> ObservedLegacyBehavior:
        """Register a newly observed legacy behavior.

        BROWN-01: Creates an ObservedLegacyBehavior entry in the register.
        BROWN-02: This method NEVER creates a PRLItem. Legacy behaviors go
        to the register, NOT the PRL, until human disposition.

        Args:
            system: The legacy system where behavior was observed.
            behavior_description: Description of the observed behavior.
            inferred_by: ID of the agent that inferred the behavior.
            confidence: Confidence score (0.0 to 1.0).
            source_manifest_id: Optional manifest ID that triggered discovery.

        Returns:
            The created ObservedLegacyBehavior domain model.
        """
        entry_id = f"OLB-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        behavior = ObservedLegacyBehavior(
            entry_id=entry_id,
            system=system,
            behavior_description=behavior_description,
            inferred_by=inferred_by,
            inferred_at=now,
            confidence=confidence,
        )

        # Persist to DB if repository available
        if self._repository is not None:
            record = LegacyBehaviorRecord(
                entry_id=behavior.entry_id,
                system=behavior.system,
                behavior_description=behavior.behavior_description,
                inferred_by=behavior.inferred_by,
                inferred_at=behavior.inferred_at,
                confidence=behavior.confidence,
                source_manifest_id=source_manifest_id,
            )
            await self._repository.save(record)

        # Log to audit ledger
        if self._audit_ledger is not None:
            await self._audit_ledger.append_event(  # type: ignore[attr-defined]
                event_type=EventType.TRUTH_CHANGE,
                actor=inferred_by,
                actor_type=ActorType.AGENT,
                action_summary=(
                    f"Registered legacy behavior {entry_id} from system '{system}': {behavior_description}"
                ),
            )

        return behavior

    async def get_pending_behaviors(self) -> list[ObservedLegacyBehavior]:
        """Get all behaviors pending human disposition.

        Returns only entries with disposition=None and discarded=False.

        Returns:
            List of pending ObservedLegacyBehavior entries.
        """
        if self._repository is None:
            return []

        rows = await self._repository.get_pending()
        return [self._row_to_behavior(row) for row in rows]

    async def get_behaviors_by_system(self, system: str) -> list[ObservedLegacyBehavior]:
        """Get all behaviors for a specific legacy system.

        Args:
            system: The legacy system name to filter by.

        Returns:
            List of ObservedLegacyBehavior entries for the system.
        """
        if self._repository is None:
            return []

        rows = await self._repository.get_by_system(system)
        return [self._row_to_behavior(row) for row in rows]

    async def review_behavior(
        self,
        entry_id: str,
        disposition: LegacyDisposition,
        reviewed_by: str,
    ) -> ObservedLegacyBehavior:
        """Review a pending behavior and set its disposition.

        Validates that the entry is pending (disposition is None), then
        transitions through the DispositionWorkflow state machine.

        Args:
            entry_id: The behavior entry to review.
            disposition: The disposition decision (PRESERVE, CHANGE, RETIRE, etc.).
            reviewed_by: Human reviewer identifier.

        Returns:
            The updated ObservedLegacyBehavior.

        Raises:
            ValueError: If entry not found or not in pending state.
        """
        if self._repository is None:
            msg = "Repository required for review_behavior"
            raise RuntimeError(msg)

        row = await self._repository.get_by_id(entry_id)
        if row is None:
            msg = f"Legacy behavior entry not found: {entry_id}"
            raise ValueError(msg)

        if row.disposition is not None:
            msg = f"Entry {entry_id} already has disposition: {row.disposition}"
            raise ValueError(msg)

        # Validate state transition via DispositionWorkflow
        wf = DispositionWorkflow()
        wf.review()

        now = datetime.now(timezone.utc)
        updated_row = await self._repository.update_disposition(
            entry_id=entry_id,
            disposition=disposition.value,
            reviewed_by=reviewed_by,
            reviewed_at=now,
        )

        if updated_row is None:
            msg = f"Failed to update disposition for {entry_id}"
            raise ValueError(msg)

        # Log to audit ledger
        if self._audit_ledger is not None:
            await self._audit_ledger.append_event(  # type: ignore[attr-defined]
                event_type=EventType.TRUTH_CHANGE,
                actor=reviewed_by,
                actor_type=ActorType.HUMAN,
                action_summary=(f"Reviewed legacy behavior {entry_id}: disposition={disposition.value}"),
            )

        return self._row_to_behavior(updated_row)

    async def promote_to_prl(
        self,
        entry_id: str,
        approver: str,
        acceptance_criteria: list[dict] | None = None,
        negative_examples: list[str] | None = None,
    ) -> tuple[ObservedLegacyBehavior, PRLItem]:
        """Promote a reviewed behavior to the PRL via copy-on-promote (BROWN-03).

        Creates a NEW PRLItem from the behavior description. The original
        register entry is PRESERVED (not deleted) with a back-reference to
        the new PRL item. This is the copy-on-promote invariant.

        Args:
            entry_id: The behavior entry to promote.
            approver: Human approver identifier (T-05-15 requirement).
            acceptance_criteria: Optional custom acceptance criteria.
            negative_examples: Optional negative examples.

        Returns:
            Tuple of (updated register entry, new PRLItem).

        Raises:
            ValueError: If entry not found, not reviewed, or already discarded.
        """
        if self._repository is None:
            msg = "Repository required for promote_to_prl"
            raise RuntimeError(msg)

        row = await self._repository.get_by_id(entry_id)
        if row is None:
            msg = f"Legacy behavior entry not found: {entry_id}"
            raise ValueError(msg)

        if row.disposition is None:
            msg = f"Entry {entry_id} must be reviewed before promotion"
            raise ValueError(msg)

        if row.discarded:
            msg = f"Entry {entry_id} is discarded and cannot be promoted"
            raise ValueError(msg)

        if row.promoted_to_prl_id is not None:
            msg = f"Entry {entry_id} already promoted to {row.promoted_to_prl_id}"
            raise ValueError(msg)

        # Validate state transition via DispositionWorkflow
        wf = DispositionWorkflow(start_value="reviewed")
        wf.promote()

        # Copy-on-promote (BROWN-03): Create a NEW PRLItem
        now = datetime.now(timezone.utc)
        prl_id = f"PRL-{uuid.uuid4().hex[:12]}"

        criteria = acceptance_criteria or [
            {
                "criterion": "Behavior preserved as observed",
                "verification_method": VerificationMethod.MANUAL,
            }
        ]
        ac_list = [
            AcceptanceCriterion(
                criterion=c["criterion"],
                verification_method=(
                    c["verification_method"]
                    if isinstance(c["verification_method"], VerificationMethod)
                    else VerificationMethod(c["verification_method"])
                ),
            )
            for c in criteria
        ]

        prl_item = PRLItem(
            schema_type="prl_item",
            prl_id=prl_id,
            type=PRLItemType.CONSTRAINT,
            statement=row.behavior_description,
            acceptance_criteria=tuple(ac_list),
            negative_examples=tuple(negative_examples) if negative_examples else (),
            priority=Priority.MEDIUM,
            release_slice="brownfield-import",
            legacy_disposition=LegacyDisposition.PRESERVE,
            legacy_source_system=row.system,
            status=ArtifactStatus.DRAFT,
            version=1,
            owner=approver,
            created_at=now,
            last_confirmed=now,
        )

        # Set back-reference on register entry (copy-on-promote preserves original)
        promoted_row = await self._repository.mark_promoted(entry_id, prl_id)
        if promoted_row is None:
            msg = f"Failed to mark {entry_id} as promoted"
            raise ValueError(msg)
        save_prl_item = getattr(self._repository, "save_prl_item", None)
        if callable(save_prl_item):
            await save_prl_item(prl_item)

        # Log promotion to audit ledger
        if self._audit_ledger is not None:
            await self._audit_ledger.append_event(  # type: ignore[attr-defined]
                event_type=EventType.TRUTH_CHANGE,
                actor=approver,
                actor_type=ActorType.HUMAN,
                action_summary=(
                    f"Promoted legacy behavior {entry_id} to PRL item {prl_id} (copy-on-promote, BROWN-03)"
                ),
            )

        updated_entry = self._row_to_behavior(promoted_row)
        return updated_entry, prl_item

    async def discard_behavior(
        self,
        entry_id: str,
        reviewed_by: str,
        reason: str,
    ) -> ObservedLegacyBehavior:
        """Discard a behavior entry.

        Marks the entry as discarded. Cannot discard an already-promoted entry.

        Args:
            entry_id: The behavior entry to discard.
            reviewed_by: Human reviewer performing the discard.
            reason: Reason for discarding.

        Returns:
            The updated ObservedLegacyBehavior.

        Raises:
            ValueError: If entry not found or already promoted.
        """
        if self._repository is None:
            msg = "Repository required for discard_behavior"
            raise RuntimeError(msg)

        row = await self._repository.get_by_id(entry_id)
        if row is None:
            msg = f"Legacy behavior entry not found: {entry_id}"
            raise ValueError(msg)

        if row.promoted_to_prl_id is not None:
            msg = f"Entry {entry_id} is already promoted to {row.promoted_to_prl_id} and cannot be discarded"
            raise ValueError(msg)

        # Transition through DispositionWorkflow
        wf = DispositionWorkflow()
        wf.review()
        wf.discard()

        now = datetime.now(timezone.utc)

        # Update disposition to RETIRE and mark as discarded
        updated_row = await self._repository.update_disposition(
            entry_id=entry_id,
            disposition=LegacyDisposition.RETIRE.value,
            reviewed_by=reviewed_by,
            reviewed_at=now,
        )

        if updated_row is None:
            msg = f"Failed to update disposition for {entry_id}"
            raise ValueError(msg)

        # Mark discarded by setting the discarded flag on the row directly
        updated_row.discarded = True
        await self._repository.save(updated_row)

        # Log to audit ledger
        if self._audit_ledger is not None:
            await self._audit_ledger.append_event(  # type: ignore[attr-defined]
                event_type=EventType.TRUTH_CHANGE,
                actor=reviewed_by,
                actor_type=ActorType.HUMAN,
                action_summary=(f"Discarded legacy behavior {entry_id}: {reason}"),
            )

        return self._row_to_behavior(updated_row)

    @staticmethod
    def _row_to_behavior(row: object) -> ObservedLegacyBehavior:
        """Convert a repository-returned row to the ObservedLegacyBehavior domain model.

        ``row`` is duck-typed: the local SQLite repository returns
        :class:`ces.brownfield.records.LegacyBehaviorRecord` and the
        SQLAlchemy compatibility repository returns ``LegacyBehaviorRow``.
        Both expose the attribute set this method reads.
        """
        return ObservedLegacyBehavior(
            entry_id=row.entry_id,
            system=row.system,
            behavior_description=row.behavior_description,
            inferred_by=row.inferred_by,
            inferred_at=row.inferred_at,
            confidence=row.confidence,
            disposition=(LegacyDisposition(row.disposition) if row.disposition else None),
            reviewed_by=row.reviewed_by,
            reviewed_at=row.reviewed_at,
            promoted_to_prl_id=row.promoted_to_prl_id,
            discarded=row.discarded,
        )
