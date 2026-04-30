"""Tests for ReviewRouter and AgentIndependenceValidator.

Covers:
- EVID-07: Agent independence validation (no self-review)
- EVID-08: Triad assignment with 3 different models
- EVID-09: Model diversity enforcement
- EVID-10: Unanimous zero-findings detection and auto-escalation
- EVID-11: Builder model excluded from review roster
- EVID-03: Adversarial challenger on different model
- D-05: Model roster >= 3, sequential role assignment
- D-06: All static validation methods
- D-08: Unanimous zero-findings -> HYBRID escalation
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ces.harness.models.review_assignment import (
    IndependenceViolation,
    ReviewAssignment,
    ReviewerRole,
)
from ces.harness.services.review_router import (
    AgentIndependenceValidator,
    KillSwitchActiveError,
    ReviewRouter,
)
from ces.shared.enums import GateType, RiskTier

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def structural_assignment() -> ReviewAssignment:
    """A valid structural reviewer assignment."""
    return ReviewAssignment(
        role=ReviewerRole.STRUCTURAL,
        model_id="model-alpha",
        agent_id="reviewer-structural-model-alpha",
    )


@pytest.fixture()
def semantic_assignment() -> ReviewAssignment:
    """A valid semantic reviewer assignment."""
    return ReviewAssignment(
        role=ReviewerRole.SEMANTIC,
        model_id="model-beta",
        agent_id="reviewer-semantic-model-beta",
    )


@pytest.fixture()
def red_team_assignment() -> ReviewAssignment:
    """A valid red team reviewer assignment."""
    return ReviewAssignment(
        role=ReviewerRole.RED_TEAM,
        model_id="model-gamma",
        agent_id="reviewer-red_team-model-gamma",
    )


# ---------------------------------------------------------------------------
# AgentIndependenceValidator: validate_no_self_review
# ---------------------------------------------------------------------------


class TestValidateNoSelfReview:
    """Tests for AgentIndependenceValidator.validate_no_self_review."""

    def test_no_self_review_passes_when_different(self) -> None:
        """No violations when all reviewer IDs differ from builder."""
        violations = AgentIndependenceValidator.validate_no_self_review(
            builder_agent_id="builder-001",
            reviewer_agent_ids=["reviewer-a", "reviewer-b", "reviewer-c"],
        )
        assert violations == []

    def test_no_self_review_catches_match(self) -> None:
        """Catches self-review when a reviewer ID matches the builder."""
        violations = AgentIndependenceValidator.validate_no_self_review(
            builder_agent_id="builder-001",
            reviewer_agent_ids=["reviewer-a", "builder-001", "reviewer-c"],
        )
        assert len(violations) == 1
        assert violations[0].violation_type == "self_review"
        assert "builder-001" in violations[0].details

    def test_no_self_review_catches_multiple_matches(self) -> None:
        """Catches multiple self-review matches."""
        violations = AgentIndependenceValidator.validate_no_self_review(
            builder_agent_id="builder-001",
            reviewer_agent_ids=["builder-001", "builder-001"],
        )
        assert len(violations) == 2

    def test_no_self_review_empty_list(self) -> None:
        """Empty reviewer list produces no violations."""
        violations = AgentIndependenceValidator.validate_no_self_review(
            builder_agent_id="builder-001",
            reviewer_agent_ids=[],
        )
        assert violations == []


# ---------------------------------------------------------------------------
# AgentIndependenceValidator: validate_model_diversity
# ---------------------------------------------------------------------------


class TestValidateModelDiversity:
    """Tests for AgentIndependenceValidator.validate_model_diversity."""

    def test_model_diversity_passes_when_unique(
        self,
        structural_assignment: ReviewAssignment,
        semantic_assignment: ReviewAssignment,
        red_team_assignment: ReviewAssignment,
    ) -> None:
        """No violations when all models are different."""
        violations = AgentIndependenceValidator.validate_model_diversity(
            [structural_assignment, semantic_assignment, red_team_assignment]
        )
        assert violations == []

    def test_model_diversity_catches_duplicate(self) -> None:
        """Catches when two assignments share the same model."""
        a1 = ReviewAssignment(
            role=ReviewerRole.STRUCTURAL,
            model_id="model-alpha",
            agent_id="reviewer-structural-model-alpha",
        )
        a2 = ReviewAssignment(
            role=ReviewerRole.SEMANTIC,
            model_id="model-alpha",  # duplicate
            agent_id="reviewer-semantic-model-alpha",
        )
        violations = AgentIndependenceValidator.validate_model_diversity([a1, a2])
        assert len(violations) >= 1
        assert violations[0].violation_type == "model_duplicate"
        assert "model-alpha" in violations[0].details

    def test_model_diversity_empty_list(self) -> None:
        """Empty list is trivially diverse."""
        violations = AgentIndependenceValidator.validate_model_diversity([])
        assert violations == []


# ---------------------------------------------------------------------------
# AgentIndependenceValidator: validate_builder_model_excluded
# ---------------------------------------------------------------------------


class TestValidateBuilderModelExcluded:
    """Tests for AgentIndependenceValidator.validate_builder_model_excluded."""

    def test_builder_model_excluded_passes(
        self,
        structural_assignment: ReviewAssignment,
        semantic_assignment: ReviewAssignment,
    ) -> None:
        """No violations when builder model not in assignments."""
        violations = AgentIndependenceValidator.validate_builder_model_excluded(
            builder_model_id="model-delta",
            assignments=[structural_assignment, semantic_assignment],
        )
        assert violations == []

    def test_builder_model_excluded_catches(self) -> None:
        """Catches when a reviewer uses the builder's model."""
        a1 = ReviewAssignment(
            role=ReviewerRole.STRUCTURAL,
            model_id="model-builder",
            agent_id="reviewer-structural-model-builder",
        )
        violations = AgentIndependenceValidator.validate_builder_model_excluded(
            builder_model_id="model-builder",
            assignments=[a1],
        )
        assert len(violations) == 1
        assert violations[0].violation_type == "builder_model_reuse"
        assert "model-builder" in violations[0].details


