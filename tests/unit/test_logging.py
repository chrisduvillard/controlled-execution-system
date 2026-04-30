"""Tests for CES structured logging configuration (ces.shared.logging).

Validates configure_logging() sets up structlog correctly and
get_logger() returns a properly bound logger instance.
"""

from __future__ import annotations

import logging

import structlog
from structlog._config import BoundLoggerLazyProxy

from ces.shared.logging import configure_logging, get_logger


class TestConfigureLogging:
    """configure_logging() sets up structlog and stdlib logging."""

    def test_configure_logging_does_not_raise(self) -> None:
        """Basic smoke test: configure_logging completes without error."""
        configure_logging(log_level="INFO", log_format="json")

    def test_root_logger_level_set_to_info(self) -> None:
        """Root logger level should match the configured log_level."""
        configure_logging(log_level="INFO", log_format="json")
        root = logging.getLogger()
        assert root.level == logging.INFO

    def test_root_logger_level_set_to_debug(self) -> None:
        """Root logger level should reflect DEBUG when configured."""
        configure_logging(log_level="DEBUG", log_format="json")
        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_root_logger_level_set_to_warning(self) -> None:
        """Root logger level should reflect WARNING when configured."""
        configure_logging(log_level="WARNING", log_format="json")
        root = logging.getLogger()
        assert root.level == logging.WARNING

    def test_root_logger_has_handler(self) -> None:
        """Root logger should have exactly one handler after configuration."""
        configure_logging(log_level="INFO", log_format="json")
        root = logging.getLogger()
        assert len(root.handlers) == 1

    def test_handler_has_structlog_formatter(self) -> None:
        """The handler should use a structlog ProcessorFormatter."""
        configure_logging(log_level="INFO", log_format="json")
        root = logging.getLogger()
        handler = root.handlers[0]
        assert isinstance(handler.formatter, structlog.stdlib.ProcessorFormatter)

    def test_json_format_uses_json_renderer(self) -> None:
        """When log_format='json', the formatter should use JSONRenderer."""
        configure_logging(log_level="INFO", log_format="json")
        root = logging.getLogger()
        formatter = root.handlers[0].formatter
        assert isinstance(formatter, structlog.stdlib.ProcessorFormatter)
        # The last processor in the chain (after remove_processors_meta) is the renderer
        processors = formatter.processors  # type: ignore[union-attr]
        renderer = processors[-1]
        assert isinstance(renderer, structlog.processors.JSONRenderer)

    def test_console_format_uses_console_renderer(self) -> None:
        """When log_format='console', the formatter should use ConsoleRenderer."""
        configure_logging(log_level="INFO", log_format="console")
        root = logging.getLogger()
        formatter = root.handlers[0].formatter
        assert isinstance(formatter, structlog.stdlib.ProcessorFormatter)
        processors = formatter.processors  # type: ignore[union-attr]
        renderer = processors[-1]
        assert isinstance(renderer, structlog.dev.ConsoleRenderer)

    def test_invalid_log_level_falls_back_to_info(self) -> None:
        """Invalid log level strings should fall back to INFO."""
        configure_logging(log_level="INVALID_LEVEL", log_format="json")
        root = logging.getLogger()
        assert root.level == logging.INFO

    def test_case_insensitive_log_level(self) -> None:
        """Log level should be case-insensitive (e.g., 'debug' works)."""
        configure_logging(log_level="debug", log_format="json")
        root = logging.getLogger()
        assert root.level == logging.DEBUG


class TestGetLogger:
    """get_logger() returns structlog BoundLogger instances."""

    def test_returns_bound_logger(self) -> None:
        """get_logger should return a structlog logger (lazy proxy wrapping BoundLogger)."""
        configure_logging(log_level="INFO", log_format="json")
        logger = get_logger("test")
        # structlog.get_logger() returns a BoundLoggerLazyProxy, not BoundLogger directly
        assert isinstance(logger, BoundLoggerLazyProxy)

    def test_logger_with_name(self) -> None:
        """get_logger with a name should not raise."""
        configure_logging(log_level="INFO", log_format="json")
        logger = get_logger("ces.test.module")
        assert logger is not None

    def test_logger_without_name(self) -> None:
        """get_logger without a name should still return a logger."""
        configure_logging(log_level="INFO", log_format="json")
        logger = get_logger()
        assert logger is not None

    def test_logger_with_initial_context(self) -> None:
        """get_logger with initial context should bind those values."""
        configure_logging(log_level="INFO", log_format="json")
        logger = get_logger("test", request_id="abc-123", user="admin")
        # .bind() resolves the lazy proxy into a real BoundLogger
        assert isinstance(logger, structlog.stdlib.BoundLogger)
