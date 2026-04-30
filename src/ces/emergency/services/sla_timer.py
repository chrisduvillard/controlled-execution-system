"""SLA timer service for emergency hotfix deadline enforcement (EMERG-03).

Tracks 15-minute SLA deadlines for emergency manifests using local datetime
state. The stored deadline is the source of truth.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


class SLATimerService:
    """Service for tracking emergency SLA deadlines.

    EMERG-03: 15-minute SLA tracked by local deadline state.
    """

    def __init__(self) -> None:
        """Initialize deadline tracking state."""
        self._deadlines: dict[str, datetime] = {}

    def start_timer(
        self,
        manifest_id: str,
        declared_at: datetime,
        sla_seconds: int = 900,
    ) -> str:
        """Start an SLA countdown timer for an emergency manifest.

        EMERG-03: Stores the deadline internally as the source of truth.

        Args:
            manifest_id: The emergency manifest to track.
            declared_at: When the emergency was declared.
            sla_seconds: SLA deadline in seconds (default 900 = 15 min).

        Returns:
            A local timer identifier for audit/debug visibility.
        """
        deadline = declared_at + timedelta(seconds=sla_seconds)
        self._deadlines[manifest_id] = deadline
        return f"local-{manifest_id}"

    def check_deadline(self, manifest_id: str) -> bool:
        """Check if the SLA deadline for a manifest has been breached.

        T-05-17: Uses stored datetime as the only source of truth.

        Args:
            manifest_id: The emergency manifest to check.

        Returns:
            True if deadline has passed (SLA breached), False otherwise.
            Returns False if manifest_id not tracked.
        """
        deadline = self._deadlines.get(manifest_id)
        if deadline is None:
            return False
        return datetime.now(timezone.utc) > deadline

    def cancel_timer(self, manifest_id: str) -> None:
        """Cancel an SLA timer (e.g., when emergency is resolved).

        Removes the deadline tracking.

        Args:
            manifest_id: The emergency manifest whose timer to cancel.
        """
        self._deadlines.pop(manifest_id, None)
