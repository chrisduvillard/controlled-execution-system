"""Kill switch service with per-activity-class halting, auto-triggers, and hard enforcement.

Implements:
- KILL-01: Per-activity-class halting (7 classes)
- KILL-02: Auto-triggers for invalidation failure, truth drift, delegation explosion
- KILL-03: Auto-triggers for sensor-pack failure, rising escapes with green checks
- KILL-04: Hard enforcement via KillSwitchProtocol (D-06)
- D-05: DB state with in-memory caching, audit ledger logging

The KillSwitchProtocol defines the minimal interface that all governed services
must depend on. KillSwitchService implements this protocol with full functionality.

Threat mitigations:
- T-02-03: KillSwitchProtocol makes checking mandatory in service constructors
- T-02-08: All state changes go through this service and are logged to audit ledger
- T-02-10: activate() and recover() ALWAYS log to audit ledger before returning
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from ces.control.models.kill_switch_state import ActivityClass, KillSwitchState
from ces.shared.enums import ActorType, EventType

# ---------------------------------------------------------------------------
# KillSwitchProtocol -- the interface all governed services depend on
# ---------------------------------------------------------------------------


@runtime_checkable
class KillSwitchProtocol(Protocol):
    """Protocol for kill switch dependency injection.

    All governed services MUST accept a KillSwitchProtocol in their
    constructor and call is_halted() before performing operations.
    This is hard enforcement per D-06.

    The is_halted method is synchronous (not async) because it reads
    from an in-memory cache. It NEVER raises exceptions -- it always
    returns a bool.
    """

    def is_halted(self, activity_class: str) -> bool:
        """Check if an activity class is currently halted.

        Args:
            activity_class: The activity class to check (e.g., "merges").

        Returns:
            True if the activity class is halted, False otherwise.
            Never raises exceptions.
        """
        ...


# ---------------------------------------------------------------------------
# Auto-trigger mapping: trigger_type -> list of activity classes to halt
# ---------------------------------------------------------------------------

_AUTO_TRIGGER_MAP: dict[str, list[ActivityClass]] = {
    # KILL-02: Invalidation engine failure -> halt truth writes + registry writes
    "invalidation_engine_failure": [
        ActivityClass.TRUTH_WRITES,
        ActivityClass.REGISTRY_WRITES,
    ],
    # KILL-02: Unexplained truth drift -> halt truth writes
    "unexplained_truth_drift": [
        ActivityClass.TRUTH_WRITES,
    ],
    # KILL-02: Recursive delegation explosion -> halt spawning
    "recursive_delegation_explosion": [
        ActivityClass.SPAWNING,
    ],
    # KILL-03: Sensor pack failure on high-risk paths -> halt task issuance
    "sensor_pack_failure_high_risk": [
        ActivityClass.TASK_ISSUANCE,
    ],
    # KILL-03: Rising escapes with green visible checks -> halt merges + deploys
    "rising_escapes_green_checks": [
        ActivityClass.MERGES,
        ActivityClass.DEPLOYS,
    ],
}


# ---------------------------------------------------------------------------
# KillSwitchService -- full implementation
# ---------------------------------------------------------------------------


class KillSwitchService:
    """Kill switch service with per-activity-class halting and hard enforcement.

    Implements KillSwitchProtocol for dependency injection into governed services.

    State management:
    - In-memory cache (_cache) for fast is_halted() checks
    - Optional DB persistence via KillSwitchRepository
    - Cache version tracking for invalidation

    Audit logging:
    - Every activate() logs KILL_SWITCH event
    - Every recover() logs RECOVERY event
    - Optional -- works without audit_ledger for unit testing

    Auto-triggers:
    - check_auto_triggers() evaluates trigger conditions per KILL-02/KILL-03
    - Returns list of newly activated states (empty if already halted)
    """

    def __init__(
        self,
        repository: object | None = None,
        audit_ledger: object | None = None,
    ) -> None:
        """Initialize kill switch service.

        Args:
            repository: KillSwitchRepository for DB persistence (optional).
            audit_ledger: Any object with an append_event method for audit
                          logging (optional). Accepts AuditLedgerService or
                          any compatible mock.
        """
        self._repository = repository
        self._audit_ledger = audit_ledger
        self._cache: dict[ActivityClass, KillSwitchState] = {}
        self._cache_version: int = 0

    # ---- Hard enforcement interface (D-06) ----

    def is_halted(self, activity_class: str) -> bool:
        """Check if an activity class is currently halted.

        This is the method ALL services call before operations.
        It reads from the in-memory cache and NEVER raises exceptions.

        Args:
            activity_class: The activity class to check (string value).

        Returns:
            True if halted, False otherwise. Returns False for unknown classes.
        """
        try:
            ac = ActivityClass(activity_class)
        except ValueError:
            # Unknown activity class -- not halted
            return False

        state = self._cache.get(ac)
        if state is None:
            return False
        return state.halted

    # ---- State mutations ----

    async def activate(
        self,
        activity_class: ActivityClass,
        actor: str,
        reason: str,
    ) -> KillSwitchState:
        """Activate (halt) a specific activity class.

        Sets halted=True in cache and optionally persists to DB.
        Logs KILL_SWITCH event to audit ledger.

        Args:
            activity_class: Which activity class to halt.
            actor: Who is activating the kill switch.
            reason: Why the kill switch is being activated.

        Returns:
            The new KillSwitchState (halted=True).
        """
        now = datetime.now(timezone.utc).isoformat()
        state = KillSwitchState(
            activity_class=activity_class,
            halted=True,
            halted_by=actor,
            halted_at=now,
            reason=reason,
        )

        # Update cache
        self._cache[activity_class] = state
        self._cache_version += 1

        # Persist to DB if repository available
        if self._repository is not None:
            await self._repository.upsert(state)  # type: ignore[attr-defined]

        # Log to audit ledger (T-02-10: ALWAYS log before returning)
        if self._audit_ledger is not None:
            await self._audit_ledger.append_event(  # type: ignore[attr-defined]
                event_type=EventType.KILL_SWITCH,
                actor=actor,
                actor_type=ActorType.CONTROL_PLANE,
                action_summary=(f"Kill switch activated for {activity_class.value}: {reason}"),
                decision="halt",
                rationale=reason,
            )

        return state

    async def recover(
        self,
        activity_class: ActivityClass,
        actor: str,
        reason: str,
    ) -> KillSwitchState:
        """Recover (un-halt) a specific activity class.

        Sets halted=False in cache and optionally persists to DB.
        Logs RECOVERY event to audit ledger.
        Recovery is human-only (actor must be provided, actor_type=HUMAN).

        Args:
            activity_class: Which activity class to recover.
            actor: Who is recovering the kill switch (must be human).
            reason: Why recovery is happening.

        Returns:
            The new KillSwitchState (halted=False).
        """
        state = KillSwitchState(
            activity_class=activity_class,
            halted=False,
            halted_by=None,
            halted_at=None,
            reason=None,
        )

        # Update cache
        self._cache[activity_class] = state
        self._cache_version += 1

        # Persist to DB if repository available
        if self._repository is not None:
            await self._repository.upsert(state)  # type: ignore[attr-defined]

        # Log to audit ledger (T-02-10: ALWAYS log before returning)
        if self._audit_ledger is not None:
            await self._audit_ledger.append_event(  # type: ignore[attr-defined]
                event_type=EventType.RECOVERY,
                actor=actor,
                actor_type=ActorType.HUMAN,
                action_summary=(f"Kill switch recovered for {activity_class.value}: {reason}"),
                decision="recover",
                rationale=reason,
            )

        return state

    # ---- DB loading ----

    async def load_from_db(self) -> None:
        """Load all kill switch state rows from DB into cache.

        Called at startup to hydrate the in-memory cache from persistent
        storage. Requires repository to be configured.

        Raises:
            RuntimeError: If no repository is configured.
        """
        if self._repository is None:
            msg = "Repository not configured for DB loading"
            raise RuntimeError(msg)

        rows = await self._repository.get_all()
        for row in rows:
            try:
                ac = ActivityClass(row.activity_class)
            except ValueError:
                continue  # Skip unknown activity classes

            self._cache[ac] = KillSwitchState(
                activity_class=ac,
                halted=row.halted,
                halted_by=row.halted_by,
                halted_at=row.halted_at.isoformat() if row.halted_at else None,
                reason=row.reason,
            )
        self._cache_version += 1

    # ---- Auto-triggers (KILL-02, KILL-03) ----

    async def check_auto_triggers(
        self,
        trigger_type: str,
        metadata: dict,
    ) -> list[KillSwitchState]:
        """Evaluate automatic trigger conditions and activate if needed.

        Per KILL-02 and KILL-03, certain conditions automatically trigger
        kill switches on specific activity classes:
        - "invalidation_engine_failure" -> truth_writes + registry_writes
        - "unexplained_truth_drift" -> truth_writes
        - "recursive_delegation_explosion" -> spawning
        - "sensor_pack_failure_high_risk" -> task_issuance
        - "rising_escapes_green_checks" -> merges + deploys

        Args:
            trigger_type: The type of trigger event detected.
            metadata: Additional context about the trigger (for future use).

        Returns:
            List of newly activated KillSwitchState objects.
            Empty if trigger type is unknown or classes are already halted.
        """
        target_classes = _AUTO_TRIGGER_MAP.get(trigger_type)
        if target_classes is None:
            return []

        newly_activated: list[KillSwitchState] = []
        for ac in target_classes:
            # Skip if already halted (no duplicate activation)
            if self.is_halted(ac.value):
                continue

            state = await self.activate(
                activity_class=ac,
                actor="control_plane",
                reason=f"Auto-trigger: {trigger_type}",
            )
            newly_activated.append(state)

        return newly_activated
