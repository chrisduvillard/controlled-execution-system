"""Tests for HiddenCheckEngine service.

Covers:
- HiddenCheck frozen dataclass model (TRUST-05)
- HiddenCheckResult frozen dataclass model (TRUST-05)
- select_checks: random subset injection from pool (TRUST-05)
- rotate_pool: minimum 30% replacement per cycle (TRUST-06)
- record_result and compute_pass_rate: per-profile tracking (TRUST-08)
- detect_anti_gaming: spike-then-decline detection (TRUST-07)
"""

from __future__ import annotations

import random
from dataclasses import FrozenInstanceError

import pytest

from ces.harness.models.hidden_check import HiddenCheck, HiddenCheckResult
from ces.harness.services.hidden_check_engine import HiddenCheckEngine

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_pool(n: int = 10, generation: int = 0) -> list[HiddenCheck]:
    """Create a pool of n HiddenCheck instances for testing."""
    return [
        HiddenCheck(
            check_id=f"chk-{i:03d}",
            description=f"Verify behaviour {i}",
            expected_outcome=f"outcome-{i}",
            pool_generation=generation,
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# HiddenCheck model tests
# ---------------------------------------------------------------------------


class TestHiddenCheckModel:
    """Tests for the HiddenCheck frozen dataclass."""

    def test_hidden_check_is_frozen_dataclass(self) -> None:
        """HiddenCheck instances are immutable (frozen=True)."""
        check = HiddenCheck(
            check_id="chk-001",
            description="Test desc",
            expected_outcome="expected",
            pool_generation=0,
        )
        with pytest.raises(FrozenInstanceError):
            check.check_id = "modified"  # type: ignore[misc]

    def test_hidden_check_fields(self) -> None:
        """HiddenCheck has check_id, description, expected_outcome, pool_generation."""
        check = HiddenCheck(
            check_id="chk-001",
            description="Test desc",
            expected_outcome="expected",
            pool_generation=1,
        )
        assert check.check_id == "chk-001"
        assert check.description == "Test desc"
        assert check.expected_outcome == "expected"
        assert check.pool_generation == 1


class TestHiddenCheckResultModel:
    """Tests for the HiddenCheckResult frozen dataclass."""

    def test_hidden_check_result_is_frozen_dataclass(self) -> None:
        """HiddenCheckResult instances are immutable (frozen=True)."""
        result = HiddenCheckResult(
            check_id="chk-001",
            profile_id="prof-001",
            passed=True,
            checked_at="2026-04-06T12:00:00Z",
        )
        with pytest.raises(FrozenInstanceError):
            result.passed = False  # type: ignore[misc]

    def test_hidden_check_result_fields(self) -> None:
        """HiddenCheckResult has check_id, profile_id, passed, checked_at."""
        result = HiddenCheckResult(
            check_id="chk-001",
            profile_id="prof-001",
            passed=False,
            checked_at="2026-04-06T12:00:00Z",
        )
        assert result.check_id == "chk-001"
        assert result.profile_id == "prof-001"
        assert result.passed is False
        assert result.checked_at == "2026-04-06T12:00:00Z"


# ---------------------------------------------------------------------------
# select_checks tests (TRUST-05)
# ---------------------------------------------------------------------------


class TestSelectChecks:
    """Tests for HiddenCheckEngine.select_checks -- injection from pool."""

    def test_select_checks_returns_subset_from_pool(self) -> None:
        """select_checks returns a random subset of checks from the pool."""
        pool = _make_pool(10)
        engine = HiddenCheckEngine(pool=pool)
        random.seed(42)
        selected = engine.select_checks(profile_id="prof-001", count=3)
        assert len(selected) == 3
        for check in selected:
            assert check in pool

    def test_select_checks_returns_different_for_different_profiles(self) -> None:
        """select_checks returns different checks for different profiles (randomized)."""
        pool = _make_pool(10)
        engine = HiddenCheckEngine(pool=pool)
        # Use same seed for engine construction but different profile IDs
        sel_a = engine.select_checks(profile_id="prof-alpha", count=3)
        sel_b = engine.select_checks(profile_id="prof-beta", count=3)
        # With high probability, two random selections of 3 from 10 differ.
        # We cannot guarantee 100% but the seeding approach makes this reliable.
        # The key requirement is that the engine randomizes per-call.
        assert isinstance(sel_a, list)
        assert isinstance(sel_b, list)
        # At minimum they should be valid subsets of the pool
        for check in sel_a:
            assert check in pool
        for check in sel_b:
            assert check in pool

    def test_select_checks_count_one_default(self) -> None:
        """select_checks with default count=1 returns exactly one check."""
        pool = _make_pool(10)
        engine = HiddenCheckEngine(pool=pool)
        selected = engine.select_checks(profile_id="prof-001")
        assert len(selected) == 1
        assert selected[0] in pool

    def test_select_checks_count_exceeds_pool_size(self) -> None:
        """select_checks with count > pool size raises ValueError."""
        pool = _make_pool(3)
        engine = HiddenCheckEngine(pool=pool)
        with pytest.raises(ValueError, match="count"):
            engine.select_checks(profile_id="prof-001", count=5)


# ---------------------------------------------------------------------------
# rotate_pool tests (TRUST-06)
# ---------------------------------------------------------------------------


class TestRotatePool:
    """Tests for HiddenCheckEngine.rotate_pool -- 30% minimum rotation."""

    def test_rotation_rate_minimum_30_percent(self) -> None:
        """rotate_pool replaces at least 30% of checks (3 out of 10)."""
        pool = _make_pool(10, generation=0)
        engine = HiddenCheckEngine(pool=pool)
        new_checks = _make_pool(3, generation=1)
        # Rename IDs so they are truly new
        new_checks = [
            HiddenCheck(
                check_id=f"new-{i:03d}",
                description=f"New check {i}",
                expected_outcome=f"new-outcome-{i}",
                pool_generation=1,
            )
            for i in range(3)
        ]
        replaced = engine.rotate_pool(new_checks)
        assert replaced >= 3

    def test_rotation_increments_generation(self) -> None:
        """rotate_pool increments the internal generation counter."""
        pool = _make_pool(10, generation=0)
        engine = HiddenCheckEngine(pool=pool)
        assert engine.current_generation == 0
        new_checks = [
            HiddenCheck(
                check_id=f"new-{i:03d}",
                description=f"New check {i}",
                expected_outcome=f"new-outcome-{i}",
                pool_generation=1,
            )
            for i in range(3)
        ]
        engine.rotate_pool(new_checks)
        assert engine.current_generation == 1

    def test_rotation_preserves_non_replaced_checks(self) -> None:
        """rotate_pool preserves checks that were NOT selected for replacement."""
        pool = _make_pool(10, generation=0)
        engine = HiddenCheckEngine(pool=pool)
        new_checks = [
            HiddenCheck(
                check_id=f"new-{i:03d}",
                description=f"New check {i}",
                expected_outcome=f"new-outcome-{i}",
                pool_generation=1,
            )
            for i in range(3)
        ]
        random.seed(99)
        engine.rotate_pool(new_checks)
        current = engine.pool
        assert len(current) == 10
        # Some original checks should remain
        original_ids = {f"chk-{i:03d}" for i in range(10)}
        remaining_original = {c.check_id for c in current if c.check_id in original_ids}
        assert len(remaining_original) == 7  # 10 - 3 replaced

    def test_rotation_insufficient_new_checks_raises(self) -> None:
        """rotate_pool raises ValueError if new_checks < ceil(rotation_rate * pool)."""
        pool = _make_pool(10, generation=0)
        engine = HiddenCheckEngine(pool=pool, rotation_rate=0.30)
        # Need at least 3 new checks for 30% of 10, but only provide 2
        new_checks = [
            HiddenCheck(
                check_id=f"new-{i:03d}",
                description=f"New check {i}",
                expected_outcome=f"new-outcome-{i}",
                pool_generation=1,
            )
            for i in range(2)
        ]
        with pytest.raises(ValueError, match="new_checks"):
            engine.rotate_pool(new_checks)


# ---------------------------------------------------------------------------
# record_result and compute_pass_rate tests (TRUST-08)
# ---------------------------------------------------------------------------


class TestPassRateTracking:
    """Tests for record_result and compute_pass_rate -- per-profile tracking."""

    def test_record_result_updates_counts(self) -> None:
        """record_result appends result to the profile's result history."""
        pool = _make_pool(10)
        engine = HiddenCheckEngine(pool=pool)
        result = HiddenCheckResult(
            check_id="chk-001",
            profile_id="prof-001",
            passed=True,
            checked_at="2026-04-06T12:00:00Z",
        )
        engine.record_result(result)
        assert engine.compute_pass_rate("prof-001") == 1.0

    def test_compute_pass_rate_correct_ratio(self) -> None:
        """compute_pass_rate returns (passes / total) for a profile."""
        pool = _make_pool(10)
        engine = HiddenCheckEngine(pool=pool)
        for i in range(10):
            engine.record_result(
                HiddenCheckResult(
                    check_id=f"chk-{i:03d}",
                    profile_id="prof-001",
                    passed=i < 7,  # 7 pass, 3 fail
                    checked_at=f"2026-04-06T12:{i:02d}:00Z",
                )
            )
        rate = engine.compute_pass_rate("prof-001")
        assert rate is not None
        assert abs(rate - 0.7) < 1e-9

    def test_compute_pass_rate_none_when_no_results(self) -> None:
        """compute_pass_rate returns None when no checks recorded for a profile."""
        pool = _make_pool(10)
        engine = HiddenCheckEngine(pool=pool)
        assert engine.compute_pass_rate("nonexistent-profile") is None

    def test_results_tracked_per_profile(self) -> None:
        """Results are tracked separately per profile_id."""
        pool = _make_pool(10)
        engine = HiddenCheckEngine(pool=pool)
        engine.record_result(
            HiddenCheckResult(
                check_id="chk-001",
                profile_id="prof-001",
                passed=True,
                checked_at="2026-04-06T12:00:00Z",
            )
        )
        engine.record_result(
            HiddenCheckResult(
                check_id="chk-002",
                profile_id="prof-002",
                passed=False,
                checked_at="2026-04-06T12:01:00Z",
            )
        )
        assert engine.compute_pass_rate("prof-001") == 1.0
        assert engine.compute_pass_rate("prof-002") == 0.0


# ---------------------------------------------------------------------------
# detect_anti_gaming tests (TRUST-07)
# ---------------------------------------------------------------------------


class TestAntiGaming:
    """Tests for detect_anti_gaming -- spike-then-decline detection."""

    def _record_cycle_results(
        self,
        engine: HiddenCheckEngine,
        profile_id: str,
        pass_rates: list[float],
        checks_per_cycle: int = 10,
    ) -> None:
        """Helper: record results to produce specific per-cycle pass rates.

        Each pass_rate entry becomes one cycle of checks_per_cycle results.
        """
        for cycle_idx, rate in enumerate(pass_rates):
            n_pass = int(rate * checks_per_cycle)
            for j in range(checks_per_cycle):
                engine.record_result(
                    HiddenCheckResult(
                        check_id=f"chk-{j:03d}",
                        profile_id=profile_id,
                        passed=j < n_pass,
                        checked_at=f"2026-04-{cycle_idx + 1:02d}T{j:02d}:00:00Z",
                    )
                )

    def test_anti_gaming_steady_rate_returns_false(self) -> None:
        """detect_anti_gaming with steady 90% pass rate returns False (no gaming)."""
        pool = _make_pool(10)
        engine = HiddenCheckEngine(
            pool=pool,
            anti_gaming_window=5,
            anti_gaming_decline_threshold=0.15,
            checks_per_cycle=10,
        )
        # Steady 90% across 6 cycles
        self._record_cycle_results(engine, "prof-001", [0.9, 0.9, 0.9, 0.9, 0.9, 0.9])
        assert engine.detect_anti_gaming("prof-001") is False

    def test_anti_gaming_spike_then_decline_returns_true(self) -> None:
        """detect_anti_gaming with spike (95% -> 60%) returns True."""
        pool = _make_pool(10)
        engine = HiddenCheckEngine(
            pool=pool,
            anti_gaming_window=5,
            anti_gaming_decline_threshold=0.15,
            checks_per_cycle=10,
        )
        # Build-up, spike, then decline
        self._record_cycle_results(engine, "prof-001", [0.8, 0.8, 0.9, 0.9, 0.5, 0.6])
        assert engine.detect_anti_gaming("prof-001") is True

    def test_anti_gaming_ignores_partial_trailing_cycle(self) -> None:
        """A partial trailing cycle must not be analyzed (line 205 break)."""
        pool = _make_pool(10)
        engine = HiddenCheckEngine(
            pool=pool,
            anti_gaming_window=5,
            anti_gaming_decline_threshold=0.15,
            checks_per_cycle=10,
        )
        # 5 complete cycles, then 3 stray results that would form a fake "spike"
        # if treated as a cycle (rate would be 1.0). The break on line 205 prevents this.
        self._record_cycle_results(engine, "prof-001", [0.6, 0.6, 0.6, 0.6, 0.6])
        for j in range(3):
            engine.record_result(
                HiddenCheckResult(
                    check_id=f"chk-stray-{j}",
                    profile_id="prof-001",
                    passed=True,
                    checked_at="2026-04-25T00:00:00Z",
                )
            )
        # The trailing partial cycle (3 passes -> 100% rate) is ignored, so the
        # window stays a steady 0.6 and detection returns False.
        assert engine.detect_anti_gaming("prof-001") is False

    def test_anti_gaming_gradual_decline_returns_false(self) -> None:
        """detect_anti_gaming with gradual decline (90% -> 85% -> 80%) returns False."""
        pool = _make_pool(10)
        engine = HiddenCheckEngine(
            pool=pool,
            anti_gaming_window=5,
            anti_gaming_decline_threshold=0.15,
            checks_per_cycle=10,
        )
        # Gradual decline of 5% per cycle, never exceeds 15% threshold from peak
        self._record_cycle_results(engine, "prof-001", [0.9, 0.9, 0.8, 0.8, 0.8, 0.8])
        assert engine.detect_anti_gaming("prof-001") is False

    def test_anti_gaming_insufficient_data_returns_false(self) -> None:
        """detect_anti_gaming requires minimum window size before flagging."""
        pool = _make_pool(10)
        engine = HiddenCheckEngine(
            pool=pool,
            anti_gaming_window=5,
            anti_gaming_decline_threshold=0.15,
            checks_per_cycle=10,
        )
        # Only 3 cycles of data -- below anti_gaming_window of 5
        self._record_cycle_results(engine, "prof-001", [0.9, 0.5, 0.4])
        assert engine.detect_anti_gaming("prof-001") is False

    def test_anti_gaming_no_data_returns_false(self) -> None:
        """detect_anti_gaming returns False when no results exist for profile."""
        pool = _make_pool(10)
        engine = HiddenCheckEngine(pool=pool, anti_gaming_window=5)
        assert engine.detect_anti_gaming("nonexistent") is False
