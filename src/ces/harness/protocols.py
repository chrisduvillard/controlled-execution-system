"""Harness plane protocols -- dependency injection interfaces.

Defines runtime_checkable protocols for harness plane components:
- SensorProtocol (D-09): sensor execution interface
- ReviewExecutorProtocol: review execution interface
- SummarizerProtocol: text summarization interface

These protocols follow the same pattern as KillSwitchProtocol
and AuditLedgerProtocol from the control plane.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ces.harness.models.review_assignment import ReviewAssignment
from ces.harness.models.sensor_result import SensorResult


@runtime_checkable
class SensorProtocol(Protocol):
    """Protocol for sensor implementations (D-09).

    Sensors are registered at startup via a plugin registry.
    Each sensor has a unique ID and belongs to a sensor pack.
    The run() method executes the sensor check and returns a SensorResult.

    Runtime checkable: use isinstance(obj, SensorProtocol) to verify
    that an object implements the sensor interface.
    """

    @property
    def sensor_id(self) -> str:
        """Unique sensor identifier."""
        ...

    @property
    def sensor_pack(self) -> str:
        """Name of the sensor pack this sensor belongs to."""
        ...

    async def run(self, context: dict) -> SensorResult:  # type: ignore[type-arg]
        """Execute the sensor check.

        Args:
            context: Dictionary with execution context for the sensor.

        Returns:
            SensorResult with pass/fail, score, and details.
        """
        ...


class ReviewExecutorProtocol(Protocol):
    """Protocol for review execution implementations.

    Phase 4 will provide LLM-backed implementations.
    Phase 3 defines the structural contract.
    """

    async def execute_review(
        self,
        assignment: ReviewAssignment,
        evidence: dict,  # type: ignore[type-arg]
    ) -> dict:  # type: ignore[type-arg]
        """Execute a review for the given assignment.

        Args:
            assignment: The review role and model assignment.
            evidence: Evidence data to review.

        Returns:
            Review findings as a dictionary.
        """
        ...


class SummarizerProtocol(Protocol):
    """Protocol for text summarization implementations.

    Phase 4 will provide LLM-backed implementations.
    Phase 3 defines the structural contract.
    """

    async def summarize(self, text: str, max_tokens: int) -> str:
        """Summarize text within a token budget.

        Args:
            text: The text to summarize.
            max_tokens: Maximum tokens in the summary.

        Returns:
            Summarized text.
        """
        ...
