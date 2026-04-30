"""Tests for CES database layer structure (ces.control.db).

Validates ORM table definitions, column names, types, constraints,
and repository API surface without requiring a live database.
These are structural assertions on the SQLAlchemy metadata.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect as sa_inspect

pytestmark = pytest.mark.integration

from tests.integration._compat.control_db.base import Base
from tests.integration._compat.control_db.repository import (
    AuditRepository,
    ManifestRepository,
    TruthArtifactRepository,
)
from tests.integration._compat.control_db.tables import (
    AuditEntryRow,
    HarnessProfileRow,
    KillSwitchStateRow,
    ManifestRow,
    TrustEventRow,
    TruthArtifactRow,
    WorkflowStateRow,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _column_names(model: type) -> set[str]:
    """Extract column names from an ORM model class."""
    mapper = sa_inspect(model)
    return {col.key for col in mapper.columns}


def _column_by_name(model: type, name: str):
    """Get a specific column object from an ORM model."""
    mapper = sa_inspect(model)
    return mapper.columns[name]


# ---------------------------------------------------------------------------
# TruthArtifactRow
# ---------------------------------------------------------------------------


class TestTruthArtifactRowStructure:
    """TruthArtifactRow has all required columns for truth artifact storage."""

    def test_tablename(self) -> None:
        assert TruthArtifactRow.__tablename__ == "truth_artifacts"

    def test_schema_is_control(self) -> None:
        assert TruthArtifactRow.__table__.schema == "control"

    def test_required_columns_exist(self) -> None:
        cols = _column_names(TruthArtifactRow)
        expected = {
            "id",
            "type",
            "version",
            "status",
            "content",
            "content_hash",
            "owner",
            "signature",
            "created_at",
            "updated_at",
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_primary_key_is_id(self) -> None:
        col = _column_by_name(TruthArtifactRow, "id")
        assert col.primary_key

    def test_content_column_is_jsonb(self) -> None:
        col = _column_by_name(TruthArtifactRow, "content")
        assert col.type.__class__.__name__ == "JSONB"

    def test_signature_is_nullable(self) -> None:
        col = _column_by_name(TruthArtifactRow, "signature")
        assert col.nullable


# ---------------------------------------------------------------------------
# ManifestRow
# ---------------------------------------------------------------------------


class TestManifestRowStructure:
    """ManifestRow has all required columns for manifest persistence."""

    def test_tablename(self) -> None:
        assert ManifestRow.__tablename__ == "manifests"

    def test_schema_is_control(self) -> None:
        assert ManifestRow.__table__.schema == "control"

    def test_required_columns_exist(self) -> None:
        cols = _column_names(ManifestRow)
        expected = {
            "manifest_id",
            "description",
            "risk_tier",
            "behavior_confidence",
            "change_class",
            "content",
            "content_hash",
            "signature",
            "status",
            "expires_at",
            "classifier_id",
            "implementer_id",
            "created_at",
            "updated_at",
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_primary_key_is_manifest_id(self) -> None:
        col = _column_by_name(ManifestRow, "manifest_id")
        assert col.primary_key

    def test_content_column_is_jsonb(self) -> None:
        col = _column_by_name(ManifestRow, "content")
        assert col.type.__class__.__name__ == "JSONB"

    def test_status_is_indexed(self) -> None:
        col = _column_by_name(ManifestRow, "status")
        assert col.index


# ---------------------------------------------------------------------------
# AuditEntryRow
# ---------------------------------------------------------------------------


class TestAuditEntryRowStructure:
    """AuditEntryRow has all required columns for append-only audit ledger."""

    def test_tablename(self) -> None:
        assert AuditEntryRow.__tablename__ == "audit_entries"

    def test_schema_is_control(self) -> None:
        assert AuditEntryRow.__table__.schema == "control"

    def test_required_columns_exist(self) -> None:
        cols = _column_names(AuditEntryRow)
        expected = {
            "entry_id",
            "sequence_num",
            "timestamp",
            "event_type",
            "actor",
            "actor_type",
            "scope",
            "action_summary",
            "decision",
            "rationale",
            "metadata_extra",
            "prev_hash",
            "entry_hash",
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_primary_key_is_entry_id(self) -> None:
        col = _column_by_name(AuditEntryRow, "entry_id")
        assert col.primary_key

    def test_sequence_num_is_unique(self) -> None:
        col = _column_by_name(AuditEntryRow, "sequence_num")
        assert col.unique

    def test_timestamp_is_indexed(self) -> None:
        col = _column_by_name(AuditEntryRow, "timestamp")
        assert col.index

    def test_scope_column_is_jsonb(self) -> None:
        col = _column_by_name(AuditEntryRow, "scope")
        assert col.type.__class__.__name__ == "JSONB"

    def test_prev_hash_has_genesis_default(self) -> None:
        col = _column_by_name(AuditEntryRow, "prev_hash")
        assert col.default is not None
        assert col.default.arg == "GENESIS"


# ---------------------------------------------------------------------------
# WorkflowStateRow
# ---------------------------------------------------------------------------


class TestWorkflowStateRowStructure:
    """WorkflowStateRow provides fast manifest workflow status lookup."""

    def test_tablename(self) -> None:
        assert WorkflowStateRow.__tablename__ == "workflow_states"

    def test_schema_is_control(self) -> None:
        assert WorkflowStateRow.__table__.schema == "control"

    def test_required_columns_exist(self) -> None:
        cols = _column_names(WorkflowStateRow)
        expected = {
            "manifest_id",
            "current_state",
            "sub_state",
            "retry_count",
            "updated_at",
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_primary_key_is_manifest_id(self) -> None:
        col = _column_by_name(WorkflowStateRow, "manifest_id")
        assert col.primary_key

    def test_manifest_id_has_foreign_key(self) -> None:
        col = _column_by_name(WorkflowStateRow, "manifest_id")
        fk_targets = {fk.target_fullname for fk in col.foreign_keys}
        assert "control.manifests.manifest_id" in fk_targets

    def test_current_state_is_indexed(self) -> None:
        col = _column_by_name(WorkflowStateRow, "current_state")
        assert col.index

    def test_retry_count_defaults_to_zero(self) -> None:
        col = _column_by_name(WorkflowStateRow, "retry_count")
        assert col.default is not None
        assert col.default.arg == 0


# ---------------------------------------------------------------------------
# HarnessProfileRow
# ---------------------------------------------------------------------------


class TestHarnessProfileRowStructure:
    """HarnessProfileRow stores agent harness profiles in the harness schema."""

    def test_tablename(self) -> None:
        assert HarnessProfileRow.__tablename__ == "harness_profiles"

    def test_schema_is_harness(self) -> None:
        assert HarnessProfileRow.__table__.schema == "harness"

    def test_required_columns_exist(self) -> None:
        cols = _column_names(HarnessProfileRow)
        expected = {
            "profile_id",
            "agent_id",
            "trust_status",
            "profile_data",
            "created_at",
            "updated_at",
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_primary_key_is_profile_id(self) -> None:
        col = _column_by_name(HarnessProfileRow, "profile_id")
        assert col.primary_key

    def test_agent_id_is_unique(self) -> None:
        col = _column_by_name(HarnessProfileRow, "agent_id")
        assert col.unique

    def test_profile_data_is_jsonb(self) -> None:
        col = _column_by_name(HarnessProfileRow, "profile_data")
        assert col.type.__class__.__name__ == "JSONB"


# ---------------------------------------------------------------------------
# KillSwitchStateRow
# ---------------------------------------------------------------------------


class TestKillSwitchStateRowStructure:
    """KillSwitchStateRow stores kill switch state per activity class."""

    def test_tablename(self) -> None:
        assert KillSwitchStateRow.__tablename__ == "kill_switch_state"

    def test_schema_is_control(self) -> None:
        assert KillSwitchStateRow.__table__.schema == "control"

    def test_required_columns_exist(self) -> None:
        cols = _column_names(KillSwitchStateRow)
        expected = {
            "activity_class",
            "halted",
            "halted_by",
            "halted_at",
            "reason",
            "updated_at",
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_primary_key_is_activity_class(self) -> None:
        col = _column_by_name(KillSwitchStateRow, "activity_class")
        assert col.primary_key


# ---------------------------------------------------------------------------
# TrustEventRow
# ---------------------------------------------------------------------------


class TestTrustEventRowStructure:
    """TrustEventRow records trust lifecycle transitions."""

    def test_tablename(self) -> None:
        assert TrustEventRow.__tablename__ == "trust_events"

    def test_schema_is_harness(self) -> None:
        assert TrustEventRow.__table__.schema == "harness"

    def test_required_columns_exist(self) -> None:
        cols = _column_names(TrustEventRow)
        expected = {
            "event_id",
            "profile_id",
            "old_status",
            "new_status",
            "trigger",
            "created_at",
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_primary_key_is_event_id(self) -> None:
        col = _column_by_name(TrustEventRow, "event_id")
        assert col.primary_key

    def test_profile_id_is_indexed(self) -> None:
        col = _column_by_name(TrustEventRow, "profile_id")
        assert col.index


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class TestDeclarativeBase:
    """Base class inherits AsyncAttrs for async lazy-load support."""

    def test_base_is_declarative_base(self) -> None:
        from sqlalchemy.orm import DeclarativeBase

        assert issubclass(Base, DeclarativeBase)

    def test_all_tables_registered_in_metadata(self) -> None:
        table_names = {t.name for t in Base.metadata.tables.values()}
        expected = {
            "truth_artifacts",
            "manifests",
            "audit_entries",
            "workflow_states",
            "harness_profiles",
            "kill_switch_state",
            "trust_events",
        }
        assert expected.issubset(table_names), f"Missing tables: {expected - table_names}"


# ---------------------------------------------------------------------------
# Repository API surface (no DB required)
# ---------------------------------------------------------------------------


class TestAuditRepositoryApiSurface:
    """AuditRepository exposes append-only API per D-07."""

    def test_has_append_method(self) -> None:
        assert hasattr(AuditRepository, "append")

    def test_has_no_update_method(self) -> None:
        """D-07: Audit repository must NOT have an update method."""
        assert not hasattr(AuditRepository, "update")

    def test_has_no_delete_method(self) -> None:
        """D-07: Audit repository must NOT have a delete method."""
        assert not hasattr(AuditRepository, "delete")

    def test_has_read_methods(self) -> None:
        assert hasattr(AuditRepository, "get_latest")
        assert hasattr(AuditRepository, "get_by_event_type")
        assert hasattr(AuditRepository, "get_by_actor")
        assert hasattr(AuditRepository, "get_by_time_range")
        assert hasattr(AuditRepository, "get_last_entry")
        assert hasattr(AuditRepository, "get_by_id")


class TestTruthArtifactRepositoryApiSurface:
    """TruthArtifactRepository supports full CRUD for truth artifacts."""

    def test_has_save_method(self) -> None:
        assert hasattr(TruthArtifactRepository, "save")

    def test_has_update_method(self) -> None:
        assert hasattr(TruthArtifactRepository, "update")

    def test_has_delete_method(self) -> None:
        assert hasattr(TruthArtifactRepository, "delete")

    def test_has_read_methods(self) -> None:
        assert hasattr(TruthArtifactRepository, "get_by_id")
        assert hasattr(TruthArtifactRepository, "get_by_type")
        assert hasattr(TruthArtifactRepository, "get_approved")


class TestManifestRepositoryApiSurface:
    """ManifestRepository supports full CRUD for manifests."""

    def test_has_save_method(self) -> None:
        assert hasattr(ManifestRepository, "save")

    def test_has_update_method(self) -> None:
        assert hasattr(ManifestRepository, "update")

    def test_has_delete_method(self) -> None:
        assert hasattr(ManifestRepository, "delete")

    def test_has_read_methods(self) -> None:
        assert hasattr(ManifestRepository, "get_by_id")
        assert hasattr(ManifestRepository, "get_active")
