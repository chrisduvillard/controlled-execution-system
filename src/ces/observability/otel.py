"""OpenTelemetry initialization for CES local tracing and metrics."""

from __future__ import annotations

import os
from typing import Any

import structlog

try:
    from opentelemetry import metrics as otel_metrics
    from opentelemetry import trace as otel_trace
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _OTEL_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - exercised via install smoke tests
    otel_metrics = None
    otel_trace = None
    _OTEL_AVAILABLE = False

logger = structlog.get_logger()

_otel_initialized: bool = False
_otel_unavailable_reported: bool = False
_tracer_provider: Any | None = None
_meter_provider: Any | None = None


def configure_otel() -> bool:
    """Initialize OpenTelemetry tracing, metrics, and local auto-instrumentation."""
    global _otel_initialized, _otel_unavailable_reported, _tracer_provider, _meter_provider  # noqa: PLW0603

    if _otel_initialized:
        return True

    if not _OTEL_AVAILABLE:
        if not _otel_unavailable_reported:
            logger.info("otel_unavailable", reason="observability extras not installed")
            _otel_unavailable_reported = True
        return False

    if os.environ.get("OTEL_SDK_DISABLED", "").lower().strip() == "true":
        logger.info("otel_disabled", reason="OTEL_SDK_DISABLED=true")
        return False

    service_name = os.environ.get("OTEL_SERVICE_NAME", "ces")
    resource = Resource.create({SERVICE_NAME: service_name})

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    otel_trace.set_tracer_provider(tracer_provider)
    _tracer_provider = tracer_provider

    metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter())
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    otel_metrics.set_meter_provider(meter_provider)
    _meter_provider = meter_provider

    HTTPXClientInstrumentor().instrument()
    SQLAlchemyInstrumentor().instrument()

    _otel_initialized = True
    logger.info("otel_configured", service_name=service_name)
    return True


def shutdown_otel() -> None:
    """Flush pending telemetry and reset providers."""
    global _otel_initialized, _otel_unavailable_reported, _tracer_provider, _meter_provider  # noqa: PLW0603

    if not _OTEL_AVAILABLE:
        _otel_initialized = False
        _otel_unavailable_reported = False
        return

    if _tracer_provider is not None:
        _tracer_provider.shutdown()
    if _meter_provider is not None:
        _meter_provider.shutdown()

    _otel_initialized = False
    _otel_unavailable_reported = False
    logger.info("otel_shutdown_complete")


def attach_governance_to_current_span(
    manifest_id: str | None = None,
    risk_tier: str | None = None,
    change_class: str | None = None,
    trust_status: str | None = None,
    review_outcome: str | None = None,
    project_id: str | None = None,
) -> None:
    """Attach governance attributes to the currently active span."""
    if not _OTEL_AVAILABLE:
        return

    span = otel_trace.get_current_span()
    if not span.is_recording():
        return

    from ces.observability.conventions import GovernanceAttributes

    kwargs: dict[str, Any] = {}
    if manifest_id is not None:
        kwargs["manifest_id"] = manifest_id
    if risk_tier is not None:
        kwargs["risk_tier"] = risk_tier
    if change_class is not None:
        kwargs["change_class"] = change_class
    if trust_status is not None:
        kwargs["trust_status"] = trust_status
    if review_outcome is not None:
        kwargs["review_outcome"] = review_outcome
    if project_id is not None:
        kwargs["project_id"] = project_id

    if not kwargs:
        return

    gov = GovernanceAttributes(**kwargs)
    for key, value in gov.as_span_attributes().items():
        span.set_attribute(key, value)
