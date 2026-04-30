"""Tests for CES ORM table definitions (ces.control.db.tables)."""

from __future__ import annotations

import pytest
from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

pytestmark = pytest.mark.integration

from tests.integration._compat.control_db.base import Base
from tests.integration._compat.control_db.tables import (
    AuditEntryRow,
    HarnessProfileRow,
    IntakeSessionRow,
    KillSwitchStateRow,
    LegacyBehaviorRow,
    ManifestRow,
    TrustEventRow,
    TruthArtifactRow,
    VaultNoteRow,
    WorkflowStateRow,
)

# ---------------------------------------------------------------------------
# Expected table metadata
# ---------------------------------------------------------------------------

ALL_TABLE_CLASSES = [
    TruthArtifactRow,
    ManifestRow,
    AuditEntryRow,
    WorkflowStateRow,
    KillSwitchStateRow,
    TrustEventRow,
    HarnessProfileRow,
    VaultNoteRow,
    IntakeSessionRow,
    LegacyBehaviorRow,
]

EXPECTED_TABLENAMES = {
    TruthArtifactRow: "truth_artifacts",
    ManifestRow: "manifests",
    AuditEntryRow: "audit_entries",
    WorkflowStateRow: "workflow_states",
    KillSwitchStateRow: "kill_switch_state",
    TrustEventRow: "trust_events",
    HarnessProfileRow: "harness_profiles",
    VaultNoteRow: "vault_notes",
    IntakeSessionRow: "intake_sessions",
    LegacyBehaviorRow: "legacy_behaviors",
}


class TestTableNames:
    """Each ORM class must map to the correct PostgreSQL table name."""

    @pytest.mark.parametrize(
        "cls,expected_name",
        list(EXPECTED_TABLENAMES.items()),
        ids=[c.__name__ for c in EXPECTED_TABLENAMES],
    )
    def test_tablename(self, cls, expected_name: str) -> None:
        assert cls.__tablename__ == expected_name


class TestMetadataRegistration:
    """All supported tables must be registered in Base.metadata."""

    def test_all_tables_in_metadata(self) -> None:
        registered = set(Base.metadata.tables.keys())
        for cls in ALL_TABLE_CLASSES:
            schema = (
                cls.__table_args__[-1]["schema"]
                if isinstance(cls.__table_args__, tuple)
                else cls.__table_args__.get("schema")
            )
            if schema:
                qualified = f"{schema}.{cls.__tablename__}"
            else:
                qualified = cls.__tablename__
            assert qualified in registered, f"{qualified} not in metadata"


class TestTruthArtifactRowColumns:
    """TruthArtifactRow must have all expected columns with correct types."""

    def test_has_expected_columns(self) -> None:
        cols = {c.name for c in TruthArtifactRow.__table__.columns}
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
        assert expected.issubset(cols)

    def test_primary_key_is_id(self) -> None:
        pk_cols = [c.name for c in TruthArtifactRow.__table__.primary_key.columns]
        assert pk_cols == ["id"]

    def test_content_column_is_jsonb(self) -> None:
        col = TruthArtifactRow.__table__.c.content
        assert isinstance(col.type, JSONB)

    def test_id_column_is_string(self) -> None:
        col = TruthArtifactRow.__table__.c.id
        assert isinstance(col.type, String)

    def test_timestamps_are_datetime(self) -> None:
        for name in ("created_at", "updated_at"):
            col = TruthArtifactRow.__table__.c[name]
            assert isinstance(col.type, DateTime)

    def test_schema_is_control(self) -> None:
        assert TruthArtifactRow.__table__.schema == "control"


class TestTruthArtifactGINIndex:
    """TruthArtifactRow must have a GIN index on content column."""

    def test_gin_index_exists(self) -> None:
        indexes = list(TruthArtifactRow.__table__.indexes)
        gin_indexes = [idx for idx in indexes if "content" in [c.name for c in idx.columns]]
        assert len(gin_indexes) >= 1, "GIN index on content not found"


class TestManifestRowColumns:
    """ManifestRow must have all expected columns."""

    def test_has_expected_columns(self) -> None:
        cols = {c.name for c in ManifestRow.__table__.columns}
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
        assert expected.issubset(cols)

    def test_primary_key_is_manifest_id(self) -> None:
        pk_cols = [c.name for c in ManifestRow.__table__.primary_key.columns]
        assert pk_cols == ["manifest_id"]

    def test_content_is_jsonb(self) -> None:
        col = ManifestRow.__table__.c.content
        assert isinstance(col.type, JSONB)


