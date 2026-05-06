"""End-to-end integration tests for Phase 3: Harness Plane.

Tests verify cross-service data flow between Phase 3 services WITHOUT
a database (all in-memory). Each test wires real service instances
together to validate cross-service contracts.

Test scenarios:
a. Sensor orchestrator -> evidence synthesizer triage pipeline
b. Triage -> review routing dispatch
c. Evidence assembly pipeline (decision views, disclosure, chain of custody)
d. Guide pack within budget
e. Guide pack oversized signals decomposition (D-13)
f. Self-correction retry loop
g. Circuit breaker halts deep nesting
h. Full pipeline flow: sensors -> triage -> review -> evidence -> guide pack
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.integration

from ces.harness.models.guide_pack import GuidePackBudget
from ces.harness.models.self_correction_state import (
    CircuitBreakerState,
    SelfCorrectionState,
)
from ces.harness.models.sensor_result import SensorResult
from ces.harness.models.triage_result import TriageColor
from ces.harness.sensors.base import BaseSensor
from ces.harness.services.evidence_synthesizer import EvidenceSynthesizer
from ces.harness.services.guide_pack_builder import GuidePackBuilder
from ces.harness.services.review_router import ReviewRouter
from ces.harness.services.self_correction_manager import SelfCorrectionManager
from ces.harness.services.sensor_orchestrator import SensorOrchestrator
from ces.shared.enums import GateType, RiskTier, TrustStatus

# ---------------------------------------------------------------------------
# Test sensor implementations
# ---------------------------------------------------------------------------


class PassingSensor(BaseSensor):
    """A sensor that always passes."""

    async def _execute(self, context: dict) -> tuple[bool, float, str]:
        return True, 1.0, "All checks passed"


class FailingSensor(BaseSensor):
    """A sensor that always fails."""

    async def _execute(self, context: dict) -> tuple[bool, float, str]:
        return False, 0.0, "Check failed"


# ---------------------------------------------------------------------------
# a. Sensor -> Triage pipeline
# ---------------------------------------------------------------------------


class TestSensorToTriagePipeline:
    """SensorOrchestrator results feed into EvidenceSynthesizer.triage()."""

    @pytest.mark.asyncio
    async def test_sensor_to_triage_pipeline(self):
        """Run 3 sensors (2 pass, 1 fail) -> triage with mixed results."""
        # Create sensors: 2 passing, 1 failing
        sensors = [
            PassingSensor(sensor_id="sec-001", sensor_pack="security"),
            PassingSensor(sensor_id="perf-001", sensor_pack="performance"),
            FailingSensor(sensor_id="dep-001", sensor_pack="dependency"),
        ]

        # Run sensors via orchestrator
        orchestrator = SensorOrchestrator(sensors=sensors)
        pack_results = await orchestrator.run_all(context={"task_id": "T-001"})
        assert len(pack_results) == 3  # 3 different packs

        # Collect all individual sensor results for triage
        all_sensor_results: list[SensorResult] = []
        for pack in pack_results:
            all_sensor_results.extend(pack.results)

        assert len(all_sensor_results) == 3
        assert sum(1 for r in all_sensor_results if r.passed) == 2

        # Feed into evidence synthesizer triage
        synthesizer = EvidenceSynthesizer()
        triage = await synthesizer.triage(
            risk_tier=RiskTier.C,
            trust_status=TrustStatus.TRUSTED,
            sensor_results=all_sensor_results,
        )

        # Tier C + Trusted + sensors NOT all green -> YELLOW
        assert triage.color == TriageColor.YELLOW
        assert triage.sensor_pass_rate == pytest.approx(2.0 / 3.0, rel=1e-2)


# ---------------------------------------------------------------------------
# b. Triage -> Review routing
# ---------------------------------------------------------------------------


class TestTriageToReviewRouting:
    """Triage result feeds into ReviewRouter dispatch."""

    @pytest.mark.asyncio
    async def test_triage_to_review_routing(self):
        """Tier A + Trusted + mixed sensors -> triad dispatch."""
        # Create sensors: all passing
        sensors = [
            PassingSensor(sensor_id="s1", sensor_pack="security"),
            PassingSensor(sensor_id="s2", sensor_pack="performance"),
        ]
        orchestrator = SensorOrchestrator(sensors=sensors)
        pack_results = await orchestrator.run_all(context={})

        all_results: list[SensorResult] = []
        for pack in pack_results:
            all_results.extend(pack.results)

        # Triage
        synthesizer = EvidenceSynthesizer()
        triage = await synthesizer.triage(
            risk_tier=RiskTier.A,
            trust_status=TrustStatus.TRUSTED,
            sensor_results=all_results,
        )

        # Tier A + Trusted + sensors green -> YELLOW (per matrix)
        assert triage.color == TriageColor.YELLOW

        # Feed into review router
        router = ReviewRouter(
            model_roster=["claude-3", "gpt-4o", "gemini-pro", "llama-3"],
        )
        review_type = router.determine_review_type(
            gate_type=GateType.AGENT,
            risk_tier=RiskTier.A,
        )

        # Tier A always gets triad
        assert review_type == "triad"

        # Assign triad reviewers
        assignments = router.assign_triad(
            builder_agent_id="builder-001",
            builder_model_id="claude-3",
        )
        assert len(assignments) == 3
        # All models different from builder
        for a in assignments:
            assert a.model_id != "claude-3"


# ---------------------------------------------------------------------------
# c. Evidence assembly pipeline
# ---------------------------------------------------------------------------


class TestEvidenceAssemblyPipeline:
    """Evidence synthesizer assembles decision views, disclosure, chain of custody."""

    @pytest.mark.asyncio
    async def test_evidence_assembly_pipeline(self):
        """Assemble decision views, disclosure set, chain tracker, summary slots."""
        synthesizer = EvidenceSynthesizer()

        # 1. Assemble 3-position decision views (D-01)
        views = synthesizer.assemble_decision_views()
        assert len(views) == 3
        positions = {v.position for v in views}
        assert positions == {"for", "against", "neutral"}

        # 2. Create disclosure set (D-04)
        disclosure = synthesizer.create_disclosure_set(
            retries_used=2,
            skipped_checks=("hidden-check-07",),
            summarized_context=True,
            summarization_details="Truth artifacts truncated to 40% quota",
            disagreements=("Reviewer 2 raised security concern",),
        )
        assert disclosure.retries_used == 2
        assert disclosure.summarized_context is True

        # 3. Chain of custody tracker (D-07)
        tracker = synthesizer.create_chain_tracker()
        entry1 = tracker.append(
            stage="build",
            agent_id="builder-001",
            model_id="claude-3",
            content={"code": "def hello(): pass"},
        )
        entry2 = tracker.append(
            stage="review",
            agent_id="reviewer-001",
            model_id="gpt-4o",
            content={"findings": ["no issues"]},
        )
        assert len(tracker.entries) == 2
        assert entry1.content_hash != ""
        assert entry2.content_hash != ""
        assert entry1.content_hash != entry2.content_hash

        # 4. Summary slots (EVID-04)
        summary = await synthesizer.format_summary_slots()
        assert summary.max_summary_lines == 10
        assert summary.max_challenge_lines == 3


# ---------------------------------------------------------------------------
# d. Guide pack within budget
# ---------------------------------------------------------------------------


class TestGuidePackWithinBudget:
    """GuidePackBuilder assembles context within budget."""

    @pytest.mark.asyncio
    async def test_guide_pack_within_budget(self):
        """Small content + 100k context window -> success."""
        builder = GuidePackBuilder()
        budget = builder.create_budget(context_window_tokens=100_000)

        # Budget = 60000 tokens. Quotas: truth=24000, vault=18000, harness=18000
        # Provide small content (100 chars each = ~25 tokens each at 4 chars/token)
        result = await builder.assemble(
            truth_artifacts="Truth artifact content for the task." * 2,
            vault_notes="Vault notes about the domain." * 2,
            harness_context="Harness context about the agent." * 2,
            budget=budget,
        )
        assert result.success is True
        assert result.oversized is False
        assert result.contents is not None
        assert result.total_tokens_used > 0
        assert result.total_tokens_used <= budget.total_budget_tokens


# ---------------------------------------------------------------------------
# e. Guide pack oversized signals decomposition (D-13)
# ---------------------------------------------------------------------------


class TestGuidePackOversizedSignalsDecomposition:
    """Oversized guide pack returns for decomposition, not inline split."""

    @pytest.mark.asyncio
    async def test_guide_pack_oversized_signals_decomposition(self):
        """Small budget + large content -> oversized=True, success=False."""
        builder = GuidePackBuilder(chars_per_token=1)

        # Very small budget: 3 tokens
        budget = GuidePackBudget(total_budget_tokens=3)

        result = await builder.assemble(
            truth_artifacts="x" * 200,
            vault_notes="y" * 200,
            harness_context="z" * 200,
            budget=budget,
        )
        assert result.success is False
        assert result.oversized is True
        assert result.contents is None  # D-13: no inline split


# ---------------------------------------------------------------------------
# f. Self-correction retry loop
# ---------------------------------------------------------------------------


class TestSelfCorrectionRetryLoop:
    """SelfCorrectionManager enforces bounded retries and token budget."""

    @pytest.mark.asyncio
    async def test_self_correction_retry_loop(self):
        """Simulate 3 retries -> can_retry becomes False at max."""
        manager = SelfCorrectionManager()

        state = SelfCorrectionState(
            task_id="T-retry-001",
            max_retries=3,
            token_budget=10000,
        )

        # Retry 1
        assert manager.can_retry(state) is True
        state = manager.record_retry(state, tokens_consumed=2000)
        assert state.retry_count == 1

        # Retry 2
        assert manager.can_retry(state) is True
        state = manager.record_retry(state, tokens_consumed=2000)
        assert state.retry_count == 2

        # Retry 3
        assert manager.can_retry(state) is True
        state = manager.record_retry(state, tokens_consumed=2000)
        assert state.retry_count == 3

        # Max reached
        assert manager.can_retry(state) is False

        # Token budget enforced
        assert manager.check_token_budget(state, tokens_needed=5000) is False
        assert manager.check_token_budget(state, tokens_needed=3000) is True


# ---------------------------------------------------------------------------
# g. Circuit breaker halts deep nesting
# ---------------------------------------------------------------------------


class TestCircuitBreakerHaltsDeepNesting:
    """Circuit breaker trips at max delegation depth."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_halts_deep_nesting(self):
        """Increment depth 3 times -> circuit breaker trips."""
        manager = SelfCorrectionManager()

        state = CircuitBreakerState(
            task_id="T-cb-001",
            max_depth=3,
            max_spawns=10,
        )

        # Increment depth 3 times
        state = manager.increment_depth(state)
        assert state.current_depth == 1
        state = manager.increment_depth(state)
        assert state.current_depth == 2
        state = manager.increment_depth(state)
        assert state.current_depth == 3

        # Check circuit breaker -- should trip at depth 3 (>= max_depth)
        tripped_state = await manager.check_circuit_breaker(state)
        assert tripped_state.tripped is True
        assert "depth" in tripped_state.trip_reason.lower()