# ---------------------------------------------------------------------------
# AgentIndependenceValidator: validate_all
# ---------------------------------------------------------------------------


class TestValidateAll:
    """Tests for AgentIndependenceValidator.validate_all."""

    def test_validate_all_empty_when_clean(
        self,
        structural_assignment: ReviewAssignment,
        semantic_assignment: ReviewAssignment,
        red_team_assignment: ReviewAssignment,
    ) -> None:
        """No violations when everything is clean."""
        violations = AgentIndependenceValidator.validate_all(
            builder_agent_id="builder-001",
            builder_model_id="model-builder",
            assignments=[
                structural_assignment,
                semantic_assignment,
                red_team_assignment,
            ],
        )
        assert violations == []

    def test_validate_all_combines_violations(self) -> None:
        """Combines violations from all 3 checks."""
        # Create assignments that violate multiple rules:
        # - model-builder reused (builder_model_reuse)
        # - model-builder duplicated (model_duplicate)
        a1 = ReviewAssignment(
            role=ReviewerRole.STRUCTURAL,
            model_id="model-builder",
            agent_id="builder-001",  # self-review
        )
        a2 = ReviewAssignment(
            role=ReviewerRole.SEMANTIC,
            model_id="model-builder",  # builder model reuse + duplicate
            agent_id="reviewer-semantic-model-builder",
        )
        violations = AgentIndependenceValidator.validate_all(
            builder_agent_id="builder-001",
            builder_model_id="model-builder",
            assignments=[a1, a2],
        )
        # Should have self_review + model_duplicate + builder_model_reuse
        violation_types = [v.violation_type for v in violations]
        assert "self_review" in violation_types
        assert "model_duplicate" in violation_types
        assert "builder_model_reuse" in violation_types
        assert len(violations) >= 3


# ---------------------------------------------------------------------------
# ReviewRouter fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def model_roster() -> list[str]:
    """A valid model roster with 4 models."""
    return ["model-alpha", "model-beta", "model-gamma", "model-delta"]


@pytest.fixture()
def kill_switch() -> MagicMock:
    """Mock kill switch that is NOT halted."""
    ks = MagicMock()
    ks.is_halted.return_value = False
    return ks


@pytest.fixture()
def halted_kill_switch() -> MagicMock:
    """Mock kill switch that IS halted."""
    ks = MagicMock()
    ks.is_halted.return_value = True
    return ks


@pytest.fixture()
def audit_ledger() -> AsyncMock:
    """Mock audit ledger."""
    ledger = AsyncMock()
    ledger.append_event = AsyncMock()
    return ledger


