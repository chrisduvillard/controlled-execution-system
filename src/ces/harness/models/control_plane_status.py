"""Compatibility re-export for control-plane readiness status models."""

from __future__ import annotations

from ces.control.models.control_plane_status import ControlPlaneStatus, GovernanceState

__all__ = ["ControlPlaneStatus", "GovernanceState"]
