"""Gate Evidence Packet model (PRD Part IV SS2.7).

Gate Evidence Packets record the evaluation of phase gates, including
classification, trust status, gate criteria evaluation, and the gate decision.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from ces.shared.base import CESBaseModel
from ces.shared.enums import (
    BehaviorConfidence,
    GateDecision,
    GateType,
    RiskTier,
    TrustStatus,
)


class GateClassification(CESBaseModel):
    """Classification details for the gated work."""

    risk_tier: RiskTier
    behavior_confidence_class: BehaviorConfidence
    classification_confidence: float = Field(ge=0.0, le=1.0)


class GateCriterion(CESBaseModel):
    """A single gate criterion evaluation.

    The met field can be True, False, or the literal string "escalated".
    """

    criterion: str
    evidence: str
    met: bool | Literal["escalated"]


class IntakeAssumption(CESBaseModel):
    """An assumption from the intake interview that the gate depends on."""

    assumption_id: str
    assumed_value: str
    status: str


class GateEvidencePacket(CESBaseModel):
    """Gate Evidence Packet (PRD SS2.7).

    Records the evaluation of a phase gate, including the gate agent's
    classification, trust status assessment, criterion-level evaluation,
    and final decision. Validator: PASS requires no open blocking questions.
    """

    gate_id: str
    phase: int
    gate_type: GateType
    gate_agent_model: str
    work_agent_models: tuple[str, ...]
    classification: GateClassification
    trust_status: TrustStatus
    gate_criteria: tuple[GateCriterion, ...]
    decision: GateDecision
    escalation_reason: str | None = None
    concerns: tuple[str, ...] = ()
    assumptions_from_intake: tuple[IntakeAssumption, ...] = ()
    intake_complete: bool
    open_blocking_questions: tuple[str, ...] = ()
    timestamp: datetime
    audit_ledger_ref: str

    @model_validator(mode="after")
    def pass_requires_no_blocking_questions(self) -> GateEvidencePacket:
        """If decision is PASS, open_blocking_questions must be empty."""
        if self.decision == GateDecision.PASS and self.open_blocking_questions:
            raise ValueError(
                f"PASS decision requires no open blocking questions, but found: {self.open_blocking_questions}"
            )
        return self
