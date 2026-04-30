"""Emergency service orchestrating the hotfix path (EMERG-01 through EMERG-04).

Coordinates:
- Emergency manifest creation via EmergencyManifestFactory (EMERG-01)
- Blast radius isolation via kill switch (EMERG-02)
- SLA timer with 15-minute countdown (EMERG-03)
- Compensating controls: emergency freeze, 24h post-incident review,
  retroactive evidence packet (EMERG-04)

Single-emergency constraint: only one active emergency at a time (T-05-18).

Threat mitigations:
- T-05-16: Emergency path abuse prevented by compensating controls --
  every declaration triggers kill switch freeze, mandatory 24h review,
  and retroactive evidence requirement.
- T-05-18: _active_emergency single-emergency constraint prevents
  resource exhaustion from concurrent emergencies.
- T-05-20: Every emergency action logged to audit ledger.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ces.control.models.kill_switch_state import ActivityClass
from ces.control.models.manifest import TaskManifest
from ces.emergency.services.manifest_factory import EmergencyManifestFactory
from ces.emergency.services.sla_timer import SLATimerService
from ces.shared.enums import ActorType, EventType


class EmergencyService:
    """Service orchestrating the emergency hotfix path.

    Implements EMERG-01 through EMERG-04:
    - EMERG-01: Simplified emergency manifest via factory
    - EMERG-02: Blast radius isolation via kill switch
    - EMERG-03: 15-minute SLA timer via local deadline tracking
    - EMERG-04: Compensating controls (freeze, 24h review, evidence)

    Only one active emergency at a time (T-05-18).
    """

    def __init__(
        self,
        kill_switch: object | None = None,
        audit_ledger: object | None = None,
        sla_timer: SLATimerService | None = None,
        manifest_factory: EmergencyManifestFactory | None = None,
    ) -> None:
        """Initialize emergency service with optional dependencies.

        Args:
            kill_switch: KillSwitchService or KillSwitchProtocol for blast radius.
            audit_ledger: Any object with append_event for audit logging.
            sla_timer: SLATimerService for deadline tracking.
            manifest_factory: EmergencyManifestFactory (uses default if None).
        """
        self._kill_switch = kill_switch
        self._audit_ledger = audit_ledger
        self._sla_timer = sla_timer
        self._manifest_factory = manifest_factory or EmergencyManifestFactory()
        self._active_emergency: str | None = None

    async def declare_emergency(
        self,
        *,
        description: str,
        affected_files: list[str],
        declared_by: str,
    ) -> TaskManifest:
        """Declare an emergency and create an emergency manifest.

        EMERG-01: Creates a simplified emergency manifest.
        EMERG-02: Activates blast radius isolation via kill switch.
        EMERG-03: Starts 15-minute SLA timer.
        EMERG-04: Logs emergency freeze to audit ledger.

        Args:
            description: What the emergency fix addresses.
            affected_files: Files that may be modified.
            declared_by: Human operator declaring the emergency.

        Returns:
            The created emergency TaskManifest.

        Raises:
            ValueError: If another emergency is already active (T-05-18).
        """
        # T-05-18: Single-emergency constraint
        if self._active_emergency is not None:
            msg = f"Only one active emergency allowed at a time. Current: {self._active_emergency}"
            raise ValueError(msg)

        # EMERG-01: Create emergency manifest via factory
        now = datetime.now(timezone.utc)
        manifest = self._manifest_factory.create(
            description=description,
            affected_files=affected_files,
            declared_by=declared_by,
        )

        # EMERG-02: Blast radius isolation via kill switch
        if self._kill_switch is not None:
            await self._kill_switch.activate(  # type: ignore[attr-defined]
                activity_class=ActivityClass.TASK_ISSUANCE,
                actor=declared_by,
                reason=f"Emergency blast radius: {affected_files}",
            )

        # EMERG-03: Start SLA timer (15-minute countdown)
        if self._sla_timer is not None:
            self._sla_timer.start_timer(manifest.manifest_id, now, sla_seconds=900)

        # EMERG-04: Log emergency declaration to audit ledger
        if self._audit_ledger is not None:
            await self._audit_ledger.append_event(  # type: ignore[attr-defined]
                event_type=EventType.KILL_SWITCH,
                actor=declared_by,
                actor_type=ActorType.HUMAN,
                action_summary=(
                    f"Emergency declared: {manifest.manifest_id} - {description}. "
                    f"Affected files: {affected_files}. "
                    f"Kill switch activated for TASK_ISSUANCE (blast radius isolation)."
                ),
            )

        self._active_emergency = manifest.manifest_id
        return manifest

    async def resolve_emergency(
        self,
        *,
        manifest_id: str,
        resolved_by: str,
    ) -> None:
        """Resolve an active emergency.

        EMERG-04 compensating controls:
        1. Recover kill switch (unfreeze non-emergency work)
        2. Cancel SLA timer
        3. Log resolution to audit ledger
        4. Schedule post-incident review within 24h (ESCALATION event)
        5. Create retroactive evidence packet placeholder (CLASSIFICATION event)

        Args:
            manifest_id: The emergency manifest to resolve.
            resolved_by: Human operator resolving the emergency.

        Raises:
            ValueError: If manifest_id doesn't match active emergency.
        """
        if self._active_emergency != manifest_id:
            msg = f"Manifest {manifest_id} is not the active emergency. Active: {self._active_emergency}"
            raise ValueError(msg)

        # Recover kill switch (EMERG-02: unfreeze)
        if self._kill_switch is not None:
            await self._kill_switch.recover(  # type: ignore[attr-defined]
                activity_class=ActivityClass.TASK_ISSUANCE,
                actor=resolved_by,
                reason=f"Emergency {manifest_id} resolved",
            )

        # Cancel SLA timer
        if self._sla_timer is not None:
            self._sla_timer.cancel_timer(manifest_id)

        # EMERG-04: Compensating controls
        if self._audit_ledger is not None:
            # 1. Log resolution
            await self._audit_ledger.append_event(  # type: ignore[attr-defined]
                event_type=EventType.RECOVERY,
                actor=resolved_by,
                actor_type=ActorType.HUMAN,
                action_summary=(
                    f"Emergency {manifest_id} resolved by {resolved_by}. Kill switch recovered for TASK_ISSUANCE."
                ),
            )

            # 2. Schedule post-incident review within 24h
            await self._audit_ledger.append_event(  # type: ignore[attr-defined]
                event_type=EventType.ESCALATION,
                actor=resolved_by,
                actor_type=ActorType.HUMAN,
                action_summary=(f"Post-incident review required within 24h for emergency {manifest_id}"),
            )

            # 3. Create retroactive evidence packet placeholder
            await self._audit_ledger.append_event(  # type: ignore[attr-defined]
                event_type=EventType.CLASSIFICATION,
                actor=resolved_by,
                actor_type=ActorType.HUMAN,
                action_summary=(f"Retroactive evidence packet pending for emergency {manifest_id}"),
            )

        self._active_emergency = None

    def get_active_emergency(self) -> str | None:
        """Get the manifest ID of the active emergency.

        Returns:
            The active emergency manifest ID, or None if no active emergency.
        """
        return self._active_emergency

    def is_emergency_active(self) -> bool:
        """Check if an emergency is currently active.

        Returns:
            True if there is an active emergency, False otherwise.
        """
        return self._active_emergency is not None
