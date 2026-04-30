"""Tests for KnowledgeVaultService.trigger_invalidation integration.

Verifies that vault invalidation:
- Changes affected notes to stale-risk trust level
- Leaves unrelated notes unchanged
- Logs invalidation events to audit ledger
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from ces.knowledge.services.vault_service import KnowledgeVaultService
from ces.shared.enums import VaultCategory, VaultTrustLevel

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_vault_note_row(
    *,
    note_id: str,
    category: str = "patterns",
    trust_level: str = "agent-inferred",
    content: str = "Test content",
    source: str = "test",
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


def _make_mock_repository() -> MagicMock:
    """Create a mock VaultRepository."""
    repo = MagicMock()
    repo.save = AsyncMock()
    repo.get_by_id = AsyncMock(return_value=None)
    repo.get_by_category = AsyncMock(return_value=[])
    repo.get_by_trust_level = AsyncMock(return_value=[])
    repo.search_by_tags = AsyncMock(return_value=[])
    repo.update_trust_level = AsyncMock(return_value=None)
    repo.delete = AsyncMock(return_value=False)
    return repo


def _make_mock_audit_ledger() -> MagicMock:
    """Create a mock audit ledger."""
    ledger = MagicMock()
    ledger.record_truth_change = AsyncMock()
    ledger.append_event = AsyncMock()
    return ledger


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestVaultInvalidation:
    """Tests for vault note invalidation via trigger_invalidation."""

    async def test_invalidation_changes_affected_notes_to_stale(self) -> None:
        """Write a note with related_artifacts=["ART-001"]. Trigger invalidation
        for ART-001. Verify note trust_level changed to stale-risk."""
        repo = _make_mock_repository()
        audit = _make_mock_audit_ledger()

        # Note related to ART-001
        related_row = _make_vault_note_row(
            note_id="VN-aff001",
            related_artifacts=["ART-001"],
            trust_level="agent-inferred",
        )

        # get_by_trust_level returns the related row for agent-inferred
        repo.get_by_trust_level = AsyncMock(
            side_effect=lambda tl: [related_row] if tl == "agent-inferred" else [],
        )

        # update_trust_level returns updated row with stale-risk
        updated_row = _make_vault_note_row(
            note_id="VN-aff001",
            related_artifacts=["ART-001"],
            trust_level="stale-risk",
        )
        repo.update_trust_level = AsyncMock(return_value=updated_row)

        vault = KnowledgeVaultService(
            repository=repo,
            audit_ledger=audit,
            query_filter=lambda notes: notes,
        )

        invalidated = await vault.trigger_invalidation(
            trigger_source="artifact-change",
            affected_artifact_ids=["ART-001"],
        )

        assert "VN-aff001" in invalidated
        repo.update_trust_level.assert_awaited()
        # Verify the update was to stale-risk
        call_args = repo.update_trust_level.call_args
        assert call_args[0][1] == "stale-risk"

    async def test_invalidation_leaves_unrelated_notes(self) -> None:
        """Write a note with related_artifacts=["ART-002"]. Trigger invalidation
        for ART-001. Verify note unchanged."""
        repo = _make_mock_repository()
        audit = _make_mock_audit_ledger()

        # Note related to ART-002, NOT ART-001
        unrelated_row = _make_vault_note_row(
            note_id="VN-unr001",
            related_artifacts=["ART-002"],
            trust_level="agent-inferred",
        )

        repo.get_by_trust_level = AsyncMock(
            side_effect=lambda tl: [unrelated_row] if tl == "agent-inferred" else [],
        )

        vault = KnowledgeVaultService(
            repository=repo,
            audit_ledger=audit,
            query_filter=lambda notes: notes,
        )

        invalidated = await vault.trigger_invalidation(
            trigger_source="artifact-change",
            affected_artifact_ids=["ART-001"],
        )

        # ART-001 invalidation should NOT affect note related to ART-002
        assert "VN-unr001" not in invalidated
        repo.update_trust_level.assert_not_awaited()

    async def test_invalidation_logs_to_audit(self) -> None:
        """Trigger invalidation, verify audit_ledger.record_truth_change called."""
        repo = _make_mock_repository()
        audit = _make_mock_audit_ledger()

        related_row = _make_vault_note_row(
            note_id="VN-aud001",
            related_artifacts=["ART-003"],
            trust_level="verified",
        )

        # Return from verified trust level query
        repo.get_by_trust_level = AsyncMock(
            side_effect=lambda tl: [related_row] if tl == "verified" else [],
        )

        updated_row = _make_vault_note_row(
            note_id="VN-aud001",
            related_artifacts=["ART-003"],
            trust_level="stale-risk",
        )
        repo.update_trust_level = AsyncMock(return_value=updated_row)

        vault = KnowledgeVaultService(
            repository=repo,
            audit_ledger=audit,
            query_filter=lambda notes: notes,
        )

        await vault.trigger_invalidation(
            trigger_source="truth-artifact-update",
            affected_artifact_ids=["ART-003"],
        )

        # Audit ledger should have been called for the invalidation event
        assert audit.record_truth_change.await_count >= 1
        call_args = audit.record_truth_change.call_args
        assert "VN-aud001" in str(call_args)
