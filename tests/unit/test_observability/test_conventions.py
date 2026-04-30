"""Tests for CES governance semantic conventions for OpenTelemetry.

Verifies GovernanceAttributes Pydantic model validates governance fields,
converts them to span attributes with ces. prefix, and handles None fields correctly.
"""

from __future__ import annotations

import pytest
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ces.observability.conventions import CES_ATTR_PREFIX, GovernanceAttributes
from ces.shared.enums import ChangeClass, RiskTier, TrustStatus


class TestCESAttrPrefix:
    """Tests for the CES_ATTR_PREFIX constant."""

    def test_prefix_value(self) -> None:
        assert CES_ATTR_PREFIX == "ces."


class TestGovernanceAttributesDefaults:
    """All fields are Optional and default to None."""

    def test_all_fields_default_none(self) -> None:
        attrs = GovernanceAttributes()
        assert attrs.manifest_id is None
        assert attrs.risk_tier is None
        assert attrs.change_class is None
        assert attrs.behavior_confidence is None
        assert attrs.trust_status is None
        assert attrs.review_outcome is None
        assert attrs.project_id is None


class TestGovernanceAttributesValidValues:
    """GovernanceAttributes accepts valid enum and string values."""

    def test_accepts_valid_enum_values(self) -> None:
        attrs = GovernanceAttributes(
            risk_tier=RiskTier.A,
            change_class=ChangeClass.CLASS_1,
            trust_status=TrustStatus.TRUSTED,
        )
        assert attrs.risk_tier == RiskTier.A
        assert attrs.change_class == ChangeClass.CLASS_1
        assert attrs.trust_status == TrustStatus.TRUSTED

    def test_accepts_string_values(self) -> None:
        attrs = GovernanceAttributes(
            manifest_id="m-12345",
            behavior_confidence="BC1",
            review_outcome="pass",
            project_id="proj-abc",
        )
        assert attrs.manifest_id == "m-12345"
        assert attrs.behavior_confidence == "BC1"
        assert attrs.review_outcome == "pass"
        assert attrs.project_id == "proj-abc"

    def test_accepts_all_behavior_confidence_values(self) -> None:
        for bc in ("BC1", "BC2", "BC3"):
            attrs = GovernanceAttributes(behavior_confidence=bc)
            assert attrs.behavior_confidence == bc

    def test_accepts_all_review_outcome_values(self) -> None:
        for outcome in ("pass", "fail", "escalate"):
            attrs = GovernanceAttributes(review_outcome=outcome)
            assert attrs.review_outcome == outcome


class TestAsSpanAttributes:
    """Tests for as_span_attributes() method."""

    def test_returns_dict_with_ces_prefix(self) -> None:
        attrs = GovernanceAttributes(manifest_id="m-123")
        span_attrs = attrs.as_span_attributes()
        assert "ces.manifest_id" in span_attrs
        assert span_attrs["ces.manifest_id"] == "m-123"

    def test_omits_none_fields(self) -> None:
        attrs = GovernanceAttributes(manifest_id="m-123")
        span_attrs = attrs.as_span_attributes()
        assert len(span_attrs) == 1
        assert "ces.risk_tier" not in span_attrs

    def test_converts_enum_values_to_strings(self) -> None:
        attrs = GovernanceAttributes(
            risk_tier=RiskTier.A,
            change_class=ChangeClass.CLASS_1,
            trust_status=TrustStatus.TRUSTED,
        )
        span_attrs = attrs.as_span_attributes()
        assert span_attrs["ces.risk_tier"] == "A"
        assert span_attrs["ces.change_class"] == "Class 1"
        assert span_attrs["ces.trust_status"] == "trusted"

    def test_all_fields_populated(self) -> None:
        attrs = GovernanceAttributes(
            manifest_id="m-999",
            risk_tier=RiskTier.B,
            change_class=ChangeClass.CLASS_3,
            behavior_confidence="BC2",
            trust_status=TrustStatus.WATCH,
            review_outcome="fail",
            project_id="proj-x",
        )
        span_attrs = attrs.as_span_attributes()
        assert len(span_attrs) == 7
        assert all(k.startswith("ces.") for k in span_attrs)

    def test_empty_model_returns_empty_dict(self) -> None:
        attrs = GovernanceAttributes()
        span_attrs = attrs.as_span_attributes()
        assert span_attrs == {}


class TestOtelSpanExporterFixture:
    """Test that InMemorySpanExporter fixture captures spans correctly."""

    def test_span_capture(self, otel_span_exporter: InMemorySpanExporter) -> None:
        tracer = trace.get_tracer("test-tracer")
        with tracer.start_as_current_span("test-span") as span:
            span.set_attribute("test.key", "test-value")

        spans = otel_span_exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "test-span"
        assert spans[0].attributes is not None
        assert spans[0].attributes.get("test.key") == "test-value"


class TestOtelMetricReaderFixture:
    """Test that InMemoryMetricReader fixture captures metrics correctly."""

    def test_metric_capture(self, otel_metric_reader: InMemoryMetricReader) -> None:
        meter = metrics.get_meter("test-meter")
        counter = meter.create_counter("test.counter", description="A test counter")
        counter.add(42)

        data = otel_metric_reader.get_metrics_data()
        assert data is not None
        resource_metrics = data.resource_metrics
        assert len(resource_metrics) > 0
        # Verify we captured the counter metric
        scope_metrics = resource_metrics[0].scope_metrics
        assert len(scope_metrics) > 0
        metric_list = scope_metrics[0].metrics
        assert len(metric_list) > 0
        assert metric_list[0].name == "test.counter"
