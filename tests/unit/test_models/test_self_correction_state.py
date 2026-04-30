"""Tests for SelfCorrectionState and CircuitBreakerState (D-10)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ces.harness.models.self_correction_state import (
    CircuitBreakerState,
    SelfCorrectionState,
)


class TestSelfCorrectionState:
    """SelfCorrectionState frozen model tests."""

    def test_create_with_defaults(self) -> None:
        sc = SelfCorrectionState(
            task_id="task-001",
            token_budget=50000,
        )
        assert sc.task_id == "task-001"
        assert sc.retry_count == 0
        assert sc.max_retries == 3
        assert sc.tokens_used == 0
        assert sc.token_budget == 50000
        assert sc.current_depth == 0
        assert sc.total_spawns == 0

    def test_frozen(self) -> None:
        sc = SelfCorrectionState(
            task_id="task-001",
            token_budget=50000,
        )
        with pytest.raises(ValidationError):
            sc.retry_count = 1  # type: ignore[misc]

    def test_create_with_custom_values(self) -> None:
        sc = SelfCorrectionState(
            task_id="task-002",
            retry_count=2,
            max_retries=5,
            tokens_used=10000,
            token_budget=100000,
            current_depth=1,
            total_spawns=3,
        )
        assert sc.retry_count == 2
        assert sc.max_retries == 5


class TestCircuitBreakerState:
    """CircuitBreakerState frozen model tests (D-10)."""

    def test_defaults(self) -> None:
        cb = CircuitBreakerState(task_id="task-001")
        assert cb.current_depth == 0
        assert cb.total_spawns == 0
        assert cb.max_depth == 3
        assert cb.max_spawns == 10
        assert cb.tripped is False
        assert cb.trip_reason == ""

    def test_frozen(self) -> None:
        cb = CircuitBreakerState(task_id="task-001")
        with pytest.raises(ValidationError):
            cb.tripped = True  # type: ignore[misc]

    def test_is_breached_false_when_under_limits(self) -> None:
        cb = CircuitBreakerState(
            task_id="task-001",
            current_depth=2,
            total_spawns=5,
        )
        assert cb.is_breached is False

    def test_is_breached_true_when_depth_exceeded(self) -> None:
        cb = CircuitBreakerState(
            task_id="task-001",
            current_depth=3,
            total_spawns=5,
        )
        assert cb.is_breached is True

    def test_is_breached_true_when_spawns_exceeded(self) -> None:
        cb = CircuitBreakerState(
            task_id="task-001",
            current_depth=1,
            total_spawns=10,
        )
        assert cb.is_breached is True

    def test_is_breached_true_when_both_exceeded(self) -> None:
        cb = CircuitBreakerState(
            task_id="task-001",
            current_depth=5,
            total_spawns=15,
        )
        assert cb.is_breached is True
