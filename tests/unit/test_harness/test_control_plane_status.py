from ces.harness.models.control_plane_status import ControlPlaneStatus, GovernanceState


def test_ready_to_ship_requires_governance_clear() -> None:
    status = ControlPlaneStatus(
        code_completed=True,
        acceptance_verified=True,
        governance_state=GovernanceState.BLOCKING_RED,
        approval_decision="approve",
        merge_allowed=True,
    )

    assert status.ready_to_ship is False
    assert status.needs_review is True
    assert status.summary_outcome == "approved, but governance is blocked"


def test_ready_to_ship_when_all_gates_clear() -> None:
    status = ControlPlaneStatus(
        code_completed=True,
        acceptance_verified=True,
        governance_state=GovernanceState.CLEAR,
        approval_decision="approve",
        merge_allowed=True,
    )

    assert status.ready_to_ship is True
    assert status.needs_review is False
    assert status.summary_outcome == "ready to ship"


def test_ready_to_ship_without_merge_controller_when_all_gates_clear() -> None:
    status = ControlPlaneStatus(
        code_completed=True,
        acceptance_verified=True,
        governance_state=GovernanceState.CLEAR,
        approval_decision="approve",
        merge_allowed=None,
    )

    assert status.ready_to_ship is True
    assert status.summary_outcome == "ready to ship"


def test_merge_not_applied_is_not_ready_to_ship_but_is_soft_outcome() -> None:
    status = ControlPlaneStatus(
        code_completed=True,
        acceptance_verified=True,
        governance_state=GovernanceState.CLEAR,
        approval_decision="approve",
        merge_allowed=False,
        merge_not_applied=True,
    )

    assert status.ready_to_ship is False
    assert status.needs_review is True
    assert status.summary_outcome == "approved, but merge was not applied"


def test_blocking_reasons_prevent_ready_to_ship() -> None:
    status = ControlPlaneStatus(
        code_completed=True,
        acceptance_verified=True,
        governance_state=GovernanceState.CLEAR,
        approval_decision="approve",
        merge_allowed=True,
        blocking_reasons=["workspace changes exceeded manifest scope"],
    )

    assert status.ready_to_ship is False
    assert status.needs_review is True
    assert status.summary_outcome == "approved, but blocking issues remain"


def test_blocking_reasons_are_preserved_as_tuple() -> None:
    status = ControlPlaneStatus(
        code_completed=True,
        acceptance_verified=False,
        governance_state=GovernanceState.CLEAR,
        approval_decision="approve",
        merge_allowed=True,
        blocking_reasons=["independent verification failed"],
    )

    assert status.blocking_reasons == ("independent verification failed",)
    assert status.summary_outcome == "approved, but acceptance verification is blocked"
