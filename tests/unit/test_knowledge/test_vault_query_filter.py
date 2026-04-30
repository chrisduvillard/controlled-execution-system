"""Unit tests for vault query filter (VAULT-06).

Tests the informational-only filter that hard-enforces VAULT-06:
The Knowledge Vault must NEVER answer requirement, policy, or
risk-acceptance questions.

Tests cover category-aware + keyword-based combined filtering to
avoid over-aggressive filtering (research Pitfall 4).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ces.control.models.knowledge_vault import VaultNote
from ces.shared.enums import VaultCategory, VaultTrustLevel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_note(
    *,
    note_id: str = "VN-filter001",
    category: VaultCategory = VaultCategory.DISCOVERY,
    trust_level: VaultTrustLevel = VaultTrustLevel.AGENT_INFERRED,
    content: str = "Test content",
) -> VaultNote:
    """Create a VaultNote for filter testing."""
    return VaultNote(
        note_id=note_id,
        category=category,
        trust_level=trust_level,
        content=content,
        source="test",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Test 1: filter_informational_only() keeps notes in discovery, domain, patterns
# ---------------------------------------------------------------------------


def test_filter_keeps_informational_notes():
    """filter_informational_only() keeps notes in discovery, domain, patterns categories."""
    from ces.knowledge.services.vault_query_filter import (
        filter_informational_only,
    )

    notes = [
        _make_note(
            note_id="VN-d1",
            category=VaultCategory.DISCOVERY,
            content="Found a new API endpoint for data retrieval",
        ),
        _make_note(
            note_id="VN-d2",
            category=VaultCategory.DOMAIN,
            content="The payment domain uses event sourcing",
        ),
        _make_note(
            note_id="VN-d3",
            category=VaultCategory.PATTERNS,
            content="Repository pattern used for data access",
        ),
    ]

    result = filter_informational_only(notes)

    assert len(result) == 3
    ids = {n.note_id for n in result}
    assert ids == {"VN-d1", "VN-d2", "VN-d3"}


# ---------------------------------------------------------------------------
# Test 2: filter_informational_only() strips notes with policy keywords
# ---------------------------------------------------------------------------


def test_filter_strips_policy_adjacent_notes():
    """filter_informational_only() strips notes containing policy keywords in decisions category."""
    from ces.knowledge.services.vault_query_filter import (
        filter_informational_only,
    )

    notes = [
        _make_note(
            note_id="VN-safe",
            category=VaultCategory.DISCOVERY,
            content="Found interesting design pattern",
        ),
        _make_note(
            note_id="VN-policy1",
            category=VaultCategory.DECISIONS,
            content="This requirement mandates encryption at rest",
        ),
        _make_note(
            note_id="VN-policy2",
            category=VaultCategory.DECISIONS,
            content="The policy states all data must be encrypted",
        ),
    ]

    result = filter_informational_only(notes)

    ids = {n.note_id for n in result}
    assert "VN-safe" in ids
    assert "VN-policy1" not in ids
    assert "VN-policy2" not in ids


# ---------------------------------------------------------------------------
# Test 3: filter uses category + keyword combined check
# ---------------------------------------------------------------------------


def test_filter_uses_category_keyword_combined_check():
    """filter_informational_only() uses category-based + keyword-based combined check."""
    from ces.knowledge.services.vault_query_filter import (
        filter_informational_only,
    )

    # A note in DECISIONS with a policy keyword should be filtered
    decisions_note = _make_note(
        note_id="VN-dec1",
        category=VaultCategory.DECISIONS,
        content="This is a requirement for the system",
    )

    # A note in DISCOVERY with same keyword should NOT be filtered
    # (looser threshold for non-policy categories - needs 2+ keywords)
    discovery_note = _make_note(
        note_id="VN-disc1",
        category=VaultCategory.DISCOVERY,
        content="Found a requirement in the codebase comments",
    )

    result = filter_informational_only([decisions_note, discovery_note])

    ids = {n.note_id for n in result}
    assert "VN-dec1" not in ids  # Filtered: decisions + 1 keyword
    assert "VN-disc1" in ids  # Kept: discovery + only 1 keyword


# ---------------------------------------------------------------------------
# Test 4: preserves notes with "must" in non-policy context
# ---------------------------------------------------------------------------


def test_filter_preserves_must_in_non_policy_context():
    """filter_informational_only() preserves notes with 'must' in non-policy context."""
    from ces.knowledge.services.vault_query_filter import (
        filter_informational_only,
    )

    # "must" in calibration context is informational
    note = _make_note(
        note_id="VN-cal1",
        category=VaultCategory.CALIBRATION,
        content="Sensors must recalibrate every 24 hours for accuracy",
    )

    result = filter_informational_only([note])

    # Only 1 keyword in non-policy category = not filtered
    assert len(result) == 1
    assert result[0].note_id == "VN-cal1"


# ---------------------------------------------------------------------------
# Test 5: _is_policy_adjacent() returns True for decisions + requirement
# ---------------------------------------------------------------------------


def test_is_policy_adjacent_true_for_decisions_with_requirement():
    """_is_policy_adjacent() returns True for notes in decisions category containing 'requirement'."""
    from ces.knowledge.services.vault_query_filter import _is_policy_adjacent

    note = _make_note(
        category=VaultCategory.DECISIONS,
        content="This is a requirement from the stakeholder",
    )

    assert _is_policy_adjacent(note) is True


# ---------------------------------------------------------------------------
# Test 6: _is_policy_adjacent() returns False for substring match
# ---------------------------------------------------------------------------


def test_is_policy_adjacent_false_for_substring_match():
    """_is_policy_adjacent() returns False for 'requirement' as substring in non-policy category."""
    from ces.knowledge.services.vault_query_filter import _is_policy_adjacent

    # "requirements.txt" contains "requirement" as a substring but not
    # as a whole word -- word boundary regex should not match
    note = _make_note(
        category=VaultCategory.DOMAIN,
        content="The project uses a requirements.txt file for dependencies",
    )

    # "requirements" matches "requirement" with word boundary because
    # "requirements" starts with "requirement" but the "s" breaks the boundary.
    # Actually \brequirement\b won't match "requirements" - correct!
    # But "requirements" does NOT match \brequirement\b.
    # Only 0 keywords matched in non-policy category = not filtered
    assert _is_policy_adjacent(note) is False
