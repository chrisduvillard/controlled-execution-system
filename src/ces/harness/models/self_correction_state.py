"""Self-correction state and circuit breaker models (D-10).

SelfCorrectionState tracks retry state for bounded self-correction.
CircuitBreakerState enforces hard limits on delegation depth and spawns.
"""

from __future__ import annotations

from ces.shared.base import CESBaseModel


class SelfCorrectionState(CESBaseModel):
    """State tracking for bounded self-correction loops.

    Frozen CESBaseModel: each state snapshot is immutable.
    New states are created for each retry iteration.

    Fields:
        task_id: The task being retried.
        retry_count: Number of retries consumed so far.
        max_retries: Maximum allowed retries (from manifest).
        tokens_used: Cumulative tokens consumed across retries.
        token_budget: Maximum token budget for all retries.
        current_depth: Current delegation depth.
        total_spawns: Total sub-agent spawns so far.
    """

    task_id: str
    retry_count: int = 0
    max_retries: int = 3
    tokens_used: int = 0
    token_budget: int
    current_depth: int = 0
    total_spawns: int = 0


class CircuitBreakerState(CESBaseModel):
    """Circuit breaker state for delegation limits (D-10).

    Hard limits: max 3 delegation depth, max 10 total spawns.
    Breach triggers kill switch auto-fire and audit logging.

    Frozen CESBaseModel: each state snapshot is immutable.
    """

    task_id: str
    current_depth: int = 0
    total_spawns: int = 0
    max_depth: int = 3
    max_spawns: int = 10
    tripped: bool = False
    trip_reason: str = ""

    @property
    def is_breached(self) -> bool:
        """Check if circuit breaker limits have been exceeded.

        Returns True when depth >= max_depth or spawns >= max_spawns.
        """
        return self.current_depth >= self.max_depth or self.total_spawns >= self.max_spawns
