"""Tests for GuidePackBudget, GuidePackContents, and GuidePackResult (D-12, D-13)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ces.harness.models.guide_pack import (
    GuidePackBudget,
    GuidePackContents,
    GuidePackResult,
)


class TestGuidePackBudget:
    """GuidePackBudget frozen model tests."""

    def test_create_with_defaults(self) -> None:
        budget = GuidePackBudget(total_budget_tokens=10000)
        assert budget.total_budget_tokens == 10000
        assert budget.truth_artifact_quota == 0.40
        assert budget.vault_notes_quota == 0.30
        assert budget.harness_context_quota == 0.30

    def test_truth_artifact_tokens(self) -> None:
        budget = GuidePackBudget(total_budget_tokens=10000)
        assert budget.truth_artifact_tokens == 4000

    def test_vault_notes_tokens(self) -> None:
        budget = GuidePackBudget(total_budget_tokens=10000)
        assert budget.vault_notes_tokens == 3000

    def test_harness_context_tokens_gets_remainder(self) -> None:
        """Harness context gets remainder to avoid rounding loss."""
        budget = GuidePackBudget(total_budget_tokens=10000)
        assert budget.harness_context_tokens == 3000
        # All tokens accounted for
        total = budget.truth_artifact_tokens + budget.vault_notes_tokens + budget.harness_context_tokens
        assert total == 10000

    def test_rounding_remainder_goes_to_harness(self) -> None:
        """With odd token counts, remainder goes to harness_context."""
        budget = GuidePackBudget(total_budget_tokens=10001)
        total = budget.truth_artifact_tokens + budget.vault_notes_tokens + budget.harness_context_tokens
        assert total == 10001

    def test_frozen(self) -> None:
        budget = GuidePackBudget(total_budget_tokens=10000)
        with pytest.raises(ValidationError):
            budget.total_budget_tokens = 5000  # type: ignore[misc]

    def test_custom_quotas(self) -> None:
        budget = GuidePackBudget(
            total_budget_tokens=10000,
            truth_artifact_quota=0.50,
            vault_notes_quota=0.25,
            harness_context_quota=0.25,
        )
        assert budget.truth_artifact_tokens == 5000
        assert budget.vault_notes_tokens == 2500
        assert budget.harness_context_tokens == 2500


class TestGuidePackContents:
    """GuidePackContents frozen model tests."""

    def test_create_with_valid_data(self) -> None:
        contents = GuidePackContents(
            truth_artifacts="manifest content...",
            vault_notes="vault notes...",
            harness_context="harness context...",
            total_tokens_used=5000,
        )
        assert contents.truth_artifacts == "manifest content..."
        assert contents.total_tokens_used == 5000

    def test_frozen(self) -> None:
        contents = GuidePackContents(
            truth_artifacts="a",
            vault_notes="b",
            harness_context="c",
            total_tokens_used=100,
        )
        with pytest.raises(ValidationError):
            contents.total_tokens_used = 200  # type: ignore[misc]


class TestGuidePackResult:
    """GuidePackResult frozen model tests."""

    def test_successful_result(self) -> None:
        budget = GuidePackBudget(total_budget_tokens=10000)
        contents = GuidePackContents(
            truth_artifacts="a",
            vault_notes="b",
            harness_context="c",
            total_tokens_used=5000,
        )
        result = GuidePackResult(
            success=True,
            contents=contents,
            total_tokens_used=5000,
            budget=budget,
        )
        assert result.success is True
        assert result.contents is not None
        assert result.oversized is False

    def test_oversized_result_has_success_false(self) -> None:
        budget = GuidePackBudget(total_budget_tokens=10000)
        result = GuidePackResult(
            success=False,
            oversized=True,
            oversized_reason="Task exceeds context budget by 5000 tokens",
            total_tokens_used=15000,
            budget=budget,
        )
        assert result.success is False
        assert result.oversized is True
        assert result.contents is None

    def test_frozen(self) -> None:
        budget = GuidePackBudget(total_budget_tokens=10000)
        result = GuidePackResult(
            success=True,
            total_tokens_used=1000,
            budget=budget,
        )
        with pytest.raises(ValidationError):
            result.success = False  # type: ignore[misc]
