"""Unit tests for GateEvaluator, GateEvaluationResult, GATE_TYPE_MATRIX, and _trust_category.

Tests cover:
- GateEvaluationResult frozen dataclass behavior and fields
- GATE_TYPE_MATRIX contains 40 entries (10 phases x 4 trust categories)
- Specific matrix entries match PRD SS16.7.2
- _trust_category helper maps (tier, BC, trust_status) to category strings
- GateEvaluator.evaluate with confidence elevation (SS16.7.6)
- Meta-review sampling at configurable rates (GATE-04)
- Hidden gate checks at 5% injection rate (GATE-05)
- Gate evidence production (GATE-03)
- CLASS-06: oracle confidence directly affects gate type

All tests run in-memory (no database).
"""

from __future__ import annotations

import random

import pytest

from ces.shared.enums import (
    BehaviorConfidence,
    GateDecision,
    GateType,
    RiskTier,
    TrustStatus,
)

# ---------------------------------------------------------------------------
# Task 1: GateEvaluationResult model, GATE_TYPE_MATRIX, _trust_category
# ---------------------------------------------------------------------------


class TestGateEvaluationResult:
    """Tests for GateEvaluationResult frozen dataclass."""

    def test_gate_evaluation_result_is_frozen_dataclass(self):
        """GateEvaluationResult must be a frozen dataclass."""
        from ces.control.models.gate_result import GateEvaluationResult

        result = GateEvaluationResult(
            gate_type=GateType.HYBRID,
            base_gate_type=GateType.HYBRID,
            confidence_used=0.95,
            phase=1,
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            trust_status=TrustStatus.TRUSTED,
            meta_review_selected=False,
            hidden_check=False,
        )
        with pytest.raises(AttributeError):
            result.gate_type = GateType.AGENT  # type: ignore[misc]

    def test_gate_evaluation_result_fields(self):
        """GateEvaluationResult has all required fields."""
        from ces.control.models.gate_result import GateEvaluationResult

        result = GateEvaluationResult(
            gate_type=GateType.AGENT,
            base_gate_type=GateType.AGENT,
            confidence_used=0.92,
            phase=2,
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            trust_status=TrustStatus.TRUSTED,
            meta_review_selected=True,
            hidden_check=False,
        )
        assert result.gate_type == GateType.AGENT
        assert result.base_gate_type == GateType.AGENT
        assert result.confidence_used == 0.92
        assert result.phase == 2
        assert result.risk_tier == RiskTier.C
        assert result.behavior_confidence == BehaviorConfidence.BC1
        assert result.trust_status == TrustStatus.TRUSTED
        assert result.meta_review_selected is True
        assert result.hidden_check is False

    def test_gate_evaluation_result_importable_from_models(self):
        """GateEvaluationResult is re-exported from ces.control.models."""
        from ces.control.models import GateEvaluationResult

        assert GateEvaluationResult is not None


