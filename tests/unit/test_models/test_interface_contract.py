"""Tests for InterfaceContract model (PRD SS2.4)."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ces.control.models.interface_contract import InterfaceContract
from ces.shared.enums import (
    ArtifactStatus,
    CompatibilityRule,
    ContractStatus,
    ImpactScope,
    InterfaceType,
    VersioningRule,
)


def _make_interface_contract(**overrides):
    """Factory for valid InterfaceContract data."""
    defaults = {
        "schema_type": "interface_contract",
        "contract_id": "IC-001",
        "version": 1,
        "status": ArtifactStatus.DRAFT,
        "owner": "team-lead@example.com",
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "last_confirmed": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "producer": "comp-api",
        "consumers": ("comp-frontend", "comp-mobile"),
        "interface_type": InterfaceType.API,
        "schema_ref": "openapi/v1/users.yaml",
        "versioning_rule": VersioningRule.SEMVER,
        "compatibility_rule": CompatibilityRule.BACKWARDS_COMPATIBLE,
        "impact_scope": ImpactScope.CROSS_TEAM,
    }
    defaults.update(overrides)
    return defaults


class TestInterfaceContract:
    """Tests for InterfaceContract model."""

    def test_schema_type_literal(self):
        """InterfaceContract has schema_type Literal['interface_contract']."""
        ic = InterfaceContract(**_make_interface_contract())
        assert ic.schema_type == "interface_contract"

    def test_required_fields(self):
        """InterfaceContract requires all specified fields."""
        ic = InterfaceContract(**_make_interface_contract())
        assert ic.contract_id == "IC-001"
        assert ic.producer == "comp-api"
        assert ic.consumers == ("comp-frontend", "comp-mobile")
        assert ic.interface_type == InterfaceType.API
        assert ic.schema_ref == "openapi/v1/users.yaml"
        assert ic.versioning_rule == VersioningRule.SEMVER
        assert ic.compatibility_rule == CompatibilityRule.BACKWARDS_COMPATIBLE
        assert ic.impact_scope == ImpactScope.CROSS_TEAM

    def test_round_trip_serialization(self):
        """InterfaceContract round-trips through model_dump/model_validate."""
        original = InterfaceContract(**_make_interface_contract())
        data = original.model_dump()
        restored = InterfaceContract.model_validate(data)
        assert original == restored

    def test_inherits_governed_artifact_base(self):
        """InterfaceContract inherits GovernedArtifactBase fields."""
        ic = InterfaceContract(**_make_interface_contract())
        assert ic.version == 1
        assert ic.status == ArtifactStatus.DRAFT
        assert ic.owner == "team-lead@example.com"

    def test_missing_required_field_raises(self):
        """Missing required field raises ValidationError."""
        data = _make_interface_contract()
        del data["producer"]
        with pytest.raises(ValidationError):
            InterfaceContract(**data)

    def test_schema_type_rejects_wrong_value(self):
        """schema_type must be exactly 'interface_contract'."""
        with pytest.raises(ValidationError):
            InterfaceContract(**_make_interface_contract(schema_type="wrong"))

    def test_all_interface_types_accepted(self):
        """All InterfaceType enum values are accepted."""
        for itype in InterfaceType:
            ic = InterfaceContract(**_make_interface_contract(interface_type=itype))
            assert ic.interface_type == itype

    def test_all_versioning_rules_accepted(self):
        """All VersioningRule enum values are accepted."""
        for rule in VersioningRule:
            ic = InterfaceContract(**_make_interface_contract(versioning_rule=rule))
            assert ic.versioning_rule == rule
