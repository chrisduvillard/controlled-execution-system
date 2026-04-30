"""Compatibility tests for CES database schema and constraints.

Tests verify:
- Alembic migrations create all expected tables
- Per-plane schema separation (control, harness, execution)
- Append-only audit ledger trigger blocks UPDATE and DELETE
- INSERT into audit_entries succeeds
- GIN index exists on truth_artifacts.content
- Repository CRUD operations work against real PostgreSQL

These tests cover internal PostgreSQL-backed repository compatibility. They are
not part of the supported end-user CES workflow.

Requires Docker for testcontainers PostgreSQL.
Run with: uv run pytest tests/integration/test_db.py -v -m integration
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Schema and table existence tests
# ---------------------------------------------------------------------------


class TestSchemaCreation:
    """Verify per-plane PostgreSQL schemas are created by migration."""

    def test_control_schema_exists(self, sync_engine) -> None:  # type: ignore[no-untyped-def]
        """Control schema must exist after migration."""
        with sync_engine.connect() as conn:
            result = conn.execute(
                text("SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'control'")
            )
            assert result.scalar_one() == "control"

    def test_harness_schema_exists(self, sync_engine) -> None:  # type: ignore[no-untyped-def]
        """Harness schema must exist after migration."""
        with sync_engine.connect() as conn:
            result = conn.execute(
                text("SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'harness'")
            )
            assert result.scalar_one() == "harness"

    def test_execution_schema_exists(self, sync_engine) -> None:  # type: ignore[no-untyped-def]
        """Execution schema must exist after migration."""
        with sync_engine.connect() as conn:
            result = conn.execute(
                text("SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'execution'")
            )
            assert result.scalar_one() == "execution"


class TestTableCreation:
    """Verify all tables are created by Alembic migration."""

    @pytest.mark.parametrize(
        "schema,table",
        [
            ("control", "truth_artifacts"),
            ("control", "manifests"),
            ("control", "audit_entries"),
            ("control", "workflow_states"),
            ("harness", "harness_profiles"),
        ],
    )
    def test_table_exists(self, sync_engine, schema: str, table: str) -> None:  # type: ignore[no-untyped-def]
        """Each expected table must exist in its plane schema."""
        with sync_engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :schema AND table_name = :table"
                ),
                {"schema": schema, "table": table},
            )
            assert result.scalar_one() == table


class TestLegacyServerStatePruned:
    """Verify removed server-era DB surfaces are absent at the migration head."""

    def test_observability_schema_absent(self, sync_engine) -> None:  # type: ignore[no-untyped-def]
        with sync_engine.connect() as conn:
            result = conn.execute(text("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'observability'"))
            assert result.scalar_one_or_none() is None

    def test_polyrepo_schema_absent(self, sync_engine) -> None:  # type: ignore[no-untyped-def]
        with sync_engine.connect() as conn:
            result = conn.execute(text("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'polyrepo'"))
            assert result.scalar_one_or_none() is None

    @pytest.mark.parametrize("table", ["api_keys", "project_members"])
    def test_removed_control_tables_absent(self, sync_engine, table: str) -> None:  # type: ignore[no-untyped-def]
        with sync_engine.connect() as conn:
            result = conn.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_schema = 'control' AND table_name = :table"),
                {"table": table},
            )
            assert result.scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# GIN index test
# ---------------------------------------------------------------------------


class TestIndexes:
    """Verify expected indexes exist."""

    def test_gin_index_on_truth_artifacts_content(self, sync_engine) -> None:  # type: ignore[no-untyped-def]
        """GIN index must exist on control.truth_artifacts.content (D-06)."""
        with sync_engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = 'control' "
                    "AND tablename = 'truth_artifacts' "
                    "AND indexname = 'ix_truth_artifacts_content'"
                )
            )
            assert result.scalar_one() == "ix_truth_artifacts_content"


# ---------------------------------------------------------------------------
# Audit ledger trigger tests (D-07)
# ---------------------------------------------------------------------------


class TestAuditLedgerTrigger:
    """Verify the append-only DB trigger on control.audit_entries."""

    def _insert_audit_entry(self, conn, entry_id: str = "test-001") -> None:  # type: ignore[no-untyped-def]
        """Helper to insert a test audit entry."""
        conn.execute(
            text(
                """
                INSERT INTO control.audit_entries
                    (entry_id, sequence_num, timestamp, event_type, actor,
                     actor_type, scope, action_summary, decision, rationale,
                     prev_hash)
                VALUES
                    (:entry_id, :seq, :ts, 'approval', 'test-actor',
                     'human', '{}', 'Test action', 'approved', 'Test rationale',
                     'GENESIS')
                """
            ),
            {
                "entry_id": entry_id,
                "seq": abs(hash(entry_id)) % 1_000_000,
                "ts": datetime.now(timezone.utc).isoformat(),
            },
        )
        conn.commit()

    def test_audit_insert_succeeds(self, sync_engine) -> None:  # type: ignore[no-untyped-def]
        """INSERT into audit_entries must succeed."""
        entry_id = f"test-insert-{uuid4().hex[:8]}"
        with sync_engine.connect() as conn:
            self._insert_audit_entry(conn, entry_id)

            result = conn.execute(
                text("SELECT entry_id FROM control.audit_entries WHERE entry_id = :eid"),
                {"eid": entry_id},
            )
            assert result.scalar_one() == entry_id

    def test_audit_trigger_blocks_update(self, sync_engine) -> None:  # type: ignore[no-untyped-def]
        """UPDATE on audit_entries must be rejected by trigger (D-07)."""
        entry_id = f"test-update-{uuid4().hex[:8]}"
        with sync_engine.connect() as conn:
            self._insert_audit_entry(conn, entry_id)

            with pytest.raises(Exception, match="may not be modified"):
                conn.execute(
                    text("UPDATE control.audit_entries SET decision = 'tampered' WHERE entry_id = :eid"),
                    {"eid": entry_id},
                )

    def test_audit_trigger_blocks_delete(self, sync_engine) -> None:  # type: ignore[no-untyped-def]
        """DELETE on audit_entries must be rejected by trigger (D-07)."""
        entry_id = f"test-delete-{uuid4().hex[:8]}"
        with sync_engine.connect() as conn:
            self._insert_audit_entry(conn, entry_id)

            with pytest.raises(Exception, match="may not be modified"):
                conn.execute(
                    text("DELETE FROM control.audit_entries WHERE entry_id = :eid"),
                    {"eid": entry_id},
                )


# ---------------------------------------------------------------------------
# Repository integration tests
# ---------------------------------------------------------------------------


class TestTruthArtifactRepository:
    """Integration tests for TruthArtifactRepository against real PG."""

    async def test_save_and_retrieve(self, async_session: AsyncSession) -> None:
        """Save a truth artifact and retrieve it by ID."""
        from tests.integration._compat.control_db.repository import TruthArtifactRepository
        from tests.integration._compat.control_db.tables import TruthArtifactRow

        repo = TruthArtifactRepository(async_session)
        row = TruthArtifactRow(
            id=f"ta-{uuid4().hex[:8]}",
            type="vision_anchor",
            version=1,
            status="draft",
            content={"name": "Test Vision", "version": 1},
            content_hash="abc123",
            owner="test-user",
        )
        saved = await repo.save(row)
        assert saved.id == row.id

        retrieved = await repo.get_by_id(row.id)
        assert retrieved is not None
        assert retrieved.type == "vision_anchor"
        assert retrieved.content["name"] == "Test Vision"


class TestAuditRepository:
    """Integration tests for AuditRepository against real PG."""

    async def test_append_and_get_latest(self, async_session: AsyncSession) -> None:
        """Append an audit entry and retrieve it."""
        from tests.integration._compat.control_db.repository import AuditRepository
        from tests.integration._compat.control_db.tables import AuditEntryRow

        repo = AuditRepository(async_session)
        row = AuditEntryRow(
            entry_id=f"ae-{uuid4().hex[:8]}",
            sequence_num=abs(hash(uuid4().hex)) % 1_000_000_000,
            timestamp=datetime.now(timezone.utc),
            event_type="approval",
            actor="test-actor",
            actor_type="human",
            scope={"manifest_id": "m-001"},
            action_summary="Approved manifest",
            decision="approved",
            rationale="All checks passed",
            prev_hash="GENESIS",
        )
        appended = await repo.append(row)
        assert appended.entry_id == row.entry_id

        last = await repo.get_last_entry()
        assert last is not None
        assert last.entry_id == row.entry_id


class TestManifestRepository:
    """Integration tests for ManifestRepository against real PG."""

    async def test_save_and_retrieve(self, async_session: AsyncSession) -> None:
        """Save a manifest and retrieve it by ID."""
        from tests.integration._compat.control_db.repository import ManifestRepository
        from tests.integration._compat.control_db.tables import ManifestRow

        repo = ManifestRepository(async_session)
        row = ManifestRow(
            manifest_id=f"m-{uuid4().hex[:8]}",
            description="Test manifest",
            risk_tier="B",
            behavior_confidence="BC2",
            change_class="Class 2",
            content={"description": "Test"},
            content_hash="def456",
            status="draft",
            expires_at=datetime(2026, 12, 31, tzinfo=timezone.utc),
        )
        saved = await repo.save(row)
        assert saved.manifest_id == row.manifest_id

        retrieved = await repo.get_by_id(row.manifest_id)
        assert retrieved is not None
        assert retrieved.risk_tier == "B"
