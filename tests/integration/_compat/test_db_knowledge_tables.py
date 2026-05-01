"""Tests for CES knowledge schema database layer (Phase 05).

Validates ORM table definitions for VaultNoteRow, IntakeSessionRow,
and LegacyBehaviorRow in the knowledge PostgreSQL schema. Also tests
repository API surface for VaultRepository, IntakeRepository, and
LegacyBehaviorRepository using mock AsyncSession.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import inspect as sa_inspect

pytestmark = pytest.mark.integration

from tests.integration._compat.control_db.base import Base

# ---------------------------------------------------------------------------
# Helpers (same pattern as test_db_structure.py)
# ---------------------------------------------------------------------------


def _column_names(model: type) -> set[str]:
    """Extract column names from an ORM model class."""
    mapper: Any = sa_inspect(model)
    return {col.key for col in mapper.columns}


def _column_by_name(model: type, name: str) -> Any:
    """Get a specific column object from an ORM model."""
    mapper: Any = sa_inspect(model)
    return mapper.columns[name]


def _has_index_with_columns(model: type, column_names: list[str]) -> bool:
    """Check if the table has an index containing the specified columns."""
    table = model.__table__
    for idx in table.indexes:
        idx_cols = {col.name for col in idx.columns}
        if set(column_names).issubset(idx_cols):
            return True
    return False


def _has_gin_index(model: type, column_name: str) -> bool:
    """Check if a column has a GIN index."""
    table = model.__table__
    for idx in table.indexes:
        idx_cols = {col.name for col in idx.columns}
        if column_name in idx_cols:
            dialect_options = idx.dialect_options.get("postgresql", {})
            if dialect_options.get("using") == "gin":
                return True
    return False


# ---------------------------------------------------------------------------
# VaultNoteRow
# ---------------------------------------------------------------------------


class TestVaultNoteRowStructure:
    """VaultNoteRow stores knowledge vault notes in the knowledge schema."""

    def test_tablename(self) -> None:
        from tests.integration._compat.control_db.tables import VaultNoteRow

        assert VaultNoteRow.__tablename__ == "vault_notes"

    def test_schema_is_knowledge(self) -> None:
        from tests.integration._compat.control_db.tables import VaultNoteRow

        assert VaultNoteRow.__table__.schema == "knowledge"

    def test_required_columns_exist(self) -> None:
        from tests.integration._compat.control_db.tables import VaultNoteRow

        cols = _column_names(VaultNoteRow)
        expected = {
            "note_id",
            "category",
            "trust_level",
            "content",
            "source",
            "note_metadata",
            "tags",
            "related_artifacts",
            "invalidation_trigger",
            "created_at",
            "updated_at",
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_primary_key_is_note_id(self) -> None:
        from tests.integration._compat.control_db.tables import VaultNoteRow

        col = _column_by_name(VaultNoteRow, "note_id")
        assert col.primary_key

    def test_note_metadata_column_is_jsonb(self) -> None:
        from tests.integration._compat.control_db.tables import VaultNoteRow

        col = _column_by_name(VaultNoteRow, "note_metadata")
        assert col.type.__class__.__name__ == "JSONB"

    def test_note_metadata_has_gin_index(self) -> None:
        from tests.integration._compat.control_db.tables import VaultNoteRow

        assert _has_gin_index(VaultNoteRow, "note_metadata")

    def test_composite_index_on_category_trust_level(self) -> None:
        from tests.integration._compat.control_db.tables import VaultNoteRow

        assert _has_index_with_columns(VaultNoteRow, ["category", "trust_level"])

    def test_created_at_has_server_default(self) -> None:
        from tests.integration._compat.control_db.tables import VaultNoteRow

        col = _column_by_name(VaultNoteRow, "created_at")
        assert col.server_default is not None

    def test_updated_at_has_server_default(self) -> None:
        from tests.integration._compat.control_db.tables import VaultNoteRow

        col = _column_by_name(VaultNoteRow, "updated_at")
        assert col.server_default is not None

    def test_tags_column_is_jsonb(self) -> None:
        from tests.integration._compat.control_db.tables import VaultNoteRow

        col = _column_by_name(VaultNoteRow, "tags")
        assert col.type.__class__.__name__ == "JSONB"

    def test_content_is_not_nullable(self) -> None:
        from tests.integration._compat.control_db.tables import VaultNoteRow

        col = _column_by_name(VaultNoteRow, "content")
        assert not col.nullable


# ---------------------------------------------------------------------------
# IntakeSessionRow
# ---------------------------------------------------------------------------


class TestIntakeSessionRowStructure:
    """IntakeSessionRow stores intake interview sessions in the knowledge schema."""

    def test_tablename(self) -> None:
        from tests.integration._compat.control_db.tables import IntakeSessionRow

        assert IntakeSessionRow.__tablename__ == "intake_sessions"

    def test_schema_is_knowledge(self) -> None:
        from tests.integration._compat.control_db.tables import IntakeSessionRow

        assert IntakeSessionRow.__table__.schema == "knowledge"

    def test_required_columns_exist(self) -> None:
        from tests.integration._compat.control_db.tables import IntakeSessionRow

        cols = _column_names(IntakeSessionRow)
        expected = {
            "session_id",
            "phase",
            "current_stage",
            "project_id",
            "answers",
            "assumptions",
            "blocked_questions",
            "created_at",
            "updated_at",
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_primary_key_is_session_id(self) -> None:
        from tests.integration._compat.control_db.tables import IntakeSessionRow

        col = _column_by_name(IntakeSessionRow, "session_id")
        assert col.primary_key

    def test_project_id_is_indexed(self) -> None:
        from tests.integration._compat.control_db.tables import IntakeSessionRow

        col = _column_by_name(IntakeSessionRow, "project_id")
        assert col.index

    def test_answers_column_is_jsonb(self) -> None:
        from tests.integration._compat.control_db.tables import IntakeSessionRow

        col = _column_by_name(IntakeSessionRow, "answers")
        assert col.type.__class__.__name__ == "JSONB"

    def test_created_at_has_server_default(self) -> None:
        from tests.integration._compat.control_db.tables import IntakeSessionRow

        col = _column_by_name(IntakeSessionRow, "created_at")
        assert col.server_default is not None

    def test_updated_at_has_server_default(self) -> None:
        from tests.integration._compat.control_db.tables import IntakeSessionRow

        col = _column_by_name(IntakeSessionRow, "updated_at")
        assert col.server_default is not None


# ---------------------------------------------------------------------------
# LegacyBehaviorRow
# ---------------------------------------------------------------------------


class TestLegacyBehaviorRowStructure:
    """LegacyBehaviorRow stores observed legacy behaviors in the knowledge schema."""

    def test_tablename(self) -> None:
        from tests.integration._compat.control_db.tables import LegacyBehaviorRow

        assert LegacyBehaviorRow.__tablename__ == "legacy_behaviors"

    def test_schema_is_knowledge(self) -> None:
        from tests.integration._compat.control_db.tables import LegacyBehaviorRow

        assert LegacyBehaviorRow.__table__.schema == "knowledge"

    def test_required_columns_exist(self) -> None:
        from tests.integration._compat.control_db.tables import LegacyBehaviorRow

        cols = _column_names(LegacyBehaviorRow)
        expected = {
            "entry_id",
            "system",
            "behavior_description",
            "inferred_by",
            "inferred_at",
            "confidence",
            "disposition",
            "reviewed_by",
            "reviewed_at",
            "promoted_to_prl_id",
            "discarded",
            "source_manifest_id",
            "created_at",
            "updated_at",
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_primary_key_is_entry_id(self) -> None:
        from tests.integration._compat.control_db.tables import LegacyBehaviorRow

        col = _column_by_name(LegacyBehaviorRow, "entry_id")
        assert col.primary_key

    def test_system_is_indexed(self) -> None:
        from tests.integration._compat.control_db.tables import LegacyBehaviorRow

        col = _column_by_name(LegacyBehaviorRow, "system")
        assert col.index

    def test_confidence_is_float(self) -> None:
        from tests.integration._compat.control_db.tables import LegacyBehaviorRow

        col = _column_by_name(LegacyBehaviorRow, "confidence")
        assert col.type.__class__.__name__ == "Float"

    def test_disposition_is_nullable(self) -> None:
        from tests.integration._compat.control_db.tables import LegacyBehaviorRow

        col = _column_by_name(LegacyBehaviorRow, "disposition")
        assert col.nullable

    def test_discarded_defaults_to_false(self) -> None:
        from tests.integration._compat.control_db.tables import LegacyBehaviorRow

        col = _column_by_name(LegacyBehaviorRow, "discarded")
        assert col.default is not None
        assert col.default.arg is False

    def test_created_at_has_server_default(self) -> None:
        from tests.integration._compat.control_db.tables import LegacyBehaviorRow

        col = _column_by_name(LegacyBehaviorRow, "created_at")
        assert col.server_default is not None

    def test_updated_at_has_server_default(self) -> None:
        from tests.integration._compat.control_db.tables import LegacyBehaviorRow

        col = _column_by_name(LegacyBehaviorRow, "updated_at")
        assert col.server_default is not None


# ---------------------------------------------------------------------------
# Knowledge tables registered in Base metadata
# ---------------------------------------------------------------------------


class TestKnowledgeTablesInMetadata:
    """All three knowledge tables are registered in the declarative Base."""

    def test_vault_notes_in_metadata(self) -> None:
        table_names = {t.name for t in Base.metadata.tables.values()}
        assert "vault_notes" in table_names

    def test_intake_sessions_in_metadata(self) -> None:
        table_names = {t.name for t in Base.metadata.tables.values()}
        assert "intake_sessions" in table_names

    def test_legacy_behaviors_in_metadata(self) -> None:
        table_names = {t.name for t in Base.metadata.tables.values()}
        assert "legacy_behaviors" in table_names


# ---------------------------------------------------------------------------
# VaultRepository API surface
# ---------------------------------------------------------------------------


class TestVaultRepositoryApiSurface:
    """VaultRepository provides typed CRUD methods for vault notes."""

    def test_has_save_method(self) -> None:
        from tests.integration._compat.control_db.repository import VaultRepository

        assert hasattr(VaultRepository, "save")

    def test_has_get_by_id_method(self) -> None:
        from tests.integration._compat.control_db.repository import VaultRepository

        assert hasattr(VaultRepository, "get_by_id")

    def test_has_get_by_category_method(self) -> None:
        from tests.integration._compat.control_db.repository import VaultRepository

        assert hasattr(VaultRepository, "get_by_category")

    def test_has_get_by_trust_level_method(self) -> None:
        from tests.integration._compat.control_db.repository import VaultRepository

        assert hasattr(VaultRepository, "get_by_trust_level")

    def test_has_update_trust_level_method(self) -> None:
        from tests.integration._compat.control_db.repository import VaultRepository

        assert hasattr(VaultRepository, "update_trust_level")

    def test_has_search_by_tags_method(self) -> None:
        from tests.integration._compat.control_db.repository import VaultRepository

        assert hasattr(VaultRepository, "search_by_tags")

    def test_has_delete_method(self) -> None:
        from tests.integration._compat.control_db.repository import VaultRepository

        assert hasattr(VaultRepository, "delete")


# ---------------------------------------------------------------------------
# IntakeRepository API surface
# ---------------------------------------------------------------------------


class TestIntakeRepositoryApiSurface:
    """IntakeRepository provides typed CRUD methods for intake sessions."""

    def test_has_save_method(self) -> None:
        from tests.integration._compat.control_db.repository import IntakeRepository

        assert hasattr(IntakeRepository, "save")

    def test_has_get_by_id_method(self) -> None:
        from tests.integration._compat.control_db.repository import IntakeRepository

        assert hasattr(IntakeRepository, "get_by_id")

    def test_has_get_by_project_method(self) -> None:
        from tests.integration._compat.control_db.repository import IntakeRepository

        assert hasattr(IntakeRepository, "get_by_project")

    def test_has_update_stage_method(self) -> None:
        from tests.integration._compat.control_db.repository import IntakeRepository

        assert hasattr(IntakeRepository, "update_stage")

    def test_has_update_answers_method(self) -> None:
        from tests.integration._compat.control_db.repository import IntakeRepository

        assert hasattr(IntakeRepository, "update_answers")


# ---------------------------------------------------------------------------
# LegacyBehaviorRepository API surface
# ---------------------------------------------------------------------------


class TestLegacyBehaviorRepositoryApiSurface:
    """LegacyBehaviorRepository provides typed CRUD methods for legacy behaviors."""

    def test_has_save_method(self) -> None:
        from tests.integration._compat.control_db.repository import LegacyBehaviorRepository

        assert hasattr(LegacyBehaviorRepository, "save")

    def test_has_get_by_id_method(self) -> None:
        from tests.integration._compat.control_db.repository import LegacyBehaviorRepository

        assert hasattr(LegacyBehaviorRepository, "get_by_id")

    def test_has_get_by_system_method(self) -> None:
        from tests.integration._compat.control_db.repository import LegacyBehaviorRepository

        assert hasattr(LegacyBehaviorRepository, "get_by_system")

    def test_has_get_pending_method(self) -> None:
        from tests.integration._compat.control_db.repository import LegacyBehaviorRepository

        assert hasattr(LegacyBehaviorRepository, "get_pending")

    def test_has_update_disposition_method(self) -> None:
        from tests.integration._compat.control_db.repository import LegacyBehaviorRepository

        assert hasattr(LegacyBehaviorRepository, "update_disposition")

    def test_has_mark_promoted_method(self) -> None:
        from tests.integration._compat.control_db.repository import LegacyBehaviorRepository

        assert hasattr(LegacyBehaviorRepository, "mark_promoted")


# ---------------------------------------------------------------------------
# VaultRepository behavior (mock session)
# ---------------------------------------------------------------------------


def _make_mock_session():
    """Create a mock AsyncSession with async methods.

    The execute() method returns an awaitable that resolves to a MagicMock
    result object. The result object's scalar_one_or_none() and
    scalars().all() are regular (non-async) methods since they operate
    on the already-fetched result.
    """
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.delete = AsyncMock()
    session.merge = AsyncMock()

    # Make execute() return a regular MagicMock result (not AsyncMock)
    # so scalar_one_or_none() and scalars().all() are synchronous
    mock_result = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)

    return session


class TestVaultRepositorySave:
    """VaultRepository.save() adds a VaultNoteRow to the session."""

    @pytest.mark.asyncio
    async def test_save_adds_and_flushes(self) -> None:
        from tests.integration._compat.control_db.repository import VaultRepository
        from tests.integration._compat.control_db.tables import VaultNoteRow

        session = _make_mock_session()
        repo = VaultRepository(session)
        row = MagicMock(spec=VaultNoteRow)

        result = await repo.save(row)

        session.add.assert_called_once_with(row)
        session.flush.assert_awaited_once()
        assert result is row


class TestVaultRepositoryGetById:
    """VaultRepository.get_by_id() retrieves by note_id."""

    @pytest.mark.asyncio
    async def test_get_by_id_returns_row(self) -> None:
        from tests.integration._compat.control_db.repository import VaultRepository
        from tests.integration._compat.control_db.tables import VaultNoteRow

        session = _make_mock_session()
        mock_row = MagicMock(spec=VaultNoteRow)
        session.execute.return_value.scalar_one_or_none.return_value = mock_row

        repo = VaultRepository(session)
        result = await repo.get_by_id("note-001")

        session.execute.assert_awaited_once()
        assert result is mock_row

    @pytest.mark.asyncio
    async def test_get_by_id_returns_none_when_not_found(self) -> None:
        from tests.integration._compat.control_db.repository import VaultRepository

        session = _make_mock_session()
        session.execute.return_value.scalar_one_or_none.return_value = None

        repo = VaultRepository(session)
        result = await repo.get_by_id("missing-id")

        assert result is None


class TestVaultRepositoryGetByCategory:
    """VaultRepository.get_by_category() filters by category string."""

    @pytest.mark.asyncio
    async def test_get_by_category_returns_list(self) -> None:
        from tests.integration._compat.control_db.repository import VaultRepository
        from tests.integration._compat.control_db.tables import VaultNoteRow

        session = _make_mock_session()
        mock_rows = [MagicMock(spec=VaultNoteRow), MagicMock(spec=VaultNoteRow)]
        session.execute.return_value.scalars.return_value.all.return_value = mock_rows

        repo = VaultRepository(session)
        result = await repo.get_by_category("decisions")

        session.execute.assert_awaited_once()
        assert len(result) == 2


class TestVaultRepositoryGetByTrustLevel:
    """VaultRepository.get_by_trust_level() filters by trust_level string."""

    @pytest.mark.asyncio
    async def test_get_by_trust_level_returns_list(self) -> None:
        from tests.integration._compat.control_db.repository import VaultRepository
        from tests.integration._compat.control_db.tables import VaultNoteRow

        session = _make_mock_session()
        mock_rows = [MagicMock(spec=VaultNoteRow)]
        session.execute.return_value.scalars.return_value.all.return_value = mock_rows

        repo = VaultRepository(session)
        result = await repo.get_by_trust_level("verified")

        session.execute.assert_awaited_once()
        assert len(result) == 1


class TestVaultRepositoryUpdateTrustLevel:
    """VaultRepository.update_trust_level() updates trust_level column."""

    @pytest.mark.asyncio
    async def test_update_trust_level_updates_and_flushes(self) -> None:
        from tests.integration._compat.control_db.repository import VaultRepository
        from tests.integration._compat.control_db.tables import VaultNoteRow

        session = _make_mock_session()
        mock_row = MagicMock(spec=VaultNoteRow)
        session.execute.return_value.scalar_one_or_none.return_value = mock_row

        repo = VaultRepository(session)
        result = await repo.update_trust_level("note-001", "stale-risk")

        assert result is mock_row
        assert mock_row.trust_level == "stale-risk"
        session.flush.assert_awaited()


class TestVaultRepositorySearchByTags:
    """VaultRepository.search_by_tags() queries JSONB tags field."""

    @pytest.mark.asyncio
    async def test_search_by_tags_returns_list(self) -> None:
        from tests.integration._compat.control_db.repository import VaultRepository
        from tests.integration._compat.control_db.tables import VaultNoteRow

        session = _make_mock_session()
        mock_rows = [MagicMock(spec=VaultNoteRow)]
        session.execute.return_value.scalars.return_value.all.return_value = mock_rows

        repo = VaultRepository(session)
        result = await repo.search_by_tags(["auth", "jwt"])

        session.execute.assert_awaited_once()
        assert len(result) == 1


# ---------------------------------------------------------------------------
# IntakeRepository behavior (mock session)
# ---------------------------------------------------------------------------


class TestIntakeRepositorySave:
    """IntakeRepository.save() adds an IntakeSessionRow."""

    @pytest.mark.asyncio
    async def test_save_adds_and_flushes(self) -> None:
        from tests.integration._compat.control_db.repository import IntakeRepository
        from tests.integration._compat.control_db.tables import IntakeSessionRow

        session = _make_mock_session()
        repo = IntakeRepository(session)
        row = MagicMock(spec=IntakeSessionRow)

        result = await repo.save(row)

        session.add.assert_called_once_with(row)
        session.flush.assert_awaited_once()
        assert result is row


class TestIntakeRepositoryGetById:
    """IntakeRepository.get_by_id() retrieves by session_id."""

    @pytest.mark.asyncio
    async def test_get_by_id_returns_row(self) -> None:
        from tests.integration._compat.control_db.repository import IntakeRepository
        from tests.integration._compat.control_db.tables import IntakeSessionRow

        session = _make_mock_session()
        mock_row = MagicMock(spec=IntakeSessionRow)
        session.execute.return_value.scalar_one_or_none.return_value = mock_row

        repo = IntakeRepository(session)
        result = await repo.get_by_id("session-001")

        session.execute.assert_awaited_once()
        assert result is mock_row


class TestIntakeRepositoryGetByProject:
    """IntakeRepository.get_by_project() retrieves sessions for a project_id."""

    @pytest.mark.asyncio
    async def test_get_by_project_returns_list(self) -> None:
        from tests.integration._compat.control_db.repository import IntakeRepository
        from tests.integration._compat.control_db.tables import IntakeSessionRow

        session = _make_mock_session()
        mock_rows = [MagicMock(spec=IntakeSessionRow)]
        session.execute.return_value.scalars.return_value.all.return_value = mock_rows

        repo = IntakeRepository(session)
        result = await repo.get_by_project("proj-001")

        session.execute.assert_awaited_once()
        assert len(result) == 1


class TestIntakeRepositoryUpdateStage:
    """IntakeRepository.update_stage() updates current_stage."""

    @pytest.mark.asyncio
    async def test_update_stage_updates_and_flushes(self) -> None:
        from tests.integration._compat.control_db.repository import IntakeRepository
        from tests.integration._compat.control_db.tables import IntakeSessionRow

        session = _make_mock_session()
        mock_row = MagicMock(spec=IntakeSessionRow)
        session.execute.return_value.scalar_one_or_none.return_value = mock_row

        repo = IntakeRepository(session)
        result = await repo.update_stage("session-001", "conditional")

        assert result is mock_row
        assert mock_row.current_stage == "conditional"
        session.flush.assert_awaited()


# ---------------------------------------------------------------------------
# LegacyBehaviorRepository behavior (mock session)
# ---------------------------------------------------------------------------


class TestLegacyBehaviorRepositorySave:
    """LegacyBehaviorRepository.save() adds a LegacyBehaviorRow."""

    @pytest.mark.asyncio
    async def test_save_adds_and_flushes(self) -> None:
        from tests.integration._compat.control_db.repository import LegacyBehaviorRepository
        from tests.integration._compat.control_db.tables import LegacyBehaviorRow

        session = _make_mock_session()
        repo = LegacyBehaviorRepository(session)
        row = MagicMock(spec=LegacyBehaviorRow)

        result = await repo.save(row)

        session.add.assert_called_once_with(row)
        session.flush.assert_awaited_once()
        assert result is row


class TestLegacyBehaviorRepositoryGetById:
    """LegacyBehaviorRepository.get_by_id() retrieves by entry_id."""

    @pytest.mark.asyncio
    async def test_get_by_id_returns_row(self) -> None:
        from tests.integration._compat.control_db.repository import LegacyBehaviorRepository
        from tests.integration._compat.control_db.tables import LegacyBehaviorRow

        session = _make_mock_session()
        mock_row = MagicMock(spec=LegacyBehaviorRow)
        session.execute.return_value.scalar_one_or_none.return_value = mock_row

        repo = LegacyBehaviorRepository(session)
        result = await repo.get_by_id("entry-001")

        session.execute.assert_awaited_once()
        assert result is mock_row


class TestLegacyBehaviorRepositoryGetPending:
    """LegacyBehaviorRepository.get_pending() returns non-discarded rows with NULL disposition."""

    @pytest.mark.asyncio
    async def test_get_pending_returns_list(self) -> None:
        from tests.integration._compat.control_db.repository import LegacyBehaviorRepository
        from tests.integration._compat.control_db.tables import LegacyBehaviorRow

        session = _make_mock_session()
        mock_rows = [MagicMock(spec=LegacyBehaviorRow)]
        session.execute.return_value.scalars.return_value.all.return_value = mock_rows

        repo = LegacyBehaviorRepository(session)
        result = await repo.get_pending()

        session.execute.assert_awaited_once()
        assert len(result) == 1


class TestLegacyBehaviorRepositoryUpdateDisposition:
    """LegacyBehaviorRepository.update_disposition() sets disposition and reviewer info."""

    @pytest.mark.asyncio
    async def test_update_disposition_sets_fields(self) -> None:
        from tests.integration._compat.control_db.repository import LegacyBehaviorRepository
        from tests.integration._compat.control_db.tables import LegacyBehaviorRow

        session = _make_mock_session()
        mock_row = MagicMock(spec=LegacyBehaviorRow)
        session.execute.return_value.scalar_one_or_none.return_value = mock_row

        repo = LegacyBehaviorRepository(session)
        now = datetime.now(tz=timezone.utc)
        result = await repo.update_disposition("entry-001", "preserve", "reviewer-1", now)

        assert result is mock_row
        assert mock_row.disposition == "preserve"
        assert mock_row.reviewed_by == "reviewer-1"
        assert mock_row.reviewed_at == now
        session.flush.assert_awaited()


# ---------------------------------------------------------------------------
# Alembic migration structure
# ---------------------------------------------------------------------------


class TestAlembicMigration005:
    """005_knowledge_tables migration creates knowledge schema and tables."""

    def _load_migration(self):
        """Load the migration module from the alembic/versions directory."""
        import importlib.util
        from pathlib import Path

        migration_path = Path(__file__).resolve().parent / "alembic" / "versions" / "005_knowledge_tables.py"
        spec = importlib.util.spec_from_file_location("migration_005", migration_path)
        assert spec is not None, f"Migration file not found at {migration_path}"
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod

    def test_migration_file_exists(self) -> None:
        mod = self._load_migration()
        assert hasattr(mod, "upgrade")
        assert hasattr(mod, "downgrade")

    def test_revision_is_005(self) -> None:
        mod = self._load_migration()
        assert mod.revision == "005"

    def test_down_revision_is_001(self) -> None:
        mod = self._load_migration()
        assert mod.down_revision == "001"
