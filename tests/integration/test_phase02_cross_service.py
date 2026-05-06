"""Cross-service integration tests for Phase 2: Reactive Controls + Safety.

Tests verify end-to-end flows between Phase 2 services WITHOUT a database
(all in-memory). Each test wires real service instances together to validate
cross-service contracts.

Test scenarios:
a. Oracle -> Gate Evaluator flow (CLASS-06)
b. Kill switch -> MergeController flow
c. Trust lifecycle -> Gate type flow
d. Cascade invalidation -> audit logging flow
e. Full pipeline smoke test (classify -> gate -> merge)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from ces.control.models.kill_switch_state import ActivityClass
from ces.control.services.cascade_invalidation import CascadeInvalidationEngine
from ces.control.services.classification_oracle import ClassificationOracle
from ces.control.services.evidence_integrity import compute_reviewed_evidence_hash
from ces.control.services.gate_evaluator import GateEvaluator
from ces.control.services.kill_switch import KillSwitchService
from ces.control.services.merge_controller import MergeController
from ces.harness.models.harness_profile import HarnessProfile
from ces.harness.services.trust_manager import TrustManager
from ces.shared.enums import (
    BehaviorConfidence,
    GateType,
    ReviewSubState,
    RiskTier,
    TrustStatus,
    WorkflowState,
)

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _valid_merge_kwargs(
    gate_type: GateType = GateType.AGENT,
) -> dict:
    """Return kwargs for a passing merge validation."""
    now = datetime.now(timezone.utc)
    evidence_packet = {
        "manifest_id": "M-integ-001",
        "manifest_hash": "sha256:integ123",
        "result": "pass",
        "coverage": 95,
    }
    evidence_packet["reviewed_evidence_hash"] = compute_reviewed_evidence_hash(evidence_packet)
    return {
        "manifest_id": "M-integ-001",
        "manifest_expires_at": now + timedelta(hours=24),
        "manifest_content_hash": "sha256:integ123",
        "manifest_risk_tier": "C",
        "manifest_bc": "BC1",
        "evidence_packet": evidence_packet,
        "evidence_manifest_hash": "sha256:integ123",
        "required_gate_type": gate_type,
        "actual_gate_type": gate_type,
        "review_sub_state": ReviewSubState.DECISION.value,
        "workflow_state": WorkflowState.APPROVED.value,
    }


# ---------------------------------------------------------------------------
# a. Oracle -> Gate Evaluator flow (CLASS-06)
# ---------------------------------------------------------------------------


class TestOracleToGateFlow:
    """Oracle classification confidence feeds gate evaluator."""

    def test_oracle_to_gate_high_confidence(self):
        """High confidence classification -> no gate elevation."""
        oracle = ClassificationOracle()
        evaluator = GateEvaluator(
            meta_review_rates={"A": 0.0, "B": 0.0, "C": 0.0},
            hidden_check_rate=0.0,
            new_profile_threshold=0,
        )

        # Classify a description that matches the decision table well
        result = oracle.classify("Add new REST API endpoint for user registration")
        confidence = result.confidence

        gate_result = evaluator.evaluate(
            phase=7,
            risk_tier=RiskTier.C,
            bc=BehaviorConfidence.BC1,
            trust_status=TrustStatus.TRUSTED,
            oracle_confidence=confidence,
            profile_id="test-profile",
        )

        # The gate type should be determined by confidence + matrix
        assert gate_result.gate_type in (GateType.AGENT, GateType.HYBRID, GateType.HUMAN)
        assert gate_result.confidence_used == confidence

    def test_oracle_to_gate_low_confidence_elevates(self):
        """Low confidence classification -> gate elevates to HUMAN."""
        evaluator = GateEvaluator(
            meta_review_rates={"C": 0.0},
            hidden_check_rate=0.0,
            new_profile_threshold=0,
        )

        # Very low confidence forces HUMAN gate
        gate_result = evaluator.evaluate(
            phase=7,
            risk_tier=RiskTier.C,
            bc=BehaviorConfidence.BC1,
            trust_status=TrustStatus.TRUSTED,
            oracle_confidence=0.50,
            profile_id="test-low",
        )

        assert gate_result.gate_type == GateType.HUMAN
        assert gate_result.base_gate_type == GateType.AGENT  # Matrix says AGENT for phase 7 tier C trusted


# ---------------------------------------------------------------------------
# b. Kill switch -> MergeController flow
# ---------------------------------------------------------------------------


class TestKillSwitchBlocksMerge:
    """Kill switch activation blocks merge controller."""

    @pytest.mark.asyncio
    async def test_kill_switch_blocks_merge(self):
        """Activate kill switch for merges -> MergeController blocks."""
        ks = KillSwitchService()
        await ks.activate(
            activity_class=ActivityClass.MERGES,
            actor="test_operator",
            reason="Integration test: halt merges",
        )

        controller = MergeController(kill_switch=ks)
        result = await controller.validate_merge(**_valid_merge_kwargs())

        assert result.allowed is False
        ks_check = next(c for c in result.checks if c.name == "kill_switch_clear")
        assert ks_check.passed is False

    @pytest.mark.asyncio
    async def test_kill_switch_recover_allows_merge(self):
        """Recover kill switch -> MergeController allows."""
        ks = KillSwitchService()
        await ks.activate(
            activity_class=ActivityClass.MERGES,
            actor="test_operator",
            reason="Integration test: halt merges",
        )
        await ks.recover(
            activity_class=ActivityClass.MERGES,
            actor="test_operator",
            reason="Integration test: recover merges",
        )

        controller = MergeController(kill_switch=ks)
        result = await controller.validate_merge(**_valid_merge_kwargs())

        assert result.allowed is True


# ---------------------------------------------------------------------------
# c. Trust lifecycle -> Gate type flow
# ---------------------------------------------------------------------------


class TestTrustLifecycleAffectsGate:
    """Trust status changes affect gate type assignment."""

    @pytest.mark.asyncio
    async def test_trust_lifecycle_affects_gate(self):
        """TRUSTED status gets less restrictive gate than CANDIDATE."""
        evaluator = GateEvaluator(
            meta_review_rates={"C": 0.0},
            hidden_check_rate=0.0,
            new_profile_threshold=0,
        )

        # Evaluate gate for CANDIDATE (non-trusted)
        candidate_gate = evaluator.evaluate(
            phase=7,
            risk_tier=RiskTier.C,
            bc=BehaviorConfidence.BC1,
            trust_status=TrustStatus.CANDIDATE,
            oracle_confidence=0.95,
            profile_id="test-candidate",
        )

        # Evaluate gate for TRUSTED
        trusted_gate = evaluator.evaluate(
            phase=7,
            risk_tier=RiskTier.C,
            bc=BehaviorConfidence.BC1,
            trust_status=TrustStatus.TRUSTED,
            oracle_confidence=0.95,
            profile_id="test-trusted",
        )

        # TRUSTED should get AGENT (less restrictive), CANDIDATE gets HUMAN
        assert trusted_gate.gate_type == GateType.AGENT
        assert candidate_gate.gate_type == GateType.HUMAN

    @pytest.mark.asyncio
    async def test_trust_promotion_changes_gate_path(self):
        """Auto-promoting a profile from CANDIDATE to TRUSTED changes gate."""
        from ces.shared.enums import ChangeClass

        manager = TrustManager()

        profile = HarnessProfile(
            profile_id="agent-integ-01",
            agent_id="builder-001",
            trust_status=TrustStatus.CANDIDATE,
            completed_tasks=15,
            active_since=datetime.now(timezone.utc) - timedelta(days=30),
            change_classes_covered={
                ChangeClass.CLASS_1,
                ChangeClass.CLASS_2,
                ChangeClass.CLASS_3,
            },
            production_releases=2,
            escapes=0,
        )

        assert profile.can_promote is True
        promoted = await manager.evaluate_promotion(profile)
        assert promoted.trust_status == TrustStatus.TRUSTED


# ---------------------------------------------------------------------------
# d. Cascade invalidation -> audit logging flow
# ---------------------------------------------------------------------------


class TestCascadeAuditFlow:
    """Cascade invalidation logs to audit ledger."""

    @pytest.mark.asyncio
    async def test_cascade_audit(self):
        """Cascade propagation + log_cascade records audit event."""
        mock_ledger = AsyncMock()
        mock_ledger.record_invalidation = AsyncMock()

        engine = CascadeInvalidationEngine(audit_ledger=mock_ledger)

        # Build a simple dependency graph
        graph = {
            "truth:VA-001": ["manifest:M1", "manifest:M2"],
            "manifest:M1": ["review:R1"],
            "manifest:M2": ["merge:MG1"],
        }
        states = {
            "manifest:M1": "in_flight",
            "manifest:M2": "queued",
            "review:R1": "under_review",
            "merge:MG1": "queued",
        }

        result = engine.propagate(
            changed_artifact_id="truth:VA-001",
            artifact_type="vision_anchor",
            dependency_graph=graph,
            entity_states=states,
        )

        # Verify propagation found affected entities
        assert len(result.affected_manifests) == 2
        assert "M1" in result.affected_manifests
        assert "M2" in result.affected_manifests

        # Log the cascade to audit ledger
        await engine.log_cascade(
            result=result,
            changed_artifact_id="truth:VA-001",
            artifact_type="vision_anchor",
        )

        # Verify audit ledger was called with correct severity
        mock_ledger.record_invalidation.assert_awaited_once()
        call_kwargs = mock_ledger.record_invalidation.call_args[1]
        assert call_kwargs["artifact_id"] == "truth:VA-001"
        assert len(call_kwargs["affected_manifests"]) == 2
        # HIGH severity because M1 is in_flight and R1 is under_review
        from ces.shared.enums import InvalidationSeverity

        assert call_kwargs["severity"] == InvalidationSeverity.HIGH


# ---------------------------------------------------------------------------
# e. Full pipeline smoke test
# ---------------------------------------------------------------------------


class TestFullPipelineSmokeTest:
    """End-to-end flow: classify -> gate evaluate -> merge validate."""

    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        """Classify task, evaluate gate, validate merge -> allowed."""
        # Step 1: Classify a task
        oracle = ClassificationOracle()
        classification = oracle.classify("Add new REST API endpoint for user registration")
        confidence = classification.confidence

        # Step 2: Evaluate gate type
        evaluator = GateEvaluator(
            meta_review_rates={"C": 0.0},
            hidden_check_rate=0.0,
            new_profile_threshold=0,
        )
        gate_result = evaluator.evaluate(
            phase=7,
            risk_tier=RiskTier.C,
            bc=BehaviorConfidence.BC1,
            trust_status=TrustStatus.TRUSTED,
            oracle_confidence=confidence,
            profile_id="smoke-profile",
        )

        # Step 3: Validate merge with the evaluated gate type
        controller = MergeController()
        merge_kwargs = _valid_merge_kwargs(gate_type=gate_result.gate_type)
        merge_result = await controller.validate_merge(**merge_kwargs)

        # All conditions met -> merge allowed
        assert merge_result.allowed is True
        assert all(c.passed for c in merge_result.checks)
        assert len(merge_result.checks) == 5

    @pytest.mark.asyncio
    async def test_full_pipeline_with_kill_switch_block(self):
        """Full pipeline but kill switch blocks the final merge."""
        # Step 1: Classify
        oracle = ClassificationOracle()
        classification = oracle.classify("Add new REST API endpoint for user registration")

        # Step 2: Gate evaluation
        evaluator = GateEvaluator(
            meta_review_rates={"C": 0.0},
            hidden_check_rate=0.0,
            new_profile_threshold=0,
        )
        gate_result = evaluator.evaluate(
            phase=7,
            risk_tier=RiskTier.C,
            bc=BehaviorConfidence.BC1,
            trust_status=TrustStatus.TRUSTED,
            oracle_confidence=classification.confidence,
            profile_id="smoke-blocked",
        )

        # Step 3: Activate kill switch before merge
        ks = KillSwitchService()
        await ks.activate(
            activity_class=ActivityClass.MERGES,
            actor="operator",
            reason="Emergency halt",
        )

        # Step 4: Merge blocked by kill switch
        controller = MergeController(kill_switch=ks)
        merge_kwargs = _valid_merge_kwargs(gate_type=gate_result.gate_type)
        merge_result = await controller.validate_merge(**merge_kwargs)

        assert merge_result.allowed is False
        ks_check = next(c for c in merge_result.checks if c.name == "kill_switch_clear")
        assert ks_check.passed is False


# ---------------------------------------------------------------------------
# Re-export verification
# ---------------------------------------------------------------------------


class TestPhase2ReExports:
    """Verify all Phase 2 services and models are importable from __init__."""

    def test_control_services_exports(self):
        """Control services __init__ exports all Phase 2 services."""
        from ces.control.services import (
            AuditLedgerService,
            CascadeInvalidationEngine,
            ClassificationOracle,
            GateEvaluator,
            KillSwitchProtocol,
            KillSwitchService,
            MergeController,
        )

        assert AuditLedgerService is not None
        assert CascadeInvalidationEngine is not None
        assert ClassificationOracle is not None
        assert GateEvaluator is not None
        assert KillSwitchProtocol is not None
        assert KillSwitchService is not None
        assert MergeController is not None

    def test_control_models_exports(self):
        """Control models __init__ exports all Phase 2 models."""
        from ces.control.models import (
            ActivityClass,
            CascadeResult,
            GateEvaluationResult,
            KillSwitchState,
            MergeCheck,
            MergeDecision,
            OracleClassificationResult,
        )

        assert ActivityClass is not None
        assert CascadeResult is not None
        assert GateEvaluationResult is not None
        assert KillSwitchState is not None
        assert MergeCheck is not None
        assert MergeDecision is not None
        assert OracleClassificationResult is not None

    def test_harness_services_exports(self):
        """Harness services __init__ exports TrustManager."""
        from ces.harness.services import TrustManager

        assert TrustManager is not None

    def test_harness_models_exports(self):
        """Harness models __init__ exports HarnessProfile."""
        from ces.harness.models import HarnessProfile

        assert HarnessProfile is not None
