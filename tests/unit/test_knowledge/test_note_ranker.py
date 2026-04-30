"""Unit tests for NoteRanker (VAULT-05).

Tests tier-based note selection and relevance ranking for guide pack
assembly. Tier limits: A=3, B=5, C=10. Scoring uses trust weight,
tag overlap, and recency bonus.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ces.control.models.knowledge_vault import VaultNote
from ces.shared.enums import RiskTier, VaultCategory, VaultTrustLevel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_note(
    *,
    note_id: str = "VN-rank001",
    trust_level: VaultTrustLevel = VaultTrustLevel.AGENT_INFERRED,
    tags: tuple[str, ...] | None = None,
    updated_at: datetime | None = None,
    content: str = "Test note content",
) -> VaultNote:
    """Create a VaultNote for ranking tests."""
    return VaultNote(
        note_id=note_id,
        category=VaultCategory.PATTERNS,
        trust_level=trust_level,
        content=content,
        source="test",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=updated_at or datetime.now(timezone.utc),
        tags=tags or (),
    )


# ---------------------------------------------------------------------------
# Test 7: NoteRanker.select_for_tier() returns max 10 notes for Tier C
# ---------------------------------------------------------------------------


def test_select_for_tier_c_returns_max_10():
    """NoteRanker.select_for_tier() returns max 10 notes for Tier C."""
    from ces.knowledge.services.note_ranker import NoteRanker

    notes = [_make_note(note_id=f"VN-c{i:03d}", tags=("test",)) for i in range(15)]

    result = NoteRanker.select_for_tier(
        notes,
        RiskTier.C,
        relevance_tags=("test",),
    )

    assert len(result) <= 10


# ---------------------------------------------------------------------------
# Test 8: NoteRanker.select_for_tier() returns max 5 notes for Tier B
# ---------------------------------------------------------------------------


def test_select_for_tier_b_returns_max_5():
    """NoteRanker.select_for_tier() returns max 5 notes for Tier B."""
    from ces.knowledge.services.note_ranker import NoteRanker

    notes = [_make_note(note_id=f"VN-b{i:03d}", tags=("auth",)) for i in range(15)]

    result = NoteRanker.select_for_tier(
        notes,
        RiskTier.B,
        relevance_tags=("auth",),
    )

    assert len(result) <= 5


# ---------------------------------------------------------------------------
# Test 9: NoteRanker.select_for_tier() returns max 3 notes for Tier A
# ---------------------------------------------------------------------------


def test_select_for_tier_a_returns_max_3():
    """NoteRanker.select_for_tier() returns max 3 notes for Tier A."""
    from ces.knowledge.services.note_ranker import NoteRanker

    notes = [_make_note(note_id=f"VN-a{i:03d}", tags=("security",)) for i in range(15)]

    result = NoteRanker.select_for_tier(
        notes,
        RiskTier.A,
        relevance_tags=("security",),
    )

    assert len(result) <= 3


# ---------------------------------------------------------------------------
# Test 10: NoteRanker.rank_notes() scores verified notes higher
# ---------------------------------------------------------------------------


def test_rank_notes_scores_verified_higher():
    """NoteRanker.rank_notes() scores verified notes higher than agent-inferred."""
    from ces.knowledge.services.note_ranker import NoteRanker

    verified = _make_note(
        note_id="VN-verified",
        trust_level=VaultTrustLevel.VERIFIED,
        tags=("auth",),
    )
    agent_inferred = _make_note(
        note_id="VN-inferred",
        trust_level=VaultTrustLevel.AGENT_INFERRED,
        tags=("auth",),
    )

    result = NoteRanker.rank_notes(
        [agent_inferred, verified],
        relevance_tags=("auth",),
    )

    assert result[0].note_id == "VN-verified"


# ---------------------------------------------------------------------------
# Test 11: rank_notes() scores notes with more tag overlap higher
# ---------------------------------------------------------------------------


def test_rank_notes_scores_more_tag_overlap_higher():
    """NoteRanker.rank_notes() scores notes with more tag overlap higher."""
    from ces.knowledge.services.note_ranker import NoteRanker

    many_tags = _make_note(
        note_id="VN-tags3",
        tags=("auth", "security", "jwt"),
    )
    few_tags = _make_note(
        note_id="VN-tags1",
        tags=("auth",),
    )

    result = NoteRanker.rank_notes(
        [few_tags, many_tags],
        relevance_tags=("auth", "security", "jwt"),
    )

    assert result[0].note_id == "VN-tags3"


# ---------------------------------------------------------------------------
# Test 12: rank_notes() gives recency bonus to newer notes
# ---------------------------------------------------------------------------


def test_rank_notes_gives_recency_bonus():
    """NoteRanker.rank_notes() gives recency bonus to newer notes."""
    from ces.knowledge.services.note_ranker import NoteRanker

    now = datetime.now(timezone.utc)
    recent = _make_note(
        note_id="VN-recent",
        updated_at=now,
    )
    old = _make_note(
        note_id="VN-old",
        updated_at=now - timedelta(days=300),
    )

    result = NoteRanker.rank_notes(
        [old, recent],
        relevance_tags=[],
    )

    assert result[0].note_id == "VN-recent"


# ---------------------------------------------------------------------------
# Test 13: rank_notes() excludes stale-risk notes
# ---------------------------------------------------------------------------


def test_rank_notes_excludes_stale_risk():
    """NoteRanker.rank_notes() excludes stale-risk notes from ranking."""
    from ces.knowledge.services.note_ranker import NoteRanker

    stale = _make_note(
        note_id="VN-stale",
        trust_level=VaultTrustLevel.STALE_RISK,
        tags=("auth",),
    )
    good = _make_note(
        note_id="VN-good",
        trust_level=VaultTrustLevel.AGENT_INFERRED,
        tags=("auth",),
    )

    result = NoteRanker.rank_notes(
        [stale, good],
        relevance_tags=("auth",),
    )

    assert len(result) == 1
    assert result[0].note_id == "VN-good"