@pytest.fixture()
def router(model_roster: list[str], kill_switch: MagicMock) -> ReviewRouter:
    """ReviewRouter with default config."""
    return ReviewRouter(
        model_roster=model_roster,
        kill_switch=kill_switch,
    )


@pytest.fixture()
def router_with_audit(
    model_roster: list[str],
    kill_switch: MagicMock,
    audit_ledger: AsyncMock,
) -> ReviewRouter:
    """ReviewRouter with audit ledger."""
    return ReviewRouter(
        model_roster=model_roster,
        kill_switch=kill_switch,
        audit_ledger=audit_ledger,
    )


# ---------------------------------------------------------------------------
# ReviewRouter: __init__
# ---------------------------------------------------------------------------


class TestReviewRouterInit:
    """Tests for ReviewRouter initialization."""

    def test_init_valid_roster(self, model_roster: list[str]) -> None:
        """Accepts roster with >= 3 models."""
        router = ReviewRouter(model_roster=model_roster)
        assert router is not None

    def test_init_exactly_3_models(self) -> None:
        """Accepts roster with exactly 3 models."""
        router = ReviewRouter(model_roster=["a", "b", "c"])
        assert router is not None

    def test_init_insufficient_models_raises(self) -> None:
        """Raises ValueError for roster with < 3 models."""
        with pytest.raises(ValueError, match="at least 3"):
            ReviewRouter(model_roster=["a", "b"])

    def test_init_empty_roster_raises(self) -> None:
        """Raises ValueError for empty roster."""
        with pytest.raises(ValueError, match="at least 3"):
            ReviewRouter(model_roster=[])


# ---------------------------------------------------------------------------
# ReviewRouter: determine_review_type
# ---------------------------------------------------------------------------


class TestDetermineReviewType:
    """Tests for ReviewRouter.determine_review_type."""

    def test_tier_a_agent_gate_gets_triad(self, router: ReviewRouter) -> None:
        """Tier A with AGENT gate -> triad (EVID-08)."""
        result = router.determine_review_type(GateType.AGENT, RiskTier.A)
        assert result == "triad"

    def test_tier_a_hybrid_gate_gets_triad(self, router: ReviewRouter) -> None:
        """Tier A with HYBRID gate -> triad."""
        result = router.determine_review_type(GateType.HYBRID, RiskTier.A)
        assert result == "triad"

    def test_tier_a_human_gate_gets_triad(self, router: ReviewRouter) -> None:
        """Tier A with HUMAN gate -> triad."""
        result = router.determine_review_type(GateType.HUMAN, RiskTier.A)
        assert result == "triad"

    def test_tier_b_agent_gate_gets_single(self, router: ReviewRouter) -> None:
        """Tier B with AGENT gate -> single."""
        result = router.determine_review_type(GateType.AGENT, RiskTier.B)
        assert result == "single"

    def test_tier_c_agent_gate_gets_single(self, router: ReviewRouter) -> None:
        """Tier C with AGENT gate -> single."""
        result = router.determine_review_type(GateType.AGENT, RiskTier.C)
        assert result == "single"

    def test_tier_b_hybrid_gate_gets_single(self, router: ReviewRouter) -> None:
        """Tier B with HYBRID gate -> single."""
        result = router.determine_review_type(GateType.HYBRID, RiskTier.B)
        assert result == "single"

    def test_tier_c_human_gate_gets_single(self, router: ReviewRouter) -> None:
        """Tier C with HUMAN gate -> single."""
        result = router.determine_review_type(GateType.HUMAN, RiskTier.C)
        assert result == "single"


# ---------------------------------------------------------------------------
# ReviewRouter: assign_triad
# ---------------------------------------------------------------------------


