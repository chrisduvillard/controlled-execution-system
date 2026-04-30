"""Integration tests for the full workflow lifecycle.

Tests the state machine transitions through realistic scenarios:
- Happy path: queued -> in_flight -> under_review -> approved -> merged -> deployed
- Retry paths: failed -> retry -> in_flight, rejected -> retry -> in_flight
- Retry exhaustion: max retries reached, retry blocked
- Cancellation from queued and in_flight states
- Review sub-state progression

Uses real WorkflowEngine with in-memory AuditLedgerService (no DB).
"""

from __future__ import annotations

import pytest
from statemachine.exceptions import TransitionNotAllowed

from ces.control.services.audit_ledger import AuditLedgerService
from ces.control.services.workflow_engine import WorkflowEngine
from ces.shared.enums import ActorType, ReviewSubState, WorkflowState


@pytest.fixture()
def audit() -> AuditLedgerService:
    """Create in-memory audit ledger."""
    return AuditLedgerService(secret_key=b"test-secret-key-32-bytes-long!!!")


@pytest.fixture()
def engine(audit: AuditLedgerService) -> WorkflowEngine:
    """Create a WorkflowEngine for manifest M-TEST."""
    return WorkflowEngine(
        manifest_id="M-TEST-001",
        audit_ledger=audit,
        max_retries=3,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_full_workflow_happy_path(engine: WorkflowEngine, audit: AuditLedgerService) -> None:
    """queued -> in_flight -> under_review -> approved -> merged -> deployed."""
    assert engine.get_current_state() == WorkflowState.QUEUED

    # Start
    state = await engine.start("dev-1", ActorType.HUMAN)
    assert state == WorkflowState.IN_FLIGHT

    # Submit for review
    state = await engine.submit_for_review("dev-1", ActorType.HUMAN)
    assert state == WorkflowState.UNDER_REVIEW
    assert engine.get_review_sub_state() == ReviewSubState.PENDING_REVIEW

    # Progress through review sub-states
    sub = await engine.begin_challenge("reviewer-1", ActorType.HUMAN)
    assert sub == ReviewSubState.CHALLENGER_BRIEF

    sub = await engine.begin_triage("reviewer-1", ActorType.HUMAN)
    assert sub == ReviewSubState.TRIAGE

    sub = await engine.reach_decision("reviewer-1", ActorType.HUMAN)
    assert sub == ReviewSubState.DECISION

    # Complete review (requires DECISION sub-state)
    state = await engine.complete_review("reviewer-1", ActorType.HUMAN)
    assert state == WorkflowState.APPROVED

    # Merge
    state = await engine.approve_merge("lead-1", ActorType.HUMAN)
    assert state == WorkflowState.MERGED

    # Deploy
    state = await engine.deploy("deployer-1", ActorType.CONTROL_PLANE)
    assert state == WorkflowState.DEPLOYED

    # Verify audit chain integrity
    assert await audit.verify_integrity()


# ---------------------------------------------------------------------------
# Retry paths
# ---------------------------------------------------------------------------


async def test_retry_from_failed(audit: AuditLedgerService) -> None:
    """in_flight -> failed -> retry -> in_flight."""
    engine = WorkflowEngine(
        manifest_id="M-RETRY-FAIL",
        audit_ledger=audit,
        max_retries=3,
    )

    await engine.start("dev-1", ActorType.HUMAN)
    assert engine.get_current_state() == WorkflowState.IN_FLIGHT

    # Fail
    state = await engine.fail("agent-1", ActorType.AGENT)
    assert state == WorkflowState.FAILED

    # Retry
    state = await engine.retry("dev-1", ActorType.HUMAN)
    assert state == WorkflowState.IN_FLIGHT

    assert await audit.verify_integrity()


async def test_retry_from_rejected(audit: AuditLedgerService) -> None:
    """in_flight -> under_review -> rejected -> retry -> in_flight."""
    engine = WorkflowEngine(
        manifest_id="M-RETRY-REJECT",
        audit_ledger=audit,
        max_retries=3,
    )

    await engine.start("dev-1", ActorType.HUMAN)
    await engine.submit_for_review("dev-1", ActorType.HUMAN)

    # Reject
    state = await engine.reject("reviewer-1", ActorType.HUMAN, rationale="Needs rework")
    assert state == WorkflowState.REJECTED

    # Retry
    state = await engine.retry("dev-1", ActorType.HUMAN)
    assert state == WorkflowState.IN_FLIGHT

    assert await audit.verify_integrity()


async def test_retry_exhaustion(audit: AuditLedgerService) -> None:
    """After max retries, further retries are blocked."""
    engine = WorkflowEngine(
        manifest_id="M-EXHAUST",
        audit_ledger=audit,
        max_retries=2,  # Only 2 retries allowed
    )

    # Use up retries
    await engine.start("dev-1", ActorType.HUMAN)
    await engine.fail("agent-1", ActorType.AGENT)
    await engine.retry("dev-1", ActorType.HUMAN)  # retry 1

    await engine.fail("agent-1", ActorType.AGENT)
    await engine.retry("dev-1", ActorType.HUMAN)  # retry 2

    await engine.fail("agent-1", ActorType.AGENT)

    # Third retry should be blocked (max_retries=2)
    with pytest.raises(TransitionNotAllowed):
        await engine.retry("dev-1", ActorType.HUMAN)

    assert engine.get_current_state() == WorkflowState.FAILED


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


async def test_cancellation_from_queued(audit: AuditLedgerService) -> None:
    """Cancel from queued state."""
    engine = WorkflowEngine(
        manifest_id="M-CANCEL-Q",
        audit_ledger=audit,
    )
    assert engine.get_current_state() == WorkflowState.QUEUED

    state = await engine.cancel("dev-1", ActorType.HUMAN)
    assert state == WorkflowState.CANCELLED

    assert await audit.verify_integrity()


async def test_cancellation_from_in_flight(
    audit: AuditLedgerService,
) -> None:
    """Cancel from in_flight state."""
    engine = WorkflowEngine(
        manifest_id="M-CANCEL-IF",
        audit_ledger=audit,
    )
    await engine.start("dev-1", ActorType.HUMAN)
    assert engine.get_current_state() == WorkflowState.IN_FLIGHT

    state = await engine.cancel("dev-1", ActorType.HUMAN)
    assert state == WorkflowState.CANCELLED

    assert await audit.verify_integrity()


async def test_cancellation_blocked_from_under_review(
    audit: AuditLedgerService,
) -> None:
    """Cannot cancel from under_review state."""
    engine = WorkflowEngine(
        manifest_id="M-CANCEL-UR",
        audit_ledger=audit,
    )
    await engine.start("dev-1", ActorType.HUMAN)
    await engine.submit_for_review("dev-1", ActorType.HUMAN)

    with pytest.raises(ValueError, match="Cannot cancel"):
        await engine.cancel("dev-1", ActorType.HUMAN)


# ---------------------------------------------------------------------------
# Review sub-state enforcement
# ---------------------------------------------------------------------------


async def test_complete_review_requires_decision_substate(
    audit: AuditLedgerService,
) -> None:
    """complete_review requires the review sub-state to be DECISION."""
    engine = WorkflowEngine(
        manifest_id="M-REVIEW-GATE",
        audit_ledger=audit,
    )
    await engine.start("dev-1", ActorType.HUMAN)
    await engine.submit_for_review("dev-1", ActorType.HUMAN)

    # Try to complete review without reaching DECISION
    with pytest.raises(ValueError, match="sub-state"):
        await engine.complete_review("reviewer-1", ActorType.HUMAN)


# ---------------------------------------------------------------------------
# State reconstruction (D-11)
# ---------------------------------------------------------------------------


async def test_state_reconstruction(audit: AuditLedgerService) -> None:
    """WorkflowEngine can reconstruct from a previously persisted state (D-11)."""
    engine = WorkflowEngine(
        manifest_id="M-RECONSTRUCT",
        audit_ledger=audit,
        initial_state="in_flight",
    )
    assert engine.get_current_state() == WorkflowState.IN_FLIGHT

    # Should be able to continue from reconstructed state
    state = await engine.submit_for_review("dev-1", ActorType.HUMAN)
    assert state == WorkflowState.UNDER_REVIEW
