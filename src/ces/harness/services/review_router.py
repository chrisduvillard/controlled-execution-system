"""Review router service with single/triad dispatch and agent independence validation.

Implements:
- EVID-03: Adversarial challenger on different model than builder
- EVID-07: Agent independence validation (no self-review)
- EVID-08: Triad assignment with 3 different models for Tier A
- EVID-09: Model diversity enforcement across all reviewers
- EVID-10: Unanimous zero-findings detection with auto-escalation to HYBRID
- EVID-11: Builder model excluded from review roster
- D-05: Model roster >= 3, sequential role assignment (STRUCTURAL/SEMANTIC/RED_TEAM)
- D-06: All validation methods are static/stateless
- D-08: Unanimous zero-findings triggers AGENT -> HYBRID escalation
- T-03-06: Both model_id diversity AND agent_id != builder validated independently
- T-03-07: Builder model excluded from roster before selection; agent_ids deterministic
- T-03-08: Auto-escalation on unanimous zero; logged to audit ledger
- T-03-09: Kill switch checked before all dispatch operations
- T-03-10: Escalation only goes stricter (AGENT->HYBRID); never downgrades

Exports:
    AgentIndependenceValidator: Static validation for reviewer independence.
    ReviewRouter: Routing service for single/triad review dispatch.
    KillSwitchActiveError: Raised when dispatch is blocked by kill switch.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from typing import TYPE_CHECKING

from ces.harness.models.review_assignment import (
    IndependenceViolation,
    ReviewAssignment,
    ReviewerRole,
)
from ces.shared.enums import ActorType, EventType, GateType, RiskTier

if TYPE_CHECKING:
    from ces.control.services.kill_switch import KillSwitchProtocol
    from ces.harness.protocols import ReviewExecutorProtocol
    from ces.harness.services.diff_extractor import DiffContext
    from ces.harness.services.findings_aggregator import AggregatedReview


# ---------------------------------------------------------------------------
# AgentIndependenceValidator -- static, stateless validation (D-06)
# ---------------------------------------------------------------------------


class AgentIndependenceValidator:
    """Validates reviewer independence from the builder (D-06).

    All methods are static -- no state, fully deterministic.

    Three independent checks (T-03-06: passing one does not skip the other):
    1. No self-review: reviewer agent_id != builder agent_id
    2. Model diversity: all reviewer model_ids are unique
    3. Builder model excluded: no reviewer uses the builder's model_id
    """

    @staticmethod
    def validate_no_self_review(
        builder_agent_id: str,
        reviewer_agent_ids: list[str],
    ) -> list[IndependenceViolation]:
        """Check that no reviewer agent is the builder (EVID-07).

        Args:
            builder_agent_id: The agent ID of the builder.
            reviewer_agent_ids: List of reviewer agent IDs.

        Returns:
            List of violations. Empty if all reviewers differ from builder.
        """
        violations: list[IndependenceViolation] = []
        for agent_id in reviewer_agent_ids:
            if agent_id == builder_agent_id:
                violations.append(
                    IndependenceViolation(
                        violation_type="self_review",
                        details=f"Reviewer {agent_id} is the builder",
                    )
                )
        return violations

    @staticmethod
    def validate_model_diversity(
        assignments: list[ReviewAssignment],
    ) -> list[IndependenceViolation]:
        """Check that all reviewer models are unique (EVID-09).

        Args:
            assignments: List of review assignments to check.

        Returns:
            List of violations. Empty if all model_ids are unique.
        """
        violations: list[IndependenceViolation] = []
        model_counts: Counter[str] = Counter(a.model_id for a in assignments)
        for model_id, count in model_counts.items():
            if count > 1:
                # Find which roles use this model
                roles = [a.role.value for a in assignments if a.model_id == model_id]
                violations.append(
                    IndependenceViolation(
                        violation_type="model_duplicate",
                        details=f"Model {model_id} used by {roles}",
                    )
                )
        return violations

    @staticmethod
    def validate_builder_model_excluded(
        builder_model_id: str,
        assignments: list[ReviewAssignment],
    ) -> list[IndependenceViolation]:
        """Check that no reviewer uses the builder's model (EVID-11).

        Args:
            builder_model_id: The model ID used by the builder.
            assignments: List of review assignments to check.

        Returns:
            List of violations. Empty if no assignment uses builder's model.
        """
        violations: list[IndependenceViolation] = []
        for assignment in assignments:
            if assignment.model_id == builder_model_id:
                violations.append(
                    IndependenceViolation(
                        violation_type="builder_model_reuse",
                        details=(f"Reviewer {assignment.role.value} uses builder model {builder_model_id}"),
                    )
                )
        return violations

    @staticmethod
    def validate_all(
        builder_agent_id: str,
        builder_model_id: str,
        assignments: list[ReviewAssignment],
    ) -> list[IndependenceViolation]:
        """Run all independence checks and return combined violations (D-06).

        T-03-06: All three checks run independently -- passing one does not
        skip the other.

        Args:
            builder_agent_id: The agent ID of the builder.
            builder_model_id: The model ID used by the builder.
            assignments: List of review assignments to validate.

        Returns:
            Combined list of all violations. Empty list = valid.
        """
        violations: list[IndependenceViolation] = []

        # Check 1: No self-review
        reviewer_ids = [a.agent_id for a in assignments]
        violations.extend(AgentIndependenceValidator.validate_no_self_review(builder_agent_id, reviewer_ids))

        # Check 2: Model diversity
        violations.extend(AgentIndependenceValidator.validate_model_diversity(assignments))

        # Check 3: Builder model excluded
        violations.extend(AgentIndependenceValidator.validate_builder_model_excluded(builder_model_id, assignments))

        return violations


# ---------------------------------------------------------------------------
# KillSwitchActiveError -- raised when dispatch is blocked
# ---------------------------------------------------------------------------


class KillSwitchActiveError(RuntimeError):
    """Raised when a dispatch operation is blocked by the kill switch (T-03-09)."""


# ---------------------------------------------------------------------------
# ReviewRouter -- single/triad dispatch with escalation
# ---------------------------------------------------------------------------

# Activity class used for kill switch checks on review operations
_REVIEW_ACTIVITY_CLASS = "task_issuance"


class ReviewRouter:
    """Routes review assignments based on gate type and risk tier.

    Dispatches single reviewer for low-risk work and Adversarial Review Triad
    (3 agents, 3 models) for Tier A. Enforces agent independence and detects
    suspicious unanimous zero-findings with auto-escalation.

    Args:
        model_roster: List of available model IDs. Must have >= 3 entries (D-05).
        kill_switch: Optional kill switch for blocking dispatch (T-03-09).
        audit_ledger: Optional audit ledger for escalation logging (T-03-08).
        review_executor: Optional review executor protocol for future use.

    Raises:
        ValueError: If model_roster has fewer than 3 entries.
    """

    def __init__(
        self,
        model_roster: list[str],
        kill_switch: KillSwitchProtocol | None = None,
        audit_ledger: object | None = None,
        review_executor: ReviewExecutorProtocol | None = None,
    ) -> None:
        if len(model_roster) < 3:
            msg = f"Model roster must have at least 3 entries, got {len(model_roster)}"
            raise ValueError(msg)

        self._model_roster = model_roster
        self._kill_switch = kill_switch
        self._audit_ledger = audit_ledger
        self._review_executor = review_executor

    # ---- Kill switch guard (T-03-09) ----

    def _check_kill_switch(self) -> None:
        """Check kill switch before dispatch operations.

        Raises:
            KillSwitchActiveError: If kill switch is active for review activity.
        """
        if self._kill_switch is not None and self._kill_switch.is_halted(_REVIEW_ACTIVITY_CLASS):
            msg = "Kill switch is active for review dispatch"
            raise KillSwitchActiveError(msg)

    # ---- Review type determination ----

    def determine_review_type(
        self,
        gate_type: GateType,
        risk_tier: RiskTier,
    ) -> str:
        """Determine whether to use single or triad review (EVID-08).

        Rules:
            - Tier A always gets triad regardless of gate type
            - Non-Tier-A with any gate type gets single

        Args:
            gate_type: The gate type from gate evaluation.
            risk_tier: The risk tier classification.

        Returns:
            "triad" for Tier A, "single" otherwise.
        """
        if risk_tier == RiskTier.A:
            return "triad"
        return "single"

    # ---- Assignment methods ----

    def assign_triad(
        self,
        builder_agent_id: str,
        builder_model_id: str,
    ) -> list[ReviewAssignment]:
        """Assign 3 reviewers with different models for Adversarial Review Triad.

        Picks 3 models from roster excluding builder_model_id (T-03-07).
        Assigns STRUCTURAL/SEMANTIC/RED_TEAM roles sequentially (D-05).
        Validates independence via AgentIndependenceValidator.

        Args:
            builder_agent_id: Agent ID of the builder.
            builder_model_id: Model ID used by the builder.

        Returns:
            List of 3 ReviewAssignment objects with distinct models and roles.

        Raises:
            KillSwitchActiveError: If kill switch is active.
            ValueError: If fewer than 3 models available after excluding builder.
        """
        self._check_kill_switch()

        # Filter roster to exclude builder model (T-03-07)
        available_models = [m for m in self._model_roster if m != builder_model_id]
        if len(available_models) < 3:
            msg = (
                f"Need at least 3 models after excluding builder model "
                f"'{builder_model_id}', only {len(available_models)} available"
            )
            raise ValueError(msg)

        # Take first 3 and assign roles sequentially (D-05)
        roles = [ReviewerRole.STRUCTURAL, ReviewerRole.SEMANTIC, ReviewerRole.RED_TEAM]
        assignments: list[ReviewAssignment] = []
        for role, model_id in zip(roles, available_models[:3]):
            agent_id = f"reviewer-{role.value}-{model_id}"
            assignments.append(
                ReviewAssignment(
                    role=role,
                    model_id=model_id,
                    agent_id=agent_id,
                )
            )

        # Validate independence (T-03-06)
        violations = AgentIndependenceValidator.validate_all(builder_agent_id, builder_model_id, assignments)
        if violations:
            details = "; ".join(v.details for v in violations)
            msg = f"Independence validation failed: {details}"
            raise ValueError(msg)

        return assignments

    def assign_single(
        self,
        builder_agent_id: str,
        builder_model_id: str,
    ) -> ReviewAssignment:
        """Assign a single reviewer on a different model.

        Picks first model from roster that differs from builder's model.
        Uses STRUCTURAL role.

        Args:
            builder_agent_id: Agent ID of the builder.
            builder_model_id: Model ID used by the builder.

        Returns:
            Single ReviewAssignment with STRUCTURAL role.

        Raises:
            KillSwitchActiveError: If kill switch is active.
            ValueError: If no model available after excluding builder.
        """
        self._check_kill_switch()

        for model_id in self._model_roster:
            if model_id != builder_model_id:
                agent_id = f"reviewer-structural-{model_id}"
                return ReviewAssignment(
                    role=ReviewerRole.STRUCTURAL,
                    model_id=model_id,
                    agent_id=agent_id,
                )

        msg = f"No model available after excluding builder model '{builder_model_id}'"
        raise ValueError(msg)

    def assign_challenger(
        self,
        builder_model_id: str,
    ) -> ReviewAssignment:
        """Assign an adversarial challenger on a different model (EVID-03).

        The challenger writes counter-briefs from a different model perspective.

        Args:
            builder_model_id: Model ID used by the builder.

        Returns:
            ReviewAssignment with RED_TEAM role on a different model.

        Raises:
            KillSwitchActiveError: If kill switch is active.
            ValueError: If no model available after excluding builder.
        """
        self._check_kill_switch()

        for model_id in self._model_roster:
            if model_id != builder_model_id:
                agent_id = f"reviewer-red_team-{model_id}"
                return ReviewAssignment(
                    role=ReviewerRole.RED_TEAM,
                    model_id=model_id,
                    agent_id=agent_id,
                )

        msg = f"No model available for challenger after excluding builder model '{builder_model_id}'"
        raise ValueError(msg)

    # ---- Zero-findings detection (D-08, EVID-10) ----

    def check_unanimous_zero_findings(
        self,
        findings: list[list],
    ) -> bool:
        """Check if all reviewers reported zero findings (D-08, EVID-10).

        Unanimous zero findings is suspicious and should trigger escalation.

        Args:
            findings: List of finding lists, one per reviewer.

        Returns:
            True if all finding lists are empty (suspicious).
            False if any finding list has items, or if no reviewers.
        """
        if not findings:
            return False
        return all(len(f) == 0 for f in findings)

    # ---- Escalation (T-03-08, T-03-10) ----

    async def escalate_gate_type(
        self,
        current: GateType,
        reason: str,
    ) -> GateType:
        """Escalate gate type to a stricter level (T-03-10).

        Escalation only goes stricter: AGENT -> HYBRID.
        HYBRID and HUMAN are never downgraded.
        Logs ESCALATION event to audit ledger (T-03-08).

        Args:
            current: Current gate type to potentially escalate.
            reason: Reason for escalation (logged to audit).

        Returns:
            Escalated gate type (HYBRID if was AGENT, unchanged otherwise).
        """
        if current == GateType.AGENT:
            escalated = GateType.HYBRID
        else:
            escalated = current

        # Log escalation to audit ledger (T-03-08)
        if self._audit_ledger is not None:
            await self._audit_ledger.append_event(  # type: ignore[attr-defined]
                event_type=EventType.ESCALATION,
                actor="review_router",
                actor_type=ActorType.CONTROL_PLANE,
                action_summary=(f"Gate escalation from {current.value} to {escalated.value}: {reason}"),
                decision="escalate",
                rationale=reason,
            )

        return escalated

    # ---- Review dispatch (end-to-end execution) ----

    async def dispatch_review(
        self,
        assignments: list[ReviewAssignment],
        diff_context: DiffContext,
        manifest_context: dict[str, str],
        current_gate_type: GateType = GateType.AGENT,
    ) -> AggregatedReview:
        """Execute reviews for all assignments and aggregate findings.

        Dispatches each assignment to the review executor, collects findings,
        checks for unanimous zero-findings, and returns an aggregated result.

        Args:
            assignments: Reviewer assignments from assign_triad/assign_single.
            diff_context: Structured diff with code changes to review.
            manifest_context: Task governance context.
            current_gate_type: Current gate type for potential escalation.

        Returns:
            AggregatedReview with combined findings from all reviewers.

        Raises:
            KillSwitchActiveError: If kill switch is active.
            RuntimeError: If no review executor is configured.
        """
        self._check_kill_switch()

        if self._review_executor is None:
            msg = "No review executor configured -- cannot dispatch reviews"
            raise RuntimeError(msg)

        from ces.harness.models.review_finding import ReviewResult
        from ces.harness.services.findings_aggregator import (
            AggregatedReview,
            FindingsAggregator,
        )

        async def _run_single(assignment: ReviewAssignment) -> ReviewResult:
            if hasattr(self._review_executor, "execute_code_review"):
                return await self._review_executor.execute_code_review(
                    assignment=assignment,
                    diff_context=diff_context,
                    manifest_context=manifest_context,
                )
            # Generic protocol path
            evidence = {
                "diff_context": diff_context,
                "manifest_context": manifest_context,
            }
            raw = await self._review_executor.execute_review(
                assignment=assignment,
                evidence=evidence,
            )
            return ReviewResult(
                assignment=assignment,
                review_duration_seconds=0.0,
                **{k: v for k, v in raw.items() if k != "assignment"},
            )

        results = list(await asyncio.gather(*[_run_single(a) for a in assignments]))

        aggregated = FindingsAggregator.aggregate(results)

        # Warn when the triad has fewer distinct underlying models than the
        # number of assignments. Tier A policy (PRD §3) requires three
        # different models for adversarial diversity; running the same model
        # three times silently undermines that guarantee. We mark the
        # aggregated review as ``degraded_model_diversity`` so downstream
        # consumers (evidence synthesizer, approval gate) can surface it
        # rather than silently trusting the degraded result.
        degraded_model_diversity = aggregated.degraded_model_diversity
        if len(results) > 1:
            model_versions = {r.model_version for r in results if r.model_version}
            if len(model_versions) < len(results):
                degraded_model_diversity = True
                if len(model_versions) == 1:
                    single_model = next(iter(model_versions))
                    logging.getLogger(__name__).warning(
                        "All %d reviewers used same model (%s) — adversarial diversity limited",
                        len(results),
                        single_model,
                    )
                    diversity_warning = (
                        f"All {len(results)} reviewers used same model ({single_model}) — adversarial diversity limited"
                    )
                else:
                    logging.getLogger(__name__).warning(
                        "%d reviewers resolved to only %d distinct models — adversarial diversity limited",
                        len(results),
                        len(model_versions),
                    )
                    diversity_warning = (
                        f"{len(results)} reviewers resolved to only "
                        f"{len(model_versions)} distinct models — adversarial diversity limited"
                    )
                aggregated = AggregatedReview(
                    review_results=aggregated.review_results,
                    all_findings=aggregated.all_findings,
                    critical_count=aggregated.critical_count,
                    high_count=aggregated.high_count,
                    disagreements=(*aggregated.disagreements, diversity_warning),
                    unanimous_zero_findings=aggregated.unanimous_zero_findings,
                    degraded_model_diversity=True,
                )
            elif degraded_model_diversity:
                aggregated = aggregated.model_copy(update={"degraded_model_diversity": True})

        # Check for suspicious unanimous zero findings (D-08, EVID-10)
        if aggregated.unanimous_zero_findings:
            await self.escalate_gate_type(
                current=current_gate_type,
                reason="Unanimous zero findings from all reviewers",
            )

        return aggregated
