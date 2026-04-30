"""TriageDecision and triage matrix (D-02) -- approval pre-screening.

Implements the exhaustive tier x trust x sensors_green matrix (24 entries)
that classifies evidence as green/yellow/red. Unknown combinations
default to RED (T-03-01 mitigation -- fail-safe).
"""

from __future__ import annotations

from enum import Enum

from ces.shared.base import CESBaseModel
from ces.shared.enums import RiskTier, TrustStatus


class TriageColor(str, Enum):
    """Triage color classification for evidence pre-screening."""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


# ---------------------------------------------------------------------------
# Exhaustive triage matrix: 3 tiers x 4 trust x 2 sensor states = 24 entries
#
# Key: (RiskTier, TrustStatus, sensors_all_green: bool)
# Value: TriageColor
#
# T-03-01 mitigation: module-level frozen dict with exhaustive keys.
# .get() with RED default for any unknown combination.
# ---------------------------------------------------------------------------

_TRIAGE_MATRIX: dict[tuple[RiskTier, TrustStatus, bool], TriageColor] = {
    # Tier C -- lowest risk
    (RiskTier.C, TrustStatus.TRUSTED, True): TriageColor.GREEN,
    (RiskTier.C, TrustStatus.TRUSTED, False): TriageColor.YELLOW,
    (RiskTier.C, TrustStatus.CANDIDATE, True): TriageColor.YELLOW,
    (RiskTier.C, TrustStatus.CANDIDATE, False): TriageColor.RED,
    (RiskTier.C, TrustStatus.WATCH, True): TriageColor.YELLOW,
    (RiskTier.C, TrustStatus.WATCH, False): TriageColor.RED,
    (RiskTier.C, TrustStatus.CONSTRAINED, True): TriageColor.RED,
    (RiskTier.C, TrustStatus.CONSTRAINED, False): TriageColor.RED,
    # Tier B -- medium risk
    (RiskTier.B, TrustStatus.TRUSTED, True): TriageColor.YELLOW,
    (RiskTier.B, TrustStatus.TRUSTED, False): TriageColor.RED,
    (RiskTier.B, TrustStatus.CANDIDATE, True): TriageColor.YELLOW,
    (RiskTier.B, TrustStatus.CANDIDATE, False): TriageColor.RED,
    (RiskTier.B, TrustStatus.WATCH, True): TriageColor.RED,
    (RiskTier.B, TrustStatus.WATCH, False): TriageColor.RED,
    (RiskTier.B, TrustStatus.CONSTRAINED, True): TriageColor.RED,
    (RiskTier.B, TrustStatus.CONSTRAINED, False): TriageColor.RED,
    # Tier A -- highest risk
    (RiskTier.A, TrustStatus.TRUSTED, True): TriageColor.YELLOW,
    (RiskTier.A, TrustStatus.TRUSTED, False): TriageColor.RED,
    (RiskTier.A, TrustStatus.CANDIDATE, True): TriageColor.RED,
    (RiskTier.A, TrustStatus.CANDIDATE, False): TriageColor.RED,
    (RiskTier.A, TrustStatus.WATCH, True): TriageColor.RED,
    (RiskTier.A, TrustStatus.WATCH, False): TriageColor.RED,
    (RiskTier.A, TrustStatus.CONSTRAINED, True): TriageColor.RED,
    (RiskTier.A, TrustStatus.CONSTRAINED, False): TriageColor.RED,
}


def triage_lookup(
    tier: RiskTier,
    trust: TrustStatus,
    sensors_green: bool,
) -> TriageColor:
    """Look up triage color for a given combination.

    Args:
        tier: Risk tier classification.
        trust: Agent trust status.
        sensors_green: Whether all sensors passed.

    Returns:
        TriageColor from the exhaustive matrix.
        Defaults to RED for unknown combinations (fail-safe).
    """
    return _TRIAGE_MATRIX.get((tier, trust, sensors_green), TriageColor.RED)


class TriageDecision(CESBaseModel):
    """Approval triage decision (D-02).

    Frozen result of the triage matrix lookup, recording the color,
    input parameters, and whether auto-approval is eligible.
    """

    color: TriageColor
    risk_tier: RiskTier
    trust_status: TrustStatus
    sensor_pass_rate: float
    reason: str
    auto_approve_eligible: bool