class TestGateTypeMatrix:
    """Tests for GATE_TYPE_MATRIX data structure."""

    def test_matrix_has_40_entries(self):
        """GATE_TYPE_MATRIX must have 10 phases x 4 categories = 40 entries."""
        from ces.control.models.gate_result import GATE_TYPE_MATRIX

        assert len(GATE_TYPE_MATRIX) == 40

    def test_matrix_covers_all_phases(self):
        """GATE_TYPE_MATRIX must cover phases 1 through 10."""
        from ces.control.models.gate_result import GATE_TYPE_MATRIX

        phases = {key[0] for key in GATE_TYPE_MATRIX}
        assert phases == set(range(1, 11))

    def test_matrix_covers_all_categories(self):
        """GATE_TYPE_MATRIX must cover all 4 trust categories for each phase."""
        from ces.control.models.gate_result import GATE_TYPE_MATRIX

        expected_categories = {
            "tier_c_bc1_trusted",
            "tier_b_bc1_trusted_mc",
            "tier_a_or_bc2_plus",
            "non_trusted",
        }
        for phase in range(1, 11):
            categories = {key[1] for key in GATE_TYPE_MATRIX if key[0] == phase}
            assert categories == expected_categories, f"Phase {phase} missing categories"

    def test_matrix_values_are_gate_types(self):
        """All GATE_TYPE_MATRIX values must be GateType enum members."""
        from ces.control.models.gate_result import GATE_TYPE_MATRIX

        for key, value in GATE_TYPE_MATRIX.items():
            assert isinstance(value, GateType), f"Matrix[{key}] is {type(value)}, not GateType"

    # PRD SS16.7.2 specific entries
    def test_phase_1_tier_c_bc1_trusted_is_hybrid(self):
        """Phase 1, Tier C/BC1 Trusted -> HYBRID (PRD SS16.7.2)."""
        from ces.control.models.gate_result import GATE_TYPE_MATRIX

        assert GATE_TYPE_MATRIX[(1, "tier_c_bc1_trusted")] == GateType.HYBRID

    def test_phase_2_tier_c_bc1_trusted_is_agent(self):
        """Phase 2, Tier C/BC1 Trusted -> AGENT (PRD SS16.7.2)."""
        from ces.control.models.gate_result import GATE_TYPE_MATRIX

        assert GATE_TYPE_MATRIX[(2, "tier_c_bc1_trusted")] == GateType.AGENT

    def test_phase_1_non_trusted_is_human(self):
        """Phase 1, non-trusted -> HUMAN (PRD SS16.7.2)."""
        from ces.control.models.gate_result import GATE_TYPE_MATRIX

        assert GATE_TYPE_MATRIX[(1, "non_trusted")] == GateType.HUMAN

    def test_phase_5_tier_b_bc1_trusted_is_agent(self):
        """Phase 5, Tier B/BC1 Trusted -> AGENT (PRD SS16.7.2)."""
        from ces.control.models.gate_result import GATE_TYPE_MATRIX

        assert GATE_TYPE_MATRIX[(5, "tier_b_bc1_trusted_mc")] == GateType.AGENT

    def test_phase_7_tier_c_bc1_trusted_is_agent(self):
        """Phase 7 (Execution), Tier C/BC1 Trusted -> AGENT (PRD SS16.7.2)."""
        from ces.control.models.gate_result import GATE_TYPE_MATRIX

        assert GATE_TYPE_MATRIX[(7, "tier_c_bc1_trusted")] == GateType.AGENT

    def test_phase_7_tier_b_bc1_trusted_is_agent(self):
        """Phase 7 (Execution), Tier B/BC1 Trusted -> AGENT (PRD SS16.7.2)."""
        from ces.control.models.gate_result import GATE_TYPE_MATRIX

        assert GATE_TYPE_MATRIX[(7, "tier_b_bc1_trusted_mc")] == GateType.AGENT

    def test_phase_10_tier_c_bc1_trusted_is_agent(self):
        """Phase 10, Tier C/BC1 Trusted -> AGENT (PRD SS16.7.2)."""
        from ces.control.models.gate_result import GATE_TYPE_MATRIX

        assert GATE_TYPE_MATRIX[(10, "tier_c_bc1_trusted")] == GateType.AGENT

    def test_phase_10_tier_b_bc1_trusted_is_hybrid(self):
        """Phase 10, Tier B/BC1 Trusted -> HYBRID (PRD SS16.7.2)."""
        from ces.control.models.gate_result import GATE_TYPE_MATRIX

        assert GATE_TYPE_MATRIX[(10, "tier_b_bc1_trusted_mc")] == GateType.HYBRID

    def test_all_non_trusted_entries_are_human(self):
        """All non-trusted entries should be HUMAN (PRD SS16.7.2)."""
        from ces.control.models.gate_result import GATE_TYPE_MATRIX

        for phase in range(1, 11):
            assert GATE_TYPE_MATRIX[(phase, "non_trusted")] == GateType.HUMAN, (
                f"Phase {phase} non_trusted should be HUMAN"
            )

    def test_all_tier_a_or_bc2_plus_entries_are_human(self):
        """All Tier A/BC2+/BC3 entries should be HUMAN (PRD SS16.7.2)."""
        from ces.control.models.gate_result import GATE_TYPE_MATRIX

        for phase in range(1, 11):
            assert GATE_TYPE_MATRIX[(phase, "tier_a_or_bc2_plus")] == GateType.HUMAN, (
                f"Phase {phase} tier_a_or_bc2_plus should be HUMAN"
            )


