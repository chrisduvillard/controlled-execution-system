"""Tests for CES OpenTelemetry initialization."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest
from opentelemetry import metrics, trace

import ces.observability.otel as otel_module


@pytest.fixture(autouse=True)
def _reset_otel_module() -> Generator[None, None, None]:
    otel_module._otel_initialized = False
    otel_module._tracer_provider = None
    otel_module._meter_provider = None
    yield
    otel_module._otel_initialized = False
    otel_module._tracer_provider = None
    otel_module._meter_provider = None
    trace.set_tracer_provider(trace.NoOpTracerProvider())
    metrics.set_meter_provider(metrics.NoOpMeterProvider())


def _patch_otel_runtime():
    return (
        patch("ces.observability.otel.OTLPSpanExporter"),
        patch("ces.observability.otel.OTLPMetricExporter"),
        patch("ces.observability.otel.HTTPXClientInstrumentor"),
        patch("ces.observability.otel.SQLAlchemyInstrumentor"),
    )


class TestConfigureOtel:
    def test_returns_true_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
        with _patch_otel_runtime()[0], _patch_otel_runtime()[1], _patch_otel_runtime()[2], _patch_otel_runtime()[3]:
            result = otel_module.configure_otel()
        assert result is True

    def test_returns_false_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
        assert otel_module.configure_otel() is False

    def test_sets_providers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
        with _patch_otel_runtime()[0], _patch_otel_runtime()[1], _patch_otel_runtime()[2], _patch_otel_runtime()[3]:
            otel_module.configure_otel()
        assert otel_module._tracer_provider is not None
        assert otel_module._meter_provider is not None

    def test_instruments_httpx_and_sqlalchemy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
        with (
            patch("ces.observability.otel.OTLPSpanExporter"),
            patch("ces.observability.otel.OTLPMetricExporter"),
            patch("ces.observability.otel.HTTPXClientInstrumentor") as mock_httpx,
            patch("ces.observability.otel.SQLAlchemyInstrumentor") as mock_sqla,
        ):
            otel_module.configure_otel()
        mock_httpx.return_value.instrument.assert_called_once()
        mock_sqla.return_value.instrument.assert_called_once()

    def test_double_initialization_is_guarded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
        with (
            patch("ces.observability.otel.OTLPSpanExporter"),
            patch("ces.observability.otel.OTLPMetricExporter"),
            patch("ces.observability.otel.HTTPXClientInstrumentor") as mock_httpx,
            patch("ces.observability.otel.SQLAlchemyInstrumentor"),
        ):
            assert otel_module.configure_otel() is True
            assert otel_module.configure_otel() is True
        assert mock_httpx.return_value.instrument.call_count == 1


class TestShutdownOtel:
    def test_shutdown_resets_initialized_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
        with (
            patch("ces.observability.otel.OTLPSpanExporter"),
            patch("ces.observability.otel.OTLPMetricExporter"),
            patch("ces.observability.otel.HTTPXClientInstrumentor"),
            patch("ces.observability.otel.SQLAlchemyInstrumentor"),
        ):
            otel_module.configure_otel()
            otel_module.shutdown_otel()
        assert otel_module._otel_initialized is False

    def test_shutdown_calls_provider_shutdown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
        with (
            patch("ces.observability.otel.OTLPSpanExporter"),
            patch("ces.observability.otel.OTLPMetricExporter"),
            patch("ces.observability.otel.HTTPXClientInstrumentor"),
            patch("ces.observability.otel.SQLAlchemyInstrumentor"),
        ):
            otel_module.configure_otel()
            tp = otel_module._tracer_provider
            mp = otel_module._meter_provider
            assert tp is not None
            assert mp is not None
            with patch.object(tp, "shutdown") as mock_tp_shutdown, patch.object(mp, "shutdown") as mock_mp_shutdown:
                otel_module.shutdown_otel()
            mock_tp_shutdown.assert_called_once()
            mock_mp_shutdown.assert_called_once()


class TestResourceServiceName:
    def test_default_service_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
        monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
        with (
            patch("ces.observability.otel.OTLPSpanExporter"),
            patch("ces.observability.otel.OTLPMetricExporter"),
            patch("ces.observability.otel.HTTPXClientInstrumentor"),
            patch("ces.observability.otel.SQLAlchemyInstrumentor"),
        ):
            otel_module.configure_otel()
        tp = otel_module._tracer_provider
        assert tp is not None
        assert dict(tp.resource.attributes).get("service.name") == "ces"

    def test_custom_service_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
        monkeypatch.setenv("OTEL_SERVICE_NAME", "ces-worker")
        with (
            patch("ces.observability.otel.OTLPSpanExporter"),
            patch("ces.observability.otel.OTLPMetricExporter"),
            patch("ces.observability.otel.HTTPXClientInstrumentor"),
            patch("ces.observability.otel.SQLAlchemyInstrumentor"),
        ):
            otel_module.configure_otel()
        tp = otel_module._tracer_provider
        assert tp is not None
        assert dict(tp.resource.attributes).get("service.name") == "ces-worker"
