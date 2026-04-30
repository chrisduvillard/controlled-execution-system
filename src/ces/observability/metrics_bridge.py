"""Bridge Phase 11 TelemetryCounters to OTel observable gauges and register custom CES metric instruments (OBS-07).

Observable gauge callbacks read the TelemetryCounters singleton via
``get_counters().get_current()`` (non-destructive read) and yield OTel
Observations.  Custom CES metrics (manifest issued counter, approval
latency histogram, etc.) are registered as standard OTel instruments
that any OTLP-compatible collector can scrape.

Usage::

    from ces.observability.metrics_bridge import register_ces_metrics

    ces_metrics = register_ces_metrics()
    ces_metrics.manifest_issued.add(1)
    ces_metrics.approval_latency.record(1.5)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

try:
    from opentelemetry import metrics
    from opentelemetry.metrics import Observation as OTelObservation

    _OTEL_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - exercised via wheel smoke test
    metrics = None
    _OTEL_AVAILABLE = False


from ces.observability.counters import get_counters


class CounterLike(Protocol):
    """Counter protocol used by both OTel and no-op shims."""

    def add(self, amount: int | float, attributes: dict[str, str] | None = None) -> None: ...


class HistogramLike(Protocol):
    """Histogram protocol used by both OTel and no-op shims."""

    def record(self, amount: int | float, attributes: dict[str, str] | None = None) -> None: ...


class _FallbackObservation:
    """Lightweight stand-in used when OTel extras are not installed."""

    def __init__(self, value: int | float, attributes: dict[str, str] | None = None) -> None:
        self.value = value
        self.attributes = attributes or {}


def _make_observation(value: int | float, attributes: dict[str, str] | None = None) -> object:
    """Create a real OTel observation when available, otherwise a shim."""
    if _OTEL_AVAILABLE:
        return OTelObservation(value, attributes or {})
    return _FallbackObservation(value, attributes)


# ---------------------------------------------------------------------------
# Observable gauge callbacks
# ---------------------------------------------------------------------------


def observe_telemetry_counters(options: object) -> list[object]:
    """Read all TelemetryCounters and yield one Observation per counter.

    Each observation carries a ``ces.metric_name`` attribute so the OTel
    backend can distinguish individual counters within the single
    ``ces.telemetry_counter`` gauge.
    """
    current = get_counters().get_current()
    return [_make_observation(value, {"ces.metric_name": metric_name}) for metric_name, value in current.items()]


def observe_queue_depths(options: object) -> list[object]:
    """Read queue depth counters and yield one Observation per queue.

    Only counters whose key starts with ``queue_depth_`` are included.
    The ``ces.queue_name`` attribute contains the queue name (suffix
    after the ``queue_depth_`` prefix).
    """
    current = get_counters().get_current()
    observations: list[object] = []
    for key, value in current.items():
        if key.startswith("queue_depth_"):
            queue_name = key[len("queue_depth_") :]
            observations.append(_make_observation(value, {"ces.queue_name": queue_name}))
    return observations


def observe_active_agents(options: object) -> list[object]:
    """Read the active agent count and yield a single Observation.

    Looks for the ``active_agent_count`` key in TelemetryCounters.
    Yields nothing if the key does not exist.
    """
    current = get_counters().get_current()
    count = current.get("active_agent_count")
    if count is not None:
        return [_make_observation(count)]
    return []


# ---------------------------------------------------------------------------
# Custom CES metric instruments
# ---------------------------------------------------------------------------


@dataclass
class CESMetrics:
    """References to custom CES OTel instruments.

    Returned by :func:`register_ces_metrics` so callers can record values
    on the counter and histogram instruments.
    """

    manifest_issued: CounterLike
    manifest_invalidated: CounterLike
    approval_latency: HistogramLike


_registered_metrics: CESMetrics | None = None


class _NoOpCounter:
    """Counter shim for lean installs without OTel extras."""

    def add(self, amount: int | float, attributes: dict[str, str] | None = None) -> None:
        return None


class _NoOpHistogram:
    """Histogram shim for lean installs without OTel extras."""

    def record(self, amount: int | float, attributes: dict[str, str] | None = None) -> None:
        return None


def register_ces_metrics() -> CESMetrics:
    """Register all custom CES metrics as OTel instruments.

    Creates:
    - ``ces.telemetry_counter`` observable gauge (bridges TelemetryCounters)
    - ``ces.queue.depth`` observable gauge (queue depths)
    - ``ces.agent.active_count`` observable gauge (active agent count)
    - ``ces.manifest.issued`` counter
    - ``ces.manifest.invalidated`` counter
    - ``ces.approval.latency`` histogram

    Returns:
        CESMetrics dataclass with references to the counter and histogram
        instruments for direct recording.
    """
    if not _OTEL_AVAILABLE:
        return CESMetrics(
            manifest_issued=_NoOpCounter(),
            manifest_invalidated=_NoOpCounter(),
            approval_latency=_NoOpHistogram(),
        )

    meter = metrics.get_meter("ces.governance", version="0.1.0")

    # Observable gauges (read TelemetryCounters on each collection cycle)
    meter.create_observable_gauge(
        name="ces.telemetry_counter",
        callbacks=[observe_telemetry_counters],
        description="CES internal telemetry counters mirrored as OTel metrics",
        unit="1",
    )

    meter.create_observable_gauge(
        name="ces.queue.depth",
        callbacks=[observe_queue_depths],
        description="Current queue depths (merge, approval)",
        unit="1",
    )

    meter.create_observable_gauge(
        name="ces.agent.active_count",
        callbacks=[observe_active_agents],
        description="Currently active agent count",
        unit="1",
    )

    # Counters and histograms (callers record values directly)
    manifest_issued = meter.create_counter(
        name="ces.manifest.issued",
        description="Total manifests issued",
        unit="1",
    )

    manifest_invalidated = meter.create_counter(
        name="ces.manifest.invalidated",
        description="Total manifests invalidated",
        unit="1",
    )

    approval_latency = meter.create_histogram(
        name="ces.approval.latency",
        description="Time from review submission to approval decision",
        unit="s",
    )

    return CESMetrics(
        manifest_issued=manifest_issued,
        manifest_invalidated=manifest_invalidated,
        approval_latency=approval_latency,
    )


def get_ces_metrics() -> CESMetrics:
    """Return the registered CES metric instruments, creating them lazily if needed."""
    global _registered_metrics  # noqa: PLW0603
    if _registered_metrics is None:
        _registered_metrics = register_ces_metrics()
    return _registered_metrics
