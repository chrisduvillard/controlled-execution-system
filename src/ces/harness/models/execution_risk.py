"""Models for cross-step execution risk monitoring."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import Field

from ces.shared.base import CESBaseModel


class ExecutionRiskSeverity(StrEnum):
    """Severity values used by execution-risk findings."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ExecutionRiskKind(StrEnum):
    """Known cross-step execution anti-patterns."""

    REPEATED_FAILURE = "repeated_failure"
    SHALLOW_VALIDATION = "shallow_validation"
    PROXY_VALIDATION = "proxy_validation"
    TIMEOUT_LOOP = "timeout_loop"
    DESTRUCTIVE_AFTER_SUCCESS = "destructive_after_success"
    COMPILE_ONLY_VALIDATION = "compile_only_validation"


class ExecutionCommandEvent(CESBaseModel):
    """One observed command event in a local execution trajectory."""

    command: str = Field(min_length=1, max_length=500)
    exit_code: int | None = None
    output_excerpt: str = Field(default="", max_length=4_000)
    after_success: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExecutionRiskFinding(CESBaseModel):
    """A deterministic command-sequence risk finding."""

    kind: ExecutionRiskKind
    severity: ExecutionRiskSeverity
    command: str
    message: str
    recommended_action: str
    evidence_refs: tuple[str, ...] = ()

    @property
    def sensor_severity(self) -> Literal["critical", "high", "medium", "low", "info"]:
        """Return severity as a SensorFinding-compatible literal."""
        return self.severity.value  # type: ignore[return-value]
