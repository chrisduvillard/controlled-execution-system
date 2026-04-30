"""Tests for the deterministic classification engine (PRD SS8.4).

Validates:
- CLASSIFICATION_TABLE has exactly 38 entries (30 PRD SS8.4 + 8 bootstrap)
- classify_by_description returns correct classification for known descriptions
- classify_by_description returns None for unknown descriptions
- classify_by_rule_index returns correct rule by index
- aggregate classification returns max risk per CLASS-02
- No LLM imports (LLM-05)
"""

from __future__ import annotations

import ast
import inspect

import pytest

from ces.control.services.classification import (
    CLASSIFICATION_TABLE,
    ClassificationEngine,
    ClassificationRule,
)
from ces.shared.enums import BehaviorConfidence, ChangeClass, RiskTier

# ---------------------------------------------------------------------------
# Table structure tests
# ---------------------------------------------------------------------------


class TestClassificationTable:
    """Tests for the CLASSIFICATION_TABLE constant."""

    def test_table_has_exactly_38_entries(self) -> None:
        assert len(CLASSIFICATION_TABLE) == 38

    def test_all_entries_are_classification_rules(self) -> None:
        for rule in CLASSIFICATION_TABLE:
            assert isinstance(rule, ClassificationRule)

    def test_each_entry_has_required_fields(self) -> None:
        for i, rule in enumerate(CLASSIFICATION_TABLE):
            assert isinstance(rule.description, str), f"Rule {i}: description must be str"
            assert isinstance(rule.risk_tier, RiskTier), f"Rule {i}: risk_tier must be RiskTier"
            assert isinstance(rule.behavior_confidence, BehaviorConfidence), (
                f"Rule {i}: behavior_confidence must be BehaviorConfidence"
            )
            assert isinstance(rule.change_class, ChangeClass), f"Rule {i}: change_class must be ChangeClass"

    def test_all_descriptions_are_unique(self) -> None:
        descriptions = [rule.description.lower() for rule in CLASSIFICATION_TABLE]
        assert len(descriptions) == len(set(descriptions)), "Duplicate descriptions found"

    def test_classification_rule_is_frozen(self) -> None:
        rule = CLASSIFICATION_TABLE[0]
        with pytest.raises(AttributeError):
            rule.description = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Specific table lookup tests (PRD SS8.4)
# ---------------------------------------------------------------------------


class TestClassifyByDescription:
    """Tests for ClassificationEngine.classify_by_description."""

    @pytest.fixture()
    def engine(self) -> ClassificationEngine:
        return ClassificationEngine()

    def test_add_new_internal_utility_function(self, engine: ClassificationEngine) -> None:
        result = engine.classify_by_description("Add a new internal utility function")
        assert result is not None
        assert result.risk_tier == RiskTier.C
        assert result.behavior_confidence == BehaviorConfidence.BC1
        assert result.change_class == ChangeClass.CLASS_1

    def test_fix_race_condition_in_payment_flow(self, engine: ClassificationEngine) -> None:
        result = engine.classify_by_description("Fix a race condition in payment flow")
        assert result is not None
        assert result.risk_tier == RiskTier.A
        assert result.behavior_confidence == BehaviorConfidence.BC2
        assert result.change_class == ChangeClass.CLASS_2

    def test_remove_database_table(self, engine: ClassificationEngine) -> None:
        result = engine.classify_by_description("Remove a database table")
        assert result is not None
        assert result.risk_tier == RiskTier.A
        assert result.behavior_confidence == BehaviorConfidence.BC3
        assert result.change_class == ChangeClass.CLASS_5

    def test_change_authentication_logic(self, engine: ClassificationEngine) -> None:
        result = engine.classify_by_description("Change authentication logic")
        assert result is not None
        assert result.risk_tier == RiskTier.A
        assert result.behavior_confidence == BehaviorConfidence.BC2
        assert result.change_class == ChangeClass.CLASS_2

    def test_fix_typo_in_ui_string(self, engine: ClassificationEngine) -> None:
        result = engine.classify_by_description("Fix a typo in a UI string")
        assert result is not None
        assert result.risk_tier == RiskTier.C
        assert result.behavior_confidence == BehaviorConfidence.BC1
        assert result.change_class == ChangeClass.CLASS_2

    def test_add_new_api_endpoint_external(self, engine: ClassificationEngine) -> None:
        result = engine.classify_by_description("Add a new API endpoint (external)")
        assert result is not None
        assert result.risk_tier == RiskTier.A
        assert result.behavior_confidence == BehaviorConfidence.BC1
        assert result.change_class == ChangeClass.CLASS_3

    def test_change_checkout_flow(self, engine: ClassificationEngine) -> None:
        result = engine.classify_by_description("Change checkout flow")
        assert result is not None
        assert result.risk_tier == RiskTier.A
        assert result.behavior_confidence == BehaviorConfidence.BC3
        assert result.change_class == ChangeClass.CLASS_2

    def test_delete_unused_code(self, engine: ClassificationEngine) -> None:
        result = engine.classify_by_description("Delete unused code")
        assert result is not None
        assert result.risk_tier == RiskTier.C
        assert result.behavior_confidence == BehaviorConfidence.BC1
        assert result.change_class == ChangeClass.CLASS_5

    def test_infrastructure_ci_config_change(self, engine: ClassificationEngine) -> None:
        result = engine.classify_by_description("Infrastructure / CI config change")
        assert result is not None
        assert result.risk_tier == RiskTier.B
        assert result.behavior_confidence == BehaviorConfidence.BC1
        assert result.change_class == ChangeClass.CLASS_2

    def test_case_insensitive_lookup(self, engine: ClassificationEngine) -> None:
        result = engine.classify_by_description("ADD A NEW INTERNAL UTILITY FUNCTION")
        assert result is not None
        assert result.risk_tier == RiskTier.C

    def test_unknown_description_returns_none(self, engine: ClassificationEngine) -> None:
        result = engine.classify_by_description("Do something completely unknown")
        assert result is None

    def test_empty_string_returns_none(self, engine: ClassificationEngine) -> None:
        result = engine.classify_by_description("")
        assert result is None


