"""Tests for MigrationControlPack model (PRD SS2.5)."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ces.control.models.migration_control_pack import (
    CoexistencePlan,
    CutoverPlan,
    DispositionDecision,
    ExitCriterion,
    GoldenMasterTrace,
    InventoryItem,
    MigrationControlPack,
    ReconciliationRule,
    RollbackScenario,
    SourceOfRecord,
)
from ces.shared.enums import (
    ArtifactStatus,
    Disposition,
    MigrationStatus,
    ReconciliationFrequency,
)


def _make_migration_pack(**overrides):
    """Factory for valid MigrationControlPack data."""
    defaults = {
        "schema_type": "migration_control_pack",
        "pack_id": "MCP-001",
        "version": 1,
        "status": ArtifactStatus.DRAFT,
        "owner": "migration-lead@example.com",
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "last_confirmed": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "domain": "user-management",
        "current_state_inventory": (
            {
                "system": "legacy-auth",
                "role": "Authentication provider",
                "data_stores": ("users_db",),
                "interfaces": ("IC-001",),
                "behavioral_notes": "Handles all auth flows",
            },
        ),
        "disposition_decisions": (
            {
                "item": "legacy-auth",
                "disposition": Disposition.CHANGE,
                "rationale": "Migrating to new auth system",
                "deciding_authority": "architect@example.com",
                "decided_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
        ),
        "source_of_record": (
            {
                "data_domain": "user-profiles",
                "current_source": "legacy-auth",
                "target_source": "new-auth",
                "transition_phase": "Phase 2",
            },
        ),
        "golden_master_traces": (
            {
                "trace_id": "GM-001",
                "behavior": "Login with valid credentials",
                "expected_output_ref": "test-fixtures/login-success.json",
            },
        ),
        "reconciliation_rules": (
            {
                "rule_id": "RR-001",
                "description": "User counts must match",
                "frequency": ReconciliationFrequency.DAILY,
                "tolerance": "0 records",
            },
        ),
        "coexistence_plan": {
            "duration": "3 months",
            "boundary": "API gateway routes",
            "routing_rules": "Feature flag per user",
            "data_sync_mechanism": "CDC via Debezium",
        },
        "cutover_plan": {
            "prerequisites": ("All users migrated", "Tests green"),
            "sequence": ("Switch DNS", "Disable legacy"),
            "rollback_trigger": "Error rate > 5%",
            "point_of_no_return": "Legacy DB archived",
        },
        "rollback_matrix": (
            {
                "scenario": "New auth fails",
                "rollback_action": "Revert DNS to legacy",
                "data_recovery": "Replay from CDC log",
                "max_rollback_window": "24 hours",
            },
        ),
        "exit_criteria": (
            {
                "criterion": "Zero traffic to legacy",
                "measurement": "Monitoring dashboard shows 0 requests",
            },
        ),
    }
    defaults.update(overrides)
    return defaults


class TestMigrationControlPack:
    """Tests for MigrationControlPack model."""

    def test_schema_type_literal(self):
        """MigrationControlPack has schema_type Literal['migration_control_pack']."""
        mcp = MigrationControlPack(**_make_migration_pack())
        assert mcp.schema_type == "migration_control_pack"

    def test_required_fields(self):
        """MigrationControlPack requires all specified fields."""
        mcp = MigrationControlPack(**_make_migration_pack())
        assert mcp.pack_id == "MCP-001"
        assert mcp.domain == "user-management"
        assert len(mcp.current_state_inventory) == 1
        assert len(mcp.disposition_decisions) == 1
        assert len(mcp.source_of_record) == 1
        assert len(mcp.golden_master_traces) == 1
        assert len(mcp.reconciliation_rules) == 1
        assert mcp.coexistence_plan is not None
        assert mcp.cutover_plan is not None
        assert len(mcp.rollback_matrix) == 1
        assert len(mcp.exit_criteria) == 1

    def test_deeply_nested_sub_models(self):
        """MigrationControlPack is the most complex model with deeply nested sub-models."""
        mcp = MigrationControlPack(**_make_migration_pack())
        # Check inventory item
        inv = mcp.current_state_inventory[0]
        assert inv.system == "legacy-auth"
        assert inv.data_stores == ("users_db",)
        # Check disposition
        disp = mcp.disposition_decisions[0]
        assert disp.disposition == Disposition.CHANGE
        # Check coexistence
        assert mcp.coexistence_plan.duration == "3 months"
        # Check cutover
        assert len(mcp.cutover_plan.prerequisites) == 2
        # Check rollback
        assert mcp.rollback_matrix[0].scenario == "New auth fails"

    def test_coexistence_plan_sub_model(self):
        """CoexistencePlan has all required fields."""
        cp = CoexistencePlan(
            duration="6 months",
            boundary="Load balancer",
            routing_rules="Percentage split",
            data_sync_mechanism="Event streaming",
        )
        assert cp.duration == "6 months"
        assert cp.data_sync_mechanism == "Event streaming"

    def test_cutover_plan_sub_model(self):
        """CutoverPlan has prerequisites, sequence, rollback_trigger, point_of_no_return."""
        cp = CutoverPlan(
            prerequisites=("All tests pass",),
            sequence=("Deploy new", "Migrate data"),
            rollback_trigger="Error rate > 1%",
            point_of_no_return="Old data archived",
        )
        assert cp.prerequisites == ("All tests pass",)
        assert cp.rollback_trigger == "Error rate > 1%"

    def test_rollback_scenario_sub_model(self):
        """RollbackScenario has scenario, rollback_action, data_recovery, max_rollback_window."""
        rs = RollbackScenario(
            scenario="Deployment fails",
            rollback_action="Revert",
            data_recovery="Restore from backup",
            max_rollback_window="1 hour",
        )
        assert rs.scenario == "Deployment fails"
        assert rs.max_rollback_window == "1 hour"

    def test_round_trip_serialization(self):
        """MigrationControlPack round-trips through model_dump/model_validate."""
        original = MigrationControlPack(**_make_migration_pack())
        data = original.model_dump()
        restored = MigrationControlPack.model_validate(data)
        assert original == restored

    def test_inherits_governed_artifact_base(self):
        """MigrationControlPack inherits GovernedArtifactBase fields."""
        mcp = MigrationControlPack(**_make_migration_pack())
        assert mcp.version == 1
        assert mcp.status == ArtifactStatus.DRAFT

    def test_missing_required_field_raises(self):
        """Missing required field raises ValidationError."""
        data = _make_migration_pack()
        del data["domain"]
        with pytest.raises(ValidationError):
            MigrationControlPack(**data)
