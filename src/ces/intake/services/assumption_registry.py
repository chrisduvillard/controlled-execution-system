"""Assumption registry service with BLOCK/FLAG enforcement and invalidation triggers.

Implements INTAKE-05: FLAG assumptions restricted to non-material only.
Material questions must BLOCK.

The registry stores assumptions in-memory with audit ledger persistence.
Assumptions are also stored in IntakeSessionRow.assumptions JSONB for
DB persistence (managed by IntakeInterviewEngine).

All assumption lifecycle events (register, invalidate, confirm) are
logged to the audit ledger when provided (T-05-08 mitigation).

Exports:
    AssumptionRegistryService: Service for managing intake assumptions.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import uuid4

from ces.control.models.intake import IntakeAssumption
from ces.shared.enums import ActorType, AssumptionCategory, EventType

if TYPE_CHECKING:
    from ces.intake.protocols import AuditLedgerProtocol


class AssumptionRegistryService:
    """Manages intake assumptions with BLOCK/FLAG enforcement.

    Stores assumptions in-memory with audit ledger integration.
    Enforces INTAKE-05 via the Pydantic model_validator on
    IntakeAssumption (FLAG + is_material=True raises ValueError).

    All lifecycle events are logged to the audit ledger:
    - ESCALATION for BLOCK assumptions
    - CLASSIFICATION for FLAG/PROCEED assumptions
    - INVALIDATION for invalidated assumptions
    - CLASSIFICATION for confirmed assumptions
    """

    def __init__(
        self,
        audit_ledger: AuditLedgerProtocol | None = None,
    ) -> None:
        """Initialize the assumption registry.

        Args:
            audit_ledger: AuditLedgerProtocol for logging governance events.
                          Optional -- works without for testing.
        """
        self._audit = audit_ledger
        self._assumptions: dict[str, IntakeAssumption] = {}

    def _fire_and_forget_audit(
        self,
        event_type: EventType,
        action_summary: str,
    ) -> None:
        """Log an event to the audit ledger if available.

        Uses fire-and-forget since register_assumption is synchronous
        but audit_ledger.append_event is async.
        """
        if self._audit is not None:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self._audit.append_event(
                        event_type=event_type,
                        actor="assumption_registry",
                        actor_type=ActorType.CONTROL_PLANE,
                        action_summary=action_summary,
                    )
                )
            except RuntimeError:
                # No running event loop -- skip audit in sync context
                pass

    # ---- Registration ----

    def register_assumption(
        self,
        question_id: str,
        assumed_value: str,
        category: AssumptionCategory,
        is_material: bool,
        invalidation_triggers: list[str] | None = None,
    ) -> IntakeAssumption:
        """Register a new assumption for an intake question.

        Creates an IntakeAssumption and stores it. The Pydantic model
        validator will raise ValueError if FLAG + is_material (INTAKE-05).

        Args:
            question_id: The question this assumption relates to.
            assumed_value: The assumed answer value.
            category: BLOCK, FLAG, or PROCEED.
            is_material: Whether the question is material.
            invalidation_triggers: Conditions that would invalidate this assumption.

        Returns:
            The created IntakeAssumption.

        Raises:
            ValueError: If category=FLAG and is_material=True (INTAKE-05).
        """
        assumption_id = f"ASMP-{uuid4().hex[:12]}"

        # IntakeAssumption model_validator enforces INTAKE-05:
        # FLAG + is_material=True -> ValueError
        assumption = IntakeAssumption(
            assumption_id=assumption_id,
            question_id=question_id,
            assumed_value=assumed_value,
            category=category,
            is_material=is_material,
            invalidation_triggers=tuple(invalidation_triggers) if invalidation_triggers else (),
            status="active",
        )

        self._assumptions[assumption_id] = assumption

        # Log to audit ledger
        # INTAKE-05: BLOCK assumptions get ESCALATION event type
        event_type = EventType.ESCALATION if category == AssumptionCategory.BLOCK else EventType.CLASSIFICATION
        self._fire_and_forget_audit(
            event_type=event_type,
            action_summary=(
                f"Registered {category.value} assumption {assumption_id} for question {question_id}: {assumed_value}"
            ),
        )

        return assumption

    # ---- Query methods ----

    def get_active_assumptions(self) -> list[IntakeAssumption]:
        """Return all assumptions with status='active'.

        Returns:
            List of active IntakeAssumption instances.
        """
        return [a for a in self._assumptions.values() if a.status == "active"]

    def get_blocked_questions(self) -> list[str]:
        """Return question_ids for active BLOCK assumptions.

        Returns:
            List of question_id strings where the assumption is
            BLOCK category and still active.
        """
        return [
            a.question_id
            for a in self._assumptions.values()
            if a.category == AssumptionCategory.BLOCK and a.status == "active"
        ]

    def get_assumptions_for_question(self, question_id: str) -> list[IntakeAssumption]:
        """Return all assumptions for a given question_id.

        Args:
            question_id: The question to filter by.

        Returns:
            List of IntakeAssumption instances for this question.
        """
        return [a for a in self._assumptions.values() if a.question_id == question_id]

    # ---- Lifecycle management ----

    def invalidate_assumption(self, assumption_id: str, reason: str) -> IntakeAssumption:
        """Invalidate an assumption.

        Changes status to 'invalidated' and logs to audit ledger.

        Args:
            assumption_id: The assumption to invalidate.
            reason: Why the assumption is being invalidated.

        Returns:
            The updated IntakeAssumption with status='invalidated'.

        Raises:
            KeyError: If assumption_id not found.
        """
        assumption = self._assumptions[assumption_id]
        updated = assumption.model_copy(update={"status": "invalidated"})
        self._assumptions[assumption_id] = updated

        self._fire_and_forget_audit(
            event_type=EventType.INVALIDATION,
            action_summary=(f"Invalidated assumption {assumption_id} for question {assumption.question_id}: {reason}"),
        )

        return updated

    def confirm_assumption(self, assumption_id: str) -> IntakeAssumption:
        """Confirm an assumption.

        Changes status to 'confirmed' and logs to audit ledger.

        Args:
            assumption_id: The assumption to confirm.

        Returns:
            The updated IntakeAssumption with status='confirmed'.

        Raises:
            KeyError: If assumption_id not found.
        """
        assumption = self._assumptions[assumption_id]
        updated = assumption.model_copy(update={"status": "confirmed"})
        self._assumptions[assumption_id] = updated

        self._fire_and_forget_audit(
            event_type=EventType.CLASSIFICATION,
            action_summary=(f"Confirmed assumption {assumption_id} for question {assumption.question_id}"),
        )

        return updated

    def check_invalidation_triggers(self, trigger_event: str) -> list[IntakeAssumption]:
        """Check if a trigger event invalidates any active assumptions.

        For each active assumption, checks if trigger_event contains
        any of the assumption's invalidation_triggers (string containment).
        Matching assumptions are automatically invalidated.

        Args:
            trigger_event: The event string to check against triggers.

        Returns:
            List of newly invalidated IntakeAssumption instances.
        """
        invalidated: list[IntakeAssumption] = []
        # Collect IDs first to avoid modifying dict during iteration
        to_invalidate: list[str] = []

        for assumption_id, assumption in self._assumptions.items():
            if assumption.status != "active":
                continue
            for trigger in assumption.invalidation_triggers:
                if trigger in trigger_event:
                    to_invalidate.append(assumption_id)
                    break

        for assumption_id in to_invalidate:
            updated = self.invalidate_assumption(assumption_id, reason=f"Trigger matched: {trigger_event}")
            invalidated.append(updated)

        return invalidated
