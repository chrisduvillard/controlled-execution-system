"""Gate evaluator service (PRD SS16.7.2, GATE-01 through GATE-05).

Determines the required review gate type for each phase transition based on
the PRD's 10-phase x 4-trust-category matrix, applies confidence-based
elevation from the classification oracle (SS16.7.6, CLASS-06), and includes
anti-gaming mechanisms (meta-review sampling and hidden gate checks).

Exports:
    GateEvaluator: Service class for gate type evaluation.

Design:
    - GATE-01: Three gate types supported (AGENT/HYBRID/HUMAN)
    - GATE-02: Phase/tier/trust matrix lookup with 40 entries
    - GATE-03: Gate evidence packets produced with evaluation criteria
    - GATE-04: Meta-review sampling at configurable rates (10/50/100%)
    - GATE-05: Hidden gate checks at 5% injection rate
    - CLASS-06 / D-04: Oracle confidence feeds gate type selection

Threat mitigations:
    - T-02-06: Confidence elevation only makes gates stricter (never downgrades HUMAN)
    - T-02-15: GATE_TYPE_MATRIX is a frozen module-level constant with exhaustive lookup
    - T-02-16: Meta-review and hidden checks are probabilistic and not predictable
"""

from __future__ import annotations

import random

from ces.control.models.gate_result import (
    GATE_TYPE_MATRIX,
    GateEvaluationResult,
    _trust_category,
)
from ces.shared.enums import (
    BehaviorConfidence,
    GateType,
    RiskTier,
    TrustStatus,
)