# ---------------------------------------------------------------------------
# Rule index lookup tests
# ---------------------------------------------------------------------------


class TestClassifyByRuleIndex:
    """Tests for ClassificationEngine.classify_by_rule_index."""

    @pytest.fixture()
    def engine(self) -> ClassificationEngine:
        return ClassificationEngine()

    def test_index_zero_returns_first_entry(self, engine: ClassificationEngine) -> None:
        result = engine.classify_by_rule_index(0)
        assert result == CLASSIFICATION_TABLE[0]

    def test_index_29_returns_last_base_entry(self, engine: ClassificationEngine) -> None:
        result = engine.classify_by_rule_index(29)
        assert result == CLASSIFICATION_TABLE[29]

    def test_index_37_returns_last_entry(self, engine: ClassificationEngine) -> None:
        result = engine.classify_by_rule_index(37)
        assert result == CLASSIFICATION_TABLE[37]

    def test_index_out_of_range_raises(self, engine: ClassificationEngine) -> None:
        with pytest.raises(IndexError):
            engine.classify_by_rule_index(38)


# ---------------------------------------------------------------------------
# Aggregate classification tests (CLASS-02)
# ---------------------------------------------------------------------------


class TestAggregateClassification:
    """Tests for ClassificationEngine.aggregate (CLASS-02)."""

    def test_aggregate_single_task(self) -> None:
        rule = ClassificationRule(
            description="test",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
        )
        result = ClassificationEngine.aggregate([rule])
        assert result.risk_tier == RiskTier.C
        assert result.behavior_confidence == BehaviorConfidence.BC1
        assert result.change_class == ChangeClass.CLASS_1

    def test_aggregate_mixed_tiers(self) -> None:
        rules = [
            ClassificationRule("low", RiskTier.C, BehaviorConfidence.BC1, ChangeClass.CLASS_1),
            ClassificationRule("high", RiskTier.A, BehaviorConfidence.BC2, ChangeClass.CLASS_3),
        ]
        result = ClassificationEngine.aggregate(rules)
        assert result.risk_tier == RiskTier.A
        assert result.behavior_confidence == BehaviorConfidence.BC2
        assert result.change_class == ChangeClass.CLASS_3

    def test_aggregate_all_same(self) -> None:
        rules = [
            ClassificationRule("a", RiskTier.B, BehaviorConfidence.BC2, ChangeClass.CLASS_2),
            ClassificationRule("b", RiskTier.B, BehaviorConfidence.BC2, ChangeClass.CLASS_2),
        ]
        result = ClassificationEngine.aggregate(rules)
        assert result.risk_tier == RiskTier.B
        assert result.behavior_confidence == BehaviorConfidence.BC2
        assert result.change_class == ChangeClass.CLASS_2

    def test_aggregate_empty_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Cannot aggregate empty classification list"):
            ClassificationEngine.aggregate([])

    def test_aggregate_description_is_aggregate(self) -> None:
        rules = [
            ClassificationRule("a", RiskTier.C, BehaviorConfidence.BC1, ChangeClass.CLASS_1),
        ]
        result = ClassificationEngine.aggregate(rules)
        assert result.description == "aggregate"

    def test_aggregate_three_tasks_max_from_each(self) -> None:
        """Aggregate with max risk_tier from one task, max BC from another, max class from third."""
        rules = [
            ClassificationRule("tier-a", RiskTier.A, BehaviorConfidence.BC1, ChangeClass.CLASS_1),
            ClassificationRule("bc3", RiskTier.C, BehaviorConfidence.BC3, ChangeClass.CLASS_2),
            ClassificationRule("class5", RiskTier.B, BehaviorConfidence.BC2, ChangeClass.CLASS_5),
        ]
        result = ClassificationEngine.aggregate(rules)
        assert result.risk_tier == RiskTier.A
        assert result.behavior_confidence == BehaviorConfidence.BC3
        assert result.change_class == ChangeClass.CLASS_5


