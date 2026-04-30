"""Tests for AuditEntry model (PRD SS2.9)."""

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from ces.control.models.audit_entry import AuditEntry, AuditScope, CostImpact
from ces.shared.enums import ActorType, EventType, InvalidationSeverity


def _make_audit_entry(**overrides):
    """Factory for valid AuditEntry data."""
    defaults = {
        "entry_id": "AUDIT-001",
        "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "event_type": EventType.APPROVAL,
        "actor": "human@example.com",
        "actor_type": ActorType.HUMAN,
        "scope": {
            "affected_artifacts": ("VA-001",),
            "affected_tasks": ("TASK-001",),
            "affected_manifests": ("MAN-001",),
        },
        "action_summary": "Approved Vision Anchor VA-001",
        "decision": "approve",
        "rationale": "All criteria met, signatures valid",
        "evidence_refs": ("https://ci.example.com/evidence/001",),
    }
    defaults.update(overrides)
    return defaults


class TestAuditEntry:
    """Tests for AuditEntry model."""

    def test_required_fields(self):
        """AuditEntry requires all specified fields."""
        ae = AuditEntry(**_make_audit_entry())
        assert ae.entry_id == "AUDIT-001"
        assert ae.timestamp is not None
        assert ae.event_type == EventType.APPROVAL
        assert ae.actor == "human@example.com"
        assert ae.actor_type == ActorType.HUMAN
        assert ae.scope is not None
        assert ae.action_summary == "Approved Vision Anchor VA-001"
        assert ae.decision == "approve"
        assert ae.rationale == "All criteria met, signatures valid"
        assert ae.evidence_refs == ("https://ci.example.com/evidence/001",)

    def test_audit_scope_sub_model(self):
        """AuditScope has affected_artifacts, affected_tasks, affected_manifests."""
        scope = AuditScope(
            affected_artifacts=("VA-001", "PRL-001"),
            affected_tasks=("TASK-001",),
            affected_manifests=(),
        )
        assert scope.affected_artifacts == ("VA-001", "PRL-001")
        assert scope.affected_tasks == ("TASK-001",)
        assert scope.affected_manifests == ()

    def test_audit_scope_defaults(self):
        """AuditScope fields default to empty tuples."""
        scope = AuditScope()
        assert scope.affected_artifacts == ()
        assert scope.affected_tasks == ()
        assert scope.affected_manifests == ()

    def test_cost_impact_sub_model(self):
        """CostImpact has tokens_consumed, tasks_invalidated, rework_estimated_hours."""
        ci = CostImpact(
            tokens_consumed=100000,
            tasks_invalidated=3,
            rework_estimated_hours=8.5,
        )
        assert ci.tokens_consumed == 100000
        assert ci.tasks_invalidated == 3
        assert ci.rework_estimated_hours == 8.5

    def test_cost_impact_defaults(self):
        """CostImpact fields default to 0."""
        ci = CostImpact()
        assert ci.tokens_consumed == 0
        assert ci.tasks_invalidated == 0
        assert ci.rework_estimated_hours == 0.0

    def test_optional_fields_default_none(self):
        """Optional fields default to None."""
        ae = AuditEntry(**_make_audit_entry())
        assert ae.exception_type is None
        assert ae.exception_expiry is None
        assert ae.override_owner is None
        assert ae.override_scope is None
        assert ae.retrospective_review_date is None
        assert ae.previous_state is None
        assert ae.new_state is None
        assert ae.invalidation_severity is None
        assert ae.invalidation_downstream_count is None
        assert ae.model_version is None
        assert ae.cost_impact is None

    def test_optional_fields_with_values(self):
        """Optional fields accept valid values."""
        ae = AuditEntry(
            **_make_audit_entry(
                exception_type="emergency",
                exception_expiry=datetime(2026, 2, 1, tzinfo=timezone.utc),
                override_owner="cto@example.com",
                override_scope="auth-service",
                retrospective_review_date=date(2026, 2, 15),
                previous_state="draft",
                new_state="approved",
                invalidation_severity=InvalidationSeverity.HIGH,
                invalidation_downstream_count=5,
                model_version="claude-opus-4-20250514",
                cost_impact={
                    "tokens_consumed": 50000,
                    "tasks_invalidated": 2,
                    "rework_estimated_hours": 4.0,
                },
            )
        )
        assert ae.exception_type == "emergency"
        assert ae.override_owner == "cto@example.com"
        assert ae.invalidation_severity == InvalidationSeverity.HIGH
        assert ae.invalidation_downstream_count == 5
        assert ae.cost_impact.tokens_consumed == 50000

    def test_prev_hash_defaults_to_genesis(self):
        """prev_hash defaults to 'GENESIS' for first entry."""
        ae = AuditEntry(**_make_audit_entry())
        assert ae.prev_hash == "GENESIS"

    def test_entry_hash_defaults_to_none(self):
        """entry_hash defaults to None (populated by audit ledger service)."""
        ae = AuditEntry(**_make_audit_entry())
        assert ae.entry_hash is None

    def test_hmac_chain_fields(self):
        """AuditEntry has prev_hash and entry_hash for HMAC chain (D-16)."""
        ae = AuditEntry(
            **_make_audit_entry(
                prev_hash="sha256:previoushash",
                entry_hash="sha256:currenthash",
            )
        )
        assert ae.prev_hash == "sha256:previoushash"
        assert ae.entry_hash == "sha256:currenthash"

    def test_all_event_types_accepted(self):
        """All EventType enum values are accepted."""
        for event in EventType:
            ae = AuditEntry(**_make_audit_entry(event_type=event))
            assert ae.event_type == event

    def test_round_trip_serialization(self):
        """AuditEntry round-trips through model_dump/model_validate."""
        original = AuditEntry(**_make_audit_entry())
        data = original.model_dump()
        restored = AuditEntry.model_validate(data)
        assert original == restored

    def test_missing_required_field_raises(self):
        """Missing required field raises ValidationError."""
        data = _make_audit_entry()
        del data["entry_id"]
        with pytest.raises(ValidationError):
            AuditEntry(**data)

    def test_evidence_refs_default_empty(self):
        """evidence_refs defaults to empty tuple."""
        data = _make_audit_entry()
        del data["evidence_refs"]
        ae = AuditEntry(**data)
        assert ae.evidence_refs == ()
