"""Protocols for emergency subsystem dependency injection.

Defines the EmergencyPathProtocol that governed services depend on
for emergency hotfix path operations.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ces.control.models.manifest import TaskManifest


@runtime_checkable
class EmergencyPathProtocol(Protocol):
    """Protocol for emergency path dependency injection.

    Any service needing to interact with the emergency hotfix path
    should depend on this protocol rather than the concrete EmergencyService.
    """

    async def declare_emergency(
        self,
        *,
        description: str,
        affected_files: list[str],
        declared_by: str,
    ) -> TaskManifest:
        """Declare an emergency and create an emergency manifest."""
        ...

    async def resolve_emergency(
        self,
        *,
        manifest_id: str,
        resolved_by: str,
    ) -> None:
        """Resolve an active emergency."""
        ...
