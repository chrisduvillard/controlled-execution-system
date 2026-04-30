"""Kill switch state model and activity class enum.

Provides:
- ActivityClass: Enum of 7 activity classes that can be independently halted (D-05).
- KillSwitchState: Frozen dataclass representing the current state of a kill switch
  for a single activity class.

Per D-05: Kill switch state stored in control.kill_switch_state DB table with one row
per activity class. KillSwitchService loads state at startup and caches in-memory.
Per D-06: Kill switch is hard-enforced -- services MUST check and respect kill state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ActivityClass(str, Enum):
    """Activity classes that can be independently halted by the kill switch.

    Per D-05, there are exactly 7 activity classes:
    - task_issuance: Issuing new tasks to agents
    - merges: Merging code changes
    - deploys: Deploying to environments
    - spawning: Spawning new agent instances
    - tool_classes: Using specific tool categories
    - truth_writes: Writing to truth artifacts
    - registry_writes: Writing to the observed legacy behavior register
    """

    TASK_ISSUANCE = "task_issuance"
    MERGES = "merges"
    DEPLOYS = "deploys"
    SPAWNING = "spawning"
    TOOL_CLASSES = "tool_classes"
    TRUTH_WRITES = "truth_writes"
    REGISTRY_WRITES = "registry_writes"


@dataclass(frozen=True)
class KillSwitchState:
    """Immutable snapshot of kill switch state for a single activity class.

    Frozen to prevent accidental mutation -- all state changes go through
    KillSwitchService which creates new instances.

    Attributes:
        activity_class: Which activity class this state governs.
        halted: Whether the activity class is currently halted.
        halted_by: Actor who activated the kill switch (None if not halted).
        halted_at: ISO timestamp when halted (None if not halted).
        reason: Reason for halting (None if not halted).
    """

    activity_class: ActivityClass
    halted: bool = False
    halted_by: str | None = None
    halted_at: str | None = None
    reason: str | None = None
