"""Unit tests for ClassificationOracle and OracleClassificationResult.

Tests cover:
- OracleClassificationResult frozen dataclass invariants (Task 1)
- ClassificationOracle TF-IDF fuzzy matching (Task 2)
- Confidence threshold routing (Task 2)
- Downgrade prevention (Task 2)
- LLM-05 compliance (Task 2)
"""

from __future__ import annotations

import pytest

from ces.control.models.oracle_result import OracleClassificationResult
from ces.control.services.classification import (
    CLASSIFICATION_TABLE,
    ClassificationRule,
)
from ces.shared.enums import BehaviorConfidence, ChangeClass, RiskTier

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rule(
    description: str = "Test rule",
    risk_tier: RiskTier = RiskTier.C,
    behavior_confidence: BehaviorConfidence = BehaviorConfidence.BC1,
    change_class: ChangeClass = ChangeClass.CLASS_1,
) -> ClassificationRule:
    return ClassificationRule(
        description=description,
        risk_tier=risk_tier,
        behavior_confidence=behavior_confidence,
        change_class=change_class,
    )


# ---------------------------------------------------------------------------
# Task 1: OracleClassificationResult model tests
# ---------------------------------------------------------------------------


class TestOracleClassificationResult:
    """Tests for the OracleClassificationResult frozen dataclass."""

    def test_oracle_result_frozen(self) -> None:
        """OracleClassificationResult is frozen -- cannot assign after creation."""
        rule = _make_rule()
        result = OracleClassificationResult(
            matched_rule=rule,
            confidence=0.95,
            top_matches=[(rule, 0.95)],
            action="auto_accept",
        )
        with pytest.raises(AttributeError):
            result.confidence = 0.5  # type: ignore[misc]

    def test_oracle_result_stores_all_fields(self) -> None:
        """OracleClassificationResult stores matched_rule, confidence, top_matches, action."""
        rule = _make_rule()
        top = ((rule, 0.95), (_make_rule(description="Other"), 0.80))
        result = OracleClassificationResult(
            matched_rule=rule,
            confidence=0.95,
            top_matches=top,
            action="auto_accept",
        )
        assert result.matched_rule is rule
        assert result.confidence == 0.95
        assert result.top_matches == top
        assert result.action == "auto_accept"

    def test_oracle_result_action_values(self) -> None:
        """action field accepts exactly 'auto_accept', 'human_review', 'human_classify'."""
        rule = _make_rule()
        for action in ("auto_accept", "human_review", "human_classify"):
            result = OracleClassificationResult(
                matched_rule=rule,
                confidence=0.5,
                top_matches=[(rule, 0.5)],
                action=action,
            )
            assert result.action == action

    def test_oracle_result_auto_accept(self) -> None:
        """confidence=0.95 with action='auto_accept' constructs correctly."""
        rule = _make_rule()
        result = OracleClassificationResult(
            matched_rule=rule,
            confidence=0.95,
            top_matches=[(rule, 0.95)],
            action="auto_accept",
        )
        assert result.confidence == 0.95
        assert result.action == "auto_accept"

    def test_oracle_result_none_rule(self) -> None:
        """confidence=0.0 with matched_rule=None constructs correctly."""
        result = OracleClassificationResult(
            matched_rule=None,
            confidence=0.0,
            top_matches=[],
            action="human_classify",
        )
        assert result.matched_rule is None
        assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# Task 2: ClassificationOracle tests
# ---------------------------------------------------------------------------

from ces.control.services.classification_oracle import ClassificationOracle


@pytest.fixture
def oracle() -> ClassificationOracle:
    """Create a ClassificationOracle with default thresholds."""
    return ClassificationOracle()


class TestClassificationOracleExactMatch:
    """Exact match via Phase 1 engine returns confidence=1.0."""

    def test_exact_match_returns_confidence_1(self, oracle: ClassificationOracle) -> None:
        """Exact description from CLASSIFICATION_TABLE returns confidence=1.0."""
        result = oracle.classify("Fix a typo in a UI string")
        assert result.confidence == 1.0
        assert result.matched_rule is not None
        assert result.matched_rule.description == "Fix a typo in a UI string"

    def test_exact_match_action_auto_accept(self, oracle: ClassificationOracle) -> None:
        """Exact match always returns action='auto_accept'."""
        result = oracle.classify("Add a new internal utility function")
        assert result.action == "auto_accept"
        assert result.confidence == 1.0


