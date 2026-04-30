"""Tests for CES repository classes (ces.control.db.repository).

Tests all 8 repository classes with mocked AsyncSession to cover
all 131 statements in control/db/repository.py. Uses AsyncMock
for session operations and MagicMock for query results.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.integration

from tests.integration._compat.control_db.repository import (
    AuditRepository,
    IntakeRepository,
    KillSwitchRepository,
    LegacyBehaviorRepository,
    ManifestRepository,
    TrustEventRepository,
    TruthArtifactRepository,
    VaultRepository,
)
from tests.integration._compat.control_db.tables import (
    AuditEntryRow,
    IntakeSessionRow,
    KillSwitchStateRow,
    LegacyBehaviorRow,
    ManifestRow,
    TrustEventRow,
    TruthArtifactRow,
    VaultNoteRow,
)


def _mock_session() -> AsyncMock:
    """Create a mock AsyncSession with execute, flush, add, merge, delete."""
    session = AsyncMock()
    session.add = MagicMock()  # add is sync
    return session


def _mock_execute_result(scalar=None, scalars=None):
    """Create a mock result from session.execute().

    Args:
        scalar: Value for scalar_one_or_none().
        scalars: List of items for scalars().all().
    """
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    result.scalar_one.return_value = scalar
    if scalars is not None:
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = scalars
        result.scalars.return_value = mock_scalars
    return result


# ---------------------------------------------------------------------------
# TruthArtifactRepository
# ---------------------------------------------------------------------------


class TestTruthArtifactRepository:
    """Tests for TruthArtifactRepository covering save, get, update, delete."""

    def test_init_stores_session(self) -> None:
        session = _mock_session()
        repo = TruthArtifactRepository(session)
        assert repo.session is session

    @pytest.mark.asyncio
    async def test_save_adds_and_flushes(self) -> None:
        session = _mock_session()
        repo = TruthArtifactRepository(session)
        row = MagicMock(spec=TruthArtifactRow)

        result = await repo.save(row)

        session.add.assert_called_once_with(row)
        session.flush.assert_awaited_once()
        assert result is row

    @pytest.mark.asyncio
    async def test_get_by_id_found(self) -> None:
        session = _mock_session()
        repo = TruthArtifactRepository(session)
        mock_row = MagicMock(spec=TruthArtifactRow)
        session.execute.return_value = _mock_execute_result(scalar=mock_row)

        result = await repo.get_by_id("art-1")

        assert result is mock_row
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self) -> None:
        session = _mock_session()
        repo = TruthArtifactRepository(session)
        session.execute.return_value = _mock_execute_result(scalar=None)

        result = await repo.get_by_id("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_type(self) -> None:
        session = _mock_session()
        repo = TruthArtifactRepository(session)
        rows = [MagicMock(spec=TruthArtifactRow)]
        session.execute.return_value = _mock_execute_result(scalars=rows)

        result = await repo.get_by_type("evidence_packet")

        assert result == rows

    @pytest.mark.asyncio
    async def test_get_approved(self) -> None:
        session = _mock_session()
        repo = TruthArtifactRepository(session)
        rows = [MagicMock(spec=TruthArtifactRow)]
        session.execute.return_value = _mock_execute_result(scalars=rows)

        result = await repo.get_approved()

        assert result == rows

    @pytest.mark.asyncio
    async def test_update_merges_and_flushes(self) -> None:
        session = _mock_session()
        repo = TruthArtifactRepository(session)
        row = MagicMock(spec=TruthArtifactRow)
        merged = MagicMock(spec=TruthArtifactRow)
        session.merge.return_value = merged

        result = await repo.update(row)

        session.merge.assert_awaited_once_with(row)
        session.flush.assert_awaited_once()
        assert result is merged

    @pytest.mark.asyncio
    async def test_delete_found(self) -> None:
        session = _mock_session()
        repo = TruthArtifactRepository(session)
        mock_row = MagicMock(spec=TruthArtifactRow)
        session.execute.return_value = _mock_execute_result(scalar=mock_row)

        result = await repo.delete("art-1")

        assert result is True
        session.delete.assert_awaited_once_with(mock_row)

    @pytest.mark.asyncio
    async def test_delete_not_found(self) -> None:
        session = _mock_session()
        repo = TruthArtifactRepository(session)
        session.execute.return_value = _mock_execute_result(scalar=None)

        result = await repo.delete("nonexistent")

        assert result is False
        session.delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# ManifestRepository
# ---------------------------------------------------------------------------


class TestManifestRepository:
    """Tests for ManifestRepository covering save, get, update, delete."""

    def test_init_stores_session(self) -> None:
        session = _mock_session()
        repo = ManifestRepository(session)
        assert repo.session is session

    @pytest.mark.asyncio
    async def test_save(self) -> None:
        session = _mock_session()
        repo = ManifestRepository(session)
        row = MagicMock(spec=ManifestRow)

        result = await repo.save(row)

        session.add.assert_called_once_with(row)
        session.flush.assert_awaited_once()
        assert result is row

    @pytest.mark.asyncio
    async def test_get_by_id_found(self) -> None:
        session = _mock_session()
        repo = ManifestRepository(session)
        mock_row = MagicMock(spec=ManifestRow)
        session.execute.return_value = _mock_execute_result(scalar=mock_row)

        result = await repo.get_by_id("mfst-1")

        assert result is mock_row

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self) -> None:
        session = _mock_session()
        repo = ManifestRepository(session)
        session.execute.return_value = _mock_execute_result(scalar=None)

        result = await repo.get_by_id("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_active(self) -> None:
        session = _mock_session()
        repo = ManifestRepository(session)
        rows = [MagicMock(spec=ManifestRow)]
        session.execute.return_value = _mock_execute_result(scalars=rows)

        result = await repo.get_active()

        assert result == rows

    @pytest.mark.asyncio
    async def test_update(self) -> None:
        session = _mock_session()
        repo = ManifestRepository(session)
        row = MagicMock(spec=ManifestRow)
        merged = MagicMock(spec=ManifestRow)
        session.merge.return_value = merged

        result = await repo.update(row)

        assert result is merged
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_found(self) -> None:
        session = _mock_session()
        repo = ManifestRepository(session)
        mock_row = MagicMock(spec=ManifestRow)
        session.execute.return_value = _mock_execute_result(scalar=mock_row)

        result = await repo.delete("mfst-1")

        assert result is True

    @pytest.mark.asyncio
    async def test_delete_not_found(self) -> None:
        session = _mock_session()
        repo = ManifestRepository(session)
        session.execute.return_value = _mock_execute_result(scalar=None)

        result = await repo.delete("nonexistent")

        assert result is False


# ---------------------------------------------------------------------------
# AuditRepository
# ---------------------------------------------------------------------------


class TestAuditRepository:
    """Tests for AuditRepository -- append-only, no update or delete."""

    def test_init_stores_session(self) -> None:
        session = _mock_session()
        repo = AuditRepository(session)
        assert repo.session is session

    def test_no_update_method(self) -> None:
        """AuditRepository must NOT have update method (D-07 enforcement)."""
        assert not hasattr(AuditRepository, "update")

    def test_no_delete_method(self) -> None:
        """AuditRepository must NOT have delete method (D-07 enforcement)."""
        assert not hasattr(AuditRepository, "delete")

    @pytest.mark.asyncio
    async def test_append(self) -> None:
        session = _mock_session()
        repo = AuditRepository(session)
        row = MagicMock(spec=AuditEntryRow)

        result = await repo.append(row)

        session.add.assert_called_once_with(row)
        session.flush.assert_awaited_once()
        assert result is row

    @pytest.mark.asyncio
    async def test_get_latest(self) -> None:
        session = _mock_session()
        repo = AuditRepository(session)
        rows = [MagicMock(spec=AuditEntryRow)]
        session.execute.return_value = _mock_execute_result(scalars=rows)

        result = await repo.get_latest(limit=10)

        assert result == rows

    @pytest.mark.asyncio
    async def test_get_by_event_type(self) -> None:
        session = _mock_session()
        repo = AuditRepository(session)
        rows = [MagicMock(spec=AuditEntryRow)]
        session.execute.return_value = _mock_execute_result(scalars=rows)

        result = await repo.get_by_event_type("approval")

        assert result == rows

    @pytest.mark.asyncio
    async def test_get_by_actor(self) -> None:
        session = _mock_session()
        repo = AuditRepository(session)
        rows = [MagicMock(spec=AuditEntryRow)]
        session.execute.return_value = _mock_execute_result(scalars=rows)

        result = await repo.get_by_actor("agent-1")

        assert result == rows

    @pytest.mark.asyncio
    async def test_get_by_time_range(self) -> None:
        session = _mock_session()
        repo = AuditRepository(session)
        rows = [MagicMock(spec=AuditEntryRow)]
        session.execute.return_value = _mock_execute_result(scalars=rows)

        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 12, 31, tzinfo=timezone.utc)
        result = await repo.get_by_time_range(start, end)

        assert result == rows

    @pytest.mark.asyncio
    async def test_get_last_entry(self) -> None:
        session = _mock_session()
        repo = AuditRepository(session)
        mock_row = MagicMock(spec=AuditEntryRow)
        session.execute.return_value = _mock_execute_result(scalar=mock_row)

        result = await repo.get_last_entry()

        assert result is mock_row

    @pytest.mark.asyncio
    async def test_get_by_id(self) -> None:
        session = _mock_session()
        repo = AuditRepository(session)
        mock_row = MagicMock(spec=AuditEntryRow)
        session.execute.return_value = _mock_execute_result(scalar=mock_row)

        result = await repo.get_by_id("entry-1")

        assert result is mock_row


# ---------------------------------------------------------------------------
# KillSwitchRepository
# ---------------------------------------------------------------------------


class TestKillSwitchRepository:
    """Tests for KillSwitchRepository including upsert and initialize_defaults."""

    def test_init_stores_session(self) -> None:
        session = _mock_session()
        repo = KillSwitchRepository(session)
        assert repo.session is session

    @pytest.mark.asyncio
    async def test_get_all(self) -> None:
        session = _mock_session()
        repo = KillSwitchRepository(session)
        rows = [MagicMock(spec=KillSwitchStateRow)]
        session.execute.return_value = _mock_execute_result(scalars=rows)

        result = await repo.get_all()

        assert result == rows

    @pytest.mark.asyncio
    async def test_get_by_activity_class(self) -> None:
        session = _mock_session()
        repo = KillSwitchRepository(session)
        mock_row = MagicMock(spec=KillSwitchStateRow)
        session.execute.return_value = _mock_execute_result(scalar=mock_row)

        result = await repo.get_by_activity_class("merges")

        assert result is mock_row

    @pytest.mark.asyncio
    async def test_upsert(self) -> None:
        session = _mock_session()
        repo = KillSwitchRepository(session)
        row = MagicMock(spec=KillSwitchStateRow)
        merged = MagicMock(spec=KillSwitchStateRow)
        session.merge.return_value = merged

        result = await repo.upsert(row)

        session.merge.assert_awaited_once_with(row)
        session.flush.assert_awaited_once()
        assert result is merged

    @pytest.mark.asyncio
    async def test_initialize_defaults_creates_missing(self) -> None:
        """initialize_defaults should create rows for activity classes not yet in DB."""
        session = _mock_session()
        repo = KillSwitchRepository(session)
        # All get_by_activity_class return None -> all need creation
        session.execute.return_value = _mock_execute_result(scalar=None)

        await repo.initialize_defaults()

        # 7 activity classes should be added
        assert session.add.call_count == 7
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_initialize_defaults_skips_existing(self) -> None:
        """initialize_defaults should skip activity classes that already exist."""
        session = _mock_session()
        repo = KillSwitchRepository(session)
        # All get_by_activity_class return a row -> none need creation
        existing = MagicMock(spec=KillSwitchStateRow)
        session.execute.return_value = _mock_execute_result(scalar=existing)

        await repo.initialize_defaults()

        session.add.assert_not_called()


# ---------------------------------------------------------------------------
# TrustEventRepository
# ---------------------------------------------------------------------------


class TestTrustEventRepository:
    """Tests for TrustEventRepository covering save and get_by_profile."""

    def test_init_stores_session(self) -> None:
        session = _mock_session()
        repo = TrustEventRepository(session)
        assert repo.session is session

    @pytest.mark.asyncio
    async def test_save(self) -> None:
        session = _mock_session()
        repo = TrustEventRepository(session)
        row = MagicMock(spec=TrustEventRow)

        result = await repo.save(row)

        session.add.assert_called_once_with(row)
        session.flush.assert_awaited_once()
        assert result is row

    @pytest.mark.asyncio
    async def test_get_by_profile(self) -> None:
        session = _mock_session()
        repo = TrustEventRepository(session)
        rows = [MagicMock(spec=TrustEventRow)]
        session.execute.return_value = _mock_execute_result(scalars=rows)

        result = await repo.get_by_profile("profile-1", limit=10)

        assert result == rows


# ---------------------------------------------------------------------------
# VaultRepository
# ---------------------------------------------------------------------------


class TestVaultRepository:
    """Tests for VaultRepository covering all CRUD and search methods."""

    def test_init_stores_session(self) -> None:
        session = _mock_session()
        repo = VaultRepository(session)
        assert repo.session is session

    @pytest.mark.asyncio
    async def test_save(self) -> None:
        session = _mock_session()
        repo = VaultRepository(session)
        row = MagicMock(spec=VaultNoteRow)

        result = await repo.save(row)

        session.add.assert_called_once_with(row)
        assert result is row

    @pytest.mark.asyncio
    async def test_get_by_id_found(self) -> None:
        session = _mock_session()
        repo = VaultRepository(session)
        mock_row = MagicMock(spec=VaultNoteRow)
        session.execute.return_value = _mock_execute_result(scalar=mock_row)

        result = await repo.get_by_id("note-1")

        assert result is mock_row

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self) -> None:
        session = _mock_session()
        repo = VaultRepository(session)
        session.execute.return_value = _mock_execute_result(scalar=None)

        result = await repo.get_by_id("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_category(self) -> None:
        session = _mock_session()
        repo = VaultRepository(session)
        rows = [MagicMock(spec=VaultNoteRow)]
        session.execute.return_value = _mock_execute_result(scalars=rows)

        result = await repo.get_by_category("patterns")

        assert result == rows

    @pytest.mark.asyncio
    async def test_get_by_trust_level(self) -> None:
        session = _mock_session()
        repo = VaultRepository(session)
        rows = [MagicMock(spec=VaultNoteRow)]
        session.execute.return_value = _mock_execute_result(scalars=rows)

        result = await repo.get_by_trust_level("verified")

        assert result == rows

    @pytest.mark.asyncio
    async def test_update_trust_level_found(self) -> None:
        session = _mock_session()
        repo = VaultRepository(session)
        mock_row = MagicMock(spec=VaultNoteRow)
        session.execute.return_value = _mock_execute_result(scalar=mock_row)

        result = await repo.update_trust_level("note-1", "stale-risk")

        assert result is mock_row
        assert mock_row.trust_level == "stale-risk"
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_trust_level_not_found(self) -> None:
        session = _mock_session()
        repo = VaultRepository(session)
        session.execute.return_value = _mock_execute_result(scalar=None)

        result = await repo.update_trust_level("nonexistent", "stale-risk")

        assert result is None

    @pytest.mark.asyncio
    async def test_search_by_tags(self) -> None:
        session = _mock_session()
        repo = VaultRepository(session)
        rows = [MagicMock(spec=VaultNoteRow)]
        session.execute.return_value = _mock_execute_result(scalars=rows)

        result = await repo.search_by_tags(["python", "auth"])

        assert result == rows

    @pytest.mark.asyncio
    async def test_delete_found(self) -> None:
        session = _mock_session()
        repo = VaultRepository(session)
        mock_row = MagicMock(spec=VaultNoteRow)
        session.execute.return_value = _mock_execute_result(scalar=mock_row)

        result = await repo.delete("note-1")

        assert result is True
        session.delete.assert_awaited_once_with(mock_row)

    @pytest.mark.asyncio
    async def test_delete_not_found(self) -> None:
        session = _mock_session()
        repo = VaultRepository(session)
        session.execute.return_value = _mock_execute_result(scalar=None)

        result = await repo.delete("nonexistent")

        assert result is False


# ---------------------------------------------------------------------------
# IntakeRepository
# ---------------------------------------------------------------------------


class TestIntakeRepository:
    """Tests for IntakeRepository covering CRUD and stage/answers update."""

    def test_init_stores_session(self) -> None:
        session = _mock_session()
        repo = IntakeRepository(session)
        assert repo.session is session

    @pytest.mark.asyncio
    async def test_save(self) -> None:
        session = _mock_session()
        repo = IntakeRepository(session)
        row = MagicMock(spec=IntakeSessionRow)

        result = await repo.save(row)

        session.add.assert_called_once_with(row)
        assert result is row

    @pytest.mark.asyncio
    async def test_get_by_id_found(self) -> None:
        session = _mock_session()
        repo = IntakeRepository(session)
        mock_row = MagicMock(spec=IntakeSessionRow)
        session.execute.return_value = _mock_execute_result(scalar=mock_row)

        result = await repo.get_by_id("sess-1")

        assert result is mock_row

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self) -> None:
        session = _mock_session()
        repo = IntakeRepository(session)
        session.execute.return_value = _mock_execute_result(scalar=None)

        result = await repo.get_by_id("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_project(self) -> None:
        session = _mock_session()
        repo = IntakeRepository(session)
        rows = [MagicMock(spec=IntakeSessionRow)]
        session.execute.return_value = _mock_execute_result(scalars=rows)

        result = await repo.get_by_project("project-1")

        assert result == rows

    @pytest.mark.asyncio
    async def test_update_stage_found(self) -> None:
        session = _mock_session()
        repo = IntakeRepository(session)
        mock_row = MagicMock(spec=IntakeSessionRow)
        session.execute.return_value = _mock_execute_result(scalar=mock_row)

        result = await repo.update_stage("sess-1", "completed")

        assert result is mock_row
        assert mock_row.current_stage == "completed"

    @pytest.mark.asyncio
    async def test_update_stage_not_found(self) -> None:
        session = _mock_session()
        repo = IntakeRepository(session)
        session.execute.return_value = _mock_execute_result(scalar=None)

        result = await repo.update_stage("nonexistent", "completed")

        assert result is None

    @pytest.mark.asyncio
    async def test_update_answers_found(self) -> None:
        session = _mock_session()
        repo = IntakeRepository(session)
        mock_row = MagicMock(spec=IntakeSessionRow)
        session.execute.return_value = _mock_execute_result(scalar=mock_row)
        new_answers = {"q1": "a1"}

        result = await repo.update_answers("sess-1", new_answers)

        assert result is mock_row
        assert mock_row.answers == new_answers

    @pytest.mark.asyncio
    async def test_update_answers_not_found(self) -> None:
        session = _mock_session()
        repo = IntakeRepository(session)
        session.execute.return_value = _mock_execute_result(scalar=None)

        result = await repo.update_answers("nonexistent", {})

        assert result is None


# ---------------------------------------------------------------------------
# LegacyBehaviorRepository
# ---------------------------------------------------------------------------


class TestLegacyBehaviorRepository:
    """Tests for LegacyBehaviorRepository covering all methods."""

    def test_init_stores_session(self) -> None:
        session = _mock_session()
        repo = LegacyBehaviorRepository(session)
        assert repo.session is session

    @pytest.mark.asyncio
    async def test_save(self) -> None:
        session = _mock_session()
        repo = LegacyBehaviorRepository(session)
        row = MagicMock(spec=LegacyBehaviorRow)

        result = await repo.save(row)

        session.add.assert_called_once_with(row)
        assert result is row

    @pytest.mark.asyncio
    async def test_get_by_id_found(self) -> None:
        session = _mock_session()
        repo = LegacyBehaviorRepository(session)
        mock_row = MagicMock(spec=LegacyBehaviorRow)
        session.execute.return_value = _mock_execute_result(scalar=mock_row)

        result = await repo.get_by_id("entry-1")

        assert result is mock_row

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self) -> None:
        session = _mock_session()
        repo = LegacyBehaviorRepository(session)
        session.execute.return_value = _mock_execute_result(scalar=None)

        result = await repo.get_by_id("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_system(self) -> None:
        session = _mock_session()
        repo = LegacyBehaviorRepository(session)
        rows = [MagicMock(spec=LegacyBehaviorRow)]
        session.execute.return_value = _mock_execute_result(scalars=rows)

        result = await repo.get_by_system("legacy-system")

        assert result == rows

    @pytest.mark.asyncio
    async def test_get_pending(self) -> None:
        session = _mock_session()
        repo = LegacyBehaviorRepository(session)
        rows = [MagicMock(spec=LegacyBehaviorRow)]
        session.execute.return_value = _mock_execute_result(scalars=rows)

        result = await repo.get_pending()

        assert result == rows

    @pytest.mark.asyncio
    async def test_update_disposition_found(self) -> None:
        session = _mock_session()
        repo = LegacyBehaviorRepository(session)
        mock_row = MagicMock(spec=LegacyBehaviorRow)
        session.execute.return_value = _mock_execute_result(scalar=mock_row)
        now = datetime(2026, 4, 7, tzinfo=timezone.utc)

        result = await repo.update_disposition("entry-1", "preserve", "reviewer-1", now)

        assert result is mock_row
        assert mock_row.disposition == "preserve"
        assert mock_row.reviewed_by == "reviewer-1"
        assert mock_row.reviewed_at == now

    @pytest.mark.asyncio
    async def test_update_disposition_not_found(self) -> None:
        session = _mock_session()
        repo = LegacyBehaviorRepository(session)
        session.execute.return_value = _mock_execute_result(scalar=None)
        now = datetime(2026, 4, 7, tzinfo=timezone.utc)

        result = await repo.update_disposition("nonexistent", "preserve", "reviewer-1", now)

        assert result is None

    @pytest.mark.asyncio
    async def test_mark_promoted_found(self) -> None:
        session = _mock_session()
        repo = LegacyBehaviorRepository(session)
        mock_row = MagicMock(spec=LegacyBehaviorRow)
        session.execute.return_value = _mock_execute_result(scalar=mock_row)

        result = await repo.mark_promoted("entry-1", "prl-1")

        assert result is mock_row
        assert mock_row.promoted_to_prl_id == "prl-1"

    @pytest.mark.asyncio
    async def test_mark_promoted_not_found(self) -> None:
        session = _mock_session()
        repo = LegacyBehaviorRepository(session)
        session.execute.return_value = _mock_execute_result(scalar=None)

        result = await repo.mark_promoted("nonexistent", "prl-1")

        assert result is None
