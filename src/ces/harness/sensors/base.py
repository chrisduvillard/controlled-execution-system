"""Base sensor implementation for the harness plane sensor framework.

BaseSensor provides an abstract base class that implements SensorProtocol.
Concrete sensor packs inherit from BaseSensor and implement _execute().

Pattern:
    - BaseSensor stores sensor_id and sensor_pack as private attributes
    - Properties expose them as read-only (matching SensorProtocol)
    - run() calls abstract _execute() and wraps the result in SensorResult
    - _execute() is the only method subclasses need to implement
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone

from ces.harness.models.sensor_result import SensorFinding, SensorResult


class BaseSensor(ABC):
    """Abstract base class implementing SensorProtocol.

    Subclasses must implement _execute(context) which returns a tuple of
    (passed, score, details). BaseSensor.run() wraps the result into
    a SensorResult with timestamp.

    Subclasses can populate ``self._findings`` during ``_execute()`` to
    attach structured :class:`SensorFinding` objects to the result without
    changing the ``_execute()`` return signature.  Call
    ``self._mark_skipped(reason)`` to flag the sensor as skipped.

    Args:
        sensor_id: Unique identifier for this sensor.
        sensor_pack: Name of the sensor pack this sensor belongs to.
    """

    def __init__(self, sensor_id: str, sensor_pack: str) -> None:
        self._sensor_id = sensor_id
        self._sensor_pack = sensor_pack
        self._findings: list[SensorFinding] = []
        self._skipped_flag: bool = False
        self._skip_reason: str | None = None
        self._configured: bool | None = None
        self._required: bool | None = None
        self._reason: str | None = None

    @property
    def sensor_id(self) -> str:
        """Unique sensor identifier."""
        return self._sensor_id

    @property
    def sensor_pack(self) -> str:
        """Name of the sensor pack this sensor belongs to."""
        return self._sensor_pack

    @abstractmethod
    async def _execute(self, context: dict) -> tuple[bool, float, str]:
        """Execute the sensor check (implemented by subclasses).

        Args:
            context: Dictionary with execution context for the sensor.

        Returns:
            Tuple of (passed, score, details):
                - passed: Whether the check passed.
                - score: Normalized score between 0.0 and 1.0.
                - details: Human-readable details about the result.
        """
        ...

    def _mark_skipped(self, reason: str) -> None:
        """Mark this sensor execution as skipped.

        Call from ``_execute()`` when the sensor is not applicable
        (e.g., no files of the relevant type in scope).

        Args:
            reason: Human-readable reason the sensor was skipped.
        """
        self._skipped_flag = True
        self._skip_reason = reason

    def _set_verification_metadata(self, *, configured: bool, required: bool, reason: str) -> None:
        """Attach verification-profile metadata to this sensor run."""
        self._configured = configured
        self._required = required
        self._reason = reason

    async def run(self, context: dict) -> SensorResult:
        """Execute the sensor check and return a SensorResult.

        Calls _execute() and wraps the result into a SensorResult
        with the sensor's ID, pack, and current UTC timestamp.
        Structured findings populated via ``self._findings`` during
        ``_execute()`` are included in the result.

        Args:
            context: Dictionary with execution context for the sensor.

        Returns:
            SensorResult with pass/fail, score, details, and findings.
        """
        passed, score, details = await self._execute(context)
        result = SensorResult(
            sensor_id=self._sensor_id,
            sensor_pack=self._sensor_pack,
            passed=passed,
            score=score,
            details=details,
            timestamp=datetime.now(timezone.utc),
            findings=tuple(self._findings),
            skipped=self._skipped_flag,
            skip_reason=self._skip_reason,
            configured=self._configured,
            required=self._required,
            reason=self._reason,
        )
        # Reset per-run state for next invocation
        self._findings = []
        self._skipped_flag = False
        self._skip_reason = None
        self._configured = None
        self._required = None
        self._reason = None
        return result
