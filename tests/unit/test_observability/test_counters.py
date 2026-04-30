"""Tests for TelemetryCounters thread-safe in-memory counters.

Validates:
- increment increases counter by 1 (default) or specified amount
- snapshot_and_reset returns current counters and clears them
- get_current returns copy without resetting
- Thread safety under concurrent increments
"""

from __future__ import annotations

import threading

from ces.observability.counters import TelemetryCounters, get_counters


class TestTelemetryCounters:
    def test_increment_default(self) -> None:
        c = TelemetryCounters()
        c.increment("requests")
        snap = c.get_current()
        assert snap["requests"] == 1

    def test_increment_custom_amount(self) -> None:
        c = TelemetryCounters()
        c.increment("tokens", 5)
        snap = c.get_current()
        assert snap["tokens"] == 5

    def test_increment_accumulates(self) -> None:
        c = TelemetryCounters()
        c.increment("errors")
        c.increment("errors")
        c.increment("errors", 3)
        snap = c.get_current()
        assert snap["errors"] == 5

    def test_snapshot_and_reset_returns_data(self) -> None:
        c = TelemetryCounters()
        c.increment("a", 10)
        c.increment("b", 20)
        snap = c.snapshot_and_reset()
        assert snap == {"a": 10, "b": 20}

    def test_snapshot_and_reset_clears(self) -> None:
        c = TelemetryCounters()
        c.increment("a", 10)
        c.snapshot_and_reset()
        snap = c.get_current()
        assert snap == {}

    def test_get_current_does_not_clear(self) -> None:
        c = TelemetryCounters()
        c.increment("x", 7)
        c.get_current()
        snap = c.get_current()
        assert snap["x"] == 7

    def test_get_current_returns_copy(self) -> None:
        c = TelemetryCounters()
        c.increment("x", 1)
        snap1 = c.get_current()
        snap1["x"] = 999
        snap2 = c.get_current()
        assert snap2["x"] == 1

    def test_thread_safety(self) -> None:
        c = TelemetryCounters()
        barrier = threading.Barrier(10)

        def worker() -> None:
            barrier.wait()
            for _ in range(100):
                c.increment("counter")

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snap = c.snapshot_and_reset()
        assert snap["counter"] == 1000


class TestGetCounters:
    def test_returns_singleton(self) -> None:
        c1 = get_counters()
        c2 = get_counters()
        assert c1 is c2

    def test_is_telemetry_counters(self) -> None:
        c = get_counters()
        assert isinstance(c, TelemetryCounters)

    def test_double_check_returns_existing_singleton(self, monkeypatch) -> None:
        """If another thread sets _global_counters between the outer check and
        lock acquisition, the inner check returns the existing instance instead
        of overwriting it."""
        from ces.observability import counters as mod

        pre_existing = TelemetryCounters()
        monkeypatch.setattr(mod, "_global_counters", None)

        real_lock = threading.Lock()

        class _PrimedLock:
            def __enter__(self):
                # Simulate another thread completing init while we wait for the lock.
                mod._global_counters = pre_existing
                return real_lock.__enter__()

            def __exit__(self, *args):
                return real_lock.__exit__(*args)

        monkeypatch.setattr(mod, "_singleton_lock", _PrimedLock())

        assert mod.get_counters() is pre_existing


class TestLastFlush:
    def test_last_flush_initialized_on_construction(self) -> None:
        c = TelemetryCounters()
        # Property reads under the lock; just confirm it returns a datetime.
        from datetime import datetime

        assert isinstance(c.last_flush, datetime)

    def test_last_flush_advances_after_snapshot_and_reset(self) -> None:
        import time

        c = TelemetryCounters()
        before = c.last_flush
        time.sleep(0.001)  # ensure datetime.now ticks past `before`
        c.snapshot_and_reset()
        assert c.last_flush > before
