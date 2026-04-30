"""Tests for Intake models (MODEL-13): IntakeQuestion, IntakeAnswer, IntakeAssumption."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ces.control.models.intake import IntakeAnswer, IntakeAssumption, IntakeQuestion
from ces.shared.enums import AssumptionCategory


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TestIntakeQuestion:
    """Tests for IntakeQuestion model."""

    def test_create_question(self) -> None:
        q = IntakeQuestion(
            question_id="IQ-001",
            phase=1,
            stage="mandatory",
            text="What is the primary user story?",
            category=AssumptionCategory.BLOCK,
        )
        assert q.question_id == "IQ-001"
        assert q.phase == 1
        assert q.stage == "mandatory"
        assert q.text == "What is the primary user story?"
        assert q.category == AssumptionCategory.BLOCK

    def test_stage_mandatory(self) -> None:
        q = IntakeQuestion(
            question_id="IQ-001",
            phase=1,
            stage="mandatory",
            text="Test",
            category=AssumptionCategory.BLOCK,
        )
        assert q.stage == "mandatory"

    def test_stage_conditional(self) -> None:
        q = IntakeQuestion(
            question_id="IQ-002",
            phase=2,
            stage="conditional",
            text="Test",
            category=AssumptionCategory.FLAG,
        )
        assert q.stage == "conditional"

    def test_stage_completeness(self) -> None:
        q = IntakeQuestion(
            question_id="IQ-003",
            phase=3,
            stage="completeness",
            text="Test",
            category=AssumptionCategory.PROCEED,
        )
        assert q.stage == "completeness"

    def test_invalid_stage_rejected(self) -> None:
        with pytest.raises(ValidationError):
            IntakeQuestion(
                question_id="IQ-001",
                phase=1,
                stage="invalid",
                text="Test",
                category=AssumptionCategory.BLOCK,
            )

    def test_is_material_default_false(self) -> None:
        q = IntakeQuestion(
            question_id="IQ-001",
            phase=1,
            stage="mandatory",
            text="Test",
            category=AssumptionCategory.BLOCK,
        )
        assert q.is_material is False

    def test_is_frozen(self) -> None:
        q = IntakeQuestion(
            question_id="IQ-001",
            phase=1,
            stage="mandatory",
            text="Test",
            category=AssumptionCategory.BLOCK,
        )
        with pytest.raises(ValidationError):
            q.text = "Changed"  # type: ignore[misc]


class TestIntakeAnswer:
    """Tests for IntakeAnswer model."""

    def test_create_answer(self) -> None:
        now = _now()
        a = IntakeAnswer(
            answer_id="IA-001",
            question_id="IQ-001",
            answer_text="The user should be able to log in with email/password.",
            answered_by="human-engineer",
            answered_at=now,
        )
        assert a.answer_id == "IA-001"
        assert a.question_id == "IQ-001"
        assert a.answer_text == "The user should be able to log in with email/password."
        assert a.answered_by == "human-engineer"
        assert a.answered_at == now

    def test_is_frozen(self) -> None:
        a = IntakeAnswer(
            answer_id="IA-001",
            question_id="IQ-001",
            answer_text="Test",
            answered_by="engineer",
            answered_at=_now(),
        )
        with pytest.raises(ValidationError):
            a.answer_text = "Changed"  # type: ignore[misc]


class TestIntakeAssumption:
    """Tests for IntakeAssumption model."""

    def test_create_assumption(self) -> None:
        a = IntakeAssumption(
            assumption_id="AS-001",
            question_id="IQ-001",
            assumed_value="Users will authenticate via email/password",
            category=AssumptionCategory.PROCEED,
        )
        assert a.assumption_id == "AS-001"
        assert a.question_id == "IQ-001"
        assert a.assumed_value == "Users will authenticate via email/password"
        assert a.category == AssumptionCategory.PROCEED

    def test_invalidation_triggers_default_empty(self) -> None:
        a = IntakeAssumption(
            assumption_id="AS-001",
            question_id="IQ-001",
            assumed_value="Test",
            category=AssumptionCategory.PROCEED,
        )
        assert a.invalidation_triggers == ()

    def test_invalidation_triggers_set(self) -> None:
        a = IntakeAssumption(
            assumption_id="AS-001",
            question_id="IQ-001",
            assumed_value="Test",
            category=AssumptionCategory.PROCEED,
            invalidation_triggers=("PRL change", "stakeholder override"),
        )
        assert a.invalidation_triggers == ("PRL change", "stakeholder override")

    def test_is_material_default_false(self) -> None:
        a = IntakeAssumption(
            assumption_id="AS-001",
            question_id="IQ-001",
            assumed_value="Test",
            category=AssumptionCategory.PROCEED,
        )
        assert a.is_material is False

    def test_status_default_active(self) -> None:
        a = IntakeAssumption(
            assumption_id="AS-001",
            question_id="IQ-001",
            assumed_value="Test",
            category=AssumptionCategory.PROCEED,
        )
        assert a.status == "active"

    def test_status_confirmed(self) -> None:
        a = IntakeAssumption(
            assumption_id="AS-001",
            question_id="IQ-001",
            assumed_value="Test",
            category=AssumptionCategory.PROCEED,
            status="confirmed",
        )
        assert a.status == "confirmed"

    def test_status_invalidated(self) -> None:
        a = IntakeAssumption(
            assumption_id="AS-001",
            question_id="IQ-001",
            assumed_value="Test",
            category=AssumptionCategory.PROCEED,
            status="invalidated",
        )
        assert a.status == "invalidated"

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            IntakeAssumption(
                assumption_id="AS-001",
                question_id="IQ-001",
                assumed_value="Test",
                category=AssumptionCategory.PROCEED,
                status="unknown",
            )


class TestIntakeAssumptionFlagMaterialRule:
    """Tests for INTAKE-05: FLAG assumptions restricted to non-material only."""

    def test_flag_non_material_ok(self) -> None:
        a = IntakeAssumption(
            assumption_id="AS-001",
            question_id="IQ-001",
            assumed_value="Non-critical assumption",
            category=AssumptionCategory.FLAG,
            is_material=False,
        )
        assert a.category == AssumptionCategory.FLAG
        assert a.is_material is False

    def test_flag_material_rejected(self) -> None:
        """INTAKE-05: FLAG assumptions restricted to non-material only."""
        with pytest.raises(ValidationError, match="FLAG assumptions restricted to non-material"):
            IntakeAssumption(
                assumption_id="AS-001",
                question_id="IQ-001",
                assumed_value="Critical assumption",
                category=AssumptionCategory.FLAG,
                is_material=True,
            )

    def test_block_material_ok(self) -> None:
        a = IntakeAssumption(
            assumption_id="AS-001",
            question_id="IQ-001",
            assumed_value="Critical assumption",
            category=AssumptionCategory.BLOCK,
            is_material=True,
        )
        assert a.category == AssumptionCategory.BLOCK
        assert a.is_material is True

    def test_proceed_non_material_ok(self) -> None:
        a = IntakeAssumption(
            assumption_id="AS-001",
            question_id="IQ-001",
            assumed_value="Safe assumption",
            category=AssumptionCategory.PROCEED,
            is_material=False,
        )
        assert a.category == AssumptionCategory.PROCEED