class TestAuditEntryRowColumns:
    """AuditEntryRow must have all expected columns including sequence."""

    def test_has_expected_columns(self) -> None:
        cols = {c.name for c in AuditEntryRow.__table__.columns}
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
        assert expected.issubset(cols)

    def test_primary_key_is_entry_id(self) -> None:
        pk_cols = [c.name for c in AuditEntryRow.__table__.primary_key.columns]
        assert pk_cols == ["entry_id"]

    def test_sequence_num_is_biginteger(self) -> None:
        col = AuditEntryRow.__table__.c.sequence_num
        assert isinstance(col.type, BigInteger)

    def test_scope_is_jsonb(self) -> None:
        col = AuditEntryRow.__table__.c.scope
        assert isinstance(col.type, JSONB)


class TestWorkflowStateRowColumns:
    """WorkflowStateRow must have the expected columns and FK."""

    def test_has_expected_columns(self) -> None:
        cols = {c.name for c in WorkflowStateRow.__table__.columns}
        expected = {
            "manifest_id",
            "current_state",
            "sub_state",
            "retry_count",
            "updated_at",
        }
        assert expected.issubset(cols)

    def test_foreign_key_to_manifests(self) -> None:
        fks = list(WorkflowStateRow.__table__.foreign_keys)
        assert len(fks) >= 1
        fk_targets = [fk.target_fullname for fk in fks]
        assert any("manifests.manifest_id" in t for t in fk_targets)


class TestKillSwitchStateRowColumns:
    """KillSwitchStateRow must have activity_class as PK."""

    def test_has_expected_columns(self) -> None:
        cols = {c.name for c in KillSwitchStateRow.__table__.columns}
        expected = {
            "activity_class",
            "halted",
            "halted_by",
            "halted_at",
            "reason",
            "updated_at",
        }
        assert expected.issubset(cols)

    def test_primary_key_is_activity_class(self) -> None:
        pk_cols = [c.name for c in KillSwitchStateRow.__table__.primary_key.columns]
        assert pk_cols == ["activity_class"]

    def test_halted_is_boolean(self) -> None:
        col = KillSwitchStateRow.__table__.c.halted
        assert isinstance(col.type, Boolean)


class TestTrustEventRowColumns:
    """TrustEventRow must have the expected columns in harness schema."""

    def test_has_expected_columns(self) -> None:
        cols = {c.name for c in TrustEventRow.__table__.columns}
        expected = {
            "event_id",
            "profile_id",
            "old_status",
            "new_status",
            "trigger",
            "metadata_extra",
            "created_at",
        }
        assert expected.issubset(cols)

    def test_schema_is_harness(self) -> None:
        assert TrustEventRow.__table__.schema == "harness"


class TestHarnessProfileRowColumns:
    """HarnessProfileRow must have the expected columns."""

    def test_has_expected_columns(self) -> None:
        cols = {c.name for c in HarnessProfileRow.__table__.columns}
        expected = {
            "profile_id",
            "agent_id",
            "trust_status",
            "profile_data",
            "created_at",
            "updated_at",
        }
        assert expected.issubset(cols)

    def test_profile_data_is_jsonb(self) -> None:
        col = HarnessProfileRow.__table__.c.profile_data
        assert isinstance(col.type, JSONB)


class TestVaultNoteRowColumns:
    """VaultNoteRow must have the expected columns in knowledge schema."""

    def test_has_expected_columns(self) -> None:
        cols = {c.name for c in VaultNoteRow.__table__.columns}
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
        assert expected.issubset(cols)

    def test_schema_is_knowledge(self) -> None:
        assert VaultNoteRow.__table__.schema == "knowledge"

    def test_tags_is_jsonb(self) -> None:
        col = VaultNoteRow.__table__.c.tags
        assert isinstance(col.type, JSONB)

    def test_composite_index_category_trust(self) -> None:
        indexes = list(VaultNoteRow.__table__.indexes)
        composite = [idx for idx in indexes if {c.name for c in idx.columns} == {"category", "trust_level"}]
        assert len(composite) >= 1, "Composite index on (category, trust_level) not found"


class TestIntakeSessionRowColumns:
    """IntakeSessionRow must have the expected columns."""

    def test_has_expected_columns(self) -> None:
        cols = {c.name for c in IntakeSessionRow.__table__.columns}
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
        assert expected.issubset(cols)

    def test_phase_is_integer(self) -> None:
        col = IntakeSessionRow.__table__.c.phase
        assert isinstance(col.type, Integer)


class TestLegacyBehaviorRowColumns:
    """LegacyBehaviorRow must have the expected columns."""

    def test_has_expected_columns(self) -> None:
        cols = {c.name for c in LegacyBehaviorRow.__table__.columns}
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
        assert expected.issubset(cols)

    def test_confidence_is_float(self) -> None:
        col = LegacyBehaviorRow.__table__.c.confidence
        assert isinstance(col.type, Float)

    def test_discarded_is_boolean(self) -> None:
        col = LegacyBehaviorRow.__table__.c.discarded
        assert isinstance(col.type, Boolean)