class TestTrustCategory:
    """Tests for _trust_category helper function."""

    def test_candidate_returns_non_trusted(self):
        """CANDIDATE status -> non_trusted."""
        from ces.control.models.gate_result import _trust_category

        result = _trust_category(RiskTier.C, BehaviorConfidence.BC1, TrustStatus.CANDIDATE)
        assert result == "non_trusted"

    def test_watch_returns_non_trusted(self):
        """WATCH status -> non_trusted."""
        from ces.control.models.gate_result import _trust_category

        result = _trust_category(RiskTier.C, BehaviorConfidence.BC1, TrustStatus.WATCH)
        assert result == "non_trusted"

    def test_constrained_returns_non_trusted(self):
        """CONSTRAINED status -> non_trusted."""
        from ces.control.models.gate_result import _trust_category

        result = _trust_category(RiskTier.C, BehaviorConfidence.BC1, TrustStatus.CONSTRAINED)
        assert result == "non_trusted"

    def test_trusted_tier_a_returns_tier_a_or_bc2_plus(self):
        """TRUSTED + Tier A -> tier_a_or_bc2_plus."""
        from ces.control.models.gate_result import _trust_category

        result = _trust_category(RiskTier.A, BehaviorConfidence.BC1, TrustStatus.TRUSTED)
        assert result == "tier_a_or_bc2_plus"

    def test_trusted_bc2_returns_tier_a_or_bc2_plus(self):
        """TRUSTED + BC2 -> tier_a_or_bc2_plus (regardless of tier)."""
        from ces.control.models.gate_result import _trust_category

        result = _trust_category(RiskTier.C, BehaviorConfidence.BC2, TrustStatus.TRUSTED)
        assert result == "tier_a_or_bc2_plus"

    def test_trusted_bc3_returns_tier_a_or_bc2_plus(self):
        """TRUSTED + BC3 -> tier_a_or_bc2_plus."""
        from ces.control.models.gate_result import _trust_category

        result = _trust_category(RiskTier.B, BehaviorConfidence.BC3, TrustStatus.TRUSTED)
        assert result == "tier_a_or_bc2_plus"

    def test_trusted_tier_c_bc1_returns_tier_c_bc1_trusted(self):
        """TRUSTED + Tier C + BC1 -> tier_c_bc1_trusted."""
        from ces.control.models.gate_result import _trust_category

        result = _trust_category(RiskTier.C, BehaviorConfidence.BC1, TrustStatus.TRUSTED)
        assert result == "tier_c_bc1_trusted"

    def test_trusted_tier_b_bc1_returns_tier_b_bc1_trusted_mc(self):
        """TRUSTED + Tier B + BC1 -> tier_b_bc1_trusted_mc."""
        from ces.control.models.gate_result import _trust_category

        result = _trust_category(RiskTier.B, BehaviorConfidence.BC1, TrustStatus.TRUSTED)
        assert result == "tier_b_bc1_trusted_mc"


# ---------------------------------------------------------------------------
# Task 2: GateEvaluator service tests (stubs for now)
# ---------------------------------------------------------------------------


