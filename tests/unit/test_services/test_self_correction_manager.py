"""Tests for SelfCorrectionManager service.

Covers:
- SENS-04: Bounded retries within manifest limits (can_retry, record_retry)
- SENS-05: Second-agent validation for Tier A final retry (needs_second_agent)
- SENS-06: Token budget enforcement (check_token_budget)
- SENS-07: Circuit breaker with D-10 hard limits (check_circuit_breaker, increment_depth)
- D-11: Alternate model selection (select_alternate_model)
- Audit logging on retry and circuit breaker trip
"""

from __future__ import annotations

import pytest

from ces.harness.models.completion_claim import (
    VerificationFinding,
    VerificationFindingKind,
)
from ces.harness.models.self_correction_state import (
    CircuitBreakerState,
    SelfCorrectionState,
)
from ces.harness.models.tool_call_signature import ToolCallSignature
from ces.harness.services.self_correction_manager import SelfCorrectionManager
from ces.shared.enums import RiskTier

# ---------------------------------------------------------------------------
# Test helpers: mock kill switch and audit ledger
# ---------------------------------------------------------------------------


class _MockKillSwitch:
    """Mock kill switch for testing."""

    def __init__(self, halted: bool = False) -> None:
        self._halted = halted
        self.calls: list[str] = []

    def is_halted(self, activity_class: str) -> bool:
        self.calls.append(activity_class)
        return self._halted


