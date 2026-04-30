"""Unit tests for TelemetryCollector and structlog telemetry_processor.

Tests cover:
- Event buffering (emit/drain/size)
- Bounded buffer (maxlen drops oldest)
- Thread safety under concurrent access
- structlog processor integration
- Module-level singleton
"""

from __future__ import annotations

import threading

import pytest


class TestTelemetryCollector:
    """Tests for the in-memory telemetry event buffer."""

    def test_emit_adds_event_to_buffer(self) -> None:
        """emit() should add an event with level, data, and timestamp."""
        from ces.observability.services.collector import TelemetryCollector

        collector = TelemetryCollector()
        collector.emit(level="task", data={"tokens_consumed": 100})

        assert collector.size() == 1

    def test_drain_returns_events_and_clears(self) -> None:
        """drain() should return all buffered events and leave buffer empty."""
        from ces.observability.services.collector import TelemetryCollector

        collector = TelemetryCollector()
        collector.emit(level="task", data={"tokens_consumed": 100})
        collector.emit(level="agent", data={"error_rate": 0.05})

        events = collector.drain()

        assert len(events) == 2
        assert events[0]["level"] == "task"
        assert events[0]["data"]["tokens_consumed"] == 100
        assert events[1]["level"] == "agent"
        assert events[1]["data"]["error_rate"] == 0.05
        assert collector.size() == 0

    def test_drain_returns_empty_list_when_no_events(self) -> None:
        """drain() on empty buffer returns empty list."""
        from ces.observability.services.collector import TelemetryCollector

        collector = TelemetryCollector()
        events = collector.drain()

        assert events == []

    def test_event_contains_timestamp(self) -> None:
        """Each buffered event should have an ISO-format timestamp."""
        from ces.observability.services.collector import TelemetryCollector

        collector = TelemetryCollector()
        collector.emit(level="system", data={"count": 1})

        events = collector.drain()
        assert "timestamp" in events[0]
        # Should be parseable as ISO format
        assert "T" in events[0]["timestamp"]

    def test_max_buffer_size_drops_oldest(self) -> None:
        """When buffer is full, oldest events should be dropped (deque maxlen)."""
        from ces.observability.services.collector import TelemetryCollector

        collector = TelemetryCollector(max_buffer_size=3)

        for i in range(5):
            collector.emit(level="task", data={"index": i})

        events = collector.drain()
        assert len(events) == 3
        # Should have the last 3 events (indices 2, 3, 4)
        assert events[0]["data"]["index"] == 2
        assert events[1]["data"]["index"] == 3
        assert events[2]["data"]["index"] == 4

    def test_size_reflects_current_count(self) -> None:
        """size() should reflect the number of buffered events."""
        from ces.observability.services.collector import TelemetryCollector

        collector = TelemetryCollector()
        assert collector.size() == 0

        collector.emit(level="task", data={"a": 1})
        assert collector.size() == 1

        collector.emit(level="agent", data={"b": 2})
        assert collector.size() == 2

        collector.drain()
        assert collector.size() == 0

    def test_thread_safety_concurrent_emit(self) -> None:
        """10 threads each emitting 100 events should result in exactly 1000 events."""
        from ces.observability.services.collector import TelemetryCollector

        collector = TelemetryCollector()
        barrier = threading.Barrier(10)

        def emit_events() -> None:
            barrier.wait()
            for i in range(100):
                collector.emit(level="task", data={"thread_event": i})

        threads = [threading.Thread(target=emit_events) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        events = collector.drain()
        assert len(events) == 1000


class TestTelemetryProcessor:
    """Tests for the structlog telemetry_processor function."""

    def test_intercepts_telemetry_marked_events(self) -> None:
        """Events with telemetry=True should be routed to the collector buffer."""
        from ces.observability.services.collector import (
            TelemetryCollector,
            telemetry_processor,
        )

        # Use a fresh collector for isolation
        collector = TelemetryCollector()
        # Patch the global collector temporarily
        import ces.observability.services.collector as mod

        original = mod._global_collector
        mod._global_collector = collector

        try:
            event_dict = {
                "event": "task completed",
                "telemetry": True,
                "level": "task",
                "tokens_consumed": 500,
                "manifest_id": "m-123",
            }
            result = telemetry_processor(None, "info", event_dict)

            # Should pass through the event (not consume it)
            assert result is event_dict

            # Should have captured it in the collector
            events = collector.drain()
            assert len(events) == 1
            assert events[0]["level"] == "task"
            assert events[0]["data"]["tokens_consumed"] == 500
            assert events[0]["data"]["manifest_id"] == "m-123"
            # Internal structlog keys should be excluded from data
            assert "event" not in events[0]["data"]
            assert "telemetry" not in events[0]["data"]
        finally:
            mod._global_collector = original

    def test_passes_non_telemetry_events_unchanged(self) -> None:
        """Events without telemetry=True should pass through unchanged."""
        from ces.observability.services.collector import (
            TelemetryCollector,
            telemetry_processor,
        )

        collector = TelemetryCollector()
        import ces.observability.services.collector as mod

        original = mod._global_collector
        mod._global_collector = collector

        try:
            event_dict = {
                "event": "normal log",
                "some_key": "some_value",
            }
            result = telemetry_processor(None, "info", event_dict)

            assert result is event_dict
            assert collector.size() == 0
        finally:
            mod._global_collector = original

    def test_telemetry_false_not_intercepted(self) -> None:
        """Events with telemetry=False should not be captured."""
        from ces.observability.services.collector import (
            TelemetryCollector,
            telemetry_processor,
        )

        collector = TelemetryCollector()
        import ces.observability.services.collector as mod

        original = mod._global_collector
        mod._global_collector = collector

        try:
            event_dict = {"event": "log", "telemetry": False}
            telemetry_processor(None, "info", event_dict)
            assert collector.size() == 0
        finally:
            mod._global_collector = original


class TestGetCollector:
    """Tests for the module-level singleton."""

    def test_returns_same_instance(self) -> None:
        """get_collector() should return the same instance across calls."""
        from ces.observability.services.collector import get_collector

        c1 = get_collector()
        c2 = get_collector()
        assert c1 is c2

    def test_returns_telemetry_collector_instance(self) -> None:
        """get_collector() should return a TelemetryCollector."""
        from ces.observability.services.collector import (
            TelemetryCollector,
            get_collector,
        )

        c = get_collector()
        assert isinstance(c, TelemetryCollector)
