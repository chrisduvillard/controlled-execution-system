"""Tests for TrustManager service and TrustLifecycle state machine.

Covers:
- TrustLifecycle state machine transitions (Task 1)
- TrustEventRow DB table schema (Task 1)
- TrustEventRepository (Task 1)
- TrustManager auto-promotion (TRUST-02, D-07)
- TrustManager escape contraction (TRUST-03, D-08)
- TrustManager recovery lifecycle (D-08)
- TrustManager autonomy ceilings (TRUST-04)
- Kill switch guard integration (D-06)
- Audit ledger integration (WORK-03)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from statemachine.exceptions import TransitionNotAllowed

from ces.harness.models.harness_profile import HarnessProfile
from ces.shared.enums import (
    BehaviorConfidence,
    ChangeClass,
    GateType,
    RiskTier,
    TrustStatus,
)

# ---------------------------------------------------------------------------
# Task 1: TrustLifecycle state machine tests
# ---------------------------------------------------------------------------


class TestTrustLifecycle:
    """Tests for the TrustLifecycle state machine transitions."""

    def test_lifecycle_initial_state_is_candidate(self) -> None:
        """TrustLifecycle starts in 'candidate' state."""
        from ces.harness.services.trust_manager import TrustLifecycle

        sm = TrustLifecycle()
        assert next(iter(sm.configuration)).id == "candidate"

    def test_promote_transition_candidate_to_trusted(self) -> None:
        """promote: candidate -> trusted."""
        from ces.harness.services.trust_manager import TrustLifecycle

        sm = TrustLifecycle()
        sm.promote()
        assert next(iter(sm.configuration)).id == "trusted"

    def test_contract_to_watch_from_trusted(self) -> None:
        """contract_to_watch: trusted -> watch."""
        from ces.harness.services.trust_manager import TrustLifecycle

        sm = TrustLifecycle()
        sm.promote()
        sm.contract_to_watch()
        assert next(iter(sm.configuration)).id == "watch"

    def test_contract_to_watch_from_candidate(self) -> None:
        """contract_to_watch: candidate -> watch."""
        from ces.harness.services.trust_manager import TrustLifecycle

        sm = TrustLifecycle()
        sm.contract_to_watch()
        assert next(iter(sm.configuration)).id == "watch"

    def test_contract_to_constrained_from_watch(self) -> None:
        """contract_to_constrained: watch -> constrained."""
        from ces.harness.services.trust_manager import TrustLifecycle

        sm = TrustLifecycle()
        sm.contract_to_watch()
        sm.contract_to_constrained()
        assert next(iter(sm.configuration)).id == "constrained"

    def test_contract_to_constrained_from_trusted(self) -> None:
        """contract_to_constrained: trusted -> constrained."""
        from ces.harness.services.trust_manager import TrustLifecycle

        sm = TrustLifecycle()
        sm.promote()
        sm.contract_to_constrained()
        assert next(iter(sm.configuration)).id == "constrained"

    def test_recover_from_watch_to_trusted(self) -> None:
        """recover_from_watch: watch -> trusted."""
        from ces.harness.services.trust_manager import TrustLifecycle

        sm = TrustLifecycle()
        sm.contract_to_watch()
        sm.recover_from_watch()
        assert next(iter(sm.configuration)).id == "trusted"

    def test_recover_from_constrained_to_candidate(self) -> None:
        """recover_from_constrained: constrained -> candidate."""
        from ces.harness.services.trust_manager import TrustLifecycle

        sm = TrustLifecycle()
        sm.contract_to_watch()
        sm.contract_to_constrained()
        sm.recover_from_constrained()
        assert next(iter(sm.configuration)).id == "candidate"

    def test_invalid_transition_constrained_to_trusted(self) -> None:
        """Invalid: constrained -> trusted directly raises TransitionNotAllowed."""
        from ces.harness.services.trust_manager import TrustLifecycle

        sm = TrustLifecycle()
        sm.contract_to_watch()
        sm.contract_to_constrained()
        with pytest.raises(TransitionNotAllowed):
            sm.promote()

    def test_invalid_transition_candidate_promote_twice(self) -> None:
        """Invalid: promote from trusted raises TransitionNotAllowed."""
        from ces.harness.services.trust_manager import TrustLifecycle

        sm = TrustLifecycle()
        sm.promote()
        with pytest.raises(TransitionNotAllowed):
            sm.promote()

    def test_invalid_transition_recover_from_trusted(self) -> None:
        """Invalid: recover_from_watch when not in watch state."""
        from ces.harness.services.trust_manager import TrustLifecycle

        sm = TrustLifecycle()
        sm.promote()
        with pytest.raises(TransitionNotAllowed):
            sm.recover_from_watch()

    def test_lifecycle_start_value_reconstruction(self) -> None:
        """TrustLifecycle can be reconstructed from a known state."""
        from ces.harness.services.trust_manager import TrustLifecycle

        sm = TrustLifecycle(start_value="watch")
        assert next(iter(sm.configuration)).id == "watch"
        sm.contract_to_constrained()
        assert next(iter(sm.configuration)).id == "constrained"


# ---------------------------------------------------------------------------
# Task 1: TrustEventRow DB table schema tests
# ---------------------------------------------------------------------------


class TestTrustEventRow:
    """Tests for the TrustEventRow DB table definition."""

    def test_trust_event_row_table_exists(self) -> None:
        """TrustEventRow is defined in tables.py."""
        from tests.integration._compat.control_db.tables import TrustEventRow

        assert TrustEventRow.__tablename__ == "trust_events"

    def test_trust_event_row_schema(self) -> None:
        """TrustEventRow uses harness schema."""
        from tests.integration._compat.control_db.tables import TrustEventRow

        assert TrustEventRow.__table_args__[-1]["schema"] == "harness"

    def test_trust_event_row_has_required_columns(self) -> None:
        """TrustEventRow has event_id, profile_id, old_status, new_status, trigger, metadata_extra, created_at."""
        from tests.integration._compat.control_db.tables import TrustEventRow

        columns = TrustEventRow.__table__.columns
        column_names = {c.name for c in columns}
        expected = {
            "event_id",
            "profile_id",
            "old_status",
            "new_status",
            "trigger",
            "metadata_extra",
            "created_at",
        }
        assert expected.issubset(column_names)

    def test_trust_event_row_profile_id_indexed(self) -> None:
        """profile_id column is indexed for fast lookups."""
        from tests.integration._compat.control_db.tables import TrustEventRow

        col = TrustEventRow.__table__.columns["profile_id"]
        assert col.index is True


# ---------------------------------------------------------------------------
# Task 1: TrustEventRepository tests
# ---------------------------------------------------------------------------


class TestTrustEventRepository:
    """Tests for the TrustEventRepository data access layer."""

    def test_trust_event_repository_class_exists(self) -> None:
        """TrustEventRepository is importable from repository module."""
        from tests.integration._compat.control_db.repository import TrustEventRepository

        assert TrustEventRepository is not None

    def test_trust_event_repository_has_save_method(self) -> None:
        """TrustEventRepository has a save method."""
        from tests.integration._compat.control_db.repository import TrustEventRepository

        assert hasattr(TrustEventRepository, "save")

    def test_trust_event_repository_has_get_by_profile_method(self) -> None:
        """TrustEventRepository has a get_by_profile method."""
        from tests.integration._compat.control_db.repository import TrustEventRepository

        assert hasattr(TrustEventRepository, "get_by_profile")


# ---------------------------------------------------------------------------
# Task 2: TrustManager promotion tests (TRUST-02, D-07)
# ---------------------------------------------------------------------------


def _make_promotable_profile() -> HarnessProfile:
    """Create a HarnessProfile that meets all TRUST-02 promotion criteria."""
    return HarnessProfile(
        profile_id="prof-001",
        agent_id="agent-001",
        trust_status=TrustStatus.CANDIDATE,
        completed_tasks=15,
        active_since=datetime.now(timezone.utc) - timedelta(days=30),
        change_classes_covered={
            ChangeClass.CLASS_1,
            ChangeClass.CLASS_2,
            ChangeClass.CLASS_3,
        },
        production_releases=2,
        escapes=0,
        escape_history=(),
    )


def _make_non_promotable_profile() -> HarnessProfile:
    """Create a HarnessProfile that does NOT meet promotion criteria."""
    return HarnessProfile(
        profile_id="prof-002",
        agent_id="agent-002",
        trust_status=TrustStatus.CANDIDATE,
        completed_tasks=3,  # too few
        active_since=datetime.now(timezone.utc) - timedelta(days=5),  # too short
        change_classes_covered={ChangeClass.CLASS_1},  # too few
        production_releases=0,  # none
    )


class TestTrustManagerPromotion:
    """Tests for TrustManager.evaluate_promotion (TRUST-02, D-07)."""

    @pytest.mark.asyncio
    async def test_promotion_candidate_to_trusted_when_eligible(self) -> None:
        """evaluate_promotion promotes CANDIDATE to TRUSTED when can_promote is True."""
        from ces.harness.services.trust_manager import TrustManager

        tm = TrustManager()
        profile = _make_promotable_profile()
        assert profile.can_promote is True

        result = await tm.evaluate_promotion(profile)
        assert result.trust_status == TrustStatus.TRUSTED

    @pytest.mark.asyncio
    async def test_promotion_no_change_when_not_eligible(self) -> None:
        """evaluate_promotion does NOT change status when can_promote is False."""
        from ces.harness.services.trust_manager import TrustManager

        tm = TrustManager()
        profile = _make_non_promotable_profile()
        assert profile.can_promote is False

        result = await tm.evaluate_promotion(profile)
        assert result.trust_status == TrustStatus.CANDIDATE

    @pytest.mark.asyncio
    async def test_promotion_no_change_when_already_trusted(self) -> None:
        """evaluate_promotion does nothing if profile is already TRUSTED."""
        from ces.harness.services.trust_manager import TrustManager

        tm = TrustManager()
        profile = _make_promotable_profile()
        profile.trust_status = TrustStatus.TRUSTED

        result = await tm.evaluate_promotion(profile)
        assert result.trust_status == TrustStatus.TRUSTED


# ---------------------------------------------------------------------------
# Task 2: TrustManager contraction tests (TRUST-03, D-08)
# ---------------------------------------------------------------------------


class TestTrustManagerContraction:
    """Tests for TrustManager.record_escape (TRUST-03)."""

    @pytest.mark.asyncio
    async def test_contraction_trusted_to_watch_on_escape(self) -> None:
        """record_escape on TRUSTED profile transitions to WATCH."""
        from ces.harness.services.trust_manager import TrustManager

        tm = TrustManager()
        profile = _make_promotable_profile()
        profile.trust_status = TrustStatus.TRUSTED

        result = await tm.record_escape(profile, "ESC-001", severity=2)
        assert result.trust_status == TrustStatus.WATCH
        assert result.escapes == 1
        assert "ESC-001" in result.escape_history

    @pytest.mark.asyncio
    async def test_contraction_watch_to_constrained_on_repeated_escape(
        self,
    ) -> None:
        """record_escape on WATCH profile transitions to CONSTRAINED (repeated escape)."""
        from ces.harness.services.trust_manager import TrustManager

        tm = TrustManager()
        profile = _make_promotable_profile()
        profile.trust_status = TrustStatus.WATCH
        profile.escapes = 1

        result = await tm.record_escape(profile, "ESC-002", severity=2)
        assert result.trust_status == TrustStatus.CONSTRAINED
        assert result.escapes == 2

    @pytest.mark.asyncio
    async def test_contraction_candidate_to_watch_on_escape(self) -> None:
        """record_escape on CANDIDATE profile transitions to WATCH."""
        from ces.harness.services.trust_manager import TrustManager

        tm = TrustManager()
        profile = _make_non_promotable_profile()
        assert profile.trust_status == TrustStatus.CANDIDATE

        result = await tm.record_escape(profile, "ESC-003", severity=2)
        assert result.trust_status == TrustStatus.WATCH
        assert result.escapes == 1


# ---------------------------------------------------------------------------
# Task 2: TrustManager recovery tests (D-08)
# ---------------------------------------------------------------------------


class TestTrustManagerRecovery:
    """Tests for TrustManager.attempt_recovery (D-08)."""

    @pytest.mark.asyncio
    async def test_recovery_from_watch_to_trusted(self) -> None:
        """attempt_recovery from WATCH with can_promote=True transitions to TRUSTED."""
        from ces.harness.services.trust_manager import TrustManager

        tm = TrustManager()
        profile = _make_promotable_profile()
        profile.trust_status = TrustStatus.WATCH
        assert profile.can_promote is True

        result = await tm.attempt_recovery(profile)
        assert result.trust_status == TrustStatus.TRUSTED

    @pytest.mark.asyncio
    async def test_recovery_from_constrained_to_candidate(self) -> None:
        """attempt_recovery from CONSTRAINED transitions to CANDIDATE (must re-earn trust)."""
        from ces.harness.services.trust_manager import TrustManager

        tm = TrustManager()
        profile = _make_promotable_profile()
        profile.trust_status = TrustStatus.CONSTRAINED

        result = await tm.attempt_recovery(profile)
        assert result.trust_status == TrustStatus.CANDIDATE

    @pytest.mark.asyncio
    async def test_recovery_from_watch_fails_if_not_eligible(self) -> None:
        """attempt_recovery from WATCH without can_promote does NOT transition."""
        from ces.harness.services.trust_manager import TrustManager

        tm = TrustManager()
        profile = _make_non_promotable_profile()
        profile.trust_status = TrustStatus.WATCH
        assert profile.can_promote is False

        result = await tm.attempt_recovery(profile)
        assert result.trust_status == TrustStatus.WATCH


# ---------------------------------------------------------------------------
# Task 2: TrustManager autonomy ceiling tests (TRUST-04)
# ---------------------------------------------------------------------------


class TestTrustManagerAutonomyCeiling:
    """Tests for TrustManager.get_autonomy_ceiling (TRUST-04)."""

    def test_autonomy_ceiling_bc3_always_human(self) -> None:
        """BC3 always returns HUMAN gate regardless of tier or trust."""
        from ces.harness.services.trust_manager import TrustManager

        result = TrustManager.get_autonomy_ceiling(BehaviorConfidence.BC3, RiskTier.C, TrustStatus.TRUSTED)
        assert result == GateType.HUMAN

    def test_autonomy_ceiling_bc2_tier_a_human(self) -> None:
        """BC2 + Tier A returns HUMAN (ceiling)."""
        from ces.harness.services.trust_manager import TrustManager

        result = TrustManager.get_autonomy_ceiling(BehaviorConfidence.BC2, RiskTier.A, TrustStatus.TRUSTED)
        assert result == GateType.HUMAN

    def test_autonomy_ceiling_bc2_tier_b_hybrid(self) -> None:
        """BC2 + Tier B returns HYBRID."""
        from ces.harness.services.trust_manager import TrustManager

        result = TrustManager.get_autonomy_ceiling(BehaviorConfidence.BC2, RiskTier.B, TrustStatus.TRUSTED)
        assert result == GateType.HYBRID

    def test_autonomy_ceiling_bc1_trusted_tier_c_agent(self) -> None:
        """BC1 + TRUSTED + Tier C returns AGENT (maximum autonomy)."""
        from ces.harness.services.trust_manager import TrustManager

        result = TrustManager.get_autonomy_ceiling(BehaviorConfidence.BC1, RiskTier.C, TrustStatus.TRUSTED)
        assert result == GateType.AGENT

    def test_autonomy_ceiling_bc1_candidate_tier_c_hybrid(self) -> None:
        """BC1 + CANDIDATE + Tier C returns HYBRID (not yet trusted)."""
        from ces.harness.services.trust_manager import TrustManager

        result = TrustManager.get_autonomy_ceiling(BehaviorConfidence.BC1, RiskTier.C, TrustStatus.CANDIDATE)
        assert result == GateType.HYBRID

    def test_autonomy_ceiling_bc1_constrained_human(self) -> None:
        """BC1 + CONSTRAINED returns HUMAN regardless of tier."""
        from ces.harness.services.trust_manager import TrustManager

        result = TrustManager.get_autonomy_ceiling(BehaviorConfidence.BC1, RiskTier.C, TrustStatus.CONSTRAINED)
        assert result == GateType.HUMAN

    def test_autonomy_ceiling_bc1_watch_hybrid(self) -> None:
        """BC1 + WATCH returns HYBRID (reduced autonomy while under observation)."""
        from ces.harness.services.trust_manager import TrustManager

        result = TrustManager.get_autonomy_ceiling(BehaviorConfidence.BC1, RiskTier.C, TrustStatus.WATCH)
        assert result == GateType.HYBRID

    def test_autonomy_ceiling_bc1_tier_a_hybrid(self) -> None:
        """BC1 + Tier A + TRUSTED returns HYBRID (high-risk tier ceiling)."""
        from ces.harness.services.trust_manager import TrustManager

        result = TrustManager.get_autonomy_ceiling(BehaviorConfidence.BC1, RiskTier.A, TrustStatus.TRUSTED)
        assert result == GateType.HYBRID


# ---------------------------------------------------------------------------
# Task 2: Audit ledger integration tests
# ---------------------------------------------------------------------------


class TestTrustManagerAuditIntegration:
    """Tests for TrustManager audit ledger logging."""

    @pytest.mark.asyncio
    async def test_promotion_logs_to_audit_ledger(self) -> None:
        """evaluate_promotion logs HARNESS_CHANGE event to audit ledger."""
        from ces.harness.services.trust_manager import TrustManager

        mock_audit = AsyncMock()
        tm = TrustManager(audit_ledger=mock_audit)
        profile = _make_promotable_profile()

        await tm.evaluate_promotion(profile)
        mock_audit.record_state_transition.assert_called_once()
        call_kwargs = mock_audit.record_state_transition.call_args.kwargs
        assert call_kwargs["from_state"] == "candidate"
        assert call_kwargs["to_state"] == "trusted"

    @pytest.mark.asyncio
    async def test_contraction_logs_to_audit_ledger(self) -> None:
        """record_escape logs HARNESS_CHANGE event to audit ledger."""
        from ces.harness.services.trust_manager import TrustManager

        mock_audit = AsyncMock()
        tm = TrustManager(audit_ledger=mock_audit)
        profile = _make_promotable_profile()
        profile.trust_status = TrustStatus.TRUSTED

        await tm.record_escape(profile, "ESC-001", severity=2)
        mock_audit.record_state_transition.assert_called_once()
        call_kwargs = mock_audit.record_state_transition.call_args.kwargs
        assert call_kwargs["from_state"] == "trusted"
        assert call_kwargs["to_state"] == "watch"

    @pytest.mark.asyncio
    async def test_recovery_logs_to_audit_ledger(self) -> None:
        """attempt_recovery logs HARNESS_CHANGE event to audit ledger."""
        from ces.harness.services.trust_manager import TrustManager

        mock_audit = AsyncMock()
        tm = TrustManager(audit_ledger=mock_audit)
        profile = _make_promotable_profile()
        profile.trust_status = TrustStatus.CONSTRAINED

        await tm.attempt_recovery(profile)
        mock_audit.record_state_transition.assert_called_once()
        call_kwargs = mock_audit.record_state_transition.call_args.kwargs
        assert call_kwargs["from_state"] == "constrained"
        assert call_kwargs["to_state"] == "candidate"


# ---------------------------------------------------------------------------
# Task 2: Kill switch guard tests (D-06)
# ---------------------------------------------------------------------------


class TestTrustManagerKillSwitchGuard:
    """Tests for kill switch guard in TrustManager operations."""

    @pytest.mark.asyncio
    async def test_promotion_blocked_when_kill_switch_halted(self) -> None:
        """Operations blocked when kill_switch.is_halted('registry_writes') is True."""
        from ces.harness.services.trust_manager import TrustManager

        mock_ks = MagicMock()
        mock_ks.is_halted.return_value = True
        tm = TrustManager(kill_switch=mock_ks)
        profile = _make_promotable_profile()

        result = await tm.evaluate_promotion(profile)
        # Status should NOT change when kill switch is halted
        assert result.trust_status == TrustStatus.CANDIDATE
        mock_ks.is_halted.assert_called_with("registry_writes")

    @pytest.mark.asyncio
    async def test_escape_blocked_when_kill_switch_halted(self) -> None:
        """record_escape blocked when kill_switch.is_halted('registry_writes') is True."""
        from ces.harness.services.trust_manager import TrustManager

        mock_ks = MagicMock()
        mock_ks.is_halted.return_value = True
        tm = TrustManager(kill_switch=mock_ks)
        profile = _make_promotable_profile()
        profile.trust_status = TrustStatus.TRUSTED

        result = await tm.record_escape(profile, "ESC-001", severity=2)
        # Status should NOT change when kill switch is halted
        assert result.trust_status == TrustStatus.TRUSTED
        assert result.escapes == 0  # escape not recorded

    @pytest.mark.asyncio
    async def test_operations_work_without_kill_switch(self) -> None:
        """TrustManager works with kill_switch=None for unit testing."""
        from ces.harness.services.trust_manager import TrustManager

        tm = TrustManager()
        profile = _make_promotable_profile()

        result = await tm.evaluate_promotion(profile)
        assert result.trust_status == TrustStatus.TRUSTED

    @pytest.mark.asyncio
    async def test_operations_work_without_audit_ledger(self) -> None:
        """TrustManager works with audit_ledger=None for unit testing."""
        from ces.harness.services.trust_manager import TrustManager

        tm = TrustManager()
        profile = _make_promotable_profile()

        result = await tm.evaluate_promotion(profile)
        assert result.trust_status == TrustStatus.TRUSTED