# ---------------------------------------------------------------------------
# h. Full pipeline flow
# ---------------------------------------------------------------------------


class TestFullPipelineFlow:
    """Orchestrate full pipeline: sensors -> triage -> review -> evidence -> guide pack."""

    @pytest.mark.asyncio
    async def test_full_pipeline_flow(self):
        """End-to-end pipeline executes without errors."""
        # Step 1: Run sensors
        sensors = [
            PassingSensor(sensor_id="s1", sensor_pack="security"),
            PassingSensor(sensor_id="s2", sensor_pack="performance"),
            PassingSensor(sensor_id="s3", sensor_pack="dependency"),
        ]
        orchestrator = SensorOrchestrator(sensors=sensors)
        pack_results = await orchestrator.run_all(context={"task_id": "T-full-001"})
        assert len(pack_results) == 3

        # Collect all sensor results
        all_results: list[SensorResult] = []
        for pack in pack_results:
            all_results.extend(pack.results)

        # Step 2: Triage via evidence synthesizer
        synthesizer = EvidenceSynthesizer()
        triage = await synthesizer.triage(
            risk_tier=RiskTier.C,
            trust_status=TrustStatus.TRUSTED,
            sensor_results=all_results,
        )
        assert triage.color == TriageColor.GREEN  # C + Trusted + all green

        # Step 3: Review routing
        router = ReviewRouter(
            model_roster=["claude-3", "gpt-4o", "gemini-pro", "llama-3"],
        )
        review_type = router.determine_review_type(
            gate_type=GateType.AGENT,
            risk_tier=RiskTier.C,
        )
        assert review_type == "single"  # Non-Tier-A gets single

        assignment = router.assign_single(
            builder_agent_id="builder-001",
            builder_model_id="claude-3",
        )
        assert assignment.model_id != "claude-3"

        # Step 4: Evidence assembly
        views = synthesizer.assemble_decision_views()
        assert len(views) == 3

        disclosure = synthesizer.create_disclosure_set(
            retries_used=0,
            skipped_checks=(),
            summarized_context=False,
            summarization_details=None,
            disagreements=(),
        )
        assert disclosure.retries_used == 0

        tracker = synthesizer.create_chain_tracker()
        tracker.append(
            stage="build",
            agent_id="builder-001",
            model_id="claude-3",
            content={"artifacts": "built"},
        )
        tracker.append(
            stage="review",
            agent_id=assignment.agent_id,
            model_id=assignment.model_id,
            content={"review": "approved"},
        )
        assert len(tracker.entries) == 2

        summary = await synthesizer.format_summary_slots()
        assert summary is not None

        # Step 5: Guide pack assembly
        builder = GuidePackBuilder()
        budget = builder.create_budget(context_window_tokens=100_000)
        guide_result = await builder.assemble(
            truth_artifacts="Task specification and requirements.",
            vault_notes="Domain knowledge and patterns.",
            harness_context="Agent profile and trust status.",
            budget=budget,
        )
        assert guide_result.success is True
        assert guide_result.contents is not None

        # All artifacts created without errors
        assert triage is not None
        assert assignment is not None
        assert views is not None
        assert disclosure is not None
        assert guide_result is not None


# ---------------------------------------------------------------------------
# Re-export verification
# ---------------------------------------------------------------------------


class TestPhase3ReExports:
    """Verify all Phase 3 services are importable from harness.services."""

    def test_harness_services_exports_all_phase3(self):
        """Harness services __init__ exports all 9 Phase 3 items."""
        from ces.harness.services import (
            AgentIndependenceValidator,
            EvidenceSynthesizer,
            GuidePackBuilder,
            HiddenCheckEngine,
            ReviewRouter,
            SelfCorrectionManager,
            SensorOrchestrator,
            TrustLifecycle,
            TrustManager,
        )

        assert TrustManager is not None
        assert TrustLifecycle is not None
        assert HiddenCheckEngine is not None
        assert EvidenceSynthesizer is not None
        assert ReviewRouter is not None
        assert AgentIndependenceValidator is not None
        assert SensorOrchestrator is not None
        assert SelfCorrectionManager is not None
        assert GuidePackBuilder is not None
