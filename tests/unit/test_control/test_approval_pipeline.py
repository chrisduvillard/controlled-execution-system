"""Tests for approval pipeline policy helpers."""

from __future__ import annotations

from ces.control.services.approval_pipeline import persisted_governance_blocks_merge, required_gate_type_for_risk
from ces.shared.enums import GateType


def test_required_gate_type_for_risk_is_shared_policy() -> None:
    assert required_gate_type_for_risk("A") is GateType.HUMAN
    assert required_gate_type_for_risk("B") is GateType.HYBRID
    assert required_gate_type_for_risk("C") is GateType.AGENT


def test_persisted_governance_blocks_merge_when_sensor_policy_blocks() -> None:
    assert persisted_governance_blocks_merge({"sensor_policy": {"blocking": True}}, merge_allowed=True) is True
    assert persisted_governance_blocks_merge({"sensor_policy": {"blocking": False}}, merge_allowed=True) is False
    assert persisted_governance_blocks_merge(None, merge_allowed=True) is False


def test_persisted_governance_blocks_merge_for_control_plane_status() -> None:
    clear_status = {
        "code_completed": True,
        "acceptance_verified": True,
        "governance_state": "clear",
        "merge_not_applied": False,
        "blocking_reasons": [],
    }
    blocking_status = {
        "code_completed": True,
        "acceptance_verified": True,
        "governance_state": "blocking_red",
        "merge_not_applied": False,
        "blocking_reasons": ["sensor policy blocked"],
    }

    assert persisted_governance_blocks_merge({"control_plane_status": clear_status}, merge_allowed=True) is False
    assert persisted_governance_blocks_merge({"control_plane_status": clear_status}, merge_allowed=False) is True
    assert persisted_governance_blocks_merge({"control_plane_status": blocking_status}, merge_allowed=True) is True
    assert persisted_governance_blocks_merge({"control_plane_status": {"bad": "payload"}}, merge_allowed=True) is True
