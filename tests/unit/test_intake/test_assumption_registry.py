"""Tests for the assumption registry service.

Tests cover:
- register_assumption() creates and stores IntakeAssumption
- INTAKE-05: FLAG + is_material=True raises ValueError
- BLOCK assumptions stored with status="active"
- Audit ledger integration for register_assumption
- get_active_assumptions() returns only active
- get_blocked_questions() returns BLOCK question_ids
- invalidate_assumption() changes status and logs
- confirm_assumption() changes status and logs
- check_invalidation_triggers() auto-invalidates matching assumptions
- get_assumptions_for_question() filters by question_id
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ces.intake.protocols import AuditLedgerProtocol
from ces.intake.services.assumption_registry import AssumptionRegistryService
from ces.shared.enums import AssumptionCategory


class TestRegisterAssumption:
    """Test assumption registration."""

    async def test_register_creates_assumption(self) -> None:
        """Test 1: register_assumption() creates IntakeAssumption and stores it."""
        registry = AssumptionRegistryService()
        assumption = registry.register_assumption(
            question_id="Q-P1-M01",
            assumed_value="Python 3.12",
            category=AssumptionCategory.PROCEED,
            is_material=False,
        )
        assert assumption.question_id == "Q-P1-M01"
        assert assumption.assumed_value == "Python 3.12"
        assert assumption.category == AssumptionCategory.PROCEED
        assert assumption.assumption_id.startswith("ASMP-")

    async def test_flag_material_raises_value_error(self) -> None:
        """Test 2: register_assumption() with category=FLAG and is_material=True raises ValueError (INTAKE-05)."""
        registry = AssumptionRegistryService()
        with pytest.raises(ValueError, match="FLAG assumptions restricted to non-material only"):
            registry.register_assumption(
                question_id="Q-P1-M01",
                assumed_value="some value",
                category=AssumptionCategory.FLAG,
                is_material=True,
            )

    async def test_block_assumption_has_active_status(self) -> None:
        """Test 3: register_assumption() with category=BLOCK returns the assumption with status='active'."""
        registry = AssumptionRegistryService()
        assumption = registry.register_assumption(
            question_id="Q-P1-M03",
            assumed_value="preserve all behavior",
            category=AssumptionCategory.BLOCK,
            is_material=True,
        )
        assert assumption.status == "active"
        assert assumption.category == AssumptionCategory.BLOCK

    async def test_register_logs_to_audit_ledger(self) -> None:
        """Test 4: register_assumption() logs to audit ledger when provided."""
        audit_mock = AsyncMock(spec=AuditLedgerProtocol)
        registry = AssumptionRegistryService(audit_ledger=audit_mock)
        registry.register_assumption(
            question_id="Q-P1-M01",
            assumed_value="Python",
            category=AssumptionCategory.BLOCK,
            is_material=True,
        )
        assert audit_mock.append_event.call_count >= 1


class TestQueryAssumptions:
    """Test assumption query methods."""

    async def test_get_active_assumptions(self) -> None:
        """Test 5: get_active_assumptions() returns only assumptions with status='active'."""
        registry = AssumptionRegistryService()
        a1 = registry.register_assumption(
            question_id="Q1",
            assumed_value="v1",
            category=AssumptionCategory.PROCEED,
            is_material=False,
        )
        a2 = registry.register_assumption(
            question_id="Q2",
            assumed_value="v2",
            category=AssumptionCategory.PROCEED,
            is_material=False,
        )
        # Invalidate one
        registry.invalidate_assumption(a1.assumption_id, reason="wrong")
        active = registry.get_active_assumptions()
        assert len(active) == 1
        assert active[0].assumption_id == a2.assumption_id

    async def test_get_blocked_questions(self) -> None:
        """Test 6: get_blocked_questions() returns question_ids for BLOCK assumptions."""
        registry = AssumptionRegistryService()
        registry.register_assumption(
            question_id="Q1",
            assumed_value="v1",
            category=AssumptionCategory.BLOCK,
            is_material=True,
        )
        registry.register_assumption(
            question_id="Q2",
            assumed_value="v2",
            category=AssumptionCategory.PROCEED,
            is_material=False,
        )
        blocked = registry.get_blocked_questions()
        assert blocked == ["Q1"]


class TestAssumptionLifecycle:
    """Test assumption invalidation and confirmation."""

    async def test_invalidate_assumption(self) -> None:
        """Test 7: invalidate_assumption() changes status to 'invalidated' and logs event."""
        audit_mock = AsyncMock(spec=AuditLedgerProtocol)
        registry = AssumptionRegistryService(audit_ledger=audit_mock)
        a = registry.register_assumption(
            question_id="Q1",
            assumed_value="v1",
            category=AssumptionCategory.PROCEED,
            is_material=False,
        )
        audit_mock.reset_mock()
        updated = registry.invalidate_assumption(a.assumption_id, reason="new info")
        assert updated.status == "invalidated"
        assert audit_mock.append_event.call_count >= 1

    async def test_confirm_assumption(self) -> None:
        """Test 8: confirm_assumption() changes status to 'confirmed' and logs event."""
        audit_mock = AsyncMock(spec=AuditLedgerProtocol)
        registry = AssumptionRegistryService(audit_ledger=audit_mock)
        a = registry.register_assumption(
            question_id="Q1",
            assumed_value="v1",
            category=AssumptionCategory.PROCEED,
            is_material=False,
        )
        audit_mock.reset_mock()
        updated = registry.confirm_assumption(a.assumption_id)
        assert updated.status == "confirmed"
        assert audit_mock.append_event.call_count >= 1

    async def test_check_invalidation_triggers(self) -> None:
        """Test 9: check_invalidation_triggers() detects when trigger conditions match and auto-invalidates."""
        registry = AssumptionRegistryService()
        registry.register_assumption(
            question_id="Q1",
            assumed_value="v1",
            category=AssumptionCategory.PROCEED,
            is_material=False,
            invalidation_triggers=["schema_change", "api_update"],
        )
        registry.register_assumption(
            question_id="Q2",
            assumed_value="v2",
            category=AssumptionCategory.PROCEED,
            is_material=False,
            invalidation_triggers=["config_change"],
        )
        invalidated = registry.check_invalidation_triggers("schema_change detected")
        assert len(invalidated) == 1
        assert invalidated[0].question_id == "Q1"
        assert invalidated[0].status == "invalidated"

    async def test_get_assumptions_for_question(self) -> None:
        """Test 10: get_assumptions_for_question() returns all assumptions for a given question_id."""
        registry = AssumptionRegistryService()
        registry.register_assumption(
            question_id="Q1",
            assumed_value="v1",
            category=AssumptionCategory.PROCEED,
            is_material=False,
        )
        registry.register_assumption(
            question_id="Q1",
            assumed_value="v2",
            category=AssumptionCategory.FLAG,
            is_material=False,
        )
        registry.register_assumption(
            question_id="Q2",
            assumed_value="v3",
            category=AssumptionCategory.PROCEED,
            is_material=False,
        )
        q1_assumptions = registry.get_assumptions_for_question("Q1")
        assert len(q1_assumptions) == 2
        assert all(a.question_id == "Q1" for a in q1_assumptions)


def test_register_in_sync_context_silently_skips_audit() -> None:
    """When called from a sync context (no event loop), the audit-event hook
    catches the RuntimeError from get_running_loop() and continues silently."""
    audit_mock = AsyncMock(spec=AuditLedgerProtocol)
    registry = AssumptionRegistryService(audit_ledger=audit_mock)
    # No event loop is running here -- the create_task path raises RuntimeError
    # which the registry must swallow.
    assumption = registry.register_assumption(
        question_id="Q-SYNC",
        assumed_value="x",
        category=AssumptionCategory.PROCEED,
        is_material=False,
    )
    assert assumption.question_id == "Q-SYNC"
    # The audit event was never enqueued because there was no loop to schedule it on.
    audit_mock.append_event.assert_not_called()


async def test_check_invalidation_triggers_skips_already_invalidated() -> None:
    """An assumption already marked invalidated is not re-considered for trigger matching."""
    registry = AssumptionRegistryService()
    a = registry.register_assumption(
        question_id="Q-X",
        assumed_value="v",
        category=AssumptionCategory.PROCEED,
        is_material=False,
        invalidation_triggers=["schema_change"],
    )
    registry.invalidate_assumption(a.assumption_id, reason="manual override")
    # Trigger event would have matched, but the assumption is no longer active.
    invalidated = registry.check_invalidation_triggers("schema_change detected")
    assert invalidated == []
