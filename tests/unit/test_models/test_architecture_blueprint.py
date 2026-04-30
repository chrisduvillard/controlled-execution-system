"""Tests for ArchitectureBlueprint model (PRD SS2.3)."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ces.control.models.architecture_blueprint import (
    ArchitectureBlueprint,
    Component,
    ComponentBoundaries,
    DataFlow,
    NFRequirement,
    ProhibitedPattern,
    StateOwnership,
    TrustBoundary,
)
from ces.shared.enums import ArtifactStatus, NFRCategory, Sensitivity


def _make_component(**overrides):
    """Factory for valid Component data."""
    defaults = {
        "component_id": "comp-api",
        "name": "API Gateway",
        "responsibility": "Route requests to services",
        "boundaries": {
            "allowed_dependencies": ("comp-auth",),
            "prohibited_dependencies": ("comp-db-direct",),
        },
        "data_flows": (
            {
                "from_component": "comp-api",
                "to": "comp-auth",
                "data_type": "auth_token",
                "sensitivity": Sensitivity.SENSITIVE,
            },
        ),
        "state_ownership": ({"state_name": "request_context", "owner_component_id": "comp-api"},),
    }
    defaults.update(overrides)
    return defaults


def _make_blueprint(**overrides):
    """Factory for valid ArchitectureBlueprint data."""
    defaults = {
        "schema_type": "architecture_blueprint",
        "blueprint_id": "ARCH-001",
        "version": 1,
        "status": ArtifactStatus.DRAFT,
        "owner": "architect@example.com",
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "last_confirmed": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "components": (_make_component(),),
        "trust_boundaries": (
            {
                "boundary_id": "tb-external",
                "inside": ("comp-api",),
                "outside": ("external-client",),
                "crossing_rules": "All requests must be authenticated",
            },
        ),
        "non_functional_requirements": (
            {
                "nfr_id": "NFR-001",
                "category": NFRCategory.PERFORMANCE,
                "requirement": "API latency < 200ms p99",
                "measurement": "p99 latency from APM",
            },
        ),
        "prohibited_patterns": (
            {
                "pattern": "Direct database access from API handlers",
                "reason": "Bypasses service layer validation",
            },
        ),
    }
    defaults.update(overrides)
    return defaults


class TestArchitectureBlueprint:
    """Tests for ArchitectureBlueprint model."""

    def test_schema_type_literal(self):
        """ArchitectureBlueprint has schema_type Literal['architecture_blueprint']."""
        bp = ArchitectureBlueprint(**_make_blueprint())
        assert bp.schema_type == "architecture_blueprint"

    def test_required_fields(self):
        """ArchitectureBlueprint requires all specified fields."""
        bp = ArchitectureBlueprint(**_make_blueprint())
        assert bp.blueprint_id == "ARCH-001"
        assert len(bp.components) == 1
        assert len(bp.trust_boundaries) == 1
        assert len(bp.non_functional_requirements) == 1
        assert len(bp.prohibited_patterns) == 1

    def test_component_sub_model(self):
        """Component has all required fields."""
        comp = Component(**_make_component())
        assert comp.component_id == "comp-api"
        assert comp.name == "API Gateway"
        assert comp.responsibility == "Route requests to services"
        assert isinstance(comp.boundaries, ComponentBoundaries)
        assert len(comp.data_flows) == 1
        assert len(comp.state_ownership) == 1

    def test_data_flow_sensitivity(self):
        """DataFlow has sensitivity enum field."""
        df = DataFlow(
            from_component="comp-a",
            to="comp-b",
            data_type="user_data",
            sensitivity=Sensitivity.REGULATED,
        )
        assert df.sensitivity == Sensitivity.REGULATED

    def test_trust_boundary_sub_model(self):
        """TrustBoundary has boundary_id, inside, outside, crossing_rules."""
        tb = TrustBoundary(
            boundary_id="tb-1",
            inside=("comp-a",),
            outside=("comp-b",),
            crossing_rules="Must authenticate",
        )
        assert tb.boundary_id == "tb-1"
        assert tb.inside == ("comp-a",)
        assert tb.outside == ("comp-b",)

    def test_nf_requirement_sub_model(self):
        """NFRequirement has nfr_id, category, requirement, measurement."""
        nfr = NFRequirement(
            nfr_id="NFR-001",
            category=NFRCategory.SECURITY,
            requirement="All data encrypted at rest",
            measurement="Encryption audit check",
        )
        assert nfr.category == NFRCategory.SECURITY

    def test_prohibited_pattern_sub_model(self):
        """ProhibitedPattern has pattern and reason."""
        pp = ProhibitedPattern(
            pattern="God objects",
            reason="Violates single responsibility",
        )
        assert pp.pattern == "God objects"
        assert pp.reason == "Violates single responsibility"

    def test_state_ownership_sub_model(self):
        """StateOwnership has state_name and owner_component_id."""
        so = StateOwnership(
            state_name="session",
            owner_component_id="comp-auth",
        )
        assert so.state_name == "session"
        assert so.owner_component_id == "comp-auth"

    def test_round_trip_serialization(self):
        """ArchitectureBlueprint round-trips through model_dump/model_validate."""
        original = ArchitectureBlueprint(**_make_blueprint())
        data = original.model_dump()
        restored = ArchitectureBlueprint.model_validate(data)
        assert original == restored

    def test_inherits_governed_artifact_base(self):
        """ArchitectureBlueprint inherits GovernedArtifactBase fields."""
        bp = ArchitectureBlueprint(**_make_blueprint())
        assert bp.version == 1
        assert bp.status == ArtifactStatus.DRAFT
        assert bp.owner == "architect@example.com"

    def test_missing_required_field_raises(self):
        """Missing required field raises ValidationError."""
        data = _make_blueprint()
        del data["components"]
        with pytest.raises(ValidationError):
            ArchitectureBlueprint(**data)