class TestAssignTriad:
    """Tests for ReviewRouter.assign_triad."""

    def test_assign_triad_3_different_models(self, router: ReviewRouter) -> None:
        """Triad assignment produces 3 assignments with different models."""
        assignments = router.assign_triad("builder-001", "model-delta")
        assert len(assignments) == 3
        model_ids = {a.model_id for a in assignments}
        assert len(model_ids) == 3

    def test_assign_triad_excludes_builder_model(self, router: ReviewRouter) -> None:
        """Builder model is excluded from triad assignments (T-03-07)."""
        assignments = router.assign_triad("builder-001", "model-alpha")
        model_ids = {a.model_id for a in assignments}
        assert "model-alpha" not in model_ids

    def test_assign_triad_sequential_roles(self, router: ReviewRouter) -> None:
        """Roles are assigned sequentially: STRUCTURAL, SEMANTIC, RED_TEAM."""
        assignments = router.assign_triad("builder-001", "model-delta")
        assert assignments[0].role == ReviewerRole.STRUCTURAL
        assert assignments[1].role == ReviewerRole.SEMANTIC
        assert assignments[2].role == ReviewerRole.RED_TEAM

    def test_assign_triad_deterministic_agent_ids(self, router: ReviewRouter) -> None:
        """Agent IDs are generated deterministically from role+model (T-03-07)."""
        assignments = router.assign_triad("builder-001", "model-delta")
        for a in assignments:
            assert a.agent_id == f"reviewer-{a.role.value}-{a.model_id}"

    def test_assign_triad_insufficient_models_raises(self) -> None:
        """Raises ValueError if < 3 models available after exclusion."""
        # Roster has exactly 3, and we exclude one
        router = ReviewRouter(model_roster=["a", "b", "c"])
        with pytest.raises(ValueError, match="at least 3"):
            router.assign_triad("builder-001", "a")

    def test_assign_triad_raises_on_independence_violation(self, router: ReviewRouter) -> None:
        """Independence validator failures surface as ValueError from assign_triad.

        assign_triad deterministically generates agent_ids shaped as
        "reviewer-<role>-<model_id>". With the router fixture's roster and a
        builder on model-delta, the structural reviewer is assigned
        agent_id "reviewer-structural-model-alpha". If the builder shares that
        exact agent_id, validate_no_self_review fires and the whole triad is
        rejected (T-03-06).
        """
        with pytest.raises(ValueError, match="Independence validation failed"):
            router.assign_triad(
                builder_agent_id="reviewer-structural-model-alpha",
                builder_model_id="model-delta",
            )

    def test_assign_triad_kill_switch_blocks(self, halted_kill_switch: MagicMock) -> None:
        """Kill switch blocks triad dispatch (T-03-09)."""
        router = ReviewRouter(
            model_roster=["a", "b", "c", "d"],
            kill_switch=halted_kill_switch,
        )
        with pytest.raises(KillSwitchActiveError):
            router.assign_triad("builder-001", "d")


# ---------------------------------------------------------------------------
# ReviewRouter: assign_single
# ---------------------------------------------------------------------------


class TestAssignSingle:
    """Tests for ReviewRouter.assign_single."""

    def test_assign_single_excludes_builder(self, router: ReviewRouter) -> None:
        """Single assignment excludes builder model."""
        assignment = router.assign_single("builder-001", "model-alpha")
        assert assignment.model_id != "model-alpha"

    def test_assign_single_structural_role(self, router: ReviewRouter) -> None:
        """Single assignment uses STRUCTURAL role."""
        assignment = router.assign_single("builder-001", "model-alpha")
        assert assignment.role == ReviewerRole.STRUCTURAL

    def test_assign_single_deterministic_agent_id(self, router: ReviewRouter) -> None:
        """Single assignment has deterministic agent ID."""
        assignment = router.assign_single("builder-001", "model-alpha")
        assert assignment.agent_id == f"reviewer-structural-{assignment.model_id}"

    def test_assign_single_kill_switch_blocks(self, halted_kill_switch: MagicMock) -> None:
        """Kill switch blocks single dispatch (T-03-09)."""
        router = ReviewRouter(
            model_roster=["a", "b", "c"],
            kill_switch=halted_kill_switch,
        )
        with pytest.raises(KillSwitchActiveError):
            router.assign_single("builder-001", "a")


# ---------------------------------------------------------------------------
# ReviewRouter: assign_challenger
# ---------------------------------------------------------------------------


