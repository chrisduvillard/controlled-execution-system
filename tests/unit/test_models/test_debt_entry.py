"""Tests for DebtEntry model (PRD SS2.8)."""

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from ces.control.models.debt_entry import DebtEntry
from ces.shared.enums import DebtOriginType, DebtSeverity, DebtStatus


def _make_debt_entry(**overrides):
    """Factory for valid DebtEntry data."""
    defaults = {
        "debt_id": "DEBT-001",
        "origin_type": DebtOriginType.INTRODUCED,
        "description": "Missing input validation on user registration",
        "affected_artifacts": ("PRL-042", "IC-001"),
        "affected_task_classes": ("CLASS_2", "CLASS_3"),
        "severity": DebtSeverity.DEGRADES_FUTURE_WORK,
        "owner": "dev-team@example.com",
        "resolution_plan_ref": "PLAN-001",
        "resolution_deadline": date(2026, 6, 30),
        "accepting_approver": "tech-lead@example.com",
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "status": DebtStatus.OPEN,
    }
    defaults.update(overrides)
    return defaults


class TestDebtEntry:
    """Tests for DebtEntry model."""

    def test_required_fields(self):
        """DebtEntry requires all specified fields."""
        de = DebtEntry(**_make_debt_entry())
        assert de.debt_id == "DEBT-001"
        assert de.origin_type == DebtOriginType.INTRODUCED
        assert de.description == "Missing input validation on user registration"
        assert de.affected_artifacts == ("PRL-042", "IC-001")
        assert de.affected_task_classes == ("CLASS_2", "CLASS_3")
        assert de.severity == DebtSeverity.DEGRADES_FUTURE_WORK
        assert de.owner == "dev-team@example.com"
        assert de.resolution_plan_ref == "PLAN-001"
        assert de.resolution_deadline == date(2026, 6, 30)
        assert de.accepting_approver == "tech-lead@example.com"
        assert de.status == DebtStatus.OPEN

    def test_optional_legacy_fields_default(self):
        """Optional legacy fields default to None or empty."""
        de = DebtEntry(**_make_debt_entry())
        assert de.legacy_source_system is None
        assert de.related_prl_items == ()
        assert de.related_migration_pack is None

    def test_optional_legacy_fields_with_values(self):
        """Optional legacy fields accept values."""
        de = DebtEntry(
            **_make_debt_entry(
                legacy_source_system="old-system",
                related_prl_items=("PRL-001",),
                related_migration_pack="MCP-001",
            )
        )
        assert de.legacy_source_system == "old-system"
        assert de.related_prl_items == ("PRL-001",)
        assert de.related_migration_pack == "MCP-001"

    def test_inherited_debt_allows_null_resolution(self):
        """Inherited debt under investigation allows null resolution fields."""
        de = DebtEntry(
            **_make_debt_entry(
                origin_type=DebtOriginType.INHERITED,
                resolution_plan_ref=None,
                resolution_deadline=None,
            )
        )
        assert de.origin_type == DebtOriginType.INHERITED
        assert de.resolution_plan_ref is None
        assert de.resolution_deadline is None

    def test_non_inherited_requires_resolution(self):
        """Non-inherited debt requires resolution_plan_ref and deadline."""
        with pytest.raises(ValidationError, match="resolution"):
            DebtEntry(
                **_make_debt_entry(
                    origin_type=DebtOriginType.INTRODUCED,
                    resolution_plan_ref=None,
                )
            )

    def test_non_inherited_requires_resolution_deadline(self):
        """Non-inherited debt with a plan_ref but no deadline still fails the second check."""
        with pytest.raises(ValidationError, match="resolution_deadline"):
            DebtEntry(
                **_make_debt_entry(
                    origin_type=DebtOriginType.INTRODUCED,
                    resolution_plan_ref="PLAN-001",
                    resolution_deadline=None,
                )
            )

    def test_all_debt_statuses_accepted(self):
        """All DebtStatus enum values are accepted."""
        for status in DebtStatus:
            de = DebtEntry(**_make_debt_entry(status=status))
            assert de.status == status

    def test_round_trip_serialization(self):
        """DebtEntry round-trips through model_dump/model_validate."""
        original = DebtEntry(**_make_debt_entry())
        data = original.model_dump()
        restored = DebtEntry.model_validate(data)
        assert original == restored

    def test_missing_required_field_raises(self):
        """Missing required field raises ValidationError."""
        data = _make_debt_entry()
        del data["debt_id"]
        with pytest.raises(ValidationError):
            DebtEntry(**data)
