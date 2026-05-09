from ces.harness.models.control_plane_status import ControlPlaneStatus, GovernanceState
from ces.harness.services.control_plane_status import build_control_plane_status, derive_governance_state


def test_governance_disabled_is_not_configured() -> None:
    assert (
        derive_governance_state(governance_enabled=False, triage_color="red", sensor_policy_blocking=True)
        == GovernanceState.NOT_CONFIGURED
    )


def test_blocking_sensor_policy_wins_over_triage_color() -> None:
    assert (
        derive_governance_state(governance_enabled=True, triage_color="green", sensor_policy_blocking=True)
        == GovernanceState.BLOCKING_RED
    )


def test_red_triage_without_blocking_policy_is_advisory_yellow() -> None:
    assert (
        derive_governance_state(governance_enabled=True, triage_color="red", sensor_policy_blocking=False)
        == GovernanceState.ADVISORY_YELLOW
    )


def test_green_triage_without_blocking_policy_is_clear() -> None:
    assert (
        derive_governance_state(governance_enabled=True, triage_color="green", sensor_policy_blocking=False)
        == GovernanceState.CLEAR
    )


def test_build_control_plane_status_marks_auto_blockers_as_not_acceptance_verified() -> None:
    status = build_control_plane_status(
        code_completed=True,
        governance_enabled=True,
        triage_color="green",
        sensor_policy_blocking=False,
        approval_decision="approve",
        merge_allowed=True,
        auto_blockers=["independent verification failed"],
    )

    assert isinstance(status, ControlPlaneStatus)
    assert status.acceptance_verified is False
    assert status.ready_to_ship is False
    assert status.blocking_reasons == ("independent verification failed",)
