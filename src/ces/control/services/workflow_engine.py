"""Workflow state machine and engine for CES task lifecycle.

Implements the main task lifecycle using python-statemachine v3:
    queued -> in_flight -> under_review -> approved -> merged -> deployed

Per D-09: Hard enforcement -- invalid transitions raise TransitionNotAllowed.
Per D-10: Compound review sub-states via separate ReviewSubWorkflow.
Per D-11: State persistence and reconstruction via start_value parameter.
Per D-12: Explicit rejected and failed states with retry guards.
Per WORK-03: Every state transition logged to audit ledger (optional dependency).

The audit ledger dependency is injected via constructor (protocol/duck typing).
Works with audit_ledger=None for standalone usage and testing.

Exports:
    TaskWorkflow: The main state machine (python-statemachine v3).
    ReviewSubWorkflow: The review sub-state machine (D-10).
    WorkflowEngine: Async service wrapper with audit integration.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from statemachine import State, StateMachine

from ces.shared.enums import ActorType, ReviewSubState, WorkflowState

# ---------------------------------------------------------------------------
# Audit ledger protocol -- accepts any object with record_state_transition
# This avoids importing AuditLedgerService from Plan 06 directly.
# ---------------------------------------------------------------------------


@runtime_checkable
class AuditLedgerProtocol(Protocol):
    """Protocol for audit ledger dependency injection.

    Any object implementing this protocol can be used as the audit_ledger
    parameter for WorkflowEngine. This decouples the workflow engine from
    the concrete AuditLedgerService implementation (Plan 06).
    """

    async def record_state_transition(
        self,
        *,
        manifest_id: str,
        actor: str,
        actor_type: ActorType,
        from_state: str,
        to_state: str,
        rationale: str,
    ) -> object: ...


# ---------------------------------------------------------------------------
# TaskWorkflow -- main lifecycle state machine
# ---------------------------------------------------------------------------


class TaskWorkflow(StateMachine):
    """Main CES task lifecycle state machine.

    States: queued, in_flight, under_review, approved, merged, deployed,
            rejected, failed, cancelled.

    Per D-09: Hard enforcement -- invalid transitions raise TransitionNotAllowed.
    Per D-12: Explicit rejected + failed states with retry guard via can_retry.

    Note: Review sub-states (D-10) are handled by a separate ReviewSubWorkflow
    composed inside WorkflowEngine, since python-statemachine v3 compound states
    would add complexity without benefit here (the sub-workflow has its own
    lifecycle independent of the main state machine).
    """

    # Main states
    queued = State(initial=True)
    in_flight = State()
    verifying = State()
    under_review = State()
    approved = State()
    merged = State()
    deployed = State(final=True)
    rejected = State()
    failed = State()
    cancelled = State(final=True)

    # Main transitions (happy path)
    start = queued.to(in_flight)
    # Legacy direct path: kept for tasks with no verification_sensors configured.
    submit_for_review = in_flight.to(under_review)
    # Completion Gate (P0): in_flight -> verifying -> {under_review, failed}.
    submit_for_verification = in_flight.to(verifying)
    verification_passed = verifying.to(under_review)
    verification_failed = verifying.to(failed)
    complete_review = under_review.to(approved)
    approve_merge = approved.to(merged)
    deploy = merged.to(deployed)

    # Rejection and failure (D-12)
    reject = under_review.to(rejected)
    fail = in_flight.to(failed)
    retry_from_rejected = rejected.to(in_flight, cond="can_retry")
    retry_from_failed = failed.to(in_flight, cond="can_retry")

    # Cancellation (from pre-execution states only)
    cancel_from_queued = queued.to(cancelled)
    cancel_from_in_flight = in_flight.to(cancelled)

    def __init__(
        self,
        max_retries: int = 3,
        retry_count: int = 0,
        start_value: str | None = None,
    ) -> None:
        self.retry_count = retry_count
        self.max_retries = max_retries
        if start_value is not None:
            super().__init__(start_value=start_value)
        else:
            super().__init__()

    def can_retry(self) -> bool:
        """Guard: only allow retry when retry_count < max_retries."""
        return self.retry_count < self.max_retries

    def on_retry_from_rejected(self) -> None:
        """Increment retry count on retry from rejected state."""
        self.retry_count += 1

    def on_retry_from_failed(self) -> None:
        """Increment retry count on retry from failed state."""
        self.retry_count += 1


# ---------------------------------------------------------------------------
# ReviewSubWorkflow -- review sub-state machine (D-10)
# ---------------------------------------------------------------------------


class ReviewSubWorkflow(StateMachine):
    """Review sub-workflow state machine (D-10).

    Sub-states: pending_review -> challenger_brief -> triage -> decision.

    The decision sub-state is final -- reaching it means the review process
    is complete and the main workflow can transition to approved.
    """

    pending_review = State(initial=True)
    challenger_brief = State()
    triage = State()
    decision = State(final=True)

    begin_challenge = pending_review.to(challenger_brief)
    begin_triage = challenger_brief.to(triage)
    reach_decision = triage.to(decision)


# ---------------------------------------------------------------------------
# WorkflowEngine -- async service wrapper
# ---------------------------------------------------------------------------


class WorkflowEngine:
    """Orchestrates workflow transitions with audit logging and persistence.

    Wraps TaskWorkflow (state machine) with:
    - Audit ledger integration (WORK-03) -- optional, works with audit_ledger=None
    - DB persistence support (D-11) via state reconstruction
    - Review sub-state tracking (D-10)

    The audit_ledger parameter accepts any object implementing
    AuditLedgerProtocol (duck typing via Protocol). Pass None to skip auditing.
    """

    def __init__(
        self,
        manifest_id: str,
        audit_ledger: AuditLedgerProtocol | None = None,
        max_retries: int = 3,
        retry_count: int = 0,
        initial_state: str | None = None,
        initial_review_sub_state: ReviewSubState | None = None,
    ) -> None:
        self.manifest_id = manifest_id
        self._audit = audit_ledger
        self._workflow = TaskWorkflow(
            max_retries=max_retries,
            retry_count=retry_count,
            start_value=initial_state,
        )
        # Review sub-workflow tracking (D-10)
        self._review_sub: ReviewSubWorkflow | None = None
        self._review_sub_state: ReviewSubState | None = None

        # If reconstructing into under_review with a sub-state
        if initial_state == "under_review" and initial_review_sub_state is not None:
            self._review_sub = ReviewSubWorkflow(
                start_value=initial_review_sub_state.value,
            )
            self._review_sub_state = initial_review_sub_state
        elif initial_state == "under_review":
            # Default to pending_review
            self._review_sub = ReviewSubWorkflow()
            self._review_sub_state = ReviewSubState.PENDING_REVIEW

    # ---- State access ----

    def get_current_state(self) -> WorkflowState:
        """Get the current main workflow state."""
        # configuration is an OrderedSet of State objects; get the top-level one
        for state in self._workflow.configuration:
            return WorkflowState(state.id)
        msg = "No active state in workflow"
        raise RuntimeError(msg)

    def get_review_sub_state(self) -> ReviewSubState | None:
        """Get the current review sub-state (only valid during under_review)."""
        return self._review_sub_state

    # ---- Audit helper ----

    async def _audit_transition(
        self,
        actor: str,
        actor_type: ActorType,
        from_state: str,
        to_state: str,
        rationale: str = "",
    ) -> None:
        """Log a state transition to the audit ledger if available."""
        if self._audit is not None:
            await self._audit.record_state_transition(
                manifest_id=self.manifest_id,
                actor=actor,
                actor_type=actor_type,
                from_state=from_state,
                to_state=to_state,
                rationale=rationale,
            )

    # ---- Main transitions ----

    async def start(self, actor: str, actor_type: ActorType) -> WorkflowState:
        """Transition: queued -> in_flight."""
        from_state = self.get_current_state().value
        self._workflow.start()
        to_state = self.get_current_state().value
        await self._audit_transition(actor, actor_type, from_state, to_state)
        return self.get_current_state()

    async def submit_for_review(self, actor: str, actor_type: ActorType) -> WorkflowState:
        """Transition: in_flight -> under_review. Initializes review sub-workflow.

        Legacy direct path used when no verification_sensors are configured on
        the manifest. Tasks with a configured Completion Gate must go through
        submit_for_verification + verification_passed instead.
        """
        from_state = self.get_current_state().value
        self._workflow.submit_for_review()
        # Initialize review sub-workflow (D-10)
        self._review_sub = ReviewSubWorkflow()
        self._review_sub_state = ReviewSubState.PENDING_REVIEW
        to_state = self.get_current_state().value
        await self._audit_transition(actor, actor_type, from_state, to_state)
        return self.get_current_state()

    async def submit_for_verification(
        self,
        actor: str,
        actor_type: ActorType,
    ) -> WorkflowState:
        """Transition: in_flight -> verifying (Completion Gate, P0)."""
        from_state = self.get_current_state().value
        self._workflow.submit_for_verification()
        to_state = self.get_current_state().value
        await self._audit_transition(actor, actor_type, from_state, to_state)
        return self.get_current_state()

    async def verification_passed(
        self,
        actor: str,
        actor_type: ActorType,
    ) -> WorkflowState:
        """Transition: verifying -> under_review. Initializes review sub-workflow."""
        from_state = self.get_current_state().value
        self._workflow.verification_passed()
        self._review_sub = ReviewSubWorkflow()
        self._review_sub_state = ReviewSubState.PENDING_REVIEW
        to_state = self.get_current_state().value
        await self._audit_transition(actor, actor_type, from_state, to_state)
        return self.get_current_state()

    async def verification_failed(
        self,
        actor: str,
        actor_type: ActorType,
        rationale: str = "",
    ) -> WorkflowState:
        """Transition: verifying -> failed. Rationale carries the failing-finding summary."""
        from_state = self.get_current_state().value
        self._workflow.verification_failed()
        to_state = self.get_current_state().value
        await self._audit_transition(actor, actor_type, from_state, to_state, rationale)
        return self.get_current_state()

    async def complete_review(self, actor: str, actor_type: ActorType) -> WorkflowState:
        """Transition: under_review -> approved (requires DECISION sub-state)."""
        if self._review_sub_state != ReviewSubState.DECISION:
            msg = f"Cannot complete review: sub-state is {self._review_sub_state}, must be DECISION"
            raise ValueError(msg)
        from_state = self.get_current_state().value
        self._workflow.complete_review()
        # Clear review sub-state
        self._review_sub = None
        self._review_sub_state = None
        to_state = self.get_current_state().value
        await self._audit_transition(actor, actor_type, from_state, to_state)
        return self.get_current_state()

    async def approve_merge(self, actor: str, actor_type: ActorType) -> WorkflowState:
        """Transition: approved -> merged."""
        from_state = self.get_current_state().value
        self._workflow.approve_merge()
        to_state = self.get_current_state().value
        await self._audit_transition(actor, actor_type, from_state, to_state)
        return self.get_current_state()

    async def deploy(self, actor: str, actor_type: ActorType) -> WorkflowState:
        """Transition: merged -> deployed."""
        from_state = self.get_current_state().value
        self._workflow.deploy()
        to_state = self.get_current_state().value
        await self._audit_transition(actor, actor_type, from_state, to_state)
        return self.get_current_state()

    # ---- Rejection and failure (D-12) ----

    async def reject(
        self,
        actor: str,
        actor_type: ActorType,
        rationale: str = "",
    ) -> WorkflowState:
        """Transition: under_review -> rejected."""
        from_state = self.get_current_state().value
        self._workflow.reject()
        # Clear review sub-state
        self._review_sub = None
        self._review_sub_state = None
        to_state = self.get_current_state().value
        await self._audit_transition(actor, actor_type, from_state, to_state, rationale)
        return self.get_current_state()

    async def fail(self, actor: str, actor_type: ActorType) -> WorkflowState:
        """Transition: in_flight -> failed."""
        from_state = self.get_current_state().value
        self._workflow.fail()
        to_state = self.get_current_state().value
        await self._audit_transition(actor, actor_type, from_state, to_state)
        return self.get_current_state()

    async def retry(self, actor: str, actor_type: ActorType) -> WorkflowState:
        """Retry from rejected or failed state.

        Guards: retry_count must be < max_retries.
        Raises ValueError if not in rejected or failed state.
        Raises TransitionNotAllowed if guard blocks the transition.
        """
        current = self.get_current_state()
        from_state = current.value
        if current == WorkflowState.REJECTED:
            self._workflow.retry_from_rejected()
        elif current == WorkflowState.FAILED:
            self._workflow.retry_from_failed()
        else:
            msg = f"Cannot retry from state: {from_state}"
            raise ValueError(msg)
        to_state = self.get_current_state().value
        await self._audit_transition(actor, actor_type, from_state, to_state)
        return self.get_current_state()

    # ---- Cancellation ----

    async def cancel(self, actor: str, actor_type: ActorType) -> WorkflowState:
        """Cancel from queued or in_flight state.

        Raises ValueError if not in a cancellable state.
        """
        current = self.get_current_state()
        from_state = current.value
        if current == WorkflowState.QUEUED:
            self._workflow.cancel_from_queued()
        elif current == WorkflowState.IN_FLIGHT:
            self._workflow.cancel_from_in_flight()
        else:
            msg = f"Cannot cancel from state: {from_state}"
            raise ValueError(msg)
        to_state = self.get_current_state().value
        await self._audit_transition(actor, actor_type, from_state, to_state)
        return self.get_current_state()

    # ---- Review sub-state transitions (D-10) ----

    async def begin_challenge(self, actor: str, actor_type: ActorType) -> ReviewSubState:
        """Advance review: pending_review -> challenger_brief."""
        if self._review_sub is None:
            msg = "Not in review state"
            raise ValueError(msg)
        self._review_sub.begin_challenge()
        self._review_sub_state = ReviewSubState.CHALLENGER_BRIEF
        return self._review_sub_state

    async def begin_triage(self, actor: str, actor_type: ActorType) -> ReviewSubState:
        """Advance review: challenger_brief -> triage."""
        if self._review_sub is None:
            msg = "Not in review state"
            raise ValueError(msg)
        self._review_sub.begin_triage()
        self._review_sub_state = ReviewSubState.TRIAGE
        return self._review_sub_state

    async def reach_decision(self, actor: str, actor_type: ActorType) -> ReviewSubState:
        """Advance review: triage -> decision."""
        if self._review_sub is None:
            msg = "Not in review state"
            raise ValueError(msg)
        self._review_sub.reach_decision()
        self._review_sub_state = ReviewSubState.DECISION
        return self._review_sub_state