class TestGateEvaluatorEvaluate:
    """Tests for GateEvaluator.evaluate method."""

    def test_evaluate_returns_gate_evaluation_result(self):
        """evaluate() returns a GateEvaluationResult."""
        from ces.control.services.gate_evaluator import GateEvaluator

        evaluator = GateEvaluator()
        result = evaluator.evaluate(
            phase=2,
            risk_tier=RiskTier.C,
            bc=BehaviorConfidence.BC1,
            trust_status=TrustStatus.TRUSTED,
            oracle_confidence=0.95,
        )
        from ces.control.models.gate_result import GateEvaluationResult

        assert isinstance(result, GateEvaluationResult)

    def test_phase_2_tier_c_bc1_trusted_high_confidence_agent(self):
        """Phase 2, Tier C, BC1, TRUSTED, confidence 0.95 -> AGENT (no elevation)."""
        from ces.control.services.gate_evaluator import GateEvaluator

        evaluator = GateEvaluator()
        result = evaluator.evaluate(
            phase=2,
            risk_tier=RiskTier.C,
            bc=BehaviorConfidence.BC1,
            trust_status=TrustStatus.TRUSTED,
            oracle_confidence=0.95,
        )
        assert result.gate_type == GateType.AGENT
        assert result.base_gate_type == GateType.AGENT

    def test_phase_1_tier_c_bc1_trusted_high_confidence_hybrid(self):
        """Phase 1, Tier C, BC1, TRUSTED, confidence 0.95 -> HYBRID (matrix says HYBRID)."""
        from ces.control.services.gate_evaluator import GateEvaluator

        evaluator = GateEvaluator()
        result = evaluator.evaluate(
            phase=1,
            risk_tier=RiskTier.C,
            bc=BehaviorConfidence.BC1,
            trust_status=TrustStatus.TRUSTED,
            oracle_confidence=0.95,
        )
        assert result.gate_type == GateType.HYBRID
        assert result.base_gate_type == GateType.HYBRID

    def test_confidence_elevation_agent_to_hybrid(self):
        """Phase 2, Tier C, BC1, TRUSTED, confidence 0.75 -> HYBRID (elevation: AGENT -> HYBRID)."""
        from ces.control.services.gate_evaluator import GateEvaluator

        evaluator = GateEvaluator()
        result = evaluator.evaluate(
            phase=2,
            risk_tier=RiskTier.C,
            bc=BehaviorConfidence.BC1,
            trust_status=TrustStatus.TRUSTED,
            oracle_confidence=0.75,
        )
        assert result.gate_type == GateType.HYBRID
        assert result.base_gate_type == GateType.AGENT

    def test_low_confidence_forces_human(self):
        """Phase 2, Tier C, BC1, TRUSTED, confidence 0.60 -> HUMAN (low confidence)."""
        from ces.control.services.gate_evaluator import GateEvaluator

        evaluator = GateEvaluator()
        result = evaluator.evaluate(
            phase=2,
            risk_tier=RiskTier.C,
            bc=BehaviorConfidence.BC1,
            trust_status=TrustStatus.TRUSTED,
            oracle_confidence=0.60,
        )
        assert result.gate_type == GateType.HUMAN
        assert result.base_gate_type == GateType.AGENT

    def test_tier_a_trusted_phase_1_is_human(self):
        """Any Tier A or BC2+, TRUSTED -> at least HUMAN in phase 1."""
        from ces.control.services.gate_evaluator import GateEvaluator

        evaluator = GateEvaluator()
        result = evaluator.evaluate(
            phase=1,
            risk_tier=RiskTier.A,
            bc=BehaviorConfidence.BC1,
            trust_status=TrustStatus.TRUSTED,
            oracle_confidence=0.95,
        )
        assert result.gate_type == GateType.HUMAN

    def test_non_trusted_phases_1_3_is_human(self):
        """Any non-trusted status -> HUMAN in phases 1-3."""
        from ces.control.services.gate_evaluator import GateEvaluator

        evaluator = GateEvaluator()
        for phase in [1, 2, 3]:
            result = evaluator.evaluate(
                phase=phase,
                risk_tier=RiskTier.C,
                bc=BehaviorConfidence.BC1,
                trust_status=TrustStatus.CANDIDATE,
                oracle_confidence=0.95,
            )
            assert result.gate_type == GateType.HUMAN, f"Phase {phase} non-trusted should be HUMAN"

    def test_class06_oracle_confidence_affects_gate(self):
        """CLASS-06: oracle confidence directly affects gate type selection."""
        from ces.control.services.gate_evaluator import GateEvaluator

        evaluator = GateEvaluator()
        # Same inputs, different confidence -> different gate
        high = evaluator.evaluate(
            phase=2,
            risk_tier=RiskTier.C,
            bc=BehaviorConfidence.BC1,
            trust_status=TrustStatus.TRUSTED,
            oracle_confidence=0.95,
        )
        medium = evaluator.evaluate(
            phase=2,
            risk_tier=RiskTier.C,
            bc=BehaviorConfidence.BC1,
            trust_status=TrustStatus.TRUSTED,
            oracle_confidence=0.75,
        )
        low = evaluator.evaluate(
            phase=2,
            risk_tier=RiskTier.C,
            bc=BehaviorConfidence.BC1,
            trust_status=TrustStatus.TRUSTED,
            oracle_confidence=0.60,
        )
        assert high.gate_type == GateType.AGENT
        assert medium.gate_type == GateType.HYBRID
        assert low.gate_type == GateType.HUMAN

    def test_human_gate_never_downgraded(self):
        """HUMAN gate is never downgraded by any mechanism."""
        from ces.control.services.gate_evaluator import GateEvaluator

        evaluator = GateEvaluator()
        # Phase 1, Tier A -> base is HUMAN
        result = evaluator.evaluate(
            phase=1,
            risk_tier=RiskTier.A,
            bc=BehaviorConfidence.BC1,
            trust_status=TrustStatus.TRUSTED,
            oracle_confidence=0.99,  # Very high confidence should NOT downgrade HUMAN
        )
        assert result.gate_type == GateType.HUMAN
        assert result.base_gate_type == GateType.HUMAN

    def test_confidence_used_field_populated(self):
        """GateEvaluationResult.confidence_used contains the oracle confidence used."""
        from ces.control.services.gate_evaluator import GateEvaluator

        evaluator = GateEvaluator()
        result = evaluator.evaluate(
            phase=2,
            risk_tier=RiskTier.C,
            bc=BehaviorConfidence.BC1,
            trust_status=TrustStatus.TRUSTED,
            oracle_confidence=0.87,
        )
        assert result.confidence_used == 0.87

    def test_mid_confidence_elevates_hybrid_to_human(self):
        """Mid-confidence band (0.70 <= c < 0.90) elevates HYBRID -> HUMAN (T-02-06)."""
        from ces.control.services.gate_evaluator import GateEvaluator

        evaluator = GateEvaluator()
        # Phase 1, Tier C, BC1, TRUSTED -> base is HYBRID (PRD SS16.7.2)
        result = evaluator.evaluate(
            phase=1,
            risk_tier=RiskTier.C,
            bc=BehaviorConfidence.BC1,
            trust_status=TrustStatus.TRUSTED,
            oracle_confidence=0.75,
        )
        assert result.base_gate_type == GateType.HYBRID
        assert result.gate_type == GateType.HUMAN

    def test_mid_confidence_keeps_human_human(self):
        """Mid-confidence band (0.70 <= c < 0.90) leaves HUMAN base unchanged (T-02-06)."""
        from ces.control.services.gate_evaluator import GateEvaluator

        evaluator = GateEvaluator()
        # Phase 1, non-trusted -> base is HUMAN (PRD SS16.7.2)
        result = evaluator.evaluate(
            phase=1,
            risk_tier=RiskTier.C,
            bc=BehaviorConfidence.BC1,
            trust_status=TrustStatus.CANDIDATE,
            oracle_confidence=0.75,
        )
        assert result.base_gate_type == GateType.HUMAN
        assert result.gate_type == GateType.HUMAN


