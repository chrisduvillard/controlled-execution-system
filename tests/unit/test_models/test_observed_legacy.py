"""Tests for ObservedLegacyBehavior model (MODEL-15)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ces.harness.models.observed_legacy import ObservedLegacyBehavior
from ces.shared.enums import LegacyDisposition


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_legacy(**overrides: object) -> ObservedLegacyBehavior:
    """Create a valid ObservedLegacyBehavior with sensible defaults."""
    defaults = {
        "entry_id": "OLB-001",
        "system": "payment-service",
        "behavior_description": "Retries failed transactions up to 3 times with exponential backoff",
        "inferred_by": "agent-alpha",
        "inferred_at": _now(),
        "confidence": 0.85,
    }
    defaults.update(overrides)
    return ObservedLegacyBehavior(**defaults)


class TestObservedLegacyBehaviorBasicFields:
    """Tests for basic fields."""

    def test_create_entry(self) -> None:
        entry = _make_legacy()
        assert entry.entry_id == "OLB-001"
        assert entry.system == "payment-service"
        assert entry.behavior_description == "Retries failed transactions up to 3 times with exponential backoff"
        assert entry.inferred_by == "agent-alpha"
        assert entry.confidence == 0.85

    def test_confidence_bounds_valid(self) -> None:
        entry = _make_legacy(confidence=0.0)
        assert entry.confidence == 0.0

        entry = _make_legacy(confidence=1.0)
        assert entry.confidence == 1.0

    def test_confidence_above_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_legacy(confidence=1.1)

    def test_confidence_below_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_legacy(confidence=-0.1)


class TestObservedLegacyBehaviorDisposition:
    """Tests for disposition field."""

    def test_disposition_default_none(self) -> None:
        entry = _make_legacy()
        assert entry.disposition is None

    def test_disposition_set(self) -> None:
        entry = _make_legacy(disposition=LegacyDisposition.PRESERVE)
        assert entry.disposition == LegacyDisposition.PRESERVE

    def test_all_dispositions(self) -> None:
        for disp in LegacyDisposition:
            entry = _make_legacy(disposition=disp)
            assert entry.disposition == disp


class TestObservedLegacyBehaviorReview:
    """Tests for review fields."""

    def test_reviewed_by_default_none(self) -> None:
        entry = _make_legacy()
        assert entry.reviewed_by is None

    def test_reviewed_at_default_none(self) -> None:
        entry = _make_legacy()
        assert entry.reviewed_at is None

    def test_reviewed_fields_set(self) -> None:
        now = _now()
        entry = _make_legacy(
            disposition=LegacyDisposition.CHANGE,
            reviewed_by="human-engineer",
            reviewed_at=now,
        )
        assert entry.reviewed_by == "human-engineer"
        assert entry.reviewed_at == now


class TestObservedLegacyBehaviorPromotion:
    """Tests for promoted_to_prl_id field."""

    def test_promoted_to_prl_id_default_none(self) -> None:
        entry = _make_legacy()
        assert entry.promoted_to_prl_id is None

    def test_promoted_to_prl_id_set(self) -> None:
        entry = _make_legacy(
            disposition=LegacyDisposition.PRESERVE,
            promoted_to_prl_id="PRL-099",
        )
        assert entry.promoted_to_prl_id == "PRL-099"

    def test_promoted_requires_disposition(self) -> None:
        """Cannot promote without first having a disposition."""
        with pytest.raises(ValidationError, match="disposition"):
            _make_legacy(
                disposition=None,
                promoted_to_prl_id="PRL-099",
            )


class TestObservedLegacyBehaviorDiscard:
    """Tests for discarded field."""

    def test_discarded_default_false(self) -> None:
        entry = _make_legacy()
        assert entry.discarded is False

    def test_discarded_set(self) -> None:
        entry = _make_legacy(discarded=True)
        assert entry.discarded is True

    def test_discarded_cannot_be_promoted(self) -> None:
        """Discarded entries cannot have a PRL promotion."""
        with pytest.raises(ValidationError, match="promoted"):
            _make_legacy(
                disposition=LegacyDisposition.PRESERVE,
                promoted_to_prl_id="PRL-099",
                discarded=True,
            )


class TestObservedLegacyBehaviorDispositionFlow:
    """Tests for the disposition flow: None -> reviewed -> promoted."""

    def test_flow_pending(self) -> None:
        """Initial state: no disposition, no review, no promotion."""
        entry = _make_legacy()
        assert entry.disposition is None
        assert entry.reviewed_by is None
        assert entry.promoted_to_prl_id is None

    def test_flow_reviewed(self) -> None:
        """After review: disposition set, optionally reviewed_by/at."""
        entry = _make_legacy(
            disposition=LegacyDisposition.CHANGE,
            reviewed_by="engineer",
            reviewed_at=_now(),
        )
        assert entry.disposition == LegacyDisposition.CHANGE
        assert entry.promoted_to_prl_id is None

    def test_flow_promoted(self) -> None:
        """After promotion: disposition set and promoted_to_prl_id set."""
        entry = _make_legacy(
            disposition=LegacyDisposition.PRESERVE,
            reviewed_by="engineer",
            reviewed_at=_now(),
            promoted_to_prl_id="PRL-042",
        )
        assert entry.disposition == LegacyDisposition.PRESERVE
        assert entry.promoted_to_prl_id == "PRL-042"


class TestObservedLegacyBehaviorMutability:
    """Tests that ObservedLegacyBehavior is NOT frozen (disposition changes)."""

    def test_disposition_mutable(self) -> None:
        entry = _make_legacy()
        entry.disposition = LegacyDisposition.RETIRE
        assert entry.disposition == LegacyDisposition.RETIRE

    def test_reviewed_by_mutable(self) -> None:
        entry = _make_legacy()
        entry.reviewed_by = "reviewer"
        assert entry.reviewed_by == "reviewer"
