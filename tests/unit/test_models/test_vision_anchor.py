"""Tests for VisionAnchor model (PRD SS2.1)."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ces.control.models.vision_anchor import (
    HardConstraint,
    KillCriterion,
    TargetUser,
    VisionAnchor,
)
from ces.shared.enums import ArtifactStatus


def _make_vision_anchor(**overrides):
    """Factory for valid VisionAnchor data."""
    defaults = {
        "schema_type": "vision_anchor",
        "anchor_id": "VA-001",
        "version": 1,
        "status": ArtifactStatus.DRAFT,
        "owner": "product-owner@example.com",
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "last_confirmed": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "target_users": ({"segment": "engineering-teams", "description": "Teams using AI agents"},),
        "problem_statement": "AI agents ship plausible but wrong code",
        "intended_value": "Deterministic governance controls",
        "non_goals": ("Web UI", "Mobile app"),
        "experience_expectations": ("Fast feedback loops", "Clear audit trails"),
        "hard_constraints": ({"constraint": "No LLM in control plane", "source": "PRD SS2.4"},),
        "kill_criteria": (
            {
                "criterion": "Agent output uncontrollable",
                "measurement": "3 consecutive governance bypasses",
            },
        ),
    }
    defaults.update(overrides)
    return defaults


class TestVisionAnchor:
    """Tests for VisionAnchor model."""

    def test_schema_type_literal(self):
        """VisionAnchor has schema_type Literal['vision_anchor']."""
        va = VisionAnchor(**_make_vision_anchor())
        assert va.schema_type == "vision_anchor"

    def test_schema_type_rejects_wrong_value(self):
        """schema_type must be exactly 'vision_anchor'."""
        with pytest.raises(ValidationError):
            VisionAnchor(**_make_vision_anchor(schema_type="wrong"))

    def test_required_fields(self):
        """VisionAnchor requires all specified fields."""
        va = VisionAnchor(**_make_vision_anchor())
        assert va.anchor_id == "VA-001"
        assert len(va.target_users) == 1
        assert va.problem_statement == "AI agents ship plausible but wrong code"
        assert va.intended_value == "Deterministic governance controls"
        assert va.non_goals == ("Web UI", "Mobile app")
        assert len(va.experience_expectations) == 2
        assert len(va.hard_constraints) == 1
        assert len(va.kill_criteria) == 1

    def test_inherits_governed_artifact_base(self):
        """VisionAnchor inherits GovernedArtifactBase fields."""
        va = VisionAnchor(**_make_vision_anchor())
        assert va.version == 1
        assert va.status == ArtifactStatus.DRAFT
        assert va.owner == "product-owner@example.com"
        assert va.created_at is not None
        assert va.last_confirmed is not None
        assert va.signature is None
        assert va.content_hash is None

    def test_approved_without_signature_raises(self):
        """MODEL-16: Approved status without signature raises ValidationError."""
        with pytest.raises(ValidationError, match="signed"):
            VisionAnchor(**_make_vision_anchor(status=ArtifactStatus.APPROVED))

    def test_approved_with_signature_valid(self):
        """Approved status with signature is valid."""
        va = VisionAnchor(
            **_make_vision_anchor(
                status=ArtifactStatus.APPROVED,
                signature="sig_abc123",
            )
        )
        assert va.status == ArtifactStatus.APPROVED
        assert va.signature == "sig_abc123"

    def test_round_trip_serialization(self):
        """VisionAnchor round-trips through model_dump/model_validate."""
        original = VisionAnchor(**_make_vision_anchor())
        data = original.model_dump()
        restored = VisionAnchor.model_validate(data)
        assert original == restored

    def test_target_user_sub_model(self):
        """TargetUser has segment and description."""
        tu = TargetUser(segment="developers", description="Software developers")
        assert tu.segment == "developers"
        assert tu.description == "Software developers"

    def test_hard_constraint_sub_model(self):
        """HardConstraint has constraint and source."""
        hc = HardConstraint(constraint="No secrets in output", source="Security policy")
        assert hc.constraint == "No secrets in output"
        assert hc.source == "Security policy"

    def test_kill_criterion_sub_model(self):
        """KillCriterion has criterion and measurement."""
        kc = KillCriterion(criterion="Budget exceeded", measurement="Cost > $10k/month")
        assert kc.criterion == "Budget exceeded"
        assert kc.measurement == "Cost > $10k/month"

    def test_missing_required_field_raises(self):
        """Missing required field raises ValidationError."""
        data = _make_vision_anchor()
        del data["problem_statement"]
        with pytest.raises(ValidationError):
            VisionAnchor(**data)

    def test_version_must_be_ge_1(self):
        """Version must be >= 1."""
        with pytest.raises(ValidationError):
            VisionAnchor(**_make_vision_anchor(version=0))
