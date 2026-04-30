"""Tests for DisclosureSet frozen model (D-04).

Validates that DisclosureSet captures retries, skipped checks,
summarized context, and disagreements as frozen fields.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ces.harness.models.disclosure_set import DisclosureSet


class TestDisclosureSet:
    """DisclosureSet (D-04) tests."""

    def test_create_with_valid_data(self) -> None:
        """DisclosureSet can be created with valid data."""
        ds = DisclosureSet(
            retries_used=2,
            skipped_checks=("lint", "type-check"),
            summarized_context=True,
            summarization_details="Truncated to 4k tokens",
            disagreements=("Reviewer A vs B on security",),
        )
        assert ds.retries_used == 2
        assert ds.skipped_checks == ("lint", "type-check")
        assert ds.summarized_context is True
        assert ds.summarization_details == "Truncated to 4k tokens"
        assert ds.disagreements == ("Reviewer A vs B on security",)

    def test_create_with_minimal_data(self) -> None:
        """DisclosureSet works with minimal required fields."""
        ds = DisclosureSet(
            retries_used=0,
            skipped_checks=(),
            summarized_context=False,
            disagreements=(),
        )
        assert ds.retries_used == 0
        assert ds.summarization_details is None

    def test_frozen_immutability(self) -> None:
        """DisclosureSet is frozen -- assignment raises ValidationError."""
        ds = DisclosureSet(
            retries_used=1,
            skipped_checks=(),
            summarized_context=False,
            disagreements=(),
        )
        with pytest.raises(ValidationError):
            ds.retries_used = 5  # type: ignore[misc]

    def test_retries_used_must_be_int(self) -> None:
        """retries_used must be an int (strict mode)."""
        with pytest.raises(ValidationError):
            DisclosureSet(
                retries_used="two",  # type: ignore[arg-type]
                skipped_checks=(),
                summarized_context=False,
                disagreements=(),
            )

    def test_skipped_checks_must_be_list_of_str(self) -> None:
        """skipped_checks must be a list of strings."""
        with pytest.raises(ValidationError):
            DisclosureSet(
                retries_used=0,
                skipped_checks=(1, 2, 3),  # type: ignore[arg-type]
                summarized_context=False,
                disagreements=(),
            )
