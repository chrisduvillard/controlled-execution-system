"""Harness Profile model (MODEL-12) - agent trust tracking.

The Harness Profile tracks an agent's trust status, completed tasks,
change class coverage, production releases, and escape history.
Used by the Trust Manager to determine promotion eligibility.

Implements TRUST-02 promotion criteria via the can_promote property.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ces.shared.enums import ChangeClass, TrustStatus


class HarnessProfile(BaseModel):
    """Agent harness profile tracking trust status and performance metrics.

    Not frozen because trust_status and metrics change over time.

    Promotion criteria (TRUST-02, via can_promote property):
    - completed_tasks >= 10
    - active_since >= 14 days ago
    - len(change_classes_covered) >= 3
    - production_releases >= 1
    """

    model_config = ConfigDict(strict=True)

    # Identity
    profile_id: str
    agent_id: str

    # Trust status
    trust_status: TrustStatus = TrustStatus.CANDIDATE

    # Task tracking
    completed_tasks: int = Field(default=0, ge=0)
    active_since: datetime | None = None
    change_classes_covered: set[ChangeClass] = set()

    # Production metrics
    production_releases: int = Field(default=0, ge=0)
    escapes: int = Field(default=0, ge=0)
    escape_history: tuple[str, ...] = ()  # References to escape events

    # Hidden check metrics
    hidden_check_pass_rate: float | None = Field(default=None, ge=0.0, le=1.0)

    # Contracts for harness components (populated by harness plane)
    guide_contract: dict[str, Any] | None = None
    sensor_contract: dict[str, Any] | None = None
    review_contract: dict[str, Any] | None = None
    merge_contract: dict[str, Any] | None = None

    @property
    def can_promote(self) -> bool:
        """Check if profile meets TRUST-02 promotion criteria.

        An agent can be promoted from CANDIDATE to TRUSTED when:
        - At least 10 tasks completed
        - Active for at least 14 days
        - Has covered at least 3 different change classes
        - Has at least 1 production release
        """
        if self.active_since is None:
            return False
        days_active = (datetime.now(timezone.utc) - self.active_since).days
        return (
            self.completed_tasks >= 10
            and days_active >= 14
            and len(self.change_classes_covered) >= 3
            and self.production_releases >= 1
        )
