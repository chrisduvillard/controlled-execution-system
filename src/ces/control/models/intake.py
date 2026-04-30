"""Intake models (MODEL-13) - interview protocol support.

Defines models for the Intake Interview Engine:
- IntakeQuestion: Questions asked during intake phases
- IntakeAnswer: Human/agent responses to intake questions
- IntakeAssumption: Assumptions made when questions cannot be answered

Implements INTAKE-05: FLAG assumptions restricted to non-material only.
Material questions must BLOCK.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from ces.shared.base import CESBaseModel
from ces.shared.enums import AssumptionCategory


class IntakeQuestion(CESBaseModel):
    """A question asked during the intake interview process.

    Questions are organized by phase and stage:
    - mandatory: Must be answered before work begins
    - conditional: Asked based on prior answers
    - completeness: Final verification questions
    """

    question_id: str
    phase: int
    stage: Literal["mandatory", "conditional", "completeness"]
    text: str
    category: AssumptionCategory
    is_material: bool = False


class IntakeAnswer(CESBaseModel):
    """A response to an intake question.

    Records who answered, when, and what they said.
    Frozen because answers are immutable once recorded.
    """

    answer_id: str
    question_id: str
    answer_text: str
    answered_by: str
    answered_at: datetime


class IntakeAssumption(CESBaseModel):
    """An assumption made when an intake question cannot be answered.

    Assumptions have categories that determine their handling:
    - BLOCK: Work stops until resolved (for material questions)
    - FLAG: Work continues but assumption is tracked (non-material only)
    - PROCEED: Work continues, assumption is low-risk

    Enforces INTAKE-05: FLAG assumptions restricted to non-material only.
    """

    assumption_id: str
    question_id: str
    assumed_value: str
    category: AssumptionCategory
    is_material: bool = False
    invalidation_triggers: tuple[str, ...] = Field(default_factory=tuple)
    status: Literal["active", "confirmed", "invalidated"] = "active"

    @model_validator(mode="after")
    def flag_cannot_be_material(self) -> IntakeAssumption:
        """Enforce INTAKE-05: FLAG assumptions restricted to non-material only.

        Material questions must BLOCK, not FLAG. This prevents
        critical assumptions from being silently flagged instead
        of properly blocking work.
        """
        if self.category == AssumptionCategory.FLAG and self.is_material:
            msg = "FLAG assumptions restricted to non-material only; material questions must BLOCK (INTAKE-05)"
            raise ValueError(msg)
        return self
