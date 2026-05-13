"""In-memory telemetry event buffer with structlog processor integration.

Provides:
- TelemetryCollector: Thread-safe bounded buffer for telemetry events
- get_collector: Module-level singleton accessor
- telemetry_processor: structlog processor that intercepts telemetry-marked events

The collector captures events emitted by application code via structlog and
holds them in memory for local status inspection and tests. The buffer uses a
bounded deque to prevent memory exhaustion (T-11-06).
"""

from __future__ import annotations

import collections
import threading
from datetime import datetime, timezone
from typing import Any


class TelemetryCollector:
    """In-memory telemetry event buffer with bounded size.

    Uses a ``collections.deque`` with ``maxlen`` to automatically drop
    the oldest events when the buffer is full, preventing unbounded
    memory growth (threat T-11-06).

    Thread-safe: all operations acquire a lock for correctness under
    concurrent access from multiple threads.
    """

    def __init__(self, max_buffer_size: int = 10000) -> None:
        self._lock = threading.Lock()
        self._buffer: collections.deque[dict[str, Any]] = collections.deque(maxlen=max_buffer_size)

    def emit(self, level: str, data: dict[str, Any]) -> None:
        """Add a telemetry event to the buffer.

        Args:
            level: One of "task", "agent", "harness", "control_plane", "system".
            data: Dict of metric key-value pairs.
        """
        with self._lock:
            self._buffer.append(
                {
                    "level": level,
                    "data": data,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

    def drain(self) -> list[dict[str, Any]]:
        """Atomically drain all events from buffer.

        Returns:
            List of all buffered events. Buffer is empty after this call.
        """
        with self._lock:
            events = list(self._buffer)
            self._buffer.clear()
            return events

    def size(self) -> int:
        """Return the number of events currently in the buffer."""
        with self._lock:
            return len(self._buffer)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_global_collector: TelemetryCollector | None = None
_singleton_lock = threading.Lock()


def get_collector() -> TelemetryCollector:
    """Return the global TelemetryCollector singleton (lazily created)."""
    global _global_collector  # noqa: PLW0603
    if _global_collector is None:
        with _singleton_lock:
            if _global_collector is None:
                _global_collector = TelemetryCollector()
    return _global_collector


# ---------------------------------------------------------------------------
# structlog processor
# ---------------------------------------------------------------------------

# Keys that belong to structlog internals and should NOT be forwarded
# as metric data to the telemetry buffer.
_EXCLUDE_KEYS = frozenset({"event", "telemetry", "level", "logger", "log_level", "timestamp", "_record"})


def telemetry_processor(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Structlog processor that intercepts telemetry-marked events.

    If ``event_dict`` contains ``telemetry=True``, routes the event to the
    global collector buffer. The event is still passed through to normal
    logging so it can appear in log output.

    Args:
        logger: The wrapped logger (unused).
        method_name: The method name called on the logger (unused).
        event_dict: The event dictionary being processed.

    Returns:
        The event_dict unchanged (pass-through for downstream processors).
    """
    del logger, method_name
    if event_dict.get("telemetry") is True:
        level = event_dict.get("level", "unknown")
        # Extract metric data: everything except structlog internal keys
        data = {k: v for k, v in event_dict.items() if k not in _EXCLUDE_KEYS}
        get_collector().emit(level=level, data=data)
    return event_dict
