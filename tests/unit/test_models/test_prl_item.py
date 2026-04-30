"""Tests for PRLItem model (PRD SS2.2)."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ces.control.models.prl_item import AcceptanceCriterion, PRLItem
from ces.shared.enums import (
    ArtifactStatus,
    LegacyDisposition,
    Priority,
    PRLItemType,
    VerificationMethod,
)


def _make_prl_item(**overrides):
    """Factory for valid PRLItem data."""
    defaults = {
        "schema_type": "prl_item",
        "prl_id": "PRL-0042",
        "version": 1,
        "status": ArtifactStatus.DRAFT,
        "owner": "product-owner@example.com",
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "last_confirmed": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "type": PRLItemType.FEATURE,
        "statement": "System must validate all YAML schemas",
        "acceptance_criteria": (
            {
                "criterion": "All schemas validated",
                "verification_method": VerificationMethod.DETERMINISTIC,
            },
        ),
        "negative_examples": ("Does NOT validate arbitrary JSON",),
        "priority": Priority.HIGH,
        "release_slice": "v1.0",
        "dependencies": (),
    }
    defaults.update(overrides)
    return defaults


class TestPRLItem:
    """Tests for PRLItem model."""

    def test_schema_type_literal(self):
        """PRLItem has schema_type Literal['prl_item']."""
        prl = PRLItem(**_make_prl_item())
        assert prl.schema_type == "prl_item"

    def test_required_fields(self):
        """PRLItem requires all specified fields."""
        prl = PRLItem(**_make_prl_item())
        assert prl.prl_id == "PRL-0042"
        assert prl.type == PRLItemType.FEATURE
        assert prl.statement == "System must validate all YAML schemas"
        assert len(prl.acceptance_criteria) == 1
        assert prl.negative_examples == ("Does NOT validate arbitrary JSON",)
        assert prl.priority == Priority.HIGH
        assert prl.release_slice == "v1.0"
        assert prl.dependencies == ()

    def test_optional_fields_default_none(self):
        """Optional fields default to None or empty list."""
        prl = PRLItem(**_make_prl_item())
        assert prl.legacy_disposition is None
        assert prl.legacy_source_system is None
        assert prl.legacy_golden_master_ref is None
        assert prl.technical_debt_refs == ()

    def test_optional_fields_with_values(self):
        """Optional fields accept valid values."""
        prl = PRLItem(
            **_make_prl_item(
                legacy_disposition=LegacyDisposition.PRESERVE,
                legacy_source_system="old-system",
                legacy_golden_master_ref="GM-001",
                technical_debt_refs=("DEBT-001",),
            )
        )
        assert prl.legacy_disposition == LegacyDisposition.PRESERVE
        assert prl.legacy_source_system == "old-system"
        assert prl.legacy_golden_master_ref == "GM-001"
        assert prl.technical_debt_refs == ("DEBT-001",)

    def test_acceptance_criterion_sub_model(self):
        """AcceptanceCriterion has criterion and verification_method."""
        ac = AcceptanceCriterion(
            criterion="All tests pass",
            verification_method=VerificationMethod.DETERMINISTIC,
        )
        assert ac.criterion == "All tests pass"
        assert ac.verification_method == VerificationMethod.DETERMINISTIC

    def test_round_trip_serialization(self):
        """PRLItem round-trips through model_dump/model_validate."""
        original = PRLItem(**_make_prl_item())
        data = original.model_dump()
        restored = PRLItem.model_validate(data)
        assert original == restored

    def test_missing_required_field_raises(self):
        """Missing required field raises ValidationError."""
        data = _make_prl_item()
        del data["statement"]
        with pytest.raises(ValidationError):
            PRLItem(**data)

    def test_inherits_governed_artifact_base(self):
        """PRLItem inherits GovernedArtifactBase fields."""
        prl = PRLItem(**_make_prl_item())
        assert prl.version == 1
        assert prl.status == ArtifactStatus.DRAFT
        assert prl.owner == "product-owner@example.com"
