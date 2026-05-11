"""Shared approval and review policy helpers."""

from __future__ import annotations

from ces.harness.models.control_plane_status import ControlPlaneStatus, GovernanceState
from ces.shared.enums import GateType


def required_gate_type_for_risk(risk_tier_value: str) -> GateType:
    """Map risk tier to the required review gate type."""

    if risk_tier_value == "A":
        return GateType.HUMAN
    if risk_tier_value == "B":
        return GateType.HYBRID
    return GateType.AGENT


def persisted_governance_blocks_merge(evidence_payload: dict | None, *, merge_allowed: bool) -> bool:
    """Return True when persisted governance state is not ready to ship."""

    if not isinstance(evidence_payload, dict):
        return False
    control_status = evidence_payload.get("control_plane_status")
    if isinstance(control_status, dict):
        status_data = dict(control_status)
        governance_state = status_data.get("governance_state")
        if isinstance(governance_state, str):
            try:
                status_data["governance_state"] = GovernanceState(governance_state)
            except ValueError:
                return True
        status_data["approval_decision"] = "approve"
        status_data["merge_allowed"] = merge_allowed
        try:
            status = ControlPlaneStatus.model_validate(status_data)
        except ValueError:
            return True
        return not status.ready_to_ship
    sensor_policy = evidence_payload.get("sensor_policy")
    return isinstance(sensor_policy, dict) and bool(sensor_policy.get("blocking"))
