"""Tests for the workflow state machine and WorkflowEngine service.

Tests cover:
- Main workflow transitions: queued -> in_flight -> under_review -> approved -> merged -> deployed
- Invalid transitions raise TransitionNotAllowed (D-09)
- Rejection and failure paths with retry guards (D-12)
- Cancellation paths
- Compound review sub-states (D-10)
- Audit ledger integration (WORK-03) -- works with audit_ledger=None and with mock
- State reconstruction from persisted state (D-11)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ces.control.services.workflow_engine import (
    ReviewSubWorkflow,
    TaskWorkflow,
    WorkflowEngine,
)
from ces.shared.enums import ActorType, ReviewSubState, WorkflowState

# ---------------------------------------------------------------------------
# TaskWorkflow (state machine) -- direct tests
# ---------------------------------------------------------------------------


class TestTaskWorkflowHappyPath:
    """Test the main happy-path transition sequence."""

    def test_initial_state_is_queued(self) -> None:
        wf = TaskWorkflow()
        state_ids = {s.id for s in wf.configuration}
        assert "queued" in state_ids

    def test_queued_to_in_flight(self) -> None:
        wf = TaskWorkflow()
        wf.start()
        state_ids = {s.id for s in wf.configuration}
        assert "in_flight" in state_ids

    def test_in_flight_to_under_review(self) -> None:
        wf = TaskWorkflow()
        wf.start()
        wf.submit_for_review()
        state_ids = {s.id for s in wf.configuration}
        assert "under_review" in state_ids

    def test_under_review_to_approved(self) -> None:
        wf = TaskWorkflow()
        wf.start()
        wf.submit_for_review()
        wf.complete_review()
        state_ids = {s.id for s in wf.configuration}
        assert "approved" in state_ids

    def test_approved_to_merged(self) -> None:
        wf = TaskWorkflow()
        wf.start()
        wf.submit_for_review()
        wf.complete_review()
        wf.approve_merge()
        state_ids = {s.id for s in wf.configuration}
        assert "merged" in state_ids

    def test_merged_to_deployed(self) -> None:
        wf = TaskWorkflow()
        wf.start()
        wf.submit_for_review()
        wf.complete_review()
        wf.approve_merge()
        wf.deploy()
        state_ids = {s.id for s in wf.configuration}
        assert "deployed" in state_ids

    def test_deployed_is_final(self) -> None:
        wf = TaskWorkflow()
        wf.start()
        wf.submit_for_review()
        wf.complete_review()
        wf.approve_merge()
        wf.deploy()
        assert wf.is_terminated


class TestTaskWorkflowInvalidTransitions:
    """Test that invalid transitions raise exceptions (D-09)."""

    def test_queued_to_approved_invalid(self) -> None:
        wf = TaskWorkflow()
        with pytest.raises(Exception):
            wf.complete_review()

    def test_deployed_to_queued_invalid(self) -> None:
        wf = TaskWorkflow()
        wf.start()
        wf.submit_for_review()
        wf.complete_review()
        wf.approve_merge()
        wf.deploy()
        with pytest.raises(Exception):
            wf.start()

    def test_approved_to_in_flight_invalid(self) -> None:
        wf = TaskWorkflow()
        wf.start()
        wf.submit_for_review()
        wf.complete_review()
        with pytest.raises(Exception):
            wf.start()

    def test_merged_to_in_flight_invalid(self) -> None:
        wf = TaskWorkflow()
        wf.start()
        wf.submit_for_review()
        wf.complete_review()
        wf.approve_merge()
        with pytest.raises(Exception):
            wf.start()


class TestTaskWorkflowRejectionAndFailure:
    """Test rejection, failure, and retry paths (D-12)."""

    def test_under_review_to_rejected(self) -> None:
        wf = TaskWorkflow()
        wf.start()
        wf.submit_for_review()
        wf.reject()
        state_ids = {s.id for s in wf.configuration}
        assert "rejected" in state_ids

    def test_in_flight_to_failed(self) -> None:
        wf = TaskWorkflow()
        wf.start()
        wf.fail()
        state_ids = {s.id for s in wf.configuration}
        assert "failed" in state_ids

    def test_retry_from_rejected_succeeds_when_under_max(self) -> None:
        wf = TaskWorkflow(max_retries=3)
        wf.start()
        wf.submit_for_review()
        wf.reject()
        wf.retry_from_rejected()
        state_ids = {s.id for s in wf.configuration}
        assert "in_flight" in state_ids

    def test_retry_from_failed_succeeds_when_under_max(self) -> None:
        wf = TaskWorkflow(max_retries=3)
        wf.start()
        wf.fail()
        wf.retry_from_failed()
        state_ids = {s.id for s in wf.configuration}
        assert "in_flight" in state_ids

    def test_retry_from_rejected_blocked_when_at_max(self) -> None:
        wf = TaskWorkflow(max_retries=1)
        wf.start()
        wf.submit_for_review()
        wf.reject()
        # First retry should work
        wf.retry_from_rejected()
        # Now at retry_count=1, max_retries=1, should fail
        wf.submit_for_review()
        wf.reject()
        with pytest.raises(Exception):
            wf.retry_from_rejected()

    def test_retry_from_failed_blocked_when_at_max(self) -> None:
        wf = TaskWorkflow(max_retries=1)
        wf.start()
        wf.fail()
        # First retry works
        wf.retry_from_failed()
        # Now at retry_count=1, should block
        wf.fail()
        with pytest.raises(Exception):
            wf.retry_from_failed()

    def test_retry_increments_retry_count(self) -> None:
        wf = TaskWorkflow(max_retries=5)
        assert wf.retry_count == 0
        wf.start()
        wf.submit_for_review()
        wf.reject()
        wf.retry_from_rejected()
        assert wf.retry_count == 1
        wf.fail()
        wf.retry_from_failed()
        assert wf.retry_count == 2


class TestTaskWorkflowCancellation:
    """Test cancellation transitions."""

    def test_queued_to_cancelled(self) -> None:
        wf = TaskWorkflow()
        wf.cancel_from_queued()
        state_ids = {s.id for s in wf.configuration}
        assert "cancelled" in state_ids

    def test_in_flight_to_cancelled(self) -> None:
        wf = TaskWorkflow()
        wf.start()
        wf.cancel_from_in_flight()
        state_ids = {s.id for s in wf.configuration}
        assert "cancelled" in state_ids

    def test_cancelled_is_final(self) -> None:
        wf = TaskWorkflow()
        wf.cancel_from_queued()
        assert wf.is_terminated


# ---------------------------------------------------------------------------
# ReviewSubWorkflow (compound review sub-states) -- D-10
# ---------------------------------------------------------------------------


class TestReviewSubWorkflow:
    """Test the review sub-workflow state machine (D-10)."""

    def test_initial_state_is_pending_review(self) -> None:
        rsw = ReviewSubWorkflow()
        state_ids = {s.id for s in rsw.configuration}
        assert "pending_review" in state_ids

    def test_pending_review_to_challenger_brief(self) -> None:
        rsw = ReviewSubWorkflow()
        rsw.begin_challenge()
        state_ids = {s.id for s in rsw.configuration}
        assert "challenger_brief" in state_ids

    def test_challenger_brief_to_triage(self) -> None:
        rsw = ReviewSubWorkflow()
        rsw.begin_challenge()
        rsw.begin_triage()
        state_ids = {s.id for s in rsw.configuration}
        assert "triage" in state_ids

    def test_triage_to_decision(self) -> None:
        rsw = ReviewSubWorkflow()
        rsw.begin_challenge()
        rsw.begin_triage()
        rsw.reach_decision()
        state_ids = {s.id for s in rsw.configuration}
        assert "decision" in state_ids

    def test_decision_is_final(self) -> None:
        rsw = ReviewSubWorkflow()
        rsw.begin_challenge()
        rsw.begin_triage()
        rsw.reach_decision()
        assert rsw.is_terminated


# ---------------------------------------------------------------------------
# WorkflowEngine -- async service wrapper
# ---------------------------------------------------------------------------


class TestWorkflowEngineHappyPath:
    """Test WorkflowEngine async transition methods."""

    @pytest.mark.asyncio
    async def test_start_transitions_to_in_flight(self) -> None:
        engine = WorkflowEngine(manifest_id="test-001")
        result = await engine.start(actor="agent-1", actor_type=ActorType.AGENT)
        assert result == WorkflowState.IN_FLIGHT

    @pytest.mark.asyncio
    async def test_full_happy_path(self) -> None:
        engine = WorkflowEngine(manifest_id="test-001")
        await engine.start(actor="agent-1", actor_type=ActorType.AGENT)
        await engine.submit_for_review(actor="agent-1", actor_type=ActorType.AGENT)

        # Advance through review sub-states
        sub = await engine.begin_challenge(actor="reviewer-1", actor_type=ActorType.HUMAN)
        assert sub == ReviewSubState.CHALLENGER_BRIEF
        sub = await engine.begin_triage(actor="reviewer-1", actor_type=ActorType.HUMAN)
        assert sub == ReviewSubState.TRIAGE
        sub = await engine.reach_decision(actor="reviewer-1", actor_type=ActorType.HUMAN)
        assert sub == ReviewSubState.DECISION

        result = await engine.complete_review(actor="reviewer-1", actor_type=ActorType.HUMAN)
        assert result == WorkflowState.APPROVED

        result = await engine.approve_merge(actor="human-1", actor_type=ActorType.HUMAN)
        assert result == WorkflowState.MERGED

        result = await engine.deploy(actor="control-plane", actor_type=ActorType.CONTROL_PLANE)
        assert result == WorkflowState.DEPLOYED

    @pytest.mark.asyncio
    async def test_get_current_state(self) -> None:
        engine = WorkflowEngine(manifest_id="test-001")
        assert engine.get_current_state() == WorkflowState.QUEUED
        await engine.start(actor="a", actor_type=ActorType.AGENT)
        assert engine.get_current_state() == WorkflowState.IN_FLIGHT


class TestWorkflowEngineReviewSubStates:
    """Test review sub-state tracking in WorkflowEngine (D-10)."""

    @pytest.mark.asyncio
    async def test_under_review_starts_in_pending_review(self) -> None:
        engine = WorkflowEngine(manifest_id="test-001")
        await engine.start(actor="a", actor_type=ActorType.AGENT)
        await engine.submit_for_review(actor="a", actor_type=ActorType.AGENT)
        assert engine.get_review_sub_state() == ReviewSubState.PENDING_REVIEW

    @pytest.mark.asyncio
    async def test_review_sub_state_progression(self) -> None:
        engine = WorkflowEngine(manifest_id="test-001")
        await engine.start(actor="a", actor_type=ActorType.AGENT)
        await engine.submit_for_review(actor="a", actor_type=ActorType.AGENT)

        sub = await engine.begin_challenge(actor="r", actor_type=ActorType.HUMAN)
        assert sub == ReviewSubState.CHALLENGER_BRIEF

        sub = await engine.begin_triage(actor="r", actor_type=ActorType.HUMAN)
        assert sub == ReviewSubState.TRIAGE

        sub = await engine.reach_decision(actor="r", actor_type=ActorType.HUMAN)
        assert sub == ReviewSubState.DECISION

    @pytest.mark.asyncio
    async def test_complete_review_requires_decision_sub_state(self) -> None:
        engine = WorkflowEngine(manifest_id="test-001")
        await engine.start(actor="a", actor_type=ActorType.AGENT)
        await engine.submit_for_review(actor="a", actor_type=ActorType.AGENT)
        # Sub-state is PENDING_REVIEW, not DECISION
        with pytest.raises(ValueError, match="must be DECISION"):
            await engine.complete_review(actor="r", actor_type=ActorType.HUMAN)

    @pytest.mark.asyncio
    async def test_review_sub_state_cleared_after_complete_review(self) -> None:
        engine = WorkflowEngine(manifest_id="test-001")
        await engine.start(actor="a", actor_type=ActorType.AGENT)
        await engine.submit_for_review(actor="a", actor_type=ActorType.AGENT)
        await engine.begin_challenge(actor="r", actor_type=ActorType.HUMAN)
        await engine.begin_triage(actor="r", actor_type=ActorType.HUMAN)
        await engine.reach_decision(actor="r", actor_type=ActorType.HUMAN)
        await engine.complete_review(actor="r", actor_type=ActorType.HUMAN)
        assert engine.get_review_sub_state() is None

    @pytest.mark.asyncio
    async def test_review_sub_state_cleared_after_reject(self) -> None:
        engine = WorkflowEngine(manifest_id="test-001")
        await engine.start(actor="a", actor_type=ActorType.AGENT)
        await engine.submit_for_review(actor="a", actor_type=ActorType.AGENT)
        await engine.reject(actor="r", actor_type=ActorType.HUMAN, rationale="bad code")
        assert engine.get_review_sub_state() is None


class TestWorkflowEngineRejectionRetry:
    """Test rejection, failure, and retry via WorkflowEngine."""

    @pytest.mark.asyncio
    async def test_reject_from_under_review(self) -> None:
        engine = WorkflowEngine(manifest_id="test-001")
        await engine.start(actor="a", actor_type=ActorType.AGENT)
        await engine.submit_for_review(actor="a", actor_type=ActorType.AGENT)
        result = await engine.reject(actor="r", actor_type=ActorType.HUMAN)
        assert result == WorkflowState.REJECTED

    @pytest.mark.asyncio
    async def test_fail_from_in_flight(self) -> None:
        engine = WorkflowEngine(manifest_id="test-001")
        await engine.start(actor="a", actor_type=ActorType.AGENT)
        result = await engine.fail(actor="a", actor_type=ActorType.AGENT)
        assert result == WorkflowState.FAILED

    @pytest.mark.asyncio
    async def test_retry_from_rejected(self) -> None:
        engine = WorkflowEngine(manifest_id="test-001")
        await engine.start(actor="a", actor_type=ActorType.AGENT)
        await engine.submit_for_review(actor="a", actor_type=ActorType.AGENT)
        await engine.reject(actor="r", actor_type=ActorType.HUMAN)
        result = await engine.retry(actor="a", actor_type=ActorType.AGENT)
        assert result == WorkflowState.IN_FLIGHT

    @pytest.mark.asyncio
    async def test_retry_from_failed(self) -> None:
        engine = WorkflowEngine(manifest_id="test-001")
        await engine.start(actor="a", actor_type=ActorType.AGENT)
        await engine.fail(actor="a", actor_type=ActorType.AGENT)
        result = await engine.retry(actor="a", actor_type=ActorType.AGENT)
        assert result == WorkflowState.IN_FLIGHT

    @pytest.mark.asyncio
    async def test_retry_blocked_when_exhausted(self) -> None:
        engine = WorkflowEngine(manifest_id="test-001", max_retries=0)
        await engine.start(actor="a", actor_type=ActorType.AGENT)
        await engine.fail(actor="a", actor_type=ActorType.AGENT)
        with pytest.raises(Exception):
            await engine.retry(actor="a", actor_type=ActorType.AGENT)

    @pytest.mark.asyncio
    async def test_retry_from_invalid_state_raises(self) -> None:
        engine = WorkflowEngine(manifest_id="test-001")
        # In QUEUED state, retry is invalid
        with pytest.raises(ValueError, match="Cannot retry"):
            await engine.retry(actor="a", actor_type=ActorType.AGENT)


class TestWorkflowEngineCancellation:
    """Test cancellation via WorkflowEngine."""

    @pytest.mark.asyncio
    async def test_cancel_from_queued(self) -> None:
        engine = WorkflowEngine(manifest_id="test-001")
        result = await engine.cancel(actor="h", actor_type=ActorType.HUMAN)
        assert result == WorkflowState.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_from_in_flight(self) -> None:
        engine = WorkflowEngine(manifest_id="test-001")
        await engine.start(actor="a", actor_type=ActorType.AGENT)
        result = await engine.cancel(actor="h", actor_type=ActorType.HUMAN)
        assert result == WorkflowState.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_from_invalid_state_raises(self) -> None:
        engine = WorkflowEngine(manifest_id="test-001")
        await engine.start(actor="a", actor_type=ActorType.AGENT)
        await engine.submit_for_review(actor="a", actor_type=ActorType.AGENT)
        with pytest.raises(ValueError, match="Cannot cancel"):
            await engine.cancel(actor="h", actor_type=ActorType.HUMAN)


class TestWorkflowEngineAuditIntegration:
    """Test audit ledger integration (WORK-03)."""

    @pytest.mark.asyncio
    async def test_works_with_audit_ledger_none(self) -> None:
        """WorkflowEngine works correctly when audit_ledger=None."""
        engine = WorkflowEngine(manifest_id="test-001", audit_ledger=None)
        await engine.start(actor="a", actor_type=ActorType.AGENT)
        assert engine.get_current_state() == WorkflowState.IN_FLIGHT

    @pytest.mark.asyncio
    async def test_transition_calls_audit_record(self) -> None:
        """Every transition calls audit_ledger.record_state_transition."""
        mock_audit = AsyncMock()
        engine = WorkflowEngine(manifest_id="test-001", audit_ledger=mock_audit)
        await engine.start(actor="agent-1", actor_type=ActorType.AGENT)

        mock_audit.record_state_transition.assert_called_once_with(
            manifest_id="test-001",
            actor="agent-1",
            actor_type=ActorType.AGENT,
            from_state="queued",
            to_state="in_flight",
            rationale="",
        )

    @pytest.mark.asyncio
    async def test_multiple_transitions_all_audited(self) -> None:
        """Each transition triggers a separate audit call."""
        mock_audit = AsyncMock()
        engine = WorkflowEngine(manifest_id="test-001", audit_ledger=mock_audit)
        await engine.start(actor="a", actor_type=ActorType.AGENT)
        await engine.submit_for_review(actor="a", actor_type=ActorType.AGENT)
        assert mock_audit.record_state_transition.call_count == 2

    @pytest.mark.asyncio
    async def test_reject_passes_rationale_to_audit(self) -> None:
        mock_audit = AsyncMock()
        engine = WorkflowEngine(manifest_id="test-001", audit_ledger=mock_audit)
        await engine.start(actor="a", actor_type=ActorType.AGENT)
        await engine.submit_for_review(actor="a", actor_type=ActorType.AGENT)
        await engine.reject(actor="r", actor_type=ActorType.HUMAN, rationale="code quality")

        # Third call is the reject transition
        _, kwargs = mock_audit.record_state_transition.call_args
        assert kwargs["rationale"] == "code quality"
        assert kwargs["from_state"] == "under_review"
        assert kwargs["to_state"] == "rejected"


class TestWorkflowEnginePersistence:
    """Test state reconstruction from persisted state (D-11)."""

    @pytest.mark.asyncio
    async def test_reconstruct_from_persisted_state(self) -> None:
        """WorkflowEngine can be reconstructed from a persisted state."""
        engine = WorkflowEngine(
            manifest_id="test-001",
            initial_state="in_flight",
        )
        assert engine.get_current_state() == WorkflowState.IN_FLIGHT

    @pytest.mark.asyncio
    async def test_reconstructed_engine_can_transition(self) -> None:
        """Reconstructed engine can continue normal transitions."""
        engine = WorkflowEngine(
            manifest_id="test-001",
            initial_state="in_flight",
        )
        await engine.submit_for_review(actor="a", actor_type=ActorType.AGENT)
        assert engine.get_current_state() == WorkflowState.UNDER_REVIEW

    @pytest.mark.asyncio
    async def test_reconstruct_with_review_sub_state(self) -> None:
        """WorkflowEngine can be reconstructed with a review sub-state."""
        engine = WorkflowEngine(
            manifest_id="test-001",
            initial_state="under_review",
            initial_review_sub_state=ReviewSubState.TRIAGE,
        )
        assert engine.get_current_state() == WorkflowState.UNDER_REVIEW
        assert engine.get_review_sub_state() == ReviewSubState.TRIAGE

    @pytest.mark.asyncio
    async def test_reconstruct_with_retry_count(self) -> None:
        """WorkflowEngine can be reconstructed with an existing retry count."""
        engine = WorkflowEngine(
            manifest_id="test-001",
            initial_state="rejected",
            max_retries=3,
            retry_count=2,
        )
        assert engine.get_current_state() == WorkflowState.REJECTED
        # Should be able to retry once more
        result = await engine.retry(actor="a", actor_type=ActorType.AGENT)
        assert result == WorkflowState.IN_FLIGHT
        # Now at retry_count=3, max=3, should block
        await engine.fail(actor="a", actor_type=ActorType.AGENT)
        with pytest.raises(Exception):
            await engine.retry(actor="a", actor_type=ActorType.AGENT)


# ---------------------------------------------------------------------------
# Verification gate (P0) -- Completion Gate transitions
# ---------------------------------------------------------------------------


class TestTaskWorkflowVerificationGate:
    """Direct state machine tests for in_flight -> verifying -> {under_review,failed}."""

    def test_in_flight_to_verifying(self) -> None:
        wf = TaskWorkflow()
        wf.start()
        wf.submit_for_verification()
        state_ids = {s.id for s in wf.configuration}
        assert "verifying" in state_ids

    def test_verifying_to_under_review_on_pass(self) -> None:
        wf = TaskWorkflow()
        wf.start()
        wf.submit_for_verification()
        wf.verification_passed()
        state_ids = {s.id for s in wf.configuration}
        assert "under_review" in state_ids

    def test_verifying_to_failed_on_failure(self) -> None:
        wf = TaskWorkflow()
        wf.start()
        wf.submit_for_verification()
        wf.verification_failed()
        state_ids = {s.id for s in wf.configuration}
        assert "failed" in state_ids

    def test_legacy_submit_for_review_still_works(self) -> None:
        """Tier C / no-sensors path: skip verification, go straight to review."""
        wf = TaskWorkflow()
        wf.start()
        wf.submit_for_review()
        state_ids = {s.id for s in wf.configuration}
        assert "under_review" in state_ids

    def test_cannot_submit_for_verification_from_queued(self) -> None:
        from statemachine.exceptions import TransitionNotAllowed

        wf = TaskWorkflow()
        with pytest.raises(TransitionNotAllowed):
            wf.submit_for_verification()

    def test_cannot_submit_for_review_from_verifying(self) -> None:
        """Verification gate cannot be bypassed once entered."""
        from statemachine.exceptions import TransitionNotAllowed

        wf = TaskWorkflow()
        wf.start()
        wf.submit_for_verification()
        with pytest.raises(TransitionNotAllowed):
            wf.submit_for_review()

    def test_retry_from_verification_failed_uses_existing_guard(self) -> None:
        """A verification failure lands in `failed` and reuses retry_from_failed."""
        wf = TaskWorkflow(max_retries=2, retry_count=0)
        wf.start()
        wf.submit_for_verification()
        wf.verification_failed()
        wf.retry_from_failed()
        state_ids = {s.id for s in wf.configuration}
        assert "in_flight" in state_ids
        assert wf.retry_count == 1


class TestWorkflowEngineVerificationGate:
    """Async wrapper tests for the verification gate."""

    @pytest.mark.asyncio
    async def test_submit_for_verification_transitions(self) -> None:
        engine = WorkflowEngine(manifest_id="test-001")
        await engine.start(actor="a", actor_type=ActorType.AGENT)
        result = await engine.submit_for_verification(actor="a", actor_type=ActorType.AGENT)
        assert result == WorkflowState.VERIFYING

    @pytest.mark.asyncio
    async def test_verification_passed_advances_to_under_review(self) -> None:
        engine = WorkflowEngine(manifest_id="test-001")
        await engine.start(actor="a", actor_type=ActorType.AGENT)
        await engine.submit_for_verification(actor="a", actor_type=ActorType.AGENT)
        result = await engine.verification_passed(actor="a", actor_type=ActorType.CONTROL_PLANE)
        assert result == WorkflowState.UNDER_REVIEW
        # Sub-workflow should be initialized just like submit_for_review does
        assert engine.get_review_sub_state() == ReviewSubState.PENDING_REVIEW

    @pytest.mark.asyncio
    async def test_verification_failed_advances_to_failed(self) -> None:
        engine = WorkflowEngine(manifest_id="test-001")
        await engine.start(actor="a", actor_type=ActorType.AGENT)
        await engine.submit_for_verification(actor="a", actor_type=ActorType.AGENT)
        result = await engine.verification_failed(
            actor="a",
            actor_type=ActorType.CONTROL_PLANE,
            rationale="lint violations: 3",
        )
        assert result == WorkflowState.FAILED

    @pytest.mark.asyncio
    async def test_verification_failed_then_retry_loops_back_to_in_flight(self) -> None:
        engine = WorkflowEngine(manifest_id="test-001", max_retries=2)
        await engine.start(actor="a", actor_type=ActorType.AGENT)
        await engine.submit_for_verification(actor="a", actor_type=ActorType.AGENT)
        await engine.verification_failed(
            actor="a",
            actor_type=ActorType.CONTROL_PLANE,
            rationale="tests failing",
        )
        result = await engine.retry(actor="a", actor_type=ActorType.AGENT)
        assert result == WorkflowState.IN_FLIGHT

    @pytest.mark.asyncio
    async def test_full_happy_path_with_verification_gate(self) -> None:
        """End-to-end: queued -> in_flight -> verifying -> under_review -> ... -> deployed."""
        engine = WorkflowEngine(manifest_id="test-001")
        await engine.start(actor="a", actor_type=ActorType.AGENT)
        await engine.submit_for_verification(actor="a", actor_type=ActorType.AGENT)
        await engine.verification_passed(actor="a", actor_type=ActorType.CONTROL_PLANE)
        await engine.begin_challenge(actor="r", actor_type=ActorType.HUMAN)
        await engine.begin_triage(actor="r", actor_type=ActorType.HUMAN)
        await engine.reach_decision(actor="r", actor_type=ActorType.HUMAN)
        await engine.complete_review(actor="r", actor_type=ActorType.HUMAN)
        await engine.approve_merge(actor="h", actor_type=ActorType.HUMAN)
        result = await engine.deploy(actor="cp", actor_type=ActorType.CONTROL_PLANE)
        assert result == WorkflowState.DEPLOYED

    @pytest.mark.asyncio
    async def test_reconstruct_in_verifying_state(self) -> None:
        """WorkflowEngine can be reconstructed mid-verification."""
        engine = WorkflowEngine(manifest_id="test-001", initial_state="verifying")
        assert engine.get_current_state() == WorkflowState.VERIFYING
        result = await engine.verification_passed(actor="a", actor_type=ActorType.CONTROL_PLANE)
        assert result == WorkflowState.UNDER_REVIEW

    @pytest.mark.asyncio
    async def test_audit_records_verification_transitions(self) -> None:
        audit = MagicMock()
        audit.record_state_transition = AsyncMock()
        engine = WorkflowEngine(manifest_id="test-001", audit_ledger=audit)
        await engine.start(actor="a", actor_type=ActorType.AGENT)
        await engine.submit_for_verification(actor="a", actor_type=ActorType.AGENT)
        await engine.verification_failed(
            actor="a",
            actor_type=ActorType.CONTROL_PLANE,
            rationale="coverage 72% < 88%",
        )
        # 3 transitions: start, submit_for_verification, verification_failed
        assert audit.record_state_transition.call_count == 3
        last_call = audit.record_state_transition.call_args
        assert last_call.kwargs["from_state"] == "verifying"
        assert last_call.kwargs["to_state"] == "failed"
        assert last_call.kwargs["rationale"] == "coverage 72% < 88%"
