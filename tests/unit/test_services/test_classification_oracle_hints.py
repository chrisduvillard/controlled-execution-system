"""Tests for ClassificationOracle.classify_from_hints().

Covers the spec-authoring hint path (Task 10). These tests do NOT exercise
the TF-IDF fuzzy matcher — they prove pure rule-based mapping from
``SignalHints`` into an ``OracleClassificationResult``.
"""

from __future__ import annotations

from ces.control.models.spec import SignalHints
from ces.control.services.classification_oracle import ClassificationOracle
from ces.shared.enums import RiskTier


def test_classify_from_hints_returns_result_with_rule() -> None:
    oracle = ClassificationOracle()
    result = oracle.classify_from_hints(
        signals=SignalHints(
            primary_change_class="feature",
            blast_radius_hint="isolated",
            touches_data=False,
            touches_auth=False,
            touches_billing=False,
        ),
        risk_hint="C",
    )
    assert result.matched_rule is not None
    assert result.matched_rule.risk_tier == RiskTier.C
    assert 0.0 <= result.confidence <= 1.0
    assert result.action in ("auto_accept", "human_review", "human_classify")


def test_classify_from_hints_escalates_on_auth_touch() -> None:
    """Auth touch must never result in a LOWER risk tier than the same
    otherwise-isolated feature change.

    ``RiskTier`` ordering is A=3, B=2, C=1 (see ``_RISK_TIER_ORDER`` in
    ``ces.shared.enums``), so ``A > C`` under ``_OrderableEnumMixin``.
    """
    oracle = ClassificationOracle()
    low = oracle.classify_from_hints(
        signals=SignalHints(
            primary_change_class="feature",
            blast_radius_hint="isolated",
            touches_data=False,
            touches_auth=False,
            touches_billing=False,
        ),
        risk_hint=None,
    )
    auth = oracle.classify_from_hints(
        signals=SignalHints(
            primary_change_class="feature",
            blast_radius_hint="isolated",
            touches_data=False,
            touches_auth=True,
            touches_billing=False,
        ),
        risk_hint=None,
    )
    assert auth.matched_rule is not None
    assert low.matched_rule is not None
    # Auth touch must not LOWER the risk tier. Higher ordering_value = higher risk.
    assert auth.matched_rule.risk_tier >= low.matched_rule.risk_tier
    # Conservative: auth-touch baseline escalates all the way to A.
    assert auth.matched_rule.risk_tier == RiskTier.A


def test_classify_from_hints_explicit_risk_overrides_blast_radius() -> None:
    """Explicit ``risk_hint`` escalates (but never downgrades) the baseline."""
    oracle = ClassificationOracle()
    # isolated baseline is C; hint A should win (escalation).
    result = oracle.classify_from_hints(
        signals=SignalHints(
            primary_change_class="feature",
            blast_radius_hint="isolated",
            touches_data=False,
            touches_auth=False,
            touches_billing=False,
        ),
        risk_hint="A",
    )
    assert result.matched_rule is not None
    assert result.matched_rule.risk_tier == RiskTier.A
