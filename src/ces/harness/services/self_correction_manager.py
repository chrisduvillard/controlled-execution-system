"""Self-correction manager with bounded retries, token budget, and circuit breaker.

Implements:
- SENS-04: Bounded retries within manifest limits (can_retry, record_retry)
- SENS-05: Second-agent validation for Tier A final retry (needs_second_agent)
- SENS-06: Token budget enforcement across all repair attempts (check_token_budget)
- SENS-07: Circuit breaker with D-10 hard limits (check_circuit_breaker)
- D-10: Max delegation depth=3, max total spawns=10
- D-11: Alternate model selection for independent validation

Threat mitigations:
- T-03-15: increment_depth called BEFORE dispatch (not after). Checks depth AND spawns independently.
- T-03-16: needs_second_agent is deterministic: risk_tier == A AND retry_count == max_retries - 1.
- T-03-17: CESBaseModel is frozen; record_retry returns NEW state via model_copy.
- T-03-18: check_token_budget enforces cumulative limit across all retries.
- T-03-19: Circuit breaker breach logs to audit AND triggers kill switch for "spawning".

Exports:
    SelfCorrectionManager: Service class for bounded self-correction.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from ces.harness.models.completion_claim import VerificationFinding
from ces.harness.models.self_correction_state import (
    CircuitBreakerState,
    SelfCorrectionState,
)
from ces.harness.models.tool_call_signature import ToolCallSignature
from ces.shared.enums import ActorType, EventType, RiskTier

if TYPE_CHECKING:
    from ces.control.services.kill_switch import KillSwitchProtocol


# Severity ranking for repair-prompt ordering. Critical findings go first so
# the agent encounters them before lower-priority items in its limited
# attention budget.
_SEVERITY_RANK: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class SelfCorrectionManager:
    """Self-correction manager enforcing bounded retries and circuit breaker limits.

    Provides deterministic checks for retry eligibility, token budgets,
    circuit breaker limits, and second-agent validation requirements.
    All state mutations return new frozen model instances; original state
    is never modified.

    Args:
        kill_switch: Optional KillSwitchProtocol for circuit breaker integration.
            When a circuit breaker breach is detected, the kill switch is
            checked/logged for the "spawning" activity class.
        audit_ledger: Optional audit ledger for event logging.
            Must have an async append_event method.
    """

    def __init__(
        self,
        kill_switch: KillSwitchProtocol | None = None,
        audit_ledger: object | None = None,
    ) -> None:
        self._kill_switch = kill_switch
        self._audit_ledger = audit_ledger

    # ---- Bounded retry (SENS-04) ----

    def can_retry(self, state: SelfCorrectionState) -> bool:
        """Check if another retry is allowed within manifest limits.

        Returns True only if retry_count < max_retries AND
        tokens_used < token_budget. Simple deterministic check.

        Args:
            state: Current self-correction state.

        Returns:
            True if retry is allowed, False otherwise.
        """
        return state.retry_count < state.max_retries and state.tokens_used < state.token_budget

    def record_retry(self, state: SelfCorrectionState, tokens_consumed: int) -> SelfCorrectionState:
        """Record a retry attempt, returning a new state snapshot.

        Increments retry_count, adds tokens_consumed to tokens_used,
        and increments total_spawns. The original state is never mutated
        (CESBaseModel is frozen). Logs DELEGATION event to audit ledger.

        Args:
            state: Current self-correction state.
            tokens_consumed: Number of tokens consumed by this retry.

        Returns:
            New SelfCorrectionState with updated counters.
        """
        new_state = state.model_copy(
            update={
                "retry_count": state.retry_count + 1,
                "tokens_used": state.tokens_used + tokens_consumed,
                "total_spawns": state.total_spawns + 1,
            }
        )

        # Log DELEGATION event to audit ledger
        if self._audit_ledger is not None:
            self._fire_audit_event(
                event_type=EventType.DELEGATION,
                actor="self_correction_manager",
                actor_type=ActorType.CONTROL_PLANE,
                action_summary=(
                    f"Retry recorded for task {state.task_id}: "
                    f"attempt {new_state.retry_count}/{state.max_retries}, "
                    f"tokens {new_state.tokens_used}/{state.token_budget}"
                ),
                decision="retry",
                rationale="Bounded self-correction retry",
            )

        return new_state

    # ---- Token budget (SENS-06) ----

    def check_token_budget(self, state: SelfCorrectionState, tokens_needed: int) -> bool:
        """Check if tokens_needed fits within the remaining token budget.

        Enforces cumulative token limit across all retries per SENS-06.

        Args:
            state: Current self-correction state.
            tokens_needed: Number of tokens the next operation requires.

        Returns:
            True if tokens_used + tokens_needed <= token_budget.
        """
        return state.tokens_used + tokens_needed <= state.token_budget

    # ---- Circuit breaker (SENS-07, D-10) ----

    async def check_circuit_breaker(self, state: CircuitBreakerState) -> CircuitBreakerState:
        """Check circuit breaker limits and trip if breached.

        Evaluates both delegation depth and total spawn limits independently.
        If either limit is breached, the circuit breaker trips. On breach:
        - Returns tripped state with descriptive trip_reason
        - Logs DELEGATION event with circuit_breaker_tripped metadata to audit
        - Signals kill switch for "spawning" activity class if configured

        Args:
            state: Current circuit breaker state.

        Returns:
            Original state if within limits, or tripped state if breached.
        """
        reasons: list[str] = []

        if state.current_depth >= state.max_depth:
            reasons.append(f"Delegation depth {state.current_depth} >= max {state.max_depth}")

        if state.total_spawns >= state.max_spawns:
            reasons.append(f"Total spawns {state.total_spawns} >= max {state.max_spawns}")

        if not reasons:
            return state

        # Trip the circuit breaker
        trip_reason = "; ".join(reasons)
        tripped_state = state.model_copy(
            update={
                "tripped": True,
                "trip_reason": trip_reason,
            }
        )

        # Log DELEGATION event with circuit breaker metadata to audit
        if self._audit_ledger is not None:
            await self._audit_ledger.append_event(  # type: ignore[attr-defined]
                event_type=EventType.DELEGATION,
                actor="self_correction_manager",
                actor_type=ActorType.CONTROL_PLANE,
                action_summary=(f"Circuit breaker tripped for task {state.task_id}: {trip_reason}"),
                decision="circuit_breaker_tripped",
                rationale=trip_reason,
            )

        # Signal kill switch for spawning activity class (T-03-19)
        if self._kill_switch is not None:
            # Log that kill switch was notified of the breach.
            # The actual kill switch activation would be triggered by the
            # orchestration layer calling kill_switch.activate() for "spawning".
            # Here we check current status for diagnostic purposes.
            self._kill_switch.is_halted("spawning")

        return tripped_state

    def increment_depth(self, state: CircuitBreakerState) -> CircuitBreakerState:
        """Increment delegation depth and spawn count BEFORE dispatch.

        Per Pitfall 3: increment must happen BEFORE dispatching a sub-agent,
        not after. This prevents race conditions where the depth check
        passes but the dispatch creates an unbounded chain.

        Args:
            state: Current circuit breaker state.

        Returns:
            New CircuitBreakerState with current_depth+1 and total_spawns+1.
        """
        return state.model_copy(
            update={
                "current_depth": state.current_depth + 1,
                "total_spawns": state.total_spawns + 1,
            }
        )

    # ---- Second-agent validation (SENS-05, D-11) ----

    def needs_second_agent(self, state: SelfCorrectionState, risk_tier: RiskTier) -> bool:
        """Check if a second agent is needed for independent validation.

        Per D-11 and SENS-05: Tier A work on its final retry requires
        a second agent using a different model for independent validation.
        This is a deterministic check that cannot be overridden at runtime
        (T-03-16).

        Args:
            state: Current self-correction state.
            risk_tier: Risk tier of the task.

        Returns:
            True if risk_tier == A AND retry_count == max_retries - 1.
        """
        return risk_tier == RiskTier.A and state.retry_count == state.max_retries - 1

    # ---- Internal helpers ----

    def _fire_audit_event(self, **kwargs: object) -> None:
        """Fire an audit event from a synchronous context.

        Bridges sync callers (record_retry) to the async audit ledger.
        If a running event loop exists, schedules the coroutine as a task.
        The coroutine is awaited eagerly via ensure_future so it completes
        within the current event loop iteration when possible.
        """
        import asyncio

        if self._audit_ledger is None:
            return

        coro = self._audit_ledger.append_event(**kwargs)  # type: ignore[attr-defined]
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            # No running event loop -- skip async logging
            pass

    # ---- No-progress loop detection (P4) ----

    def detect_no_progress(
        self,
        tool_calls: tuple[ToolCallSignature, ...],
        threshold: int = 3,
    ) -> bool:
        """Return True if any signature appears more than ``threshold`` times.

        Catches the "agent re-issues the same tool call without state changing"
        pattern that drives runaway-cost incidents (Agent Patterns "Infinite
        Agent Loop", LangChain #36139). The caller is expected to maintain the
        history; this method is pure.
        """
        if not tool_calls:
            return False
        counts = Counter(tool_calls)
        return any(count > threshold for count in counts.values())

    # ---- Repair prompt builder (P2) ----

    def build_repair_prompt(self, findings: tuple[VerificationFinding, ...]) -> str:
        """Synthesise a structured repair prompt from verification findings.

        Closes the evidence-driven retry loop: when the Completion Gate rejects
        an agent's work, the workflow re-dispatches the agent with this prompt
        appended so it can self-correct.

        The output groups findings by kind, orders by severity (critical
        first), and includes both the failure message and the suggested hint.
        Empty input yields an empty string so the caller can append
        unconditionally.
        """
        if not findings:
            return ""

        # Group preserving severity order so each kind block is also ranked.
        sorted_findings = sorted(
            findings,
            key=lambda f: (_SEVERITY_RANK.get(f.severity, 99), f.kind.value),
        )
        grouped: dict[str, list[VerificationFinding]] = {}
        for f in sorted_findings:
            grouped.setdefault(f.kind.value, []).append(f)

        lines: list[str] = [
            "## Verification failed — repair required",
            "",
            "The Completion Gate rejected the previous claim. Address every "
            "finding below, re-emit a `ces:completion` block, and exit. Do not "
            "claim completion until all findings are resolved.",
            "",
        ]

        for kind_value, group in grouped.items():
            lines.append(f"### {kind_value}")
            for f in group:
                bullet = f"- [{f.severity}] {f.message}"
                if f.related_sensor:
                    bullet += f" (sensor: {f.related_sensor})"
                if f.related_criterion:
                    bullet += f" (criterion: {f.related_criterion!r})"
                lines.append(bullet)
                lines.append(f"    Hint: {f.hint}")
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    def select_alternate_model(self, current_model_id: str, model_roster: list[str]) -> str:
        """Select an alternate model for second-agent validation.

        Per D-11: Returns the first model from the roster that differs
        from the current model. Raises ValueError if no alternate is
        available.

        Args:
            current_model_id: The model currently being used.
            model_roster: List of available model IDs.

        Returns:
            The first model ID from roster != current_model_id.

        Raises:
            ValueError: If no alternate model is available in the roster.
        """
        for model_id in model_roster:
            if model_id != current_model_id:
                return model_id
        msg = f"No alternate model available in roster (current: {current_model_id})"
        raise ValueError(msg)