class GateEvaluator:
    """Evaluates phase gate requirements per PRD SS16.7.2.

    Determines what level of review is required for each phase transition
    by combining the gate type matrix lookup, oracle confidence elevation,
    meta-review sampling, and hidden gate check injection.

    Args:
        meta_review_rates: Sampling rates per risk tier for meta-review.
            Defaults to {"A": 1.0, "B": 0.5, "C": 0.1} per GATE-04.
        hidden_check_rate: Injection rate for hidden gate checks.
            Defaults to 0.05 (5%) per GATE-05.
        new_profile_threshold: Number of evaluations per profile before
            normal sampling rates apply. First N are always meta-reviewed.
            Defaults to 50 per GATE-04.
    """

    def __init__(
        self,
        meta_review_rates: dict[str, float] | None = None,
        hidden_check_rate: float = 0.05,
        new_profile_threshold: int = 50,
    ) -> None:
        self._meta_review_rates = meta_review_rates or {
            "A": 1.0,
            "B": 0.5,
            "C": 0.1,
        }
        self._hidden_check_rate = hidden_check_rate
        self._new_profile_threshold = new_profile_threshold
        self._profile_evaluation_counts: dict[str, int] = {}

    def evaluate(
        self,
        phase: int,
        risk_tier: RiskTier,
        bc: BehaviorConfidence,
        trust_status: TrustStatus,
        oracle_confidence: float,
        profile_id: str = "",
    ) -> GateEvaluationResult:
        """Determine the required gate type for a phase transition.

        Steps:
            1. Look up base gate type from GATE_TYPE_MATRIX.
            2. Apply confidence elevation per SS16.7.6 (D-04, CLASS-06).
            3. Determine meta-review selection (GATE-04).
            4. Determine hidden gate check injection (GATE-05).
            5. Return GateEvaluationResult with all fields populated.

        Args:
            phase: Phase number (1-10).
            risk_tier: Risk tier classification (A/B/C).
            bc: Behavior confidence level (BC1/BC2/BC3).
            trust_status: Harness profile trust status.
            oracle_confidence: Classification oracle confidence score (0.0-1.0).
            profile_id: Harness profile identifier for meta-review tracking.

        Returns:
            GateEvaluationResult with the final gate type after elevation.

        Raises:
            KeyError: If (phase, trust_category) is not in GATE_TYPE_MATRIX.
        """
        # Step 1: Matrix lookup
        category = _trust_category(risk_tier, bc, trust_status)
        base_gate = GATE_TYPE_MATRIX[(phase, category)]

        # Step 2: Confidence elevation (SS16.7.6)
        # T-02-06: Elevation only makes gates stricter, never downgrades HUMAN
        gate_type = self._apply_confidence_elevation(base_gate, oracle_confidence)

        # Step 3: Meta-review selection (GATE-04)
        meta_review = self.should_meta_review(risk_tier, profile_id)

        # Step 4: Hidden gate check injection (GATE-05)
        hidden = self.is_hidden_gate_check()

        # Step 5: Track profile evaluation count
        self._profile_evaluation_counts[profile_id] = self._profile_evaluation_counts.get(profile_id, 0) + 1

        return GateEvaluationResult(
            gate_type=gate_type,
            base_gate_type=base_gate,
            confidence_used=oracle_confidence,
            phase=phase,
            risk_tier=risk_tier,
            behavior_confidence=bc,
            trust_status=trust_status,
            meta_review_selected=meta_review,
            hidden_check=hidden,
        )

    def _apply_confidence_elevation(
        self,
        base_gate: GateType,
        oracle_confidence: float,
    ) -> GateType:
        """Apply confidence-based gate elevation per SS16.7.6.

        Elevation rules:
            - confidence < 0.70: gate becomes HUMAN regardless
            - confidence 0.70-0.90: AGENT -> HYBRID, HYBRID -> HUMAN
            - confidence >= 0.90: no elevation (use matrix value)
            - HUMAN is never downgraded (T-02-06)

        Args:
            base_gate: Gate type from matrix lookup.
            oracle_confidence: Oracle confidence score (0.0-1.0).

        Returns:
            Final gate type after elevation.
        """
        if oracle_confidence < 0.70:
            return GateType.HUMAN

        if oracle_confidence < 0.90:
            # Elevate one level
            if base_gate == GateType.AGENT:
                return GateType.HYBRID
            if base_gate == GateType.HYBRID:
                return GateType.HUMAN
            # HUMAN stays HUMAN
            return base_gate

        # High confidence (>= 0.90): no elevation
        return base_gate

    def should_meta_review(
        self,
        risk_tier: RiskTier,
        profile_id: str,
    ) -> bool:
        """Determine if this gate evaluation should be meta-reviewed (GATE-04).

        Sampling rates:
            - Tier A: 100% (always meta-reviewed)
            - Tier B: 50%
            - Tier C: 10%
            - First 50 evaluations per profile: 100% (always meta-reviewed)

        T-02-16: Probabilistic sampling is not predictable by agents.

        Args:
            risk_tier: Risk tier classification.
            profile_id: Harness profile identifier for tracking.

        Returns:
            True if this evaluation should be meta-reviewed.
        """
        # First N evaluations per profile are always meta-reviewed
        current_count = self._profile_evaluation_counts.get(profile_id, 0)
        if current_count < self._new_profile_threshold:
            return True

        # Tier-based sampling rate
        rate = self._meta_review_rates.get(risk_tier.value, 1.0)
        return random.random() < rate  # noqa: S311

    def is_hidden_gate_check(self) -> bool:
        """Determine if a hidden gate check should be injected (GATE-05).

        Hidden gate checks inject work that should fail the gate, at a 5%
        injection rate. These are probabilistic and not predictable by the
        agent being evaluated (T-02-16).

        Returns:
            True if a hidden gate check should be injected.
        """
        return random.random() < self._hidden_check_rate  # noqa: S311

    def produce_gate_evidence(
        self,
        result: GateEvaluationResult,
        evaluation_details: dict,
    ) -> dict:
        """Produce a gate evidence dict for a gate evaluation (GATE-03).

        Gate evidence packets contain the evaluation criteria, gate type
        assignment, confidence data, and detailed evaluation results.

        Args:
            result: The GateEvaluationResult to package as evidence.
            evaluation_details: Additional details from the evaluation
                (e.g., criteria checks, review outcomes).

        Returns:
            Dict containing all gate evaluation evidence fields.
        """
        return {
            "gate_type": result.gate_type.value,
            "base_gate_type": result.base_gate_type.value,
            "confidence": result.confidence_used,
            "phase": result.phase,
            "risk_tier": result.risk_tier.value,
            "behavior_confidence": result.behavior_confidence.value,
            "trust_status": result.trust_status.value,
            "meta_review": result.meta_review_selected,
            "hidden_check": result.hidden_check,
            "evaluation_details": evaluation_details,
        }