# ---------------------------------------------------------------------------
# Custom table support
# ---------------------------------------------------------------------------


class TestCustomTable:
    """Tests for ClassificationEngine with custom table."""

    def test_engine_with_custom_table(self) -> None:
        custom_table = [
            ClassificationRule("custom task", RiskTier.B, BehaviorConfidence.BC2, ChangeClass.CLASS_3),
        ]
        engine = ClassificationEngine(table=custom_table)
        result = engine.classify_by_description("custom task")
        assert result is not None
        assert result.risk_tier == RiskTier.B

    def test_default_table_is_classification_table(self) -> None:
        engine = ClassificationEngine()
        assert engine.table is CLASSIFICATION_TABLE


# ---------------------------------------------------------------------------
# LLM-05: No LLM imports
# ---------------------------------------------------------------------------


class TestNoLLMImports:
    """Verify classification engine has NO LLM dependencies (LLM-05)."""

    def test_no_anthropic_import(self) -> None:
        source = inspect.getsource(ClassificationEngine)
        module_source = inspect.getfile(ClassificationEngine)
        with open(module_source) as f:
            full_source = f.read()
        tree = ast.parse(full_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "anthropic" not in alias.name, "LLM-05 violation: anthropic imported"
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert "anthropic" not in node.module, "LLM-05 violation: anthropic imported"

    def test_no_openai_import(self) -> None:
        module_source = inspect.getfile(ClassificationEngine)
        with open(module_source) as f:
            full_source = f.read()
        tree = ast.parse(full_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "openai" not in alias.name, "LLM-05 violation: openai imported"
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert "openai" not in node.module, "LLM-05 violation: openai imported"


# ---------------------------------------------------------------------------
# Bootstrap classification rules (rows 31-38)
# ---------------------------------------------------------------------------


class TestBootstrapClassificationRules:
    """Tests for governance-system self-classification rules (rows 31-38)."""

    def test_table_has_bootstrap_rules(self) -> None:
        """Table should have 38 total rows (30 original + 8 bootstrap)."""
        assert len(CLASSIFICATION_TABLE) == 38

    def test_classification_engine_change_is_tier_a_bc3(self) -> None:
        """Changes to classification engine are highest risk."""
        rule = CLASSIFICATION_TABLE[30]  # Row 31 (0-indexed)
        assert rule.risk_tier == RiskTier.A
        assert rule.behavior_confidence == BehaviorConfidence.BC3
        assert rule.change_class == ChangeClass.CLASS_4

    def test_audit_ledger_change_is_tier_a(self) -> None:
        rule = CLASSIFICATION_TABLE[31]  # Row 32
        assert rule.risk_tier == RiskTier.A
        assert rule.behavior_confidence == BehaviorConfidence.BC2

    def test_kill_switch_change_is_tier_a(self) -> None:
        rule = CLASSIFICATION_TABLE[32]  # Row 33
        assert rule.risk_tier == RiskTier.A

    def test_review_executor_change_is_tier_a_bc3(self) -> None:
        rule = CLASSIFICATION_TABLE[33]  # Row 34
        assert rule.risk_tier == RiskTier.A
        assert rule.behavior_confidence == BehaviorConfidence.BC3

    def test_sensor_framework_change_is_tier_b(self) -> None:
        """Sensors inform but don't gate -- lower risk than control plane."""
        rule = CLASSIFICATION_TABLE[37]  # Row 38
        assert rule.risk_tier == RiskTier.B
        assert rule.behavior_confidence == BehaviorConfidence.BC1

    def test_all_bootstrap_rules_are_frozen(self) -> None:
        """All bootstrap rules should be frozen dataclasses."""
        for rule in CLASSIFICATION_TABLE[30:]:
            with pytest.raises(AttributeError):
                rule.risk_tier = RiskTier.C  # type: ignore[misc]
