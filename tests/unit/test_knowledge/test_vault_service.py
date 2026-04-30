"""Unit tests for KnowledgeVaultService.

Tests vault write, query, trust management, invalidation integration,
and materialized view refresh. All tests use mocked repository and
audit ledger for unit isolation.

Tests cover VAULT-01 through VAULT-06 requirements.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ces.control.models.knowledge_vault import VaultNote
from ces.shared.enums import VaultCategory, VaultTrustLevel

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_repository():
    """Create a mock VaultRepository with async methods."""
    repo = MagicMock()
    repo.session = MagicMock()
    repo.save = AsyncMock()
    repo.get_by_id = AsyncMock(return_value=None)
    repo.get_by_category = AsyncMock(return_value=[])
    repo.get_by_trust_level = AsyncMock(return_value=[])
    repo.search_by_tags = AsyncMock(return_value=[])
    repo.update_trust_level = AsyncMock(return_value=None)
    repo.delete = AsyncMock(return_value=False)
    return repo


@pytest.fixture()
def mock_audit_ledger():
    """Create a mock audit ledger with async record_truth_change."""
    ledger = MagicMock()
    ledger.record_truth_change = AsyncMock()
    ledger.append_event = AsyncMock()
    return ledger


def _make_vault_note_row(
    *,
    note_id: str = "VN-abc123",
    category: str = "patterns",
    trust_level: str = "agent-inferred",
    content: str = "Test content",
    source: str = "test-source",
    tags: list | None = None,
    related_artifacts: list | None = None,
    invalidation_trigger: str | None = None,
) -> MagicMock:
    """Create a mock VaultNoteRow."""
    row = MagicMock()
    row.note_id = note_id
    row.category = category
    row.trust_level = trust_level
    row.content = content
    row.source = source
    row.tags = tags or []
    row.related_artifacts = related_artifacts or []
    row.invalidation_trigger = invalidation_trigger
    row.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    row.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return row


@pytest.fixture()
def vault_service(mock_repository, mock_audit_ledger):
    """Create a KnowledgeVaultService with mocked dependencies."""
    from ces.knowledge.services.vault_service import KnowledgeVaultService

    return KnowledgeVaultService(
        repository=mock_repository,
        audit_ledger=mock_audit_ledger,
        query_filter=lambda notes: [n for n in notes if "requirement" not in n.content.lower()],
    )


@pytest.fixture()
def vault_service_no_filter(mock_repository, mock_audit_ledger):
    """Create a KnowledgeVaultService without query filter override."""
    from ces.knowledge.services.vault_service import KnowledgeVaultService

    return KnowledgeVaultService(
        repository=mock_repository,
        audit_ledger=mock_audit_ledger,
    )


# ---------------------------------------------------------------------------
# Test 1: write_note() creates VaultNote with generated note_id and persists
# ---------------------------------------------------------------------------


async def test_write_note_creates_vault_note_with_generated_id(
    vault_service,
    mock_repository,
):
    """write_note() creates VaultNote with generated note_id and persists via repository."""
    mock_repository.save = AsyncMock(side_effect=lambda row: row)

    note = await vault_service.write_note(
        category=VaultCategory.PATTERNS,
        content="Use factory pattern for builders",
        source="agent-discovery",
    )

    assert isinstance(note, VaultNote)
    assert note.note_id.startswith("VN-")
    assert len(note.note_id) == 15  # "VN-" + 12 hex chars
    assert note.category == VaultCategory.PATTERNS
    assert note.content == "Use factory pattern for builders"
    assert note.source == "agent-discovery"
    mock_repository.save.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 2: write_note() defaults trust_level to AGENT_INFERRED
# ---------------------------------------------------------------------------


async def test_write_note_defaults_trust_level_to_agent_inferred(
    vault_service,
    mock_repository,
):
    """write_note() defaults trust_level to AGENT_INFERRED."""
    mock_repository.save = AsyncMock(side_effect=lambda row: row)

    note = await vault_service.write_note(
        category=VaultCategory.DOMAIN,
        content="Domain boundary at payment service",
        source="agent-analysis",
    )

    assert note.trust_level == VaultTrustLevel.AGENT_INFERRED


# ---------------------------------------------------------------------------
# Test 3: write_note() logs to audit ledger when provided
# ---------------------------------------------------------------------------


async def test_write_note_logs_to_audit_ledger(
    vault_service,
    mock_repository,
    mock_audit_ledger,
):
    """write_note() logs to audit ledger when provided."""
    mock_repository.save = AsyncMock(side_effect=lambda row: row)

    await vault_service.write_note(
        category=VaultCategory.DECISIONS,
        content="Chose PostgreSQL for state storage",
        source="team-discussion",
    )

    mock_audit_ledger.record_truth_change.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 4: query() returns notes filtered by category
# ---------------------------------------------------------------------------


async def test_query_returns_notes_filtered_by_category(
    vault_service,
    mock_repository,
):
    """query() returns notes filtered by category."""
    mock_rows = [
        _make_vault_note_row(
            note_id="VN-cat001",
            category="patterns",
            content="Some pattern",
        ),
    ]
    mock_repository.get_by_category = AsyncMock(return_value=mock_rows)

    notes = await vault_service.query(category=VaultCategory.PATTERNS)

    assert len(notes) == 1
    assert notes[0].category == VaultCategory.PATTERNS
    mock_repository.get_by_category.assert_awaited_once_with("patterns")


# ---------------------------------------------------------------------------
# Test 5: query() returns notes filtered by trust_level
# ---------------------------------------------------------------------------


async def test_query_returns_notes_filtered_by_trust_level(
    vault_service,
    mock_repository,
):
    """query() returns notes filtered by trust_level."""
    mock_rows = [
        _make_vault_note_row(
            note_id="VN-trust01",
            trust_level="verified",
            content="Verified note",
        ),
    ]
    mock_repository.get_by_trust_level = AsyncMock(return_value=mock_rows)

    notes = await vault_service.query(
        trust_level=VaultTrustLevel.VERIFIED,
    )

    assert len(notes) == 1
    assert notes[0].trust_level == VaultTrustLevel.VERIFIED
    mock_repository.get_by_trust_level.assert_awaited_once_with("verified")


# ---------------------------------------------------------------------------
# Test 6: query() returns notes filtered by tags
# ---------------------------------------------------------------------------


async def test_query_returns_notes_filtered_by_tags(
    vault_service,
    mock_repository,
):
    """query() returns notes filtered by tags."""
    mock_rows = [
        _make_vault_note_row(
            note_id="VN-tag001",
            tags=["auth", "security"],
            content="Auth pattern",
        ),
    ]
    mock_repository.search_by_tags = AsyncMock(return_value=mock_rows)

    notes = await vault_service.query(tags=["auth", "security"])

    assert len(notes) == 1
    mock_repository.search_by_tags.assert_awaited_once_with(["auth", "security"])


# ---------------------------------------------------------------------------
# Test 7: query() applies informational-only filter (VAULT-06)
# ---------------------------------------------------------------------------


async def test_query_applies_vault_06_filter(
    vault_service,
    mock_repository,
):
    """query() applies informational-only filter (VAULT-06) to all results."""
    mock_rows = [
        _make_vault_note_row(
            note_id="VN-info01",
            content="Pattern for error handling",
        ),
        _make_vault_note_row(
            note_id="VN-policy01",
            content="This is a requirement for compliance",
        ),
    ]
    mock_repository.get_by_category = AsyncMock(return_value=mock_rows)

    notes = await vault_service.query(category=VaultCategory.PATTERNS)

    # The mock filter strips notes containing "requirement"
    assert len(notes) == 1
    assert notes[0].note_id == "VN-info01"


# ---------------------------------------------------------------------------
# Test 8: query() respects limit parameter
# ---------------------------------------------------------------------------


async def test_query_respects_limit_parameter(
    vault_service,
    mock_repository,
):
    """query() respects limit parameter."""
    mock_rows = [_make_vault_note_row(note_id=f"VN-lim{i:03d}", content=f"Note {i}") for i in range(10)]
    mock_repository.get_by_category = AsyncMock(return_value=mock_rows)

    notes = await vault_service.query(
        category=VaultCategory.PATTERNS,
        limit=3,
    )

    assert len(notes) <= 3


# ---------------------------------------------------------------------------
# Test 9: update_trust_level() changes trust from agent-inferred to verified
# ---------------------------------------------------------------------------


async def test_update_trust_level_changes_trust(
    vault_service,
    mock_repository,
):
    """update_trust_level() changes trust from agent-inferred to verified."""
    updated_row = _make_vault_note_row(
        note_id="VN-upd001",
        trust_level="verified",
    )
    mock_repository.update_trust_level = AsyncMock(return_value=updated_row)

    result = await vault_service.update_trust_level(
        "VN-upd001",
        VaultTrustLevel.VERIFIED,
    )

    assert result is not None
    assert result.trust_level == VaultTrustLevel.VERIFIED
    mock_repository.update_trust_level.assert_awaited_once_with(
        "VN-upd001",
        "verified",
    )


# ---------------------------------------------------------------------------
# Test 10: update_trust_level() logs to audit ledger
# ---------------------------------------------------------------------------


async def test_update_trust_level_logs_to_audit_ledger(
    vault_service,
    mock_repository,
    mock_audit_ledger,
):
    """update_trust_level() logs to audit ledger."""
    updated_row = _make_vault_note_row(
        note_id="VN-upd002",
        trust_level="verified",
    )
    mock_repository.update_trust_level = AsyncMock(return_value=updated_row)

    await vault_service.update_trust_level(
        "VN-upd002",
        VaultTrustLevel.VERIFIED,
    )

    mock_audit_ledger.record_truth_change.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 11: delete_note() removes note and logs deletion
# ---------------------------------------------------------------------------


async def test_delete_note_removes_and_logs(
    vault_service,
    mock_repository,
    mock_audit_ledger,
):
    """delete_note() removes note and logs deletion."""
    mock_repository.delete = AsyncMock(return_value=True)

    result = await vault_service.delete_note("VN-del001")

    assert result is True
    mock_repository.delete.assert_awaited_once_with("VN-del001")
    mock_audit_ledger.record_truth_change.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 12: find_verified_answer() returns only VERIFIED notes matching
# ---------------------------------------------------------------------------


async def test_find_verified_answer_returns_verified_match(
    vault_service,
    mock_repository,
):
    """find_verified_answer() returns only VERIFIED notes matching category + content overlap."""
    mock_rows = [
        _make_vault_note_row(
            note_id="VN-ver001",
            category="domain",
            trust_level="verified",
            content="The payment gateway uses Stripe for processing transactions",
        ),
        _make_vault_note_row(
            note_id="VN-ver002",
            category="domain",
            trust_level="agent-inferred",
            content="Payment integration might use PayPal",
        ),
    ]
    mock_repository.get_by_category = AsyncMock(return_value=mock_rows)

    result = await vault_service.find_verified_answer(
        category="domain",
        question_text="What payment processing system is used for transactions?",
    )

    assert result is not None
    assert result.note_id == "VN-ver001"
    assert result.trust_level == VaultTrustLevel.VERIFIED


# ---------------------------------------------------------------------------
# Test 13: find_verified_answer() returns None when no verified match
# ---------------------------------------------------------------------------


async def test_find_verified_answer_returns_none_when_no_match(
    vault_service,
    mock_repository,
):
    """find_verified_answer() returns None when no verified match exists."""
    mock_rows = [
        _make_vault_note_row(
            note_id="VN-nomatch",
            category="domain",
            trust_level="agent-inferred",
            content="Something completely unrelated to the question",
        ),
    ]
    mock_repository.get_by_category = AsyncMock(return_value=mock_rows)

    result = await vault_service.find_verified_answer(
        category="domain",
        question_text="What database is used?",
    )

    assert result is None


# ---------------------------------------------------------------------------
# Test 14: trigger_invalidation() changes related notes to stale-risk
# ---------------------------------------------------------------------------


async def test_trigger_invalidation_changes_notes_to_stale_risk(
    vault_service,
    mock_repository,
):
    """trigger_invalidation() changes related notes to stale-risk when trigger fires."""
    # A note related to artifact "art-001"
    related_row = _make_vault_note_row(
        note_id="VN-inv001",
        related_artifacts=["art-001"],
        trust_level="agent-inferred",
    )
    mock_repository.search_by_tags = AsyncMock(return_value=[])
    # Simulate get_by_category returning the related note
    mock_repository.get_by_category = AsyncMock(return_value=[related_row])
    mock_repository.get_by_trust_level = AsyncMock(
        return_value=[related_row],
    )
    updated_row = _make_vault_note_row(
        note_id="VN-inv001",
        trust_level="stale-risk",
    )
    mock_repository.update_trust_level = AsyncMock(return_value=updated_row)

    invalidated = await vault_service.trigger_invalidation(
        trigger_source="artifact-change",
        affected_artifact_ids=["art-001"],
    )

    assert "VN-inv001" in invalidated


# ---------------------------------------------------------------------------
# Test 15: trigger_invalidation() logs invalidation event
# ---------------------------------------------------------------------------


async def test_trigger_invalidation_logs_event(
    vault_service,
    mock_repository,
    mock_audit_ledger,
):
    """trigger_invalidation() logs invalidation event."""
    related_row = _make_vault_note_row(
        note_id="VN-invlog001",
        related_artifacts=["art-002"],
        trust_level="agent-inferred",
    )
    mock_repository.get_by_trust_level = AsyncMock(
        return_value=[related_row],
    )
    updated_row = _make_vault_note_row(
        note_id="VN-invlog001",
        trust_level="stale-risk",
    )
    mock_repository.update_trust_level = AsyncMock(return_value=updated_row)

    await vault_service.trigger_invalidation(
        trigger_source="truth-artifact-update",
        affected_artifact_ids=["art-002"],
    )

    # Audit ledger should be called for the invalidation
    assert mock_audit_ledger.record_truth_change.await_count >= 1


# ---------------------------------------------------------------------------
# Test 19: refresh_indexes() calls materialized view refresh
# ---------------------------------------------------------------------------


async def test_refresh_indexes_calls_materialized_view_refresh(
    vault_service,
    mock_repository,
):
    """refresh_indexes() calls materialized view refresh (mocked at DB level)."""
    mock_result = MagicMock()
    mock_connection = AsyncMock()
    mock_connection.execute = AsyncMock(return_value=mock_result)
    mock_repository.session.execute = AsyncMock(return_value=mock_result)

    await vault_service.refresh_indexes()

    mock_repository.session.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# Defensive paths: no-repository early returns and refresh_indexes edges
# ---------------------------------------------------------------------------


@pytest.fixture()
def headless_service():
    """KnowledgeVaultService with no repository configured."""
    from ces.knowledge.services.vault_service import KnowledgeVaultService

    return KnowledgeVaultService()


async def test_query_no_repository_returns_empty(headless_service):
    assert await headless_service.query(category=VaultCategory.PATTERNS) == []


async def test_find_verified_answer_no_repository_returns_none(headless_service):
    answer = await headless_service.find_verified_answer(category="patterns", question_text="anything")
    assert answer is None


async def test_update_trust_level_no_repository_returns_none(headless_service):
    assert await headless_service.update_trust_level("VN-x", VaultTrustLevel.VERIFIED) is None


async def test_delete_note_no_repository_returns_false(headless_service):
    assert await headless_service.delete_note("VN-x") is False


async def test_trigger_invalidation_no_repository_returns_empty(headless_service):
    result = await headless_service.trigger_invalidation(trigger_source="t", affected_artifact_ids=["a1"])
    assert result == []


async def test_refresh_indexes_no_repository_is_noop(headless_service):
    await headless_service.refresh_indexes()  # should not raise


async def test_query_no_filter_returns_empty(vault_service):
    """query() with no category/tags/trust_level filter returns empty."""
    assert await vault_service.query() == []


async def test_update_trust_level_returns_none_when_row_missing(vault_service, mock_repository):
    """If repository.update_trust_level returns None, service returns None."""
    mock_repository.update_trust_level = AsyncMock(return_value=None)
    assert await vault_service.update_trust_level("VN-missing", VaultTrustLevel.VERIFIED) is None


async def test_refresh_indexes_returns_when_no_session_attribute(mock_audit_ledger):
    """refresh_indexes() returns silently when repo has no session attribute."""
    from ces.knowledge.services.vault_service import KnowledgeVaultService

    repo = MagicMock(spec=[])  # empty spec -> getattr(repo, "session", None) returns None
    service = KnowledgeVaultService(repository=repo, audit_ledger=mock_audit_ledger)
    await service.refresh_indexes()  # should not raise


async def test_refresh_indexes_swallows_session_execute_exception(vault_service, mock_repository):
    """refresh_indexes() swallows exceptions (e.g. materialized view absent in tests)."""
    mock_repository.session.execute = AsyncMock(side_effect=RuntimeError("view does not exist"))
    await vault_service.refresh_indexes()  # should not raise
