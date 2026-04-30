"""Review finding models -- structured output from LLM-based code review.

ReviewFindingSeverity defines finding severity levels.
ReviewFinding captures a single structured finding from a reviewer.
ReviewResult captures the complete output from a single review execution.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import Field

from ces.harness.models.review_assignment import ReviewAssignment, ReviewerRole
from ces.shared.base import CESBaseModel


class ReviewFindingSeverity(str, Enum):
    """Severity level for review findings."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ReviewFinding(CESBaseModel):
    """A single structured finding from a code review.

    Frozen CESBaseModel: findings are immutable once produced.

    Fields:
        finding_id: Unique identifier for this finding.
        reviewer_role: Which reviewer role produced this finding.
        severity: Finding severity level.
        category: Finding category (e.g., "architecture", "logic_error", "security_vuln").
        file_path: File where the issue was found, if applicable.
        line_number: Line number in the file, if applicable.
        title: Short title describing the finding.
        description: Detailed description of the issue.
        recommendation: Actionable fix recommendation.
        confidence: Reviewer's confidence in this finding (0.0 to 1.0).
    """

    finding_id: str
    reviewer_role: ReviewerRole
    severity: ReviewFindingSeverity
    category: str
    file_path: str | None = None
    line_number: int | None = None
    title: str
    description: str
    recommendation: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)


class ReviewResult(CESBaseModel):
    """Complete output from a single review execution.

    Captures all findings from one reviewer along with metadata
    about the review execution.

    Fields:
        assignment: The review assignment that produced this result.
        findings: Tuple of structured findings (immutable).
        summary: Brief summary of the review.
        review_duration_seconds: How long the review took.
        model_version: The actual model version that performed the review.
        tokens_used: Total tokens consumed by the review.
        timestamp: When the review was executed.
    """

    assignment: ReviewAssignment
    findings: tuple[ReviewFinding, ...] = ()
    summary: str = ""
    review_duration_seconds: float = Field(ge=0.0)
    model_version: str = ""
    tokens_used: int = Field(ge=0, default=0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
