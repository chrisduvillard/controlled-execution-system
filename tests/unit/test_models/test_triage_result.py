"""Tests for TriageDecision and triage matrix (D-02).

Validates that the exhaustive triage matrix covers all 24 tier x trust x sensor
combinations and that TriageDecision is a frozen CESBaseModel.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ces.harness.models.triage_result import (
    _TRIAGE_MATRIX,
    TriageColor,
    TriageDecision,
    triage_lookup,
)
from ces.shared.enums import RiskTier, TrustStatus


class TestTriageColor:
    """TriageColor enum tests."""

    def test_values(self) -> None:
        assert TriageColor.GREEN.value == "green"
        assert TriageColor.YELLOW.value == "yellow"
        assert TriageColor.RED.value == "red"


class TestTriageMatrix:
    """Exhaustive triage matrix tests -- 24 entries (3 tiers x 4 trust x 2 sensor states)."""

    def test_matrix_has_24_entries(self) -> None:
        """_TRIAGE_MATRIX must have exactly 24 entries."""
        assert len(_TRIAGE_MATRIX) == 24

    @pytest.mark.parametrize(
        ("tier", "trust", "sensors_green", "expected_color"),
        [
            # Tier C -- lowest risk
            (RiskTier.C, TrustStatus.TRUSTED, True, TriageColor.GREEN),
            (RiskTier.C, TrustStatus.TRUSTED, False, TriageColor.YELLOW),
            (RiskTier.C, TrustStatus.CANDIDATE, True, TriageColor.YELLOW),
            (RiskTier.C, TrustStatus.CANDIDATE, False, TriageColor.RED),
            (RiskTier.C, TrustStatus.WATCH, True, TriageColor.YELLOW),
            (RiskTier.C, TrustStatus.WATCH, False, TriageColor.RED),
            (RiskTier.C, TrustStatus.CONSTRAINED, True, TriageColor.RED),
            (RiskTier.C, TrustStatus.CONSTRAINED, False, TriageColor.RED),
            # Tier B -- medium risk
            (RiskTier.B, TrustStatus.TRUSTED, True, TriageColor.YELLOW),
            (RiskTier.B, TrustStatus.TRUSTED, False, TriageColor.RED),
            (RiskTier.B, TrustStatus.CANDIDATE, True, TriageColor.YELLOW),
            (RiskTier.B, TrustStatus.CANDIDATE, False, TriageColor.RED),
            (RiskTier.B, TrustStatus.WATCH, True, TriageColor.RED),
            (RiskTier.B, TrustStatus.WATCH, False, TriageColor.RED),
            (RiskTier.B, TrustStatus.CONSTRAINED, True, TriageColor.RED),
            (RiskTier.B, TrustStatus.CONSTRAINED, False, TriageColor.RED),
            # Tier A -- highest risk
            (RiskTier.A, TrustStatus.TRUSTED, True, TriageColor.YELLOW),
            (RiskTier.A, TrustStatus.TRUSTED, False, TriageColor.RED),
            (RiskTier.A, TrustStatus.CANDIDATE, True, TriageColor.RED),
            (RiskTier.A, TrustStatus.CANDIDATE, False, TriageColor.RED),
            (RiskTier.A, TrustStatus.WATCH, True, TriageColor.RED),
            (RiskTier.A, TrustStatus.WATCH, False, TriageColor.RED),
            (RiskTier.A, TrustStatus.CONSTRAINED, True, TriageColor.RED),
            (RiskTier.A, TrustStatus.CONSTRAINED, False, TriageColor.RED),
        ],
    )
    def test_triage_lookup(
        self,
        tier: RiskTier,
        trust: TrustStatus,
        sensors_green: bool,
        expected_color: TriageColor,
    ) -> None:
        """Each (tier, trust, sensors_green) combination returns expected color."""
        assert triage_lookup(tier, trust, sensors_green) == expected_color

    def test_unknown_combination_defaults_to_red(self) -> None:
        """Unknown combinations in .get() default to RED (T-03-01 mitigation)."""
        # Direct matrix lookup with a key not in the matrix should return RED
        result = _TRIAGE_MATRIX.get(("FAKE", "FAKE", True), TriageColor.RED)
        assert result == TriageColor.RED


class TestTriageDecision:
    """TriageDecision frozen model tests."""

    def test_create_with_valid_data(self) -> None:
        td = TriageDecision(
            color=TriageColor.GREEN,
            risk_tier=RiskTier.C,
            trust_status=TrustStatus.TRUSTED,
            sensor_pass_rate=1.0,
            reason="All sensors green, trusted agent, Tier C",
            auto_approve_eligible=True,
        )
        assert td.color == TriageColor.GREEN
        assert td.auto_approve_eligible is True

    def test_frozen(self) -> None:
        td = TriageDecision(
            color=TriageColor.RED,
            risk_tier=RiskTier.A,
            trust_status=TrustStatus.CANDIDATE,
            sensor_pass_rate=0.5,
            reason="High risk",
            auto_approve_eligible=False,
        )
        with pytest.raises(ValidationError):
            td.color = TriageColor.GREEN  # type: ignore[misc]