class _MockAuditLedger:
    """Mock audit ledger that records events."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def append_event(self, **kwargs: object) -> None:
        self.events.append(dict(kwargs))


# ---------------------------------------------------------------------------
# can_retry tests (SENS-04)
# ---------------------------------------------------------------------------


def test_can_retry_within_limits() -> None:
    """Fresh state with budget remaining should allow retry."""
    mgr = SelfCorrectionManager()
    state = SelfCorrectionState(task_id="t1", token_budget=10000)
    assert mgr.can_retry(state) is True


def test_can_retry_exceeded_retries() -> None:
    """retry_count == max_retries should block retry."""
    mgr = SelfCorrectionManager()
    state = SelfCorrectionState(task_id="t1", retry_count=3, max_retries=3, token_budget=10000)
    assert mgr.can_retry(state) is False


def test_can_retry_exceeded_budget() -> None:
    """tokens_used >= token_budget should block retry."""
    mgr = SelfCorrectionManager()
    state = SelfCorrectionState(task_id="t1", tokens_used=10000, token_budget=10000)
    assert mgr.can_retry(state) is False


def test_can_retry_both_exceeded() -> None:
    """Both retries and budget exceeded should block retry."""
    mgr = SelfCorrectionManager()
    state = SelfCorrectionState(
        task_id="t1",
        retry_count=3,
        max_retries=3,
        tokens_used=10000,
        token_budget=10000,
    )
    assert mgr.can_retry(state) is False


# ---------------------------------------------------------------------------
# record_retry tests (SENS-04)
# ---------------------------------------------------------------------------


def test_record_retry_increments() -> None:
    """record_retry should increment retry_count, tokens_used, total_spawns."""
    mgr = SelfCorrectionManager()
    state = SelfCorrectionState(task_id="t1", token_budget=10000)
    new_state = mgr.record_retry(state, tokens_consumed=500)
    assert new_state.retry_count == 1
    assert new_state.tokens_used == 500
    assert new_state.total_spawns == 1


def test_record_retry_returns_new_state() -> None:
    """Original state should remain unchanged (frozen model)."""
    mgr = SelfCorrectionManager()
    state = SelfCorrectionState(task_id="t1", token_budget=10000)
    new_state = mgr.record_retry(state, tokens_consumed=500)
    # Original unchanged
    assert state.retry_count == 0
    assert state.tokens_used == 0
    assert state.total_spawns == 0
    # New state has updates
    assert new_state is not state
    assert new_state.retry_count == 1


def test_record_retry_cumulative_tokens() -> None:
    """Multiple retries should accumulate tokens cumulatively."""
    mgr = SelfCorrectionManager()
    state = SelfCorrectionState(task_id="t1", token_budget=10000)
    state = mgr.record_retry(state, tokens_consumed=500)
    state = mgr.record_retry(state, tokens_consumed=300)
    assert state.retry_count == 2
    assert state.tokens_used == 800
    assert state.total_spawns == 2


# ---------------------------------------------------------------------------
# check_token_budget tests (SENS-06)
# ---------------------------------------------------------------------------


def test_check_token_budget_within() -> None:
    """Should return True when under budget."""
    mgr = SelfCorrectionManager()
    state = SelfCorrectionState(task_id="t1", tokens_used=500, token_budget=10000)
    assert mgr.check_token_budget(state, tokens_needed=500) is True


def test_check_token_budget_exceeded() -> None:
    """Should return False when over budget."""
    mgr = SelfCorrectionManager()
    state = SelfCorrectionState(task_id="t1", tokens_used=9500, token_budget=10000)
    assert mgr.check_token_budget(state, tokens_needed=600) is False


def test_check_token_budget_exact() -> None:
    """Should return True when exactly at budget."""
    mgr = SelfCorrectionManager()
    state = SelfCorrectionState(task_id="t1", tokens_used=9500, token_budget=10000)
    assert mgr.check_token_budget(state, tokens_needed=500) is True


# ---------------------------------------------------------------------------
# check_circuit_breaker tests (SENS-07, D-10)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_circuit_breaker_depth_breach() -> None:
    """depth >= max_depth should trip the circuit breaker."""
    mgr = SelfCorrectionManager()
    state = CircuitBreakerState(task_id="t1", current_depth=3, max_depth=3)
    result = await mgr.check_circuit_breaker(state)
    assert result.tripped is True
    assert "depth" in result.trip_reason.lower()


@pytest.mark.asyncio
async def test_circuit_breaker_spawn_breach() -> None:
    """spawns >= max_spawns should trip the circuit breaker."""
    mgr = SelfCorrectionManager()
    state = CircuitBreakerState(task_id="t1", total_spawns=10, max_spawns=10)
    result = await mgr.check_circuit_breaker(state)
    assert result.tripped is True
    assert "spawn" in result.trip_reason.lower()


@pytest.mark.asyncio
async def test_circuit_breaker_both_breached() -> None:
    """Both depth and spawn limits exceeded should mention both."""
    mgr = SelfCorrectionManager()
    state = CircuitBreakerState(task_id="t1", current_depth=3, max_depth=3, total_spawns=10, max_spawns=10)
    result = await mgr.check_circuit_breaker(state)
    assert result.tripped is True
    assert "depth" in result.trip_reason.lower()
    assert "spawn" in result.trip_reason.lower()


@pytest.mark.asyncio
async def test_circuit_breaker_no_breach() -> None:
    """Within limits should return untripped state."""
    mgr = SelfCorrectionManager()
    state = CircuitBreakerState(task_id="t1", current_depth=1, total_spawns=5)
    result = await mgr.check_circuit_breaker(state)
    assert result.tripped is False
    assert result.trip_reason == ""


@pytest.mark.asyncio
async def test_circuit_breaker_triggers_kill_switch() -> None:
    """Circuit breaker breach should signal kill switch for spawning."""
    ks = _MockKillSwitch()
    audit = _MockAuditLedger()
    mgr = SelfCorrectionManager(kill_switch=ks, audit_ledger=audit)
    state = CircuitBreakerState(task_id="t1", current_depth=3, max_depth=3)
    result = await mgr.check_circuit_breaker(state)
    assert result.tripped is True
    # Audit event should be logged for the circuit breaker trip
    assert len(audit.events) >= 1
    event_types = [e.get("event_type") for e in audit.events]
    from ces.shared.enums import EventType

    assert EventType.DELEGATION in event_types


@pytest.mark.asyncio
async def test_circuit_breaker_no_kill_switch_configured() -> None:
    """Breached circuit breaker without kill switch should still trip and log."""
    audit = _MockAuditLedger()
    mgr = SelfCorrectionManager(audit_ledger=audit)
    state = CircuitBreakerState(task_id="t1", current_depth=3, max_depth=3)
    result = await mgr.check_circuit_breaker(state)
    assert result.tripped is True
    # Audit should still be logged
    assert len(audit.events) >= 1


# ---------------------------------------------------------------------------
# increment_depth tests (Pitfall 3: increment before dispatch)
# ---------------------------------------------------------------------------


def test_increment_depth_before_dispatch() -> None:
    """increment_depth should return state with depth+1, spawns+1."""
    mgr = SelfCorrectionManager()
    state = CircuitBreakerState(task_id="t1", current_depth=1, total_spawns=5)
    new_state = mgr.increment_depth(state)
    assert new_state.current_depth == 2
    assert new_state.total_spawns == 6


def test_increment_depth_preserves_original() -> None:
    """Original state should not be mutated (frozen model)."""
    mgr = SelfCorrectionManager()
    state = CircuitBreakerState(task_id="t1", current_depth=1, total_spawns=5)
    new_state = mgr.increment_depth(state)
    assert state.current_depth == 1
    assert state.total_spawns == 5
    assert new_state is not state


# ---------------------------------------------------------------------------
# needs_second_agent tests (SENS-05, D-11)
# ---------------------------------------------------------------------------


def test_needs_second_agent_tier_a_final_retry() -> None:
    """Tier A + final retry (retry_count == max_retries - 1) -> True."""
    mgr = SelfCorrectionManager()
    state = SelfCorrectionState(task_id="t1", retry_count=2, max_retries=3, token_budget=10000)
    assert mgr.needs_second_agent(state, RiskTier.A) is True


def test_needs_second_agent_tier_b() -> None:
    """Tier B always returns False regardless of retry count."""
    mgr = SelfCorrectionManager()
    state = SelfCorrectionState(task_id="t1", retry_count=2, max_retries=3, token_budget=10000)
    assert mgr.needs_second_agent(state, RiskTier.B) is False


def test_needs_second_agent_tier_c() -> None:
    """Tier C always returns False."""
    mgr = SelfCorrectionManager()
    state = SelfCorrectionState(task_id="t1", retry_count=2, max_retries=3, token_budget=10000)
    assert mgr.needs_second_agent(state, RiskTier.C) is False


def test_needs_second_agent_not_final() -> None:
    """Tier A + not final retry -> False."""
    mgr = SelfCorrectionManager()
    state = SelfCorrectionState(task_id="t1", retry_count=0, max_retries=3, token_budget=10000)
    assert mgr.needs_second_agent(state, RiskTier.A) is False


def test_needs_second_agent_tier_a_middle_retry() -> None:
    """Tier A + middle retry (retry_count == 1 of max 3) -> False."""
    mgr = SelfCorrectionManager()
    state = SelfCorrectionState(task_id="t1", retry_count=1, max_retries=3, token_budget=10000)
    assert mgr.needs_second_agent(state, RiskTier.A) is False


# ---------------------------------------------------------------------------
# select_alternate_model tests (D-11)
# ---------------------------------------------------------------------------


def test_select_alternate_model_excludes_current() -> None:
    """Should return a model different from the current one."""
    mgr = SelfCorrectionManager()
    roster = ["claude-3-opus", "gpt-4o", "claude-3-sonnet"]
    result = mgr.select_alternate_model("claude-3-opus", roster)
    assert result != "claude-3-opus"
    assert result in roster


def test_select_alternate_model_returns_first_alternate() -> None:
    """Should return the first model in roster != current."""
    mgr = SelfCorrectionManager()
    roster = ["claude-3-opus", "gpt-4o", "claude-3-sonnet"]
    result = mgr.select_alternate_model("claude-3-opus", roster)
    assert result == "gpt-4o"


def test_select_alternate_model_no_alternatives_raises() -> None:
    """Only current model in roster should raise ValueError."""
    mgr = SelfCorrectionManager()
    with pytest.raises(ValueError, match="No alternate model"):
        mgr.select_alternate_model("gpt-4o", ["gpt-4o"])


def test_select_alternate_model_empty_roster_raises() -> None:
    """Empty roster should raise ValueError."""
    mgr = SelfCorrectionManager()
    with pytest.raises(ValueError, match="No alternate model"):
        mgr.select_alternate_model("gpt-4o", [])


# ---------------------------------------------------------------------------
# Audit logging tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_logging_on_retry() -> None:
    """record_retry should log DELEGATION event to audit ledger."""
    import asyncio

    audit = _MockAuditLedger()
    mgr = SelfCorrectionManager(audit_ledger=audit)
    state = SelfCorrectionState(task_id="t1", token_budget=10000)
    mgr.record_retry(state, tokens_consumed=500)
    # Yield to event loop so the created task completes
    await asyncio.sleep(0)
    # Audit event should be logged
    assert len(audit.events) == 1
    from ces.shared.enums import EventType

    assert audit.events[0]["event_type"] == EventType.DELEGATION


@pytest.mark.asyncio
async def test_audit_logging_on_circuit_breaker_trip() -> None:
    """Circuit breaker trip should log DELEGATION event to audit."""
    audit = _MockAuditLedger()
    mgr = SelfCorrectionManager(audit_ledger=audit)
    state = CircuitBreakerState(task_id="t1", current_depth=3, max_depth=3)
    await mgr.check_circuit_breaker(state)
    assert len(audit.events) >= 1
    from ces.shared.enums import EventType

    delegation_events = [e for e in audit.events if e.get("event_type") == EventType.DELEGATION]
    assert len(delegation_events) >= 1
    # Should mention circuit breaker
    summary = delegation_events[0].get("action_summary", "")
    assert "circuit" in summary.lower() or "breaker" in summary.lower()


@pytest.mark.asyncio
async def test_no_audit_logging_when_no_ledger() -> None:
    """Manager without audit ledger should not raise on retry."""
    mgr = SelfCorrectionManager()
    state = SelfCorrectionState(task_id="t1", token_budget=10000)
    # Should not raise
    mgr.record_retry(state, tokens_consumed=500)


@pytest.mark.asyncio
async def test_no_audit_on_circuit_breaker_no_breach() -> None:
    """No audit event when circuit breaker is not breached."""
    audit = _MockAuditLedger()
    mgr = SelfCorrectionManager(audit_ledger=audit)
    state = CircuitBreakerState(task_id="t1", current_depth=1, total_spawns=5)
    await mgr.check_circuit_breaker(state)
    assert len(audit.events) == 0


# ---------------------------------------------------------------------------
# build_repair_prompt (P2) — closes the evidence-driven retry loop
# ---------------------------------------------------------------------------


def _make_finding(
    *,
    kind: VerificationFindingKind = VerificationFindingKind.SENSOR_FAILURE,
    severity: str = "high",
    message: str = "default message",
    hint: str = "default hint",
    related_criterion: str | None = None,
    related_sensor: str | None = None,
) -> VerificationFinding:
    return VerificationFinding(
        kind=kind,
        severity=severity,  # type: ignore[arg-type]
        message=message,
        hint=hint,
        related_criterion=related_criterion,
        related_sensor=related_sensor,
    )


def test_build_repair_prompt_empty_findings_returns_empty_string() -> None:
    mgr = SelfCorrectionManager()
    assert mgr.build_repair_prompt(()) == ""


def test_build_repair_prompt_includes_each_finding_message() -> None:
    mgr = SelfCorrectionManager()
    findings = (
        _make_finding(message="Coverage 72% below 88% floor", hint="Add tests"),
        _make_finding(
            kind=VerificationFindingKind.CRITERION_UNADDRESSED,
            severity="critical",
            message="Acceptance criterion 'logout works' has no evidence",
            hint="Run the logout test",
            related_criterion="logout works",
        ),
    )
    prompt = mgr.build_repair_prompt(findings)
    assert "Coverage 72% below 88% floor" in prompt
    assert "Add tests" in prompt
    assert "logout works" in prompt
    assert "Run the logout test" in prompt


def test_build_repair_prompt_groups_by_kind() -> None:
    """Findings of the same kind appear under one heading for clarity."""
    mgr = SelfCorrectionManager()
    findings = (
        _make_finding(
            kind=VerificationFindingKind.SENSOR_FAILURE,
            message="Tests failed",
            hint="Fix tests",
            related_sensor="test_pass",
        ),
        _make_finding(
            kind=VerificationFindingKind.SENSOR_FAILURE,
            message="Lint violations",
            hint="Run ruff --fix",
            related_sensor="lint",
        ),
        _make_finding(
            kind=VerificationFindingKind.SCOPE_VIOLATION,
            message="src/payment/charge.py is out of scope",
            hint="Revert that change",
        ),
    )
    prompt = mgr.build_repair_prompt(findings)
    # Each distinct kind heading appears exactly once
    assert prompt.lower().count("sensor_failure") == 1
    assert prompt.lower().count("scope_violation") == 1
    assert "Tests failed" in prompt
    assert "Lint violations" in prompt
    assert "out of scope" in prompt


def test_build_repair_prompt_orders_critical_first() -> None:
    """Critical-severity findings appear before lower severities so the agent reads them first."""
    mgr = SelfCorrectionManager()
    findings = (
        _make_finding(severity="low", message="LOW_MARKER"),
        _make_finding(severity="critical", message="CRITICAL_MARKER"),
        _make_finding(severity="medium", message="MEDIUM_MARKER"),
    )
    prompt = mgr.build_repair_prompt(findings)
    assert prompt.index("CRITICAL_MARKER") < prompt.index("MEDIUM_MARKER") < prompt.index("LOW_MARKER")


# ---------------------------------------------------------------------------
# detect_no_progress (P4) — catches infinite-tool-call loops
# ---------------------------------------------------------------------------


def _sig(tool: str, args: dict) -> ToolCallSignature:
    return ToolCallSignature.from_call(tool, args)


def test_detect_no_progress_empty_history_false() -> None:
    mgr = SelfCorrectionManager()
    assert mgr.detect_no_progress(()) is False


def test_detect_no_progress_below_threshold_false() -> None:
    mgr = SelfCorrectionManager()
    sig = _sig("Read", {"path": "x.py"})
    history = (sig, sig, sig)  # 3 occurrences, default threshold=3
    assert mgr.detect_no_progress(history) is False


def test_detect_no_progress_above_threshold_true() -> None:
    mgr = SelfCorrectionManager()
    sig = _sig("Read", {"path": "x.py"})
    history = (sig, sig, sig, sig)  # 4 occurrences > 3
    assert mgr.detect_no_progress(history) is True


def test_detect_no_progress_distinct_calls_below_threshold() -> None:
    mgr = SelfCorrectionManager()
    history = (
        _sig("Read", {"path": "a.py"}),
        _sig("Read", {"path": "b.py"}),
        _sig("Read", {"path": "c.py"}),
        _sig("Read", {"path": "d.py"}),
    )
    assert mgr.detect_no_progress(history) is False


def test_detect_no_progress_only_specific_repeats_count() -> None:
    """A noisy mix where ONE signature exceeds the threshold trips it."""
    mgr = SelfCorrectionManager()
    repeated = _sig("Read", {"path": "x.py"})
    history = (
        repeated,
        _sig("Read", {"path": "y.py"}),
        repeated,
        _sig("Write", {"path": "z.py"}),
        repeated,
        repeated,  # 4th occurrence of `repeated`, > 3
    )
    assert mgr.detect_no_progress(history) is True


def test_detect_no_progress_custom_threshold() -> None:
    mgr = SelfCorrectionManager()
    sig = _sig("Read", {"path": "x.py"})
    assert mgr.detect_no_progress((sig, sig), threshold=1) is True
    assert mgr.detect_no_progress((sig, sig), threshold=2) is False
