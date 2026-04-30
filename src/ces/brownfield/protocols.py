"""Protocols for brownfield subsystem dependency injection.

Defines the LegacyRegisterProtocol that governed services depend on
for brownfield behavior management. This decouples consumers from the
concrete LegacyBehaviorService implementation.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ces.harness.models.observed_legacy import ObservedLegacyBehavior


@runtime_checkable
class LegacyRegisterProtocol(Protocol):
    """Protocol for legacy behavior register dependency injection.

    Any service needing to interact with the brownfield legacy behavior
    register should depend on this protocol rather than the concrete
    LegacyBehaviorService.
    """

    async def register_behavior(
        self,
        *,
        system: str,
        behavior_description: str,
        inferred_by: str,
        confidence: float,
        source_manifest_id: str | None = None,
    ) -> ObservedLegacyBehavior:
        """Register a newly observed legacy behavior."""
        ...

    async def get_pending_behaviors(self) -> list[ObservedLegacyBehavior]:
        """Get all behaviors pending human disposition."""
        ...
