"""Helpers for deriving explicit control-plane status from CES run signals."""

from __future__ import annotations

from typing import Iterable

from ces.harness.models.control_plane_status import ControlPlaneStatus, GovernanceState


def derive_governance_state(
    *,
    governance_enabled: bool,
    triage_color: str | None,
    sensor_policy_blocking: bool,
) -> GovernanceState:
    """Derive operator-facing governance state from triage and blocking policy."""

    if not governance_enabled:
        return GovernanceState.NOT_CONFIGURED
    if sensor_policy_blocking:
        return GovernanceState.BLOCKING_RED
    if str(triage_color or "").lower() == "red":
        return GovernanceState.ADVISORY_YELLOW
    return GovernanceState.CLEAR


def build_control_plane_status(
    *,
    code_completed: bool,
    governance_enabled: bool,
    triage_color: str | None,
    sensor_policy_blocking: bool,
    approval_decision: str | None,
    merge_allowed: bool | None,
    merge_not_applied: bool = False,
    auto_blockers: Iterable[str] | None = None,
    acceptance_verified: bool | None = None,
) -> ControlPlaneStatus:
    """Build a status object from builder workflow facts.

    ``auto_blockers`` are the existing CES automatic approval blockers. If the
    caller does not provide an explicit acceptance verdict, any blocker means
    acceptance is not verified.
    """

    blockers = tuple(str(item) for item in (auto_blockers or ()))
    resolved_acceptance_verified = not blockers if acceptance_verified is None else acceptance_verified
    return ControlPlaneStatus(
        code_completed=code_completed,
        acceptance_verified=resolved_acceptance_verified,
        governance_state=derive_governance_state(
            governance_enabled=governance_enabled,
            triage_color=triage_color,
            sensor_policy_blocking=sensor_policy_blocking,
        ),
        approval_decision=approval_decision,
        merge_allowed=merge_allowed,
        merge_not_applied=merge_not_applied,
        blocking_reasons=blockers,
    )