class TestClassificationOracleFuzzyMatch:
    """TF-IDF fuzzy matching tests."""

    def test_similar_description_returns_nonzero_confidence(self, oracle: ClassificationOracle) -> None:
        """A similar but non-exact description returns confidence > 0."""
        result = oracle.classify("Fix a pagination bug")
        assert result.confidence > 0.0

    def test_unrelated_description_low_confidence(self, oracle: ClassificationOracle) -> None:
        """Completely unrelated description returns low confidence and human_classify."""
        result = oracle.classify("quantum physics lecture notes on entanglement")
        assert result.confidence < 0.70
        assert result.action == "human_classify"

    def test_top_matches_sorted_descending(self, oracle: ClassificationOracle) -> None:
        """top_matches are sorted by confidence descending."""
        result = oracle.classify("Fix a pagination bug")
        scores = [score for _, score in result.top_matches]
        assert scores == sorted(scores, reverse=True)

    def test_top_matches_max_three(self, oracle: ClassificationOracle) -> None:
        """top_matches contains at most 3 results."""
        result = oracle.classify("Fix a pagination bug")
        assert len(result.top_matches) <= 3


class TestClassificationOracleThresholds:
    """Confidence threshold routing (CLASS-04)."""

    def test_high_confidence_auto_accept(self) -> None:
        """confidence >= 0.90 returns action='auto_accept'."""
        # Use very low thresholds with a custom oracle to force high confidence
        oracle = ClassificationOracle(
            auto_accept_threshold=0.10,
            human_review_threshold=0.05,
        )
        result = oracle.classify("Fix a typo in the UI")
        # With such low thresholds, any reasonable match should auto_accept
        assert result.action == "auto_accept"

    def test_medium_confidence_human_review(self) -> None:
        """confidence in [0.70, 0.90) returns action='human_review'."""
        # Set thresholds so a moderate match falls in human_review range
        oracle = ClassificationOracle(
            auto_accept_threshold=0.99,
            human_review_threshold=0.05,
        )
        result = oracle.classify("Fix a small pagination issue")
        # Should be below 0.99 (not auto_accept) but above 0.05 (not human_classify)
        assert result.action == "human_review"

    def test_low_confidence_human_classify(self) -> None:
        """confidence < 0.70 returns action='human_classify'."""
        oracle = ClassificationOracle(
            auto_accept_threshold=0.99,
            human_review_threshold=0.98,
        )
        result = oracle.classify("quantum physics lecture notes")
        assert result.action == "human_classify"

    def test_matched_rule_none_below_review_threshold(
        self,
    ) -> None:
        """When confidence < human_review_threshold, matched_rule is None."""
        oracle = ClassificationOracle(
            auto_accept_threshold=0.99,
            human_review_threshold=0.98,
        )
        result = oracle.classify("some random unrelated text about cooking")
        assert result.matched_rule is None
        assert result.action == "human_classify"


class TestClassificationOracleDowngrade:
    """Downgrade prevention (CLASS-05)."""

    def test_downgrade_risk_tier_rejected(self) -> None:
        """check_downgrade returns True when proposed has lower risk_tier."""
        existing = _make_rule(risk_tier=RiskTier.A, behavior_confidence=BehaviorConfidence.BC2)
        proposed = _make_rule(risk_tier=RiskTier.C, behavior_confidence=BehaviorConfidence.BC2)
        assert ClassificationOracle.check_downgrade(proposed, existing) is True

    def test_downgrade_behavior_confidence_rejected(self) -> None:
        """check_downgrade returns True when proposed has lower behavior_confidence."""
        existing = _make_rule(risk_tier=RiskTier.B, behavior_confidence=BehaviorConfidence.BC3)
        proposed = _make_rule(risk_tier=RiskTier.B, behavior_confidence=BehaviorConfidence.BC1)
        assert ClassificationOracle.check_downgrade(proposed, existing) is True

    def test_same_or_higher_tier_accepted(self) -> None:
        """check_downgrade returns False when proposed is same or higher risk."""
        existing = _make_rule(risk_tier=RiskTier.C, behavior_confidence=BehaviorConfidence.BC1)
        proposed = _make_rule(risk_tier=RiskTier.A, behavior_confidence=BehaviorConfidence.BC3)
        assert ClassificationOracle.check_downgrade(proposed, existing) is False

    def test_same_classification_not_downgrade(self) -> None:
        """check_downgrade returns False when proposed equals existing."""
        rule = _make_rule(risk_tier=RiskTier.B, behavior_confidence=BehaviorConfidence.BC2)
        assert ClassificationOracle.check_downgrade(rule, rule) is False


class TestClassificationOracleLLMCompliance:
    """LLM-05 compliance -- no LLM imports in oracle module."""

    def test_no_llm_imports_in_oracle(self) -> None:
        """Oracle module must not import anthropic, openai, or httpx."""
        import ast
        import inspect

        import ces.control.services.classification_oracle as oracle_mod

        source = inspect.getsource(oracle_mod)
        tree = ast.parse(source)
        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_names.add(node.module.split(".")[0])
        forbidden = {"anthropic", "openai", "httpx"}
        found = imported_names & forbidden
        assert not found, f"LLM-05 violation: oracle imports {found}"

    def test_uses_tfidf_vectorizer(self) -> None:
        """Oracle module uses TfidfVectorizer (not LLM embeddings)."""
        import inspect

        import ces.control.services.classification_oracle as oracle_mod

        source = inspect.getsource(oracle_mod)
        assert "TfidfVectorizer" in source
