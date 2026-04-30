"""Unit tests for TrustDecayManager.

Tests trust level auto-decay logic (VAULT-02). Agent-inferred notes
decay to stale-risk after configurable category thresholds.
Verified notes NEVER decay automatically.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from ces.shared.enums import VaultCategory, VaultTrustLevel

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_vault_note_row(
    *,
    note_id: str = "VN-decay001",
    category: str = "patterns",
    trust_level: str = "agent-inferred",
    content: str = "Decayable content",
    source: str = "agent",
    updated_at: datetime | None = None,
) -> MagicMock:
    """Create a mock VaultNoteRow for decay testing."""
    row = MagicMock()
    row.note_id = note_id
    row.category = category
    row.trust_level = trust_level
    row.content = content
    row.source = source
    row.tags = []
    row.related_artifacts = []
    row.invalidation_trigger = None
    row.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    row.updated_at = updated_at or datetime(2025, 1, 1, tzinfo=timezone.utc)
    return row


@pytest.fixture()
def mock_repository():
    """Create a mock VaultRepository with async methods."""
    repo = MagicMock()
    repo.get_by_category = AsyncMock(return_value=[])
    repo.get_by_trust_level = AsyncMock(return_value=[])
    repo.update_trust_level = AsyncMock(return_value=None)
    return repo


@pytest.fixture()
def mock_audit_ledger():
    """Create a mock audit ledger."""
    ledger = MagicMock()
    ledger.record_truth_change = AsyncMock()
    return ledger


@pytest.fixture()
def decay_manager(mock_repository, mock_audit_ledger):
    """Create a TrustDecayManager with mocked dependencies."""
    from ces.knowledge.services.trust_decay import TrustDecayManager

    return TrustDecayManager(
        repository=mock_repository,
        audit_ledger=mock_audit_ledger,
    )


# ---------------------------------------------------------------------------
# Test 16: decay_stale_notes() transitions agent-inferred notes older
#           than threshold to stale-risk
# ---------------------------------------------------------------------------


async def test_decay_transitions_old_agent_inferred_to_stale_risk(
    decay_manager,
    mock_repository,
):
    """decay_stale_notes() transitions agent-inferred notes older than threshold to stale-risk."""
    # Create a note older than 60 days (patterns default threshold)
    old_note = _make_vault_note_row(
        note_id="VN-old001",
        category="patterns",
        trust_level="agent-inferred",
        updated_at=datetime.now(timezone.utc) - timedelta(days=90),
    )

    mock_repository.get_by_category = AsyncMock(return_value=[old_note])
    updated_row = _make_vault_note_row(
        note_id="VN-old001",
        trust_level="stale-risk",
    )
    mock_repository.update_trust_level = AsyncMock(return_value=updated_row)

    decayed = await decay_manager.decay_stale_notes()

    assert "VN-old001" in decayed
    mock_repository.update_trust_level.assert_awaited()


# ---------------------------------------------------------------------------
# Test 17: decay_stale_notes() does not decay verified notes
# ---------------------------------------------------------------------------


async def test_decay_does_not_decay_verified_notes(
    decay_manager,
    mock_repository,
):
    """decay_stale_notes() does not decay verified notes."""
    verified_note = _make_vault_note_row(
        note_id="VN-ver001",
        category="patterns",
        trust_level="verified",
        updated_at=datetime.now(timezone.utc) - timedelta(days=365),
    )

    mock_repository.get_by_category = AsyncMock(
        return_value=[verified_note],
    )

    decayed = await decay_manager.decay_stale_notes()

    assert "VN-ver001" not in decayed
    mock_repository.update_trust_level.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 18: TrustDecayManager uses configurable decay timers per category
# ---------------------------------------------------------------------------


async def test_decay_uses_configurable_thresholds():
    """TrustDecayManager uses configurable decay timers per category (default: verified=90d, agent-inferred=30d)."""
    from ces.knowledge.services.trust_decay import TrustDecayManager

    custom_thresholds = {"patterns": 10, "decisions": 5}
    manager = TrustDecayManager(decay_thresholds=custom_thresholds)

    thresholds = manager.get_decay_thresholds()

    assert thresholds["patterns"] == 10
    assert thresholds["decisions"] == 5
    # Other categories use defaults
    assert "escapes" in thresholds


# ---------------------------------------------------------------------------
# Defensive paths: no repository, missing updated_at, fresh notes,
# failed update, missing audit ledger.
# ---------------------------------------------------------------------------


async def test_decay_returns_empty_when_no_repository():
    """No repository configured -> early return with empty list."""
    from ces.knowledge.services.trust_decay import TrustDecayManager

    manager = TrustDecayManager(repository=None)
    assert await manager.decay_stale_notes() == []


async def test_decay_skips_notes_without_updated_at(decay_manager, mock_repository):
    """Rows missing updated_at are skipped, not crashed on."""
    note = _make_vault_note_row(
        note_id="VN-no-ts",
        category="patterns",
        trust_level="agent-inferred",
        updated_at=datetime.now(timezone.utc) - timedelta(days=365),
    )
    note.updated_at = None

    mock_repository.get_by_category = AsyncMock(return_value=[note])

    decayed = await decay_manager.decay_stale_notes()

    assert decayed == []
    mock_repository.update_trust_level.assert_not_awaited()


async def test_decay_skips_fresh_agent_inferred_notes(decay_manager, mock_repository):
    """Agent-inferred notes within threshold are not decayed."""
    fresh = _make_vault_note_row(
        note_id="VN-fresh",
        category="patterns",
        trust_level="agent-inferred",
        updated_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    mock_repository.get_by_category = AsyncMock(return_value=[fresh])

    decayed = await decay_manager.decay_stale_notes()

    assert decayed == []
    mock_repository.update_trust_level.assert_not_awaited()


async def test_decay_does_not_track_when_update_returns_none(decay_manager, mock_repository):
    """If update_trust_level returns None, the note is not added to the decayed list."""
    old = _make_vault_note_row(
        note_id="VN-update-failed",
        category="patterns",
        trust_level="agent-inferred",
        updated_at=datetime.now(timezone.utc) - timedelta(days=365),
    )
    mock_repository.get_by_category = AsyncMock(return_value=[old])
    mock_repository.update_trust_level = AsyncMock(return_value=None)

    decayed = await decay_manager.decay_stale_notes()

    assert decayed == []


async def test_decay_works_without_audit_ledger(mock_repository):
    """Decay still runs when no audit ledger is supplied."""
    from ces.knowledge.services.trust_decay import TrustDecayManager

    old = _make_vault_note_row(
        note_id="VN-no-ledger",
        category="patterns",
        trust_level="agent-inferred",
        updated_at=datetime.now(timezone.utc) - timedelta(days=365),
    )
    mock_repository.get_by_category = AsyncMock(return_value=[old])
    mock_repository.update_trust_level = AsyncMock(
        return_value=_make_vault_note_row(note_id="VN-no-ledger", trust_level="stale-risk")
    )
    manager = TrustDecayManager(repository=mock_repository, audit_ledger=None)

    decayed = await manager.decay_stale_notes()

    assert "VN-no-ledger" in decayed
