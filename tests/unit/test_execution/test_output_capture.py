"""Tests for OutputCapture with byte-counted buffer and truncation.

Tests verify:
- CapturedOutput is a frozen CESBaseModel with correct fields
- OutputCapture reads stdout/stderr from Docker containers
- OutputCapture enforces 1MB size limit
- Truncation flag is set when output exceeds limit
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ces.execution.output_capture import CapturedOutput, OutputCapture
from ces.shared.base import CESBaseModel


class TestCapturedOutput:
    """Test CapturedOutput frozen model."""

    def test_captured_output_is_ces_base_model(self) -> None:
        """CapturedOutput inherits from CESBaseModel."""
        assert issubclass(CapturedOutput, CESBaseModel)

    def test_captured_output_fields(self) -> None:
        """CapturedOutput has stdout, stderr, truncated, bytes_read fields."""
        output = CapturedOutput(
            stdout="hello",
            stderr="",
            truncated=False,
            bytes_read=5,
        )
        assert output.stdout == "hello"
        assert output.stderr == ""
        assert output.truncated is False
        assert output.bytes_read == 5

    def test_captured_output_is_frozen(self) -> None:
        """CapturedOutput instances are immutable."""
        output = CapturedOutput(stdout="", stderr="", truncated=False, bytes_read=0)
        with pytest.raises(Exception):
            output.stdout = "modified"  # type: ignore[misc]


class TestOutputCapture:
    """Test OutputCapture streaming with byte limits."""

    def test_capture_reads_stdout_and_stderr(self) -> None:
        """capture() reads stdout and stderr from container."""
        container = MagicMock()
        container.attach.return_value = [
            (b"hello stdout", None),
            (None, b"hello stderr"),
        ]

        capture = OutputCapture(max_bytes=1_048_576)
        result = capture.capture(container)

        assert result.stdout == "hello stdout"
        assert result.stderr == "hello stderr"
        assert result.truncated is False
        assert result.bytes_read == 24  # 12 + 12

    def test_capture_default_max_bytes(self) -> None:
        """OutputCapture defaults to 1MB (1_048_576 bytes) max."""
        capture = OutputCapture()
        assert capture._max_bytes == 1_048_576

    def test_capture_truncates_when_exceeds_limit(self) -> None:
        """capture() truncates output and sets truncated=True when over limit."""
        max_bytes = 100
        container = MagicMock()
        container.attach.return_value = [
            (b"x" * 60, None),
            (None, b"y" * 60),
        ]

        capture = OutputCapture(max_bytes=max_bytes)
        result = capture.capture(container)

        assert result.truncated is True
        assert result.bytes_read == max_bytes
        assert len(result.stdout) == 60
        assert len(result.stderr) == 40

    def test_capture_not_truncated_at_exact_limit(self) -> None:
        """capture() does not truncate when output is exactly at limit."""
        max_bytes = 100
        container = MagicMock()
        container.attach.return_value = [
            (b"x" * 50, None),
            (None, b"y" * 50),
        ]

        capture = OutputCapture(max_bytes=max_bytes)
        result = capture.capture(container)

        assert result.truncated is False
        assert result.bytes_read == 100

    def test_capture_handles_empty_output(self) -> None:
        """capture() handles empty stdout/stderr gracefully."""
        container = MagicMock()
        container.attach.return_value = []

        capture = OutputCapture()
        result = capture.capture(container)

        assert result.stdout == ""
        assert result.stderr == ""
        assert result.truncated is False
        assert result.bytes_read == 0

    def test_capture_decodes_utf8_with_replacement(self) -> None:
        """capture() decodes bytes using utf-8 with replacement for invalid bytes."""
        container = MagicMock()
        container.attach.return_value = [
            (b"hello\xff world", None),
        ]

        capture = OutputCapture()
        result = capture.capture(container)

        # \xff should be replaced, not raise an error
        assert "\ufffd" in result.stdout  # replacement character
        assert result.truncated is False

    def test_capture_calls_attach_with_demuxed_stream(self) -> None:
        """capture() requests demuxed streaming logs from the container."""
        container = MagicMock()
        container.attach.return_value = [(b"out", b"err")]

        capture = OutputCapture()
        capture.capture(container)

        container.attach.assert_called_once_with(
            stdout=True,
            stderr=True,
            stream=True,
            logs=True,
            demux=True,
        )

    def test_capture_stops_reading_after_limit(self) -> None:
        """capture() stops consuming the stream once the byte budget is exhausted."""
        seen: list[str] = []

        def _stream():
            seen.append("first")
            yield (b"x" * 120, None)
            seen.append("second")
            yield (b"y" * 10, None)

        container = MagicMock()
        container.attach.return_value = _stream()

        capture = OutputCapture(max_bytes=100)
        result = capture.capture(container)

        assert result.truncated is True
        assert result.bytes_read == 100
        assert seen == ["first"]

    def test_capture_truncates_at_top_of_next_iteration_when_exact_fill(self) -> None:
        """A chunk that exactly fills the budget triggers truncation on the next loop iteration.

        The inline `consumed < len(stdout_chunk)` truncation path is NOT hit
        when the chunk fits exactly. Instead the loop returns to the top, computes
        `remaining = 0`, and trips the `if remaining <= 0` early-break branch.
        """
        max_bytes = 100
        container = MagicMock()
        container.attach.return_value = [
            (b"x" * max_bytes, None),  # exactly fills the buffer, no inline truncation
            (b"y" * 10, None),  # next iteration: remaining == 0, break with truncated=True
        ]

        capture = OutputCapture(max_bytes=max_bytes)
        result = capture.capture(container)

        assert result.truncated is True
        assert result.bytes_read == max_bytes
        assert len(result.stdout) == max_bytes
        # The second chunk was never appended.
        assert "y" not in result.stdout
