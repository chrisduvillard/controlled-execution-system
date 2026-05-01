"""Output capture with byte-counted buffer and truncation (EXEC-01).

Captures stdout/stderr from streaming process handles with size limits.
When output exceeds the limit, it is truncated and flagged for
mandatory disclosure in evidence packets (D-04 via DisclosureSet).

Threat mitigation:
- T-04-07: Enforces max_output_bytes limit to prevent memory DoS
           from verbose agent output.

Exports:
    CapturedOutput: Frozen model with stdout, stderr, truncated flag, bytes_read.
    OutputCapture: Service that reads attached output streams with byte counting.
"""

from __future__ import annotations

from ces.shared.base import CESBaseModel


class CapturedOutput(CESBaseModel):
    """Result of capturing process output.

    Frozen model -- once captured, output cannot be altered.
    The truncated flag MUST be disclosed in evidence packets
    via DisclosureSet.summarized_context when True.

    Attributes:
        stdout: Captured standard output (UTF-8 decoded).
        stderr: Captured standard error (UTF-8 decoded).
        truncated: True if output exceeded max_output_bytes limit.
        bytes_read: Total bytes read (capped at max_output_bytes if truncated).
    """

    stdout: str
    stderr: str
    truncated: bool
    bytes_read: int


class OutputCapture:
    """Streaming output capture with byte-counted buffer (EXEC-01).

    Enforces max_output_bytes limit. When exceeded, stops reading and
    sets truncated=True. Truncation must be disclosed in evidence packet
    via DisclosureSet.

    Args:
        max_bytes: Maximum total bytes to capture. Default 1MB (1_048_576).
    """

    def __init__(self, max_bytes: int = 1_048_576) -> None:
        self._max_bytes = max_bytes

    def capture(self, stream_source: object) -> CapturedOutput:
        """Capture stdout/stderr from an attached stream source with size limit.

        Streams output incrementally and stops reading once the
        combined byte budget is exhausted. This avoids materializing the
        full stdout/stderr payload in host memory before truncation.

        Args:
            stream_source: Object exposing an ``attach`` method that yields
                demuxed ``(stdout, stderr)`` byte chunks.

        Returns:
            CapturedOutput with decoded text, truncation flag, and byte count.
        """
        stdout_buffer = bytearray()
        stderr_buffer = bytearray()
        truncated = False

        stream = stream_source.attach(  # type: ignore[union-attr]
            stdout=True,
            stderr=True,
            stream=True,
            logs=True,
            demux=True,
        )

        for stdout_chunk, stderr_chunk in stream:
            remaining = self._max_bytes - (len(stdout_buffer) + len(stderr_buffer))
            if remaining <= 0:
                truncated = True
                break

            if stdout_chunk:
                consumed = min(len(stdout_chunk), remaining)
                stdout_buffer.extend(stdout_chunk[:consumed])
                remaining -= consumed
                if consumed < len(stdout_chunk):
                    truncated = True
                    break

            if stderr_chunk:
                consumed = min(len(stderr_chunk), remaining)
                stderr_buffer.extend(stderr_chunk[:consumed])
                if consumed < len(stderr_chunk):
                    truncated = True
                    break

        stdout_bytes = bytes(stdout_buffer)
        stderr_bytes = bytes(stderr_buffer)
        bytes_read = len(stdout_bytes) + len(stderr_bytes)

        return CapturedOutput(
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            truncated=truncated,
            bytes_read=bytes_read,
        )
