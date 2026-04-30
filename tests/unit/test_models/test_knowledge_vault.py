"""Tests for VaultNote model (MODEL-14)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ces.control.models.knowledge_vault import VaultNote
from ces.shared.enums import VaultCategory, VaultTrustLevel


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_vault_note(**overrides: object) -> VaultNote:
    """Create a valid VaultNote with sensible defaults."""
    defaults = {
        "note_id": "VN-001",
        "category": VaultCategory.DECISIONS,
        "content": "Use PostgreSQL for all control plane state.",
        "trust_level": VaultTrustLevel.VERIFIED,
        "source": "architecture-review-2026-04",
        "created_at": _now(),
        "updated_at": _now(),
    }
    defaults.update(overrides)
    return VaultNote(**defaults)


class TestVaultNoteBasicFields:
    """Tests for basic VaultNote fields."""

    def test_create_note(self) -> None:
        note = _make_vault_note()
        assert note.note_id == "VN-001"
        assert note.category == VaultCategory.DECISIONS
        assert note.content == "Use PostgreSQL for all control plane state."
        assert note.trust_level == VaultTrustLevel.VERIFIED
        assert note.source == "architecture-review-2026-04"

    def test_all_categories(self) -> None:
        for cat in VaultCategory:
            note = _make_vault_note(category=cat)
            assert note.category == cat

    def test_all_trust_levels(self) -> None:
        for level in VaultTrustLevel:
            note = _make_vault_note(trust_level=level)
            assert note.trust_level == level


class TestVaultNoteOptionalFields:
    """Tests for optional and default fields."""

    def test_tags_default_empty(self) -> None:
        note = _make_vault_note()
        assert note.tags == ()

    def test_tags_set(self) -> None:
        note = _make_vault_note(tags=("architecture", "database"))
        assert note.tags == ("architecture", "database")

    def test_related_artifacts_default_empty(self) -> None:
        note = _make_vault_note()
        assert note.related_artifacts == ()

    def test_related_artifacts_set(self) -> None:
        note = _make_vault_note(related_artifacts=("PRL-001", "ICA-002"))
        assert note.related_artifacts == ("PRL-001", "ICA-002")

    def test_invalidation_trigger_default_none(self) -> None:
        note = _make_vault_note()
        assert note.invalidation_trigger is None

    def test_invalidation_trigger_set(self) -> None:
        note = _make_vault_note(invalidation_trigger="PRL-001 status change")
        assert note.invalidation_trigger == "PRL-001 status change"


class TestVaultNoteMutability:
    """Tests that VaultNote is NOT frozen (content may update)."""

    def test_content_mutable(self) -> None:
        note = _make_vault_note()
        note.content = "Updated content"
        assert note.content == "Updated content"

    def test_trust_level_mutable(self) -> None:
        note = _make_vault_note()
        note.trust_level = VaultTrustLevel.STALE_RISK
        assert note.trust_level == VaultTrustLevel.STALE_RISK


class TestVaultNoteNineCategoriesExist:
    """Test that all 9 vault categories exist."""

    def test_nine_categories(self) -> None:
        assert len(VaultCategory) == 9

    def test_expected_categories(self) -> None:
        expected = {
            "decisions",
            "patterns",
            "escapes",
            "discovery",
            "calibration",
            "harness",
            "domain",
            "stakeholders",
            "sessions",
        }
        actual = {c.value for c in VaultCategory}
        assert actual == expected


class TestVaultNoteThreeTrustLevels:
    """Test that all 3 trust levels exist."""

    def test_three_trust_levels(self) -> None:
        assert len(VaultTrustLevel) == 3

    def test_expected_trust_levels(self) -> None:
        expected = {"verified", "agent-inferred", "stale-risk"}
        actual = {t.value for t in VaultTrustLevel}
        assert actual == expected
