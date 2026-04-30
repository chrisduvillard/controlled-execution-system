"""Trust manager service for harness profile trust lifecycle management.

Implements:
- TRUST-01: Trust lifecycle tracking (Candidate -> Trusted -> Watch -> Constrained)
- TRUST-02: Auto-promotion when can_promote criteria met (D-07)
- TRUST-03: Automatic contraction on escapes
- TRUST-04: Autonomy ceilings enforced by BC class
- D-06: Kill switch guard on trust state writes
- D-08: Recovery lifecycle (Watch -> Trusted, Constrained -> Candidate)

The TrustLifecycle state machine models valid trust transitions.
TrustManager wraps HarnessProfile with lifecycle operations, audit logging,
and kill switch enforcement.

Threat mitigations:
- T-02-04: Promotion gaming prevented by HarnessProfile.can_promote criteria
- T-02-11: All transitions go through TrustLifecycle state machine
- T-02-12: get_autonomy_ceiling is a static method with no mutable state
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from statemachine import State, StateMachine

from ces.shared.enums import (
    ActorType,
    BehaviorConfidence,
    GateType,
    RiskTier,
    TrustStatus,
)

if TYPE_CHECKING:
    from ces.control.services.kill_switch import KillSwitchProtocol
    from ces.harness.models.harness_profile import HarnessProfile


# ---------------------------------------------------------------------------
# TrustLifecycle state machine
# ---------------------------------------------------------------------------


class TrustLifecycle(StateMachine):
    """Trust status state machine with guard-protected transitions.

    States: candidate (initial), trusted, watch, constrained.

    Transitions:
    - promote: candidate -> trusted
    - contract_to_watch: trusted -> watch, candidate -> watch
    - contract_to_constrained: watch -> constrained, trusted -> constrained
    - recover_from_watch: watch -> trusted
    - recover_from_constrained: constrained -> candidate

    Invalid transitions raise TransitionNotAllowed (hard enforcement per T-02-11).
    """

    # States
    candidate = State(initial=True)
    trusted = State()
    watch = State()
    constrained = State()

    # Promotion
    promote = candidate.to(trusted)

    # Contractions (automatic on escapes)
    contract_to_watch = trusted.to(watch) | candidate.to(watch)
    contract_to_constrained = watch.to(constrained) | trusted.to(constrained)

    # Recovery
    recover_from_watch = watch.to(trusted)
    recover_from_constrained = constrained.to(candidate)

    def __init__(self, start_value: str | None = None) -> None:
        if start_value is not None:
            super().__init__(start_value=start_value)
        else:
            super().__init__()


# ---------------------------------------------------------------------------
# Autonomy ceiling matrix (TRUST-04)
# ---------------------------------------------------------------------------

# BC3 always HUMAN, regardless of tier or trust.
# BC2 + Tier A -> HUMAN.
# BC2 + other tiers -> HYBRID.
# BC1 + CONSTRAINED -> HUMAN (restricted).
# BC1 + WATCH -> HYBRID (reduced autonomy).
# BC1 + CANDIDATE -> HYBRID (not yet trusted).
# BC1 + TRUSTED + Tier A -> HYBRID (high-risk tier ceiling).
# BC1 + TRUSTED + Tier B -> HYBRID.
# BC1 + TRUSTED + Tier C -> AGENT (maximum autonomy).

_AUTONOMY_CEILING: dict[tuple[BehaviorConfidence, RiskTier, TrustStatus], GateType] = {
    # BC3: always HUMAN
    (BehaviorConfidence.BC3, RiskTier.A, TrustStatus.CANDIDATE): GateType.HUMAN,
    (BehaviorConfidence.BC3, RiskTier.A, TrustStatus.TRUSTED): GateType.HUMAN,
    (BehaviorConfidence.BC3, RiskTier.A, TrustStatus.WATCH): GateType.HUMAN,
    (BehaviorConfidence.BC3, RiskTier.A, TrustStatus.CONSTRAINED): GateType.HUMAN,
    (BehaviorConfidence.BC3, RiskTier.B, TrustStatus.CANDIDATE): GateType.HUMAN,
    (BehaviorConfidence.BC3, RiskTier.B, TrustStatus.TRUSTED): GateType.HUMAN,
    (BehaviorConfidence.BC3, RiskTier.B, TrustStatus.WATCH): GateType.HUMAN,
    (BehaviorConfidence.BC3, RiskTier.B, TrustStatus.CONSTRAINED): GateType.HUMAN,
    (BehaviorConfidence.BC3, RiskTier.C, TrustStatus.CANDIDATE): GateType.HUMAN,
    (BehaviorConfidence.BC3, RiskTier.C, TrustStatus.TRUSTED): GateType.HUMAN,
    (BehaviorConfidence.BC3, RiskTier.C, TrustStatus.WATCH): GateType.HUMAN,
    (BehaviorConfidence.BC3, RiskTier.C, TrustStatus.CONSTRAINED): GateType.HUMAN,
    # BC2 + Tier A: HUMAN
    (BehaviorConfidence.BC2, RiskTier.A, TrustStatus.CANDIDATE): GateType.HUMAN,
    (BehaviorConfidence.BC2, RiskTier.A, TrustStatus.TRUSTED): GateType.HUMAN,
    (BehaviorConfidence.BC2, RiskTier.A, TrustStatus.WATCH): GateType.HUMAN,
    (BehaviorConfidence.BC2, RiskTier.A, TrustStatus.CONSTRAINED): GateType.HUMAN,
    # BC2 + Tier B/C: HYBRID
    (BehaviorConfidence.BC2, RiskTier.B, TrustStatus.CANDIDATE): GateType.HYBRID,
    (BehaviorConfidence.BC2, RiskTier.B, TrustStatus.TRUSTED): GateType.HYBRID,
    (BehaviorConfidence.BC2, RiskTier.B, TrustStatus.WATCH): GateType.HYBRID,
    (BehaviorConfidence.BC2, RiskTier.B, TrustStatus.CONSTRAINED): GateType.HUMAN,
    (BehaviorConfidence.BC2, RiskTier.C, TrustStatus.CANDIDATE): GateType.HYBRID,
    (BehaviorConfidence.BC2, RiskTier.C, TrustStatus.TRUSTED): GateType.HYBRID,
    (BehaviorConfidence.BC2, RiskTier.C, TrustStatus.WATCH): GateType.HYBRID,
    (BehaviorConfidence.BC2, RiskTier.C, TrustStatus.CONSTRAINED): GateType.HUMAN,
    # BC1 + CONSTRAINED: HUMAN (regardless of tier)
    (BehaviorConfidence.BC1, RiskTier.A, TrustStatus.CONSTRAINED): GateType.HUMAN,
    (BehaviorConfidence.BC1, RiskTier.B, TrustStatus.CONSTRAINED): GateType.HUMAN,
    (BehaviorConfidence.BC1, RiskTier.C, TrustStatus.CONSTRAINED): GateType.HUMAN,
    # BC1 + WATCH: HYBRID (regardless of tier)
    (BehaviorConfidence.BC1, RiskTier.A, TrustStatus.WATCH): GateType.HYBRID,
    (BehaviorConfidence.BC1, RiskTier.B, TrustStatus.WATCH): GateType.HYBRID,
    (BehaviorConfidence.BC1, RiskTier.C, TrustStatus.WATCH): GateType.HYBRID,
    # BC1 + CANDIDATE: HYBRID (regardless of tier)
    (BehaviorConfidence.BC1, RiskTier.A, TrustStatus.CANDIDATE): GateType.HYBRID,
    (BehaviorConfidence.BC1, RiskTier.B, TrustStatus.CANDIDATE): GateType.HYBRID,
    (BehaviorConfidence.BC1, RiskTier.C, TrustStatus.CANDIDATE): GateType.HYBRID,
    # BC1 + TRUSTED: tier-dependent
    (BehaviorConfidence.BC1, RiskTier.A, TrustStatus.TRUSTED): GateType.HYBRID,
    (BehaviorConfidence.BC1, RiskTier.B, TrustStatus.TRUSTED): GateType.HYBRID,
    (BehaviorConfidence.BC1, RiskTier.C, TrustStatus.TRUSTED): GateType.AGENT,
}


# ---------------------------------------------------------------------------
# TrustManager service
# ---------------------------------------------------------------------------


class TrustManager:
    """Trust lifecycle service for harness profiles.

    Wraps HarnessProfile with state machine transitions, audit logging,
    and kill switch enforcement.

    Constructor accepts optional dependencies for flexibility:
    - audit_ledger: Any object implementing AuditLedgerProtocol (logs trust events)
    - kill_switch: Any object implementing KillSwitchProtocol (guards trust writes)
    - trust_event_repo: TrustEventRepository for persisting trust events

    All dependencies are optional -- works standalone for unit testing.
    """

    def __init__(
        self,
        audit_ledger: object | None = None,
        kill_switch: KillSwitchProtocol | None = None,
        trust_event_repo: object | None = None,
    ) -> None:
        self._audit = audit_ledger
        self._kill_switch = kill_switch
        self._trust_event_repo = trust_event_repo

    # ---- Kill switch guard ----

    def _is_blocked(self) -> bool:
        """Check if trust state writes are blocked by kill switch."""
        if self._kill_switch is None:
            return False
        return self._kill_switch.is_halted("registry_writes")

    # ---- Audit helper ----

    async def _log_trust_change(
        self,
        profile: HarnessProfile,
        from_status: str,
        to_status: str,
        trigger: str,
    ) -> None:
        """Log a trust lifecycle event to the audit ledger."""
        if self._audit is not None:
            await self._audit.record_state_transition(  # type: ignore[attr-defined]
                manifest_id=profile.profile_id,
                actor="trust_manager",
                actor_type=ActorType.CONTROL_PLANE,
                from_state=from_status,
                to_state=to_status,
                rationale=f"Trust {trigger}: {from_status} -> {to_status}",
            )

    # ---- Lifecycle operations ----

    async def evaluate_promotion(self, profile: HarnessProfile) -> HarnessProfile:
        """Evaluate and execute auto-promotion if eligible (TRUST-02, D-07).

        If profile.can_promote is True and status is CANDIDATE,
        automatically promotes to TRUSTED. No human confirmation needed.

        Args:
            profile: The harness profile to evaluate.

        Returns:
            The (possibly updated) harness profile.
        """
        if self._is_blocked():
            return profile

        if profile.trust_status != TrustStatus.CANDIDATE:
            return profile

        if not profile.can_promote:
            return profile

        # Execute state machine transition
        sm = TrustLifecycle(start_value=profile.trust_status.value)
        old_status = profile.trust_status.value
        sm.promote()
        profile.trust_status = TrustStatus.TRUSTED

        await self._log_trust_change(profile, old_status, profile.trust_status.value, "auto_promote")
        return profile

    async def record_escape(
        self,
        profile: HarnessProfile,
        escape_ref: str,
        severity: int,
    ) -> HarnessProfile:
        """Record an escape event and contract trust status (TRUST-03, D-08).

        - TRUSTED or CANDIDATE -> WATCH (first escape)
        - WATCH -> CONSTRAINED (repeated escape)

        Args:
            profile: The harness profile experiencing the escape.
            escape_ref: Reference identifier for the escape event.
            severity: Escape severity level (1=critical, 2=moderate).

        Returns:
            The updated harness profile with contracted trust status.
        """
        if self._is_blocked():
            return profile

        old_status = profile.trust_status.value
        sm = TrustLifecycle(start_value=profile.trust_status.value)

        # Determine contraction target
        if profile.trust_status in (TrustStatus.TRUSTED, TrustStatus.CANDIDATE):
            sm.contract_to_watch()
            profile.trust_status = TrustStatus.WATCH
        elif profile.trust_status == TrustStatus.WATCH:
            sm.contract_to_constrained()
            profile.trust_status = TrustStatus.CONSTRAINED
        else:
            # Already constrained -- no further contraction possible
            return profile

        # Update escape tracking
        profile.escapes += 1
        profile.escape_history = (*profile.escape_history, escape_ref)

        await self._log_trust_change(profile, old_status, profile.trust_status.value, "escape")
        return profile

    async def attempt_recovery(self, profile: HarnessProfile) -> HarnessProfile:
        """Attempt trust recovery from degraded status (D-08).

        - WATCH + can_promote -> TRUSTED
        - CONSTRAINED -> CANDIDATE (must re-earn trust)
        - WATCH + !can_promote -> no change

        Args:
            profile: The harness profile attempting recovery.

        Returns:
            The (possibly updated) harness profile.
        """
        if self._is_blocked():
            return profile

        old_status = profile.trust_status.value
        sm = TrustLifecycle(start_value=profile.trust_status.value)

        if profile.trust_status == TrustStatus.WATCH:
            if not profile.can_promote:
                return profile
            sm.recover_from_watch()
            profile.trust_status = TrustStatus.TRUSTED
        elif profile.trust_status == TrustStatus.CONSTRAINED:
            sm.recover_from_constrained()
            profile.trust_status = TrustStatus.CANDIDATE
        else:
            return profile

        await self._log_trust_change(profile, old_status, profile.trust_status.value, "recovery")
        return profile

    # ---- Autonomy ceiling (TRUST-04) ----

    @staticmethod
    def get_autonomy_ceiling(
        bc: BehaviorConfidence,
        risk_tier: RiskTier,
        trust_status: TrustStatus,
    ) -> GateType:
        """Determine the maximum autonomy level (gate type ceiling).

        Per TRUST-04:
        - BC3 always returns HUMAN
        - BC2 + Tier A returns HUMAN
        - Otherwise determined by trust status and tier combination

        This is a static method with no mutable instance state (T-02-12).

        Args:
            bc: Behavior confidence level.
            risk_tier: Risk tier classification.
            trust_status: Current trust status.

        Returns:
            The maximum allowed gate type (autonomy ceiling).
        """
        key = (bc, risk_tier, trust_status)
        result = _AUTONOMY_CEILING.get(key)
        if result is not None:
            return result
        # Fallback: HUMAN (most restrictive) for unknown combinations
        return GateType.HUMAN