class TestAssignChallenger:
    """Tests for ReviewRouter.assign_challenger."""

    def test_assign_challenger_different_model(self, router: ReviewRouter) -> None:
        """Challenger uses different model than builder (EVID-03)."""
        assignment = router.assign_challenger("model-alpha")
        assert assignment.model_id != "model-alpha"

    def test_assign_challenger_red_team_role(self, router: ReviewRouter) -> None:
        """Challenger gets RED_TEAM role."""
        assignment = router.assign_challenger("model-alpha")
        assert assignment.role == ReviewerRole.RED_TEAM

    def test_assign_challenger_kill_switch_blocks(self, halted_kill_switch: MagicMock) -> None:
        """Kill switch blocks challenger dispatch (T-03-09)."""
        router = ReviewRouter(
            model_roster=["a", "b", "c"],
            kill_switch=halted_kill_switch,
        )
        with pytest.raises(KillSwitchActiveError):
            router.assign_challenger("a")


# ---------------------------------------------------------------------------
# ReviewRouter: check_unanimous_zero_findings
# ---------------------------------------------------------------------------


class TestCheckUnanimousZeroFindings:
    """Tests for ReviewRouter.check_unanimous_zero_findings."""

    def test_unanimous_zero_findings_detected(self, router: ReviewRouter) -> None:
        """Detects when all findings lists are empty (D-08, EVID-10)."""
        result = router.check_unanimous_zero_findings([[], [], []])
        assert result is True

    def test_unanimous_zero_findings_not_triggered(self, router: ReviewRouter) -> None:
        """Not triggered when at least one finding exists."""
        result = router.check_unanimous_zero_findings([[], [{"issue": "bug"}], []])
        assert result is False

    def test_all_have_findings(self, router: ReviewRouter) -> None:
        """Not triggered when all have findings."""
        result = router.check_unanimous_zero_findings([[{"issue": "a"}], [{"issue": "b"}], [{"issue": "c"}]])
        assert result is False

    def test_empty_outer_list(self, router: ReviewRouter) -> None:
        """Empty outer list (no reviewers) is not suspicious."""
        result = router.check_unanimous_zero_findings([])
        assert result is False

    def test_single_empty_findings(self, router: ReviewRouter) -> None:
        """Single reviewer with no findings is suspicious."""
        result = router.check_unanimous_zero_findings([[]])
        assert result is True


# ---------------------------------------------------------------------------
# ReviewRouter: escalate_gate_type
# ---------------------------------------------------------------------------


class TestEscalateGateType:
    """Tests for ReviewRouter.escalate_gate_type."""

    @pytest.mark.asyncio
    async def test_escalate_agent_to_hybrid(self, router_with_audit: ReviewRouter) -> None:
        """AGENT escalates to HYBRID (T-03-10)."""
        result = await router_with_audit.escalate_gate_type(GateType.AGENT, "unanimous zero findings")
        assert result == GateType.HYBRID

    @pytest.mark.asyncio
    async def test_escalate_hybrid_unchanged(self, router_with_audit: ReviewRouter) -> None:
        """HYBRID stays HYBRID -- no downgrade (T-03-10)."""
        result = await router_with_audit.escalate_gate_type(GateType.HYBRID, "test reason")
        assert result == GateType.HYBRID

    @pytest.mark.asyncio
    async def test_escalate_human_unchanged(self, router_with_audit: ReviewRouter) -> None:
        """HUMAN stays HUMAN -- never downgrades."""
        result = await router_with_audit.escalate_gate_type(GateType.HUMAN, "test reason")
        assert result == GateType.HUMAN

    @pytest.mark.asyncio
    async def test_audit_logging_on_escalation(self, router_with_audit: ReviewRouter, audit_ledger: AsyncMock) -> None:
        """Escalation logs ESCALATION event to audit ledger (T-03-08)."""
        await router_with_audit.escalate_gate_type(GateType.AGENT, "unanimous zero findings")
        audit_ledger.append_event.assert_called_once()
        call_kwargs = audit_ledger.append_event.call_args
        assert call_kwargs.kwargs["event_type"].value == "escalation"

    @pytest.mark.asyncio
    async def test_no_audit_without_ledger(self, router: ReviewRouter) -> None:
        """Escalation works without audit ledger (optional dependency)."""
        result = await router.escalate_gate_type(GateType.AGENT, "test reason")
        assert result == GateType.HYBRID


# ---------------------------------------------------------------------------
# ReviewRouter: dispatch_review (parallel execution + diversity warning)
# ---------------------------------------------------------------------------


