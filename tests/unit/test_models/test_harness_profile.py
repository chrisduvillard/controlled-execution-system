"""Tests for HarnessProfile model (MODEL-12)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from ces.harness.models.harness_profile import HarnessProfile
from ces.shared.enums import ChangeClass, TrustStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_profile(**overrides: object) -> HarnessProfile:
    """Create a valid HarnessProfile with sensible defaults."""
    defaults = {
        "profile_id": "HP-001",
        "agent_id": "agent-alpha",
    }
    defaults.update(overrides)
    return HarnessProfile(**defaults)


class TestHarnessProfileBasicFields:
    """Tests for basic HarnessProfile fields."""

    def test_profile_id(self) -> None:
        p = _make_profile()
        assert p.profile_id == "HP-001"

    def test_agent_id(self) -> None:
        p = _make_profile()
        assert p.agent_id == "agent-alpha"

    def test_trust_status_default_candidate(self) -> None:
        p = _make_profile()
        assert p.trust_status == TrustStatus.CANDIDATE

    def test_trust_status_explicit(self) -> None:
        p = _make_profile(trust_status=TrustStatus.TRUSTED)
        assert p.trust_status == TrustStatus.TRUSTED


class TestHarnessProfileTracking:
    """Tests for task tracking fields."""

    def test_completed_tasks_default_zero(self) -> None:
        p = _make_profile()
        assert p.completed_tasks == 0

    def test_completed_tasks_set(self) -> None:
        p = _make_profile(completed_tasks=15)
        assert p.completed_tasks == 15

    def test_completed_tasks_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_profile(completed_tasks=-1)

    def test_active_since_default_none(self) -> None:
        p = _make_profile()
        assert p.active_since is None

    def test_active_since_set(self) -> None:
        now = _now()
        p = _make_profile(active_since=now)
        assert p.active_since == now

    def test_change_classes_covered_default_empty(self) -> None:
        p = _make_profile()
        assert p.change_classes_covered == set()

    def test_change_classes_covered_set(self) -> None:
        classes = {ChangeClass.CLASS_1, ChangeClass.CLASS_2, ChangeClass.CLASS_3}
        p = _make_profile(change_classes_covered=classes)
        assert p.change_classes_covered == classes


class TestHarnessProfileProductionMetrics:
    """Tests for production release and escape tracking."""

    def test_production_releases_default_zero(self) -> None:
        p = _make_profile()
        assert p.production_releases == 0

    def test_production_releases_set(self) -> None:
        p = _make_profile(production_releases=5)
        assert p.production_releases == 5

    def test_production_releases_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_profile(production_releases=-1)

    def test_escapes_default_zero(self) -> None:
        p = _make_profile()
        assert p.escapes == 0

    def test_escapes_set(self) -> None:
        p = _make_profile(escapes=2)
        assert p.escapes == 2

    def test_escapes_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_profile(escapes=-1)


class TestHarnessProfileHiddenCheck:
    """Tests for hidden check pass rate."""

    def test_hidden_check_pass_rate_default_none(self) -> None:
        p = _make_profile()
        assert p.hidden_check_pass_rate is None

    def test_hidden_check_pass_rate_valid(self) -> None:
        p = _make_profile(hidden_check_pass_rate=0.95)
        assert p.hidden_check_pass_rate == 0.95

    def test_hidden_check_pass_rate_zero_valid(self) -> None:
        p = _make_profile(hidden_check_pass_rate=0.0)
        assert p.hidden_check_pass_rate == 0.0

    def test_hidden_check_pass_rate_one_valid(self) -> None:
        p = _make_profile(hidden_check_pass_rate=1.0)
        assert p.hidden_check_pass_rate == 1.0

    def test_hidden_check_pass_rate_above_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_profile(hidden_check_pass_rate=1.1)

    def test_hidden_check_pass_rate_below_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_profile(hidden_check_pass_rate=-0.1)


class TestHarnessProfileContracts:
    """Tests for contract fields."""

    def test_guide_contract_default_none(self) -> None:
        p = _make_profile()
        assert p.guide_contract is None

    def test_sensor_contract_default_none(self) -> None:
        p = _make_profile()
        assert p.sensor_contract is None

    def test_review_contract_default_none(self) -> None:
        p = _make_profile()
        assert p.review_contract is None

    def test_merge_contract_default_none(self) -> None:
        p = _make_profile()
        assert p.merge_contract is None

    def test_guide_contract_set(self) -> None:
        contract = {"type": "standard", "version": 1}
        p = _make_profile(guide_contract=contract)
        assert p.guide_contract == contract


class TestHarnessProfileCanPromote:
    """Tests for can_promote property (TRUST-02)."""

    def test_can_promote_all_criteria_met(self) -> None:
        p = _make_profile(
            completed_tasks=10,
            active_since=_now() - timedelta(days=15),
            change_classes_covered={ChangeClass.CLASS_1, ChangeClass.CLASS_2, ChangeClass.CLASS_3},
            production_releases=1,
        )
        assert p.can_promote is True

    def test_can_promote_false_no_active_since(self) -> None:
        p = _make_profile(
            completed_tasks=10,
            active_since=None,
            change_classes_covered={ChangeClass.CLASS_1, ChangeClass.CLASS_2, ChangeClass.CLASS_3},
            production_releases=1,
        )
        assert p.can_promote is False

    def test_can_promote_false_too_few_tasks(self) -> None:
        p = _make_profile(
            completed_tasks=9,
            active_since=_now() - timedelta(days=15),
            change_classes_covered={ChangeClass.CLASS_1, ChangeClass.CLASS_2, ChangeClass.CLASS_3},
            production_releases=1,
        )
        assert p.can_promote is False

    def test_can_promote_false_too_recent(self) -> None:
        p = _make_profile(
            completed_tasks=10,
            active_since=_now() - timedelta(days=13),
            change_classes_covered={ChangeClass.CLASS_1, ChangeClass.CLASS_2, ChangeClass.CLASS_3},
            production_releases=1,
        )
        assert p.can_promote is False

    def test_can_promote_false_too_few_change_classes(self) -> None:
        p = _make_profile(
            completed_tasks=10,
            active_since=_now() - timedelta(days=15),
            change_classes_covered={ChangeClass.CLASS_1, ChangeClass.CLASS_2},
            production_releases=1,
        )
        assert p.can_promote is False

    def test_can_promote_false_no_production_releases(self) -> None:
        p = _make_profile(
            completed_tasks=10,
            active_since=_now() - timedelta(days=15),
            change_classes_covered={ChangeClass.CLASS_1, ChangeClass.CLASS_2, ChangeClass.CLASS_3},
            production_releases=0,
        )
        assert p.can_promote is False


class TestHarnessProfileMutability:
    """Tests that HarnessProfile is NOT frozen (trust status changes)."""

    def test_not_frozen(self) -> None:
        p = _make_profile()
        p.trust_status = TrustStatus.TRUSTED
        assert p.trust_status == TrustStatus.TRUSTED

    def test_completed_tasks_mutable(self) -> None:
        p = _make_profile()
        p.completed_tasks = 5
        assert p.completed_tasks == 5
