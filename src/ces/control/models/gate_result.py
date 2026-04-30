"""Gate evaluation result model and gate type matrix (PRD SS16.7.2).

Exports:
    GateEvaluationResult: Frozen dataclass for gate evaluation output.
    GATE_TYPE_MATRIX: Dict mapping (phase, trust_category) to GateType.
    _trust_category: Helper to map (tier, BC, trust_status) to category string.

The GATE_TYPE_MATRIX encodes the PRD SS16.7.2 table as a static data structure.
Key: (phase: int, trust_category: str) -> GateType
Trust categories:
    - "tier_c_bc1_trusted": Tier C, BC1, Trusted
    - "tier_b_bc1_trusted_mc": Tier B, BC1, Trusted (min credible)
    - "tier_a_or_bc2_plus": Tier A or BC2+ or BC3, any trust
    - "non_trusted": Candidate / Watch / Constrained
"""

from __future__ import annotations

from dataclasses import dataclass

from ces.shared.enums import (
    BehaviorConfidence,
    GateType,
    RiskTier,
    TrustStatus,
)


@dataclass(frozen=True)
class GateEvaluationResult:
    """Result of a gate evaluation with confidence elevation applied.

    Attributes:
        gate_type: Final gate type after confidence elevation.
        base_gate_type: Gate type from matrix before confidence elevation.
        confidence_used: Oracle confidence score that was applied.
        phase: Phase number (1-10).
        risk_tier: Risk tier classification.
        behavior_confidence: Behavior confidence level.
        trust_status: Harness profile trust status.
        meta_review_selected: True if this gate was selected for meta-review (GATE-04).
        hidden_check: True if this is a hidden gate check injection (GATE-05).
    """

    gate_type: GateType
    base_gate_type: GateType
    confidence_used: float
    phase: int
    risk_tier: RiskTier
    behavior_confidence: BehaviorConfidence
    trust_status: TrustStatus
    meta_review_selected: bool
    hidden_check: bool


# ---------------------------------------------------------------------------
# PRD SS16.7.2 Gate Type Matrix
# Source: docs/PRD.md lines 2782-2793 [VERIFIED]
#
# 10 phases x 4 trust categories = 40 entries
# ---------------------------------------------------------------------------

GATE_TYPE_MATRIX: dict[tuple[int, str], GateType] = {
    # Phase 1: Opportunity framing
    (1, "tier_c_bc1_trusted"): GateType.HYBRID,
    (1, "tier_b_bc1_trusted_mc"): GateType.HUMAN,
    (1, "tier_a_or_bc2_plus"): GateType.HUMAN,
    (1, "non_trusted"): GateType.HUMAN,
    # Phase 2: Discovery
    (2, "tier_c_bc1_trusted"): GateType.AGENT,
    (2, "tier_b_bc1_trusted_mc"): GateType.HYBRID,
    (2, "tier_a_or_bc2_plus"): GateType.HUMAN,
    (2, "non_trusted"): GateType.HUMAN,
    # Phase 3: Product truth
    (3, "tier_c_bc1_trusted"): GateType.HYBRID,
    (3, "tier_b_bc1_trusted_mc"): GateType.HUMAN,
    (3, "tier_a_or_bc2_plus"): GateType.HUMAN,
    (3, "non_trusted"): GateType.HUMAN,
    # Phase 4: Architecture & harness
    (4, "tier_c_bc1_trusted"): GateType.HYBRID,
    (4, "tier_b_bc1_trusted_mc"): GateType.HUMAN,
    (4, "tier_a_or_bc2_plus"): GateType.HUMAN,
    (4, "non_trusted"): GateType.HUMAN,
    # Phase 5: Planning & decomposition
    (5, "tier_c_bc1_trusted"): GateType.AGENT,
    (5, "tier_b_bc1_trusted_mc"): GateType.AGENT,
    (5, "tier_a_or_bc2_plus"): GateType.HUMAN,
    (5, "non_trusted"): GateType.HUMAN,
    # Phase 6: Calibration
    (6, "tier_c_bc1_trusted"): GateType.AGENT,
    (6, "tier_b_bc1_trusted_mc"): GateType.HYBRID,
    (6, "tier_a_or_bc2_plus"): GateType.HUMAN,
    (6, "non_trusted"): GateType.HUMAN,
    # Phase 7: Execution (per-task)
    (7, "tier_c_bc1_trusted"): GateType.AGENT,
    (7, "tier_b_bc1_trusted_mc"): GateType.AGENT,
    (7, "tier_a_or_bc2_plus"): GateType.HUMAN,
    (7, "non_trusted"): GateType.HUMAN,
    # Phase 8: Integration & hardening
    (8, "tier_c_bc1_trusted"): GateType.HYBRID,
    (8, "tier_b_bc1_trusted_mc"): GateType.HUMAN,
    (8, "tier_a_or_bc2_plus"): GateType.HUMAN,
    (8, "non_trusted"): GateType.HUMAN,
    # Phase 9: Release & cutover
    (9, "tier_c_bc1_trusted"): GateType.HYBRID,
    (9, "tier_b_bc1_trusted_mc"): GateType.HUMAN,
    (9, "tier_a_or_bc2_plus"): GateType.HUMAN,
    (9, "non_trusted"): GateType.HUMAN,
    # Phase 10: Post-launch stewardship
    (10, "tier_c_bc1_trusted"): GateType.AGENT,
    (10, "tier_b_bc1_trusted_mc"): GateType.HYBRID,
    (10, "tier_a_or_bc2_plus"): GateType.HUMAN,
    (10, "non_trusted"): GateType.HUMAN,
}


def _trust_category(
    risk_tier: RiskTier,
    bc: BehaviorConfidence,
    trust_status: TrustStatus,
) -> str:
    """Map (tier, BC, trust_status) to a gate matrix column key.

    Categories (from PRD SS16.7.2):
        - "non_trusted": Candidate, Watch, or Constrained status
        - "tier_a_or_bc2_plus": Trusted + (Tier A or BC2 or BC3)
        - "tier_b_bc1_trusted_mc": Trusted + Tier B + BC1 (min credible)
        - "tier_c_bc1_trusted": Trusted + Tier C + BC1

    Args:
        risk_tier: Risk tier classification (A/B/C).
        bc: Behavior confidence level (BC1/BC2/BC3).
        trust_status: Harness profile trust status.

    Returns:
        Trust category string for GATE_TYPE_MATRIX lookup.
    """
    if trust_status in (
        TrustStatus.CANDIDATE,
        TrustStatus.WATCH,
        TrustStatus.CONSTRAINED,
    ):
        return "non_trusted"

    # trust_status is TRUSTED from here
    if risk_tier == RiskTier.A or bc in (
        BehaviorConfidence.BC2,
        BehaviorConfidence.BC3,
    ):
        return "tier_a_or_bc2_plus"

    if risk_tier == RiskTier.B and bc == BehaviorConfidence.BC1:
        return "tier_b_bc1_trusted_mc"

    # Tier C / BC1 / Trusted
    return "tier_c_bc1_trusted"
