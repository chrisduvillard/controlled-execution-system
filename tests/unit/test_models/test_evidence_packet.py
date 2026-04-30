"""Tests for EvidencePacket model (PRD SS2.6)."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ces.control.models.evidence_packet import (
    AdversarialHonesty,
    ChainOfCustodyEntry,
    DecisionView,
    EconomicImpact,
    EvidencePacket,
    HiddenTestOutcomes,
    RawEvidenceLinks,
    TestOutcomes,
)
from ces.shared.enums import (
    BehaviorConfidence,
    ChangeClass,
    RiskTier,
    RollbackReadiness,
)


def _make_chain_entry(**overrides):
    """Factory for ChainOfCustodyEntry."""
    defaults = {
        "step": "implementation",
        "agent_model": "claude-opus-4-20250514",
        "agent_role": "builder",
        "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return defaults


def _make_decision_view(**overrides):
    """Factory for DecisionView."""
    defaults = {
        "change_summary": "Added user authentication",
        "scope": "auth-service",
        "affected_artifacts": ("VA-001", "PRL-042"),
        "risk_tier": RiskTier.B,
        "behavior_confidence_class": BehaviorConfidence.BC2,
        "change_class": ChangeClass.CLASS_3,
        "prl_impact": "Implements PRL-042",
        "architecture_impact": "New component added",
        "contract_impact": "New API endpoint",
        "migration_impact": "None",
        "harness_impact": "New review rules",
        "assumptions": ("Auth provider is available",),
        "unknowns": ("Load under peak traffic",),
        "test_outcomes": {"passed": 42, "failed": 0, "skipped": 2},
        "hidden_test_outcomes": None,
        "review_summary": "Reviewed by 3 agents, no concerns",
        "unresolved_risks": (),
        "rollback_readiness": RollbackReadiness.READY,
        "economic_impact": {
            "tokens_consumed": 50000,
            "invocations": 12,
            "wall_clock_minutes": 5.5,
        },
        "recommended_decision": "approve",
        "vault_references": ("KV-001", "KV-002"),
    }
    defaults.update(overrides)
    return defaults


def _make_adversarial_honesty(**overrides):
    """Factory for AdversarialHonesty."""
    defaults = {
        "retries_used": 0,
        "skipped_checks": (),
        "flaky_checks": (),
        "context_summarized": False,
        "context_summarization_details": None,
        "exception_paths_used": (),
        "review_disagreements": (),
        "stale_approval_risk": False,
        "stale_check_risk": False,
        "omitted_evidence_categories": (),
    }
    defaults.update(overrides)
    return defaults


def _make_raw_evidence_links(**overrides):
    """Factory for RawEvidenceLinks."""
    defaults = {
        "test_logs": ("https://ci.example.com/logs/123",),
        "review_outputs": ("https://ci.example.com/reviews/456",),
        "replay_diffs": (),
        "reconciliation_outputs": (),
        "deployment_checks": (),
        "observability_dashboards": (),
    }
    defaults.update(overrides)
    return defaults


def _make_evidence_packet(**overrides):
    """Factory for valid EvidencePacket data."""
    defaults = {
        "packet_id": "EP-001",
        "task_id": "TASK-001",
        "manifest_hash": "sha256:abc123def456",
        "agent_chain_of_custody": (_make_chain_entry(),),
        "decision_view": _make_decision_view(),
        "adversarial_honesty": _make_adversarial_honesty(),
        "raw_evidence_links": _make_raw_evidence_links(),
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "signature": None,
    }
    defaults.update(overrides)
    return defaults


class TestEvidencePacket:
    """Tests for EvidencePacket model."""

    def test_required_fields(self):
        """EvidencePacket requires all specified fields."""
        ep = EvidencePacket(**_make_evidence_packet())
        assert ep.packet_id == "EP-001"
        assert ep.task_id == "TASK-001"
        assert ep.manifest_hash == "sha256:abc123def456"
        assert len(ep.agent_chain_of_custody) == 1
        assert ep.decision_view is not None
        assert ep.adversarial_honesty is not None
        assert ep.raw_evidence_links is not None
        assert ep.created_at is not None
        assert ep.signature is None

    def test_chain_of_custody_entry(self):
        """ChainOfCustodyEntry has step, agent_model, agent_role, timestamp."""
        entry = ChainOfCustodyEntry(**_make_chain_entry())
        assert entry.step == "implementation"
        assert entry.agent_model == "claude-opus-4-20250514"
        assert entry.agent_role == "builder"
        assert entry.timestamp is not None

    def test_decision_view_all_fields(self):
        """DecisionView has all required fields."""
        dv = DecisionView(**_make_decision_view())
        assert dv.change_summary == "Added user authentication"
        assert dv.risk_tier == RiskTier.B
        assert dv.behavior_confidence_class == BehaviorConfidence.BC2
        assert dv.change_class == ChangeClass.CLASS_3
        assert dv.test_outcomes.passed == 42
        assert dv.hidden_test_outcomes is None
        assert dv.rollback_readiness == RollbackReadiness.READY
        assert dv.economic_impact.tokens_consumed == 50000
        assert dv.vault_references == ("KV-001", "KV-002")
        assert dv.recommended_decision == "approve"

    def test_decision_view_with_hidden_test_outcomes(self):
        """DecisionView can include hidden test outcomes."""
        dv = DecisionView(**_make_decision_view(hidden_test_outcomes={"passed": 5, "failed": 0}))
        assert dv.hidden_test_outcomes is not None
        assert dv.hidden_test_outcomes.passed == 5

    def test_adversarial_honesty_all_fields(self):
        """AdversarialHonesty has all required fields."""
        ah = AdversarialHonesty(**_make_adversarial_honesty())
        assert ah.retries_used == 0
        assert ah.skipped_checks == ()
        assert ah.flaky_checks == ()
        assert ah.context_summarized is False
        assert ah.context_summarization_details is None
        assert ah.exception_paths_used == ()
        assert ah.review_disagreements == ()
        assert ah.stale_approval_risk is False
        assert ah.stale_check_risk is False
        assert ah.omitted_evidence_categories == ()

    def test_adversarial_honesty_with_issues(self):
        """AdversarialHonesty records issues honestly."""
        ah = AdversarialHonesty(
            **_make_adversarial_honesty(
                retries_used=3,
                skipped_checks=("perf-check",),
                context_summarized=True,
                context_summarization_details="Summarized 50 files to 5 pages",
                review_disagreements=("Agent 2 flagged risk in auth flow",),
                stale_approval_risk=True,
            )
        )
        assert ah.retries_used == 3
        assert ah.skipped_checks == ("perf-check",)
        assert ah.context_summarized is True
        assert ah.stale_approval_risk is True

    def test_round_trip_serialization(self):
        """EvidencePacket round-trips through model_dump/model_validate."""
        original = EvidencePacket(**_make_evidence_packet())
        data = original.model_dump()
        restored = EvidencePacket.model_validate(data)
        assert original == restored

    def test_missing_required_field_raises(self):
        """Missing required field raises ValidationError."""
        data = _make_evidence_packet()
        del data["packet_id"]
        with pytest.raises(ValidationError):
            EvidencePacket(**data)

    def test_not_governed_artifact(self):
        """EvidencePacket is NOT a GovernedArtifactBase -- it's an operational artifact."""
        ep = EvidencePacket(**_make_evidence_packet())
        # Should NOT have version, status, owner fields
        assert not hasattr(ep, "version") or "version" not in ep.model_fields
        assert not hasattr(ep, "status") or "status" not in ep.model_fields
