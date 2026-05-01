"""Tests for OTel metrics bridge: observable gauge callbacks and custom CES metrics.

Tests verify that:
- observe_telemetry_counters() reads TelemetryCounters and yields OTel Observations
- observe_queue_depths() filters queue-related counters
- observe_active_agents() extracts active agent count
- register_ces_metrics() creates all expected OTel instruments
- CESMetrics dataclass provides access to counter and histogram instruments
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest
from opentelemetry.metrics import CallbackOptions, Observation

from ces.observability.counters import get_counters


@pytest.fixture(autouse=True)
def _reset_counters() -> Generator[None, None, None]:
    """Reset TelemetryCounters between tests to avoid state leakage."""
    get_counters().snapshot_and_reset()
    yield
    get_counters().snapshot_and_reset()


class TestObserveTelemetryCounters:
    """Tests for the observe_telemetry_counters callback."""

    def test_yields_observation_per_counter(self) -> None:
        """Each counter entry becomes an Observation with metric_name attribute."""
        from ces.observability.metrics_bridge import observe_telemetry_counters

        get_counters().increment("manifest_issued", 42)
        get_counters().increment("gate_evaluated", 7)

        observations = list(observe_telemetry_counters(CallbackOptions()))

        assert len(observations) == 2
        # Build a lookup by metric_name attribute
        by_name = {obs.attributes["ces.metric_name"]: obs.value for obs in observations}
        assert by_name["manifest_issued"] == 42
        assert by_name["gate_evaluated"] == 7

    def test_yields_zero_observations_when_empty(self) -> None:
        """Empty counters yield no observations."""
        from ces.observability.metrics_bridge import observe_telemetry_counters

        observations = list(observe_telemetry_counters(CallbackOptions()))
        assert observations == []

    def test_observation_values_are_correct(self) -> None:
        """Observation value matches counter value exactly."""
        from ces.observability.metrics_bridge import observe_telemetry_counters

        get_counters().increment("test_metric", 100)

        observations = list(observe_telemetry_counters(CallbackOptions()))
        assert len(observations) == 1
        assert observations[0].value == 100
        assert observations[0].attributes["ces.metric_name"] == "test_metric"


class TestObserveQueueDepths:
    """Tests for the observe_queue_depths callback."""

    def test_filters_queue_depth_keys(self) -> None:
        """Only counters with 'queue_depth_' prefix are yielded."""
        from ces.observability.metrics_bridge import observe_queue_depths

        get_counters().increment("queue_depth_merge", 3)
        get_counters().increment("queue_depth_approval", 5)
        get_counters().increment("manifest_issued", 10)  # should be ignored

        observations = list(observe_queue_depths(CallbackOptions()))

        assert len(observations) == 2
        by_name = {obs.attributes["ces.queue_name"]: obs.value for obs in observations}
        assert by_name["merge"] == 3
        assert by_name["approval"] == 5

    def test_empty_when_no_queue_counters(self) -> None:
        """No observations when no queue_depth_ counters exist."""
        from ces.observability.metrics_bridge import observe_queue_depths

        get_counters().increment("manifest_issued", 10)

        observations = list(observe_queue_depths(CallbackOptions()))
        assert observations == []


class TestObserveActiveAgents:
    """Tests for the observe_active_agents callback."""

    def test_yields_active_agent_count(self) -> None:
        """Yields single Observation for active_agent_count key."""
        from ces.observability.metrics_bridge import observe_active_agents

        get_counters().increment("active_agent_count", 4)

        observations = list(observe_active_agents(CallbackOptions()))
        assert len(observations) == 1
        assert observations[0].value == 4

    def test_empty_when_no_active_agents_counter(self) -> None:
        """No observations when active_agent_count key does not exist."""
        from ces.observability.metrics_bridge import observe_active_agents

        observations = list(observe_active_agents(CallbackOptions()))
        assert observations == []


class TestRegisterCESMetrics:
    """Tests for register_ces_metrics() instrument creation."""

    def test_creates_telemetry_counter_observable_gauge(self, otel_metric_reader) -> None:
        """Creates an observable gauge named 'ces.telemetry_counter'."""
        from ces.observability.metrics_bridge import register_ces_metrics

        get_counters().increment("test_counter", 5)
        register_ces_metrics()

        data = otel_metric_reader.get_metrics_data()
        metric_names = [m.name for rm in data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics]
        assert "ces.telemetry_counter" in metric_names

    def test_creates_manifest_issued_counter(self, otel_metric_reader) -> None:
        """Creates a Counter named 'ces.manifest.issued'."""
        from ces.observability.metrics_bridge import register_ces_metrics

        ces_metrics = register_ces_metrics()
        ces_metrics.manifest_issued.add(1)

        data = otel_metric_reader.get_metrics_data()
        metric_names = [m.name for rm in data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics]
        assert "ces.manifest.issued" in metric_names

    def test_creates_manifest_invalidated_counter(self, otel_metric_reader) -> None:
        """Creates a Counter named 'ces.manifest.invalidated'."""
        from ces.observability.metrics_bridge import register_ces_metrics

        ces_metrics = register_ces_metrics()
        ces_metrics.manifest_invalidated.add(1)

        data = otel_metric_reader.get_metrics_data()
        metric_names = [m.name for rm in data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics]
        assert "ces.manifest.invalidated" in metric_names

    def test_creates_approval_latency_histogram(self, otel_metric_reader) -> None:
        """Creates a Histogram named 'ces.approval.latency'."""
        from ces.observability.metrics_bridge import register_ces_metrics

        ces_metrics = register_ces_metrics()
        ces_metrics.approval_latency.record(1.5)

        data = otel_metric_reader.get_metrics_data()
        metric_names = [m.name for rm in data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics]
        assert "ces.approval.latency" in metric_names

    def test_creates_queue_depth_observable_gauge(self, otel_metric_reader) -> None:
        """Creates observable gauges for queue depth."""
        from ces.observability.metrics_bridge import register_ces_metrics

        get_counters().increment("queue_depth_merge", 2)
        register_ces_metrics()

        data = otel_metric_reader.get_metrics_data()
        metric_names = [m.name for rm in data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics]
        assert "ces.queue.depth" in metric_names

    def test_creates_active_agents_observable_gauge(self, otel_metric_reader) -> None:
        """Creates observable gauge for active agent count."""
        from ces.observability.metrics_bridge import register_ces_metrics

        get_counters().increment("active_agent_count", 1)
        register_ces_metrics()

        data = otel_metric_reader.get_metrics_data()
        metric_names = [m.name for rm in data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics]
        assert "ces.agent.active_count" in metric_names

    def test_ces_metrics_dataclass_provides_instrument_access(self, otel_metric_reader) -> None:
        """CESMetrics dataclass returned by register_ces_metrics() provides counter and histogram references."""
        from ces.observability.metrics_bridge import CESMetrics, register_ces_metrics

        ces_metrics = register_ces_metrics()

        assert isinstance(ces_metrics, CESMetrics)
        # Verify we can use the instruments without error
        ces_metrics.manifest_issued.add(1)
        ces_metrics.manifest_invalidated.add(1)
        ces_metrics.approval_latency.record(2.0)

        data = otel_metric_reader.get_metrics_data()
        metric_names = [m.name for rm in data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics]
        assert "ces.manifest.issued" in metric_names
        assert "ces.manifest.invalidated" in metric_names
        assert "ces.approval.latency" in metric_names


class TestOtelUnavailableFallbacks:
    """Lean-install fallbacks when opentelemetry extras are not installed."""

    def test_fallback_observation_stores_value_and_attributes(self) -> None:
        """_FallbackObservation captures the value and attributes (lines 52-53)."""
        from ces.observability.metrics_bridge import _FallbackObservation

        obs = _FallbackObservation(value=5, attributes={"k": "v"})
        assert obs.value == 5
        assert obs.attributes == {"k": "v"}

    def test_fallback_observation_defaults_attributes_to_empty(self) -> None:
        from ces.observability.metrics_bridge import _FallbackObservation

        obs = _FallbackObservation(value=1)
        assert obs.attributes == {}

    def test_make_observation_returns_fallback_when_otel_unavailable(self, monkeypatch) -> None:
        """With OTel disabled, _make_observation returns a _FallbackObservation (line 60)."""
        from ces.observability import metrics_bridge as mod

        monkeypatch.setattr(mod, "_OTEL_AVAILABLE", False)
        obs = mod._make_observation(42, {"k": "v"})
        assert isinstance(obs, mod._FallbackObservation)
        assert obs.value == 42

    def test_noop_counter_and_histogram_silently_accept_calls(self) -> None:
        """The no-op shims never raise (lines 133, 140)."""
        from ces.observability.metrics_bridge import _NoOpCounter, _NoOpHistogram

        counter = _NoOpCounter()
        histogram = _NoOpHistogram()

        counter.add(7, {"k": "v"})
        histogram.record(1.5, {"k": "v"})

    def test_register_ces_metrics_returns_noop_dataclass_without_otel(self, monkeypatch) -> None:
        """register_ces_metrics with OTel disabled returns no-op shim instruments (line 159)."""
        from ces.observability import metrics_bridge as mod

        monkeypatch.setattr(mod, "_OTEL_AVAILABLE", False)
        ces_metrics = mod.register_ces_metrics()
        assert isinstance(ces_metrics.manifest_issued, mod._NoOpCounter)
        assert isinstance(ces_metrics.manifest_invalidated, mod._NoOpCounter)
        assert isinstance(ces_metrics.approval_latency, mod._NoOpHistogram)
