"""Tests for DispositionWorkflow state machine (BROWN-03).

Verifies the three-state disposition workflow:
    pending -> reviewed -> promoted_to_prl OR discarded

Invalid transitions must raise TransitionNotAllowed.
"""

from __future__ import annotations

import pytest
from statemachine.exceptions import TransitionNotAllowed

from ces.brownfield.services.disposition_workflow import DispositionWorkflow


class TestDispositionWorkflow:
    """Test suite for DispositionWorkflow state machine."""

    def test_starts_in_pending_state(self) -> None:
        """Test 6: DispositionWorkflow starts in pending state."""
        wf = DispositionWorkflow()
        assert next(iter(wf.configuration)).id == "pending"

    def test_valid_transitions_to_promoted(self) -> None:
        """Test 7a: pending -> reviewed -> promoted_to_prl is valid."""
        wf = DispositionWorkflow()
        wf.review()
        assert next(iter(wf.configuration)).id == "reviewed"
        wf.promote()
        assert next(iter(wf.configuration)).id == "promoted_to_prl"

    def test_valid_transitions_to_discarded(self) -> None:
        """Test 7b: pending -> reviewed -> discarded is valid."""
        wf = DispositionWorkflow()
        wf.review()
        assert next(iter(wf.configuration)).id == "reviewed"
        wf.discard()
        assert next(iter(wf.configuration)).id == "discarded"

    def test_cannot_promote_from_discarded(self) -> None:
        """Test 8a: Cannot transition from discarded to promoted."""
        wf = DispositionWorkflow()
        wf.review()
        wf.discard()
        with pytest.raises(TransitionNotAllowed):
            wf.promote()

    def test_cannot_discard_from_promoted(self) -> None:
        """Test 8b: Cannot transition from promoted to discarded."""
        wf = DispositionWorkflow()
        wf.review()
        wf.promote()
        with pytest.raises(TransitionNotAllowed):
            wf.discard()

    def test_cannot_skip_review(self) -> None:
        """Cannot promote directly from pending (must go through reviewed)."""
        wf = DispositionWorkflow()
        with pytest.raises(TransitionNotAllowed):
            wf.promote()

    def test_cannot_discard_from_pending(self) -> None:
        """Cannot discard directly from pending (must go through reviewed)."""
        wf = DispositionWorkflow()
        with pytest.raises(TransitionNotAllowed):
            wf.discard()

    def test_reconstructed_from_reviewed(self) -> None:
        """Can reconstruct workflow from reviewed state."""
        wf = DispositionWorkflow(start_value="reviewed")
        assert next(iter(wf.configuration)).id == "reviewed"
        wf.promote()
        assert next(iter(wf.configuration)).id == "promoted_to_prl"
