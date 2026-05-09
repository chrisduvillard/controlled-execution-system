"""Sensor result models (D-09) -- computational and engineering practice sensors.

SensorFinding captures a single structured finding from a sensor.
SensorResult captures a single sensor execution result with optional findings.
SensorPackResult captures the aggregate results for a sensor pack.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from ces.shared.base import CESBaseModel


class SensorFinding(CESBaseModel):
    """A single structured finding from a sensor execution.

    Frozen CESBaseModel: findings are immutable once produced.

    Fields:
        category: Finding category (e.g., "secret_detected", "nested_loop").
        severity: Finding severity level.
        location: File and line location (e.g., "src/app.py:42") or empty for project-level.
        message: Human-readable description of the finding.
        suggestion: Actionable fix suggestion.
    """

    category: str
    severity: Literal["critical", "high", "medium", "low", "info"]
    location: str
    message: str
    suggestion: str


class SensorResult(CESBaseModel):
    """Result of a single sensor execution.

    Frozen CESBaseModel: sensor results are immutable once produced.

    Fields:
        sensor_id: Unique identifier for the sensor.
        sensor_pack: Which sensor pack this sensor belongs to.
        passed: Whether the sensor check passed.
        score: Normalized score between 0.0 and 1.0.
        details: Human-readable details about the result.
        timestamp: When the sensor was executed.
        findings: Tuple of structured findings (immutable, default empty).
        skipped: Whether the sensor was skipped (e.g., no applicable files).
        skip_reason: Reason the sensor was skipped, if applicable.
    """

    sensor_id: str
    sensor_pack: str
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    details: str
    timestamp: datetime
    findings: tuple[SensorFinding, ...] = ()
    skipped: bool = False
    skip_reason: str | None = None
    configured: bool | None = None
    required: bool | None = None
    reason: str | None = None


class SensorPackResult(CESBaseModel):
    """Aggregate result for a sensor pack.

    Frozen CESBaseModel containing all individual sensor results
    and computed aggregates.

    Fields:
        pack_name: Name of the sensor pack.
        results: Tuple of individual sensor results (immutable).
        pass_rate: Fraction of sensors that passed (0.0 to 1.0).
        all_passed: Whether every sensor in the pack passed.
    """

    pack_name: str
    results: tuple[SensorResult, ...]
    pass_rate: float
    all_passed: bool
