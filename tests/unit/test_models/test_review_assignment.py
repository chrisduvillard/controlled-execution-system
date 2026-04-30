"""Tests for ReviewAssignment and ReviewerRole (D-05, D-06)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ces.harness.models.review_assignment import (
    IndependenceViolation,
    ReviewAssignment,
    ReviewerRole,
)


class TestReviewerRole:
    """ReviewerRole enum tests."""

    def test_values(self) -> None:
        assert ReviewerRole.STRUCTURAL == "structural"
        assert ReviewerRole.SEMANTIC == "semantic"
        assert ReviewerRole.RED_TEAM == "red_team"


class TestReviewAssignment:
    """ReviewAssignment frozen model tests."""

    def test_create_with_valid_data(self) -> None:
        ra = ReviewAssignment(
            role=ReviewerRole.STRUCTURAL,
            model_id="claude-3-opus",
            agent_id="agent-001",
        )
        assert ra.role == ReviewerRole.STRUCTURAL
        assert ra.model_id == "claude-3-opus"
        assert ra.agent_id == "agent-001"

    def test_frozen(self) -> None:
        ra = ReviewAssignment(
            role=ReviewerRole.SEMANTIC,
            model_id="gpt-4o",
            agent_id="agent-002",
        )
        with pytest.raises(ValidationError):
            ra.role = ReviewerRole.RED_TEAM  # type: ignore[misc]

    def test_invalid_role_rejected(self) -> None:
        """Invalid role string rejected by strict enum validation."""
        with pytest.raises(ValidationError):
            ReviewAssignment(
                role="invalid_role",  # type: ignore[arg-type]
                model_id="claude-3-opus",
                agent_id="agent-001",
            )


class TestIndependenceViolation:
    """IndependenceViolation frozen model tests."""

    def test_create_with_valid_data(self) -> None:
        iv = IndependenceViolation(
            violation_type="self_review",
            details="Agent-001 reviewed its own output",
        )
        assert iv.violation_type == "self_review"
        assert iv.details == "Agent-001 reviewed its own output"

    def test_frozen(self) -> None:
        iv = IndependenceViolation(
            violation_type="model_overlap",
            details="Two reviewers share same model",
        )
        with pytest.raises(ValidationError):
            iv.violation_type = "other"  # type: ignore[misc]
