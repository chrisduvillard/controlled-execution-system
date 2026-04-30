"""Test fixtures for observability unit tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def _reset_otel_globals() -> None:
    """Reset OTel global state guards so providers can be replaced in tests.

    OTel uses a ``Once`` guard to prevent overriding providers after the first
    ``set_*_provider()`` call.  In tests we need to swap providers per-test, so
    we reset the ``_done`` flag on both guards.
    """
    # Reset MeterProvider set-once guard
    from opentelemetry.metrics._internal import _METER_PROVIDER_SET_ONCE

    _METER_PROVIDER_SET_ONCE._done = False

    # Reset TracerProvider set-once guard
    from opentelemetry.trace import _TRACER_PROVIDER_SET_ONCE

    _TRACER_PROVIDER_SET_ONCE._done = False


@pytest.fixture()
def now_utc() -> datetime:
    """Return a timezone-aware UTC datetime for test data."""
    return datetime.now(timezone.utc)


@pytest.fixture()
def otel_span_exporter() -> Generator[InMemorySpanExporter, None, None]:
    """Set up an in-memory span exporter for testing.

    Creates a TracerProvider with SimpleSpanProcessor (not Batch -- avoids
    flaky tests from async flush timing) and sets it as the global provider.
    Yields the exporter so tests can call ``get_finished_spans()``.
    Resets the global tracer provider in teardown.
    """
    _reset_otel_globals()
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    yield exporter
    provider.shutdown()
    _reset_otel_globals()
    trace.set_tracer_provider(trace.NoOpTracerProvider())


@pytest.fixture()
def otel_metric_reader() -> Generator[InMemoryMetricReader, None, None]:
    """Set up an in-memory metric reader for testing.

    Creates a MeterProvider with InMemoryMetricReader and sets it as the
    global provider. Yields the reader so tests can call ``get_metrics_data()``.
    Resets the global meter provider in teardown.
    """
    _reset_otel_globals()
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    metrics.set_meter_provider(provider)
    yield reader
    provider.shutdown()
    _reset_otel_globals()
    metrics.set_meter_provider(metrics.NoOpMeterProvider())