class TestDispatchReview:
    """Tests for dispatch_review parallel execution and diversity warning."""

    @pytest.mark.asyncio
    async def test_dispatch_calls_all_assignments(self) -> None:
        """All assignments get dispatched."""
        call_count = 0

        async def mock_code_review(assignment, diff_context, manifest_context):
            nonlocal call_count
            call_count += 1
            from ces.harness.models.review_finding import ReviewResult

            return ReviewResult(
                assignment=assignment,
                review_duration_seconds=0.01,
                model_version="test-model",
            )

        executor = MagicMock()
        executor.execute_code_review = mock_code_review

        from ces.harness.services.review_executor import LLMReviewExecutor

        # Make isinstance check pass
        executor.__class__ = LLMReviewExecutor

        roster = ["model-a", "model-b", "model-c", "model-d"]
        router = ReviewRouter(model_roster=roster)
        router._review_executor = executor

        assignments = router.assign_triad("builder-1", "model-d")

        from ces.harness.services.diff_extractor import DiffContext, DiffStats

        diff = DiffContext(
            diff_text="+ test",
            files_changed=("test.py",),
            hunks=(),
            stats=DiffStats(insertions=1, deletions=0, files_changed=1),
        )

        result = await router.dispatch_review(
            assignments=assignments,
            diff_context=diff,
            manifest_context={"description": "test"},
        )

        assert call_count == 3
        assert len(result.review_results) == 3

    @pytest.mark.asyncio
    async def test_diversity_warning_when_same_model(self) -> None:
        """Warns when all reviewers use same underlying model."""

        async def mock_code_review(assignment, diff_context, manifest_context):
            from ces.harness.models.review_finding import ReviewResult

            return ReviewResult(
                assignment=assignment,
                review_duration_seconds=0.01,
                model_version="claude-same-for-all",  # Same model
            )

        executor = MagicMock()
        executor.execute_code_review = mock_code_review

        from ces.harness.services.review_executor import LLMReviewExecutor

        executor.__class__ = LLMReviewExecutor

        roster = ["model-a", "model-b", "model-c", "model-d"]
        router = ReviewRouter(model_roster=roster)
        router._review_executor = executor

        assignments = router.assign_triad("builder-1", "model-d")

        from ces.harness.services.diff_extractor import DiffContext, DiffStats

        diff = DiffContext(
            diff_text="+ test",
            files_changed=("test.py",),
            hunks=(),
            stats=DiffStats(insertions=1, deletions=0, files_changed=1),
        )

        result = await router.dispatch_review(
            assignments=assignments,
            diff_context=diff,
            manifest_context={},
        )

        # Should have diversity warning in disagreements
        assert any("diversity" in d.lower() for d in result.disagreements)

    @pytest.mark.asyncio
    async def test_dispatch_review_without_executor_raises(self, router: ReviewRouter) -> None:
        """dispatch_review raises RuntimeError when no executor is configured."""
        from ces.harness.services.diff_extractor import DiffContext, DiffStats

        assignment = ReviewAssignment(
            role=ReviewerRole.STRUCTURAL,
            model_id="model-alpha",
            agent_id="reviewer-structural-model-alpha",
        )
        diff = DiffContext(
            diff_text="",
            files_changed=(),
            hunks=(),
            stats=DiffStats(insertions=0, deletions=0, files_changed=1),
        )
        with pytest.raises(RuntimeError, match="No review executor configured"):
            await router.dispatch_review(
                assignments=[assignment],
                diff_context=diff,
                manifest_context={},
            )

    @pytest.mark.asyncio
    async def test_single_assignment_skips_diversity_check(self) -> None:
        """A single-reviewer dispatch does not trigger the diversity-warning branch."""

        async def mock_code_review(assignment, diff_context, manifest_context):
            from ces.harness.models.review_finding import ReviewResult

            return ReviewResult(
                assignment=assignment,
                review_duration_seconds=0.01,
                model_version="solo-model",
            )

        executor = MagicMock()
        executor.execute_code_review = mock_code_review
        from ces.harness.services.review_executor import LLMReviewExecutor

        executor.__class__ = LLMReviewExecutor

        router = ReviewRouter(model_roster=["model-a", "model-b", "model-c"])
        router._review_executor = executor

        from ces.harness.services.diff_extractor import DiffContext, DiffStats

        assignment = ReviewAssignment(
            role=ReviewerRole.STRUCTURAL,
            model_id="model-a",
            agent_id="reviewer-structural-model-a",
        )
        diff = DiffContext(
            diff_text="",
            files_changed=(),
            hunks=(),
            stats=DiffStats(insertions=0, deletions=0, files_changed=1),
        )

        result = await router.dispatch_review(
            assignments=[assignment],
            diff_context=diff,
            manifest_context={},
        )
        assert len(result.review_results) == 1
        assert result.degraded_model_diversity is False
        assert not any("diversity" in d.lower() for d in result.disagreements)

    @pytest.mark.asyncio
    async def test_no_diversity_warning_when_different_models(self) -> None:
        """No warning when reviewers use different models."""
        models_iter = iter(["model-v1", "model-v2", "model-v3"])

        async def mock_code_review(assignment, diff_context, manifest_context):
            from ces.harness.models.review_finding import ReviewResult

            return ReviewResult(
                assignment=assignment,
                review_duration_seconds=0.01,
                model_version=next(models_iter),
            )

        executor = MagicMock()
        executor.execute_code_review = mock_code_review

        from ces.harness.services.review_executor import LLMReviewExecutor

        executor.__class__ = LLMReviewExecutor

        roster = ["model-a", "model-b", "model-c", "model-d"]
        router = ReviewRouter(model_roster=roster)
        router._review_executor = executor

        assignments = router.assign_triad("builder-1", "model-d")

        from ces.harness.services.diff_extractor import DiffContext, DiffStats

        diff = DiffContext(
            diff_text="+ test",
            files_changed=("test.py",),
            hunks=(),
            stats=DiffStats(insertions=1, deletions=0, files_changed=1),
        )

        result = await router.dispatch_review(
            assignments=assignments,
            diff_context=diff,
            manifest_context={},
        )

        assert not any("diversity" in d.lower() for d in result.disagreements)
        assert result.degraded_model_diversity is False

    @pytest.mark.asyncio
    async def test_degraded_flag_set_when_all_models_identical(self) -> None:
        """degraded_model_diversity is True when the triad collapses to one model."""

        async def mock_code_review(assignment, diff_context, manifest_context):
            from ces.harness.models.review_finding import ReviewResult

            return ReviewResult(
                assignment=assignment,
                review_duration_seconds=0.01,
                model_version="claude-same-for-all",
            )

        executor = MagicMock()
        executor.execute_code_review = mock_code_review
        from ces.harness.services.review_executor import LLMReviewExecutor

        executor.__class__ = LLMReviewExecutor

        roster = ["model-a", "model-b", "model-c", "model-d"]
        router = ReviewRouter(model_roster=roster)
        router._review_executor = executor

        from ces.harness.services.diff_extractor import DiffContext, DiffStats

        diff = DiffContext(
            diff_text="+ test",
            files_changed=("test.py",),
            hunks=(),
            stats=DiffStats(insertions=1, deletions=0, files_changed=1),
        )

        result = await router.dispatch_review(
            assignments=router.assign_triad("builder-1", "model-d"),
            diff_context=diff,
            manifest_context={},
        )
        assert result.degraded_model_diversity is True

    @pytest.mark.asyncio
    async def test_degraded_flag_set_when_partial_diversity(self) -> None:
        """3 reviewers / 2 distinct models: degraded, even though not all-same."""
        models = iter(["mA", "mA", "mB"])

        async def mock_code_review(assignment, diff_context, manifest_context):
            from ces.harness.models.review_finding import ReviewResult

            return ReviewResult(
                assignment=assignment,
                review_duration_seconds=0.01,
                model_version=next(models),
            )

        executor = MagicMock()
        executor.execute_code_review = mock_code_review
        from ces.harness.services.review_executor import LLMReviewExecutor

        executor.__class__ = LLMReviewExecutor

        roster = ["model-a", "model-b", "model-c", "model-d"]
        router = ReviewRouter(model_roster=roster)
        router._review_executor = executor

        from ces.harness.services.diff_extractor import DiffContext, DiffStats

        diff = DiffContext(
            diff_text="+ test",
            files_changed=("test.py",),
            hunks=(),
            stats=DiffStats(insertions=1, deletions=0, files_changed=1),
        )

        result = await router.dispatch_review(
            assignments=router.assign_triad("builder-1", "model-d"),
            diff_context=diff,
            manifest_context={},
        )
        assert result.degraded_model_diversity is True
        assert any("distinct models" in d or "same model" in d for d in result.disagreements)