class TestGateEvaluatorMetaReview:
    """Tests for GateEvaluator.should_meta_review (GATE-04)."""

    def test_meta_review_tier_c_rate(self):
        """Tier C meta-review rate is ~10% (GATE-04)."""
        from ces.control.services.gate_evaluator import GateEvaluator

        evaluator = GateEvaluator()
        # Pre-set count past threshold so normal sampling rates apply
        evaluator._profile_evaluation_counts["profile-established"] = 100
        random.seed(42)
        results = [evaluator.should_meta_review(RiskTier.C, "profile-established") for _ in range(1000)]
        rate = sum(results) / len(results)
        assert 0.05 <= rate <= 0.15, f"Tier C meta-review rate {rate} not ~10%"

    def test_meta_review_tier_b_rate(self):
        """Tier B meta-review rate is ~50% (GATE-04)."""
        from ces.control.services.gate_evaluator import GateEvaluator

        evaluator = GateEvaluator()
        # Pre-set count past threshold so normal sampling rates apply
        evaluator._profile_evaluation_counts["profile-established"] = 100
        random.seed(42)
        results = [evaluator.should_meta_review(RiskTier.B, "profile-established") for _ in range(1000)]
        rate = sum(results) / len(results)
        assert 0.40 <= rate <= 0.60, f"Tier B meta-review rate {rate} not ~50%"

    def test_meta_review_tier_a_always(self):
        """Tier A meta-review rate is 100% (GATE-04)."""
        from ces.control.services.gate_evaluator import GateEvaluator

        evaluator = GateEvaluator()
        # Pre-set count past threshold; Tier A should still be 100%
        evaluator._profile_evaluation_counts["profile-established"] = 100
        random.seed(42)
        results = [evaluator.should_meta_review(RiskTier.A, "profile-established") for _ in range(1000)]
        assert all(results), "Tier A should always have meta-review"

    def test_meta_review_first_50_always_selected(self):
        """First 50 evaluations per profile are always meta-reviewed (GATE-04)."""
        from ces.control.services.gate_evaluator import GateEvaluator

        evaluator = GateEvaluator()
        # For a new profile, first 50 evaluations should always be selected
        results = [evaluator.should_meta_review(RiskTier.C, "new-profile") for _ in range(50)]
        assert all(results), "First 50 per profile should always have meta-review"


