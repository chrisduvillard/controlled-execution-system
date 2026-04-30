"""Tests for GateEvidencePacket model (PRD SS2.7)."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ces.control.models.gate_evidence_packet import (
    GateClassification,
    GateCriterion,
    GateEvidencePacket,
    IntakeAssumption,
)
from ces.shared.enums import (
    BehaviorConfidence,
    GateDecision,
    GateType,
    RiskTier,
    TrustStatus,
)


def _make_gate_packet(**overrides):
    """Factory for valid GateEvidencePacket data."""
    defaults = {
        "gate_id": "GATE-P5-2026-04-05-001",
        "phase": 5,
        "gate_type": GateType.HYBRID,
        "gate_agent_model": "claude-opus-4-20250514",
        "work_agent_models": ("claude-opus-4-20250514", "gpt-4.1-2025-04-14"),
        "classification": {
            "risk_tier": RiskTier.B,
            "behavior_confidence_class": BehaviorConfidence.BC2,
            "classification_confidence": 0.85,
        },
        "trust_status": TrustStatus.TRUSTED,
        "gate_criteria": (
            {
                "criterion": "All tests pass",
                "evidence": "CI pipeline green",
                "met": True,
            },
        ),
        "decision": GateDecision.PASS,
        "escalation_reason": None,
        "concerns": (),
        "assumptions_from_intake": (
            {
                "assumption_id": "A-001",
                "assumed_value": "PostgreSQL 17",
                "status": "confirmed",
            },
        ),
        "intake_complete": True,
        "open_blocking_questions": (),
        "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "audit_ledger_ref": "AUDIT-001",
    }
    defaults.update(overrides)
    return defaults


class TestGateEvidencePacket:
    """Tests for GateEvidencePacket model."""

    def test_required_fields(self):
        """GateEvidencePacket requires all specified fields."""
        gep = GateEvidencePacket(**_make_gate_packet())
        assert gep.gate_id == "GATE-P5-2026-04-05-001"
        assert gep.phase == 5
        assert gep.gate_type == GateType.HYBRID
        assert gep.gate_agent_model == "claude-opus-4-20250514"
        assert len(gep.work_agent_models) == 2
        assert gep.classification is not None
        assert gep.trust_status == TrustStatus.TRUSTED
        assert len(gep.gate_criteria) == 1
        assert gep.decision == GateDecision.PASS
        assert gep.timestamp is not None
        assert gep.audit_ledger_ref == "AUDIT-001"

    def test_gate_criterion_with_bool_met(self):
        """GateCriterion met field accepts bool."""
        gc = GateCriterion(
            criterion="Tests pass",
            evidence="All green",
            met=True,
        )
        assert gc.met is True

    def test_gate_criterion_with_escalated_met(self):
        """GateCriterion met field accepts 'escalated' literal."""
        gc = GateCriterion(
            criterion="Security review",
            evidence="Needs human review",
            met="escalated",
        )
        assert gc.met == "escalated"

    def test_classification_confidence_bounds(self):
        """GateClassification classification_confidence must be 0.0-1.0."""
        # Valid
        gc = GateClassification(
            risk_tier=RiskTier.A,
            behavior_confidence_class=BehaviorConfidence.BC1,
            classification_confidence=0.5,
        )
        assert gc.classification_confidence == 0.5

        # Below 0
        with pytest.raises(ValidationError):
            GateClassification(
                risk_tier=RiskTier.A,
                behavior_confidence_class=BehaviorConfidence.BC1,
                classification_confidence=-0.1,
            )

        # Above 1
        with pytest.raises(ValidationError):
            GateClassification(
                risk_tier=RiskTier.A,
                behavior_confidence_class=BehaviorConfidence.BC1,
                classification_confidence=1.1,
            )

    def test_pass_with_blocking_questions_raises(self):
        """If decision is PASS, open_blocking_questions must be empty."""
        with pytest.raises(ValidationError, match="blocking"):
            GateEvidencePacket(
                **_make_gate_packet(
                    decision=GateDecision.PASS,
                    open_blocking_questions=("What about security?",),
                )
            )

    def test_fail_with_blocking_questions_valid(self):
        """If decision is FAIL, open_blocking_questions can be non-empty."""
        gep = GateEvidencePacket(
            **_make_gate_packet(
                decision=GateDecision.FAIL,
                open_blocking_questions=("What about security?",),
            )
        )
        assert gep.decision == GateDecision.FAIL
        assert len(gep.open_blocking_questions) == 1

    def test_intake_assumption_sub_model(self):
        """IntakeAssumption has assumption_id, assumed_value, status."""
        ia = IntakeAssumption(
            assumption_id="A-001",
            assumed_value="Redis 7.4",
            status="active",
        )
        assert ia.assumption_id == "A-001"

    def test_round_trip_serialization(self):
        """GateEvidencePacket round-trips through model_dump/model_validate."""
        original = GateEvidencePacket(**_make_gate_packet())
        data = original.model_dump()
        restored = GateEvidencePacket.model_validate(data)
        assert original == restored

    def test_missing_required_field_raises(self):
        """Missing required field raises ValidationError."""
        data = _make_gate_packet()
        del data["gate_id"]
        with pytest.raises(ValidationError):
            GateEvidencePacket(**data)
