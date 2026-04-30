"""Thread-safe in-memory counters for local real-time CES metrics.

TelemetryCounters provides atomic increment and snapshot-and-reset
operations for tracking high-frequency telemetry events (e.g., manifest
issuances, gate evaluations) without database round-trips.

The module-level ``get_counters()`` function returns a lazily-created
singleton suitable for use across the application.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timezone


class TelemetryCounters:
    """Thread-safe in-memory counters for telemetry events.

    All operations acquire a lock to guarantee correctness under
    concurrent access from multiple threads in local CLI execution and tests.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._last_flush: datetime = datetime.now(timezone.utc)

    def increment(self, metric_name: str, amount: int = 1) -> None:
        """Atomically increment a named counter.

        Args:
            metric_name: The counter key to increment.
            amount: Value to add (default 1).
        """
        with self._lock:
            self._counters[metric_name] += amount

    def snapshot_and_reset(self) -> dict[str, int]:
        """Atomically copy current counters and reset to empty.

        Returns:
            Dict of counter name -> accumulated value since last reset.
        """
        with self._lock:
            snapshot = dict(self._counters)
            self._counters.clear()
            self._last_flush = datetime.now(timezone.utc)
        return snapshot

    def get_current(self) -> dict[str, int]:
        """Return a copy of current counters without resetting.

        Useful for local status views that need a non-destructive read.

        Returns:
            Dict of counter name -> current accumulated value.
        """
        with self._lock:
            return dict(self._counters)

    @property
    def last_flush(self) -> datetime:
        """Timestamp of the last snapshot_and_reset call."""
        with self._lock:
            return self._last_flush


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_global_counters: TelemetryCounters | None = None
_singleton_lock = threading.Lock()


def get_counters() -> TelemetryCounters:
    """Return the global TelemetryCounters singleton (lazily created)."""
    global _global_counters  # noqa: PLW0603
    if _global_counters is None:
        with _singleton_lock:
            if _global_counters is None:
                _global_counters = TelemetryCounters()
    return _global_counters