class TestGateEvaluatorHiddenChecks:
    """Tests for GateEvaluator.is_hidden_gate_check (GATE-05)."""

    def test_hidden_check_rate_approximately_5_percent(self):
        """Hidden gate checks at ~5% injection rate (GATE-05)."""
        from ces.control.services.gate_evaluator import GateEvaluator

        evaluator = GateEvaluator()
        random.seed(42)
        results = [evaluator.is_hidden_gate_check() for _ in range(10000)]
        rate = sum(results) / len(results)
        assert 0.03 <= rate <= 0.07, f"Hidden check rate {rate} not ~5%"


class TestGateEvaluatorEvidence:
    """Tests for GateEvaluator.produce_gate_evidence (GATE-03)."""

    def test_produce_gate_evidence_returns_dict(self):
        """produce_gate_evidence returns a dict with required fields."""
        from ces.control.models.gate_result import GateEvaluationResult
        from ces.control.services.gate_evaluator import GateEvaluator

        evaluator = GateEvaluator()
        result = GateEvaluationResult(
            gate_type=GateType.HYBRID,
            base_gate_type=GateType.HYBRID,
            confidence_used=0.95,
            phase=1,
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            trust_status=TrustStatus.TRUSTED,
            meta_review_selected=False,
            hidden_check=False,
        )
        evidence = evaluator.produce_gate_evidence(result, {"check": "passed"})
        assert isinstance(evidence, dict)
        assert "gate_type" in evidence
        assert "base_gate_type" in evidence
        assert "confidence" in evidence
        assert "phase" in evidence
        assert "risk_tier" in evidence
        assert "trust_status" in evidence
        assert "meta_review" in evidence
        assert "hidden_check" in evidence
        assert "evaluation_details" in evidence
        assert evidence["gate_type"] == "hybrid"
        assert evidence["evaluation_details"] == {"check": "passed"}
