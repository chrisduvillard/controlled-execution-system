"""Tests for ReviewFinding and ReviewResult frozen models."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ces.harness.models.review_assignment import ReviewAssignment, ReviewerRole
from ces.harness.models.review_finding import (
    ReviewFinding,
    ReviewFindingSeverity,
    ReviewResult,
)


class TestReviewFinding:
    """ReviewFinding frozen model tests."""

    def test_create_finding_with_valid_data(self) -> None:
        finding = ReviewFinding(
            finding_id="f-001",
            reviewer_role=ReviewerRole.STRUCTURAL,
            severity=ReviewFindingSeverity.HIGH,
            category="architecture",
            file_path="src/app.py",
            line_number=42,
            title="Missing error handling",
            description="The function does not handle the case where input is None.",
            recommendation="Add a guard clause at the top of the function.",
            confidence=0.9,
        )
        assert finding.finding_id == "f-001"
        assert finding.reviewer_role == ReviewerRole.STRUCTURAL
        assert finding.severity == ReviewFindingSeverity.HIGH
        assert finding.category == "architecture"
        assert finding.file_path == "src/app.py"
        assert finding.line_number == 42
        assert finding.title == "Missing error handling"
        assert finding.confidence == 0.9

    def test_finding_frozen(self) -> None:
        finding = ReviewFinding(
            finding_id="f-001",
            reviewer_role=ReviewerRole.SEMANTIC,
            severity=ReviewFindingSeverity.MEDIUM,
            category="logic_error",
            title="Off-by-one error",
            description="Loop iterates one too many times.",
            recommendation="Use < instead of <=.",
        )
        with pytest.raises(ValidationError):
            finding.title = "Changed"  # type: ignore[misc]

    def test_confidence_must_be_between_0_and_1(self) -> None:
        """confidence must be 0.0 <= confidence <= 1.0."""
        with pytest.raises(ValidationError):
            ReviewFinding(
                finding_id="f-001",
                reviewer_role=ReviewerRole.RED_TEAM,
                severity=ReviewFindingSeverity.CRITICAL,
                category="security_vuln",
                title="SQL injection",
                description="Unsanitized input in query.",
                recommendation="Use parameterized queries.",
                confidence=1.5,
            )

    def test_confidence_cannot_be_negative(self) -> None:
        with pytest.raises(ValidationError):
            ReviewFinding(
                finding_id="f-001",
                reviewer_role=ReviewerRole.STRUCTURAL,
                severity=ReviewFindingSeverity.LOW,
                category="style",
                title="Naming convention",
                description="Variable name is unclear.",
                recommendation="Rename to something descriptive.",
                confidence=-0.1,
            )

    def test_severity_enum_values(self) -> None:
        assert ReviewFindingSeverity.CRITICAL == "critical"
        assert ReviewFindingSeverity.HIGH == "high"
        assert ReviewFindingSeverity.MEDIUM == "medium"
        assert ReviewFindingSeverity.LOW == "low"
        assert ReviewFindingSeverity.INFO == "info"

    def test_finding_optional_fields_default_to_none(self) -> None:
        finding = ReviewFinding(
            finding_id="f-002",
            reviewer_role=ReviewerRole.SEMANTIC,
            severity=ReviewFindingSeverity.INFO,
            category="documentation",
            title="Missing docstring",
            description="Public function lacks a docstring.",
            recommendation="Add a docstring.",
        )
        assert finding.file_path is None
        assert finding.line_number is None


class TestReviewResult:
    """ReviewResult frozen model tests."""

    def _make_assignment(self) -> ReviewAssignment:
        return ReviewAssignment(
            role=ReviewerRole.STRUCTURAL,
            model_id="claude-3-opus",
            agent_id="agent-001",
        )

    def test_create_result_with_valid_data(self) -> None:
        assignment = self._make_assignment()
        finding = ReviewFinding(
            finding_id="f-001",
            reviewer_role=ReviewerRole.STRUCTURAL,
            severity=ReviewFindingSeverity.HIGH,
            category="architecture",
            title="Circular dependency",
            description="Module A imports Module B which imports Module A.",
            recommendation="Extract shared interface.",
            confidence=0.85,
        )
        result = ReviewResult(
            assignment=assignment,
            findings=(finding,),
            summary="Found 1 architectural issue.",
            review_duration_seconds=12.5,
            model_version="claude-3-opus-20240229",
            tokens_used=1500,
        )
        assert result.assignment == assignment
        assert len(result.findings) == 1
        assert result.summary == "Found 1 architectural issue."
        assert result.review_duration_seconds == 12.5
        assert result.model_version == "claude-3-opus-20240229"
        assert result.tokens_used == 1500
        assert result.timestamp is not None

    def test_result_frozen(self) -> None:
        assignment = self._make_assignment()
        result = ReviewResult(
            assignment=assignment,
            summary="OK",
            review_duration_seconds=1.0,
        )
        with pytest.raises(ValidationError):
            result.summary = "Changed"  # type: ignore[misc]

    def test_result_empty_findings_default(self) -> None:
        assignment = self._make_assignment()
        result = ReviewResult(
            assignment=assignment,
            review_duration_seconds=5.0,
        )
        assert result.findings == ()

    def test_result_tokens_used_cannot_be_negative(self) -> None:
        assignment = self._make_assignment()
        with pytest.raises(ValidationError):
            ReviewResult(
                assignment=assignment,
                review_duration_seconds=1.0,
                tokens_used=-1,
            )

    def test_result_duration_cannot_be_negative(self) -> None:
        assignment = self._make_assignment()
        with pytest.raises(ValidationError):
            ReviewResult(
                assignment=assignment,
                review_duration_seconds=-1.0,
            )
