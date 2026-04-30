"""Tests for TaskManifest and ManifestDependency models."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from ces.control.models.manifest import ManifestDependency, TaskManifest
from ces.shared.enums import (
    ArtifactStatus,
    BehaviorConfidence,
    ChangeClass,
    RiskTier,
    WorkflowState,
)
from tests.unit.conftest import make_sample_manifest_kwargs


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_manifest(**overrides: object) -> TaskManifest:
    """Create a valid TaskManifest with sensible defaults, allowing overrides."""
    defaults = make_sample_manifest_kwargs()
    defaults.update(overrides)
    return TaskManifest(**defaults)


class TestManifestDependency:
    """Tests for ManifestDependency sub-model."""

    def test_create_dependency(self) -> None:
        dep = ManifestDependency(
            artifact_id="PRL-001",
            artifact_type="prl",
            content_hash="abc123def456",
        )
        assert dep.artifact_id == "PRL-001"
        assert dep.artifact_type == "prl"
        assert dep.content_hash == "abc123def456"

    def test_dependency_is_frozen(self) -> None:
        dep = ManifestDependency(
            artifact_id="PRL-001",
            artifact_type="prl",
            content_hash="abc123",
        )
        with pytest.raises(ValidationError):
            dep.artifact_id = "PRL-002"  # type: ignore[misc]


class TestTaskManifestRequiredFields:
    """Tests for required fields on TaskManifest."""

    def test_requires_manifest_id(self) -> None:
        with pytest.raises(ValidationError):
            _make_manifest(manifest_id=None)

    def test_requires_description(self) -> None:
        with pytest.raises(ValidationError):
            _make_manifest(description=None)

    def test_requires_risk_tier(self) -> None:
        with pytest.raises(ValidationError):
            _make_manifest(risk_tier=None)

    def test_requires_behavior_confidence(self) -> None:
        with pytest.raises(ValidationError):
            _make_manifest(behavior_confidence=None)

    def test_requires_change_class(self) -> None:
        with pytest.raises(ValidationError):
            _make_manifest(change_class=None)

    def test_all_fields_populated(self) -> None:
        m = _make_manifest()
        assert m.manifest_id == "MANIF-001"
        assert m.description == "Implement user login endpoint"
        assert m.risk_tier == RiskTier.B
        assert m.behavior_confidence == BehaviorConfidence.BC2
        assert m.change_class == ChangeClass.CLASS_2


class TestTaskManifestFileFields:
    """Tests for file-related fields."""

    def test_affected_files(self) -> None:
        m = _make_manifest(affected_files=("src/a.py", "src/b.py"))
        assert m.affected_files == ("src/a.py", "src/b.py")

    def test_forbidden_files_default_empty(self) -> None:
        m = _make_manifest()
        assert m.forbidden_files == ()

    def test_allowed_tools_default_empty(self) -> None:
        m = _make_manifest()
        assert m.allowed_tools == ()

    def test_forbidden_tools_default_empty(self) -> None:
        m = _make_manifest()
        assert m.forbidden_tools == ()


class TestTaskManifestTokenBudget:
    """Tests for token_budget field."""

    def test_token_budget_positive(self) -> None:
        m = _make_manifest(token_budget=10000)
        assert m.token_budget == 10000

    def test_token_budget_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_manifest(token_budget=0)

    def test_token_budget_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_manifest(token_budget=-1)


class TestTaskManifestDependencies:
    """Tests for dependencies field."""

    def test_dependencies_default_empty(self) -> None:
        m = _make_manifest()
        assert m.dependencies == ()

    def test_dependencies_with_entries(self) -> None:
        dep = ManifestDependency(
            artifact_id="PRL-001",
            artifact_type="prl",
            content_hash="sha256abc",
        )
        m = _make_manifest(dependencies=(dep,))
        assert len(m.dependencies) == 1
        assert m.dependencies[0].artifact_id == "PRL-001"


class TestTaskManifestTruthArtifactHashes:
    """Tests for truth_artifact_hashes field."""

    def test_truth_artifact_hashes_default_empty(self) -> None:
        m = _make_manifest()
        assert m.truth_artifact_hashes == {}

    def test_truth_artifact_hashes_with_entries(self) -> None:
        hashes = {"PRL-001": "abc123", "ICA-001": "def456"}
        m = _make_manifest(truth_artifact_hashes=hashes)
        assert m.truth_artifact_hashes == hashes


class TestTaskManifestExpiry:
    """Tests for expires_at and is_expired property."""

    def test_expires_at_field(self) -> None:
        future = _now() + timedelta(days=7)
        m = _make_manifest(expires_at=future)
        assert m.expires_at == future

    def test_is_expired_false_for_future(self) -> None:
        m = _make_manifest(expires_at=_now() + timedelta(hours=1))
        assert m.is_expired is False

    def test_is_expired_true_for_past(self) -> None:
        m = _make_manifest(expires_at=_now() - timedelta(hours=1))
        assert m.is_expired is True


class TestTaskManifestWorkflowState:
    """Tests for workflow_state field."""

    def test_workflow_state_default_queued(self) -> None:
        m = _make_manifest()
        assert m.workflow_state == WorkflowState.QUEUED

    def test_workflow_state_explicit(self) -> None:
        m = _make_manifest(workflow_state=WorkflowState.IN_FLIGHT)
        assert m.workflow_state == WorkflowState.IN_FLIGHT


class TestTaskManifestClassification:
    """Tests for classifier_id, implementer_id, and MANIF-07 rule."""

    def test_classifier_id_optional(self) -> None:
        m = _make_manifest()
        assert m.classifier_id is None

    def test_implementer_id_optional(self) -> None:
        m = _make_manifest()
        assert m.implementer_id is None

    def test_classifier_and_implementer_different_ok(self) -> None:
        m = _make_manifest(classifier_id="agent-A", implementer_id="agent-B")
        assert m.classifier_id == "agent-A"
        assert m.implementer_id == "agent-B"

    def test_manif07_classifier_cannot_equal_implementer(self) -> None:
        """MANIF-07: Implementer cannot be sole classifier."""
        with pytest.raises(ValidationError, match="MANIF-07"):
            _make_manifest(classifier_id="agent-A", implementer_id="agent-A")

    def test_only_classifier_set_is_ok(self) -> None:
        m = _make_manifest(classifier_id="agent-A", implementer_id=None)
        assert m.classifier_id == "agent-A"

    def test_only_implementer_set_is_ok(self) -> None:
        m = _make_manifest(classifier_id=None, implementer_id="agent-B")
        assert m.implementer_id == "agent-B"


class TestTaskManifestTTL:
    """Tests for default_ttl class method (D-15)."""

    def test_tier_a_ttl_48_hours(self) -> None:
        ttl = TaskManifest.default_ttl(RiskTier.A)
        assert ttl == timedelta(hours=48)

    def test_tier_b_ttl_7_days(self) -> None:
        ttl = TaskManifest.default_ttl(RiskTier.B)
        assert ttl == timedelta(days=7)

    def test_tier_c_ttl_14_days(self) -> None:
        ttl = TaskManifest.default_ttl(RiskTier.C)
        assert ttl == timedelta(days=14)


class TestTaskManifestInheritance:
    """Tests for GovernedArtifactBase inheritance."""

    def test_inherits_governed_artifact_base(self) -> None:
        m = _make_manifest()
        assert hasattr(m, "version")
        assert hasattr(m, "status")
        assert hasattr(m, "owner")
        assert hasattr(m, "signature")
        assert hasattr(m, "content_hash")

    def test_approved_requires_signature(self) -> None:
        with pytest.raises(ValidationError, match="Approved artifacts must be signed"):
            _make_manifest(status=ArtifactStatus.APPROVED, signature=None)

    def test_approved_with_signature_ok(self) -> None:
        m = _make_manifest(status=ArtifactStatus.APPROVED, signature="sig123")
        assert m.status == ArtifactStatus.APPROVED
        assert m.signature == "sig123"

    def test_draft_without_signature_ok(self) -> None:
        m = _make_manifest(status=ArtifactStatus.DRAFT, signature=None)
        assert m.status == ArtifactStatus.DRAFT


class TestTaskManifestRetries:
    """Tests for max_retries field (D-12)."""

    def test_max_retries_default_3(self) -> None:
        m = _make_manifest()
        assert m.max_retries == 3

    def test_max_retries_custom(self) -> None:
        m = _make_manifest(max_retries=5)
        assert m.max_retries == 5

    def test_max_retries_zero_allowed(self) -> None:
        m = _make_manifest(max_retries=0)
        assert m.max_retries == 0

    def test_max_retries_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_manifest(max_retries=-1)

    def test_retry_count_default_zero(self) -> None:
        m = _make_manifest()
        assert m.retry_count == 0

    def test_retry_count_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_manifest(retry_count=-1)


class TestTaskManifestReleaseSlice:
    """Tests for release_slice field."""

    def test_release_slice_default_none(self) -> None:
        m = _make_manifest()
        assert m.release_slice is None

    def test_release_slice_set(self) -> None:
        m = _make_manifest(release_slice="RS-2026-04-01")
        assert m.release_slice == "RS-2026-04-01"


class TestTaskManifestVerificationSensors:
    """Tests for verification_sensors field (Completion Gate, P3)."""

    def test_verification_sensors_default_empty(self) -> None:
        m = _make_manifest()
        assert m.verification_sensors == ()

    def test_verification_sensors_set(self) -> None:
        m = _make_manifest(verification_sensors=("test_pass", "lint"))
        assert m.verification_sensors == ("test_pass", "lint")

    def test_verification_sensors_is_tuple(self) -> None:
        m = _make_manifest(verification_sensors=("coverage",))
        assert isinstance(m.verification_sensors, tuple)

    def test_verification_sensors_frozen(self) -> None:
        m = _make_manifest(verification_sensors=("coverage",))
        with pytest.raises(ValidationError):
            m.verification_sensors = ("test_pass",)  # type: ignore[misc]


class TestTaskManifestReviewerCleanContext:
    """Tests for review_in_clean_context field (P5).

    Codifies the harness-engineering "review in clean context" pattern from
    Pocock: reviewer sub-agents must spawn without inheriting the builder's
    transcript so attention quality is preserved at review time.
    """

    def test_review_in_clean_context_default_true(self) -> None:
        m = _make_manifest()
        assert m.review_in_clean_context is True

    def test_review_in_clean_context_can_opt_out(self) -> None:
        m = _make_manifest(review_in_clean_context=False)
        assert m.review_in_clean_context is False


class TestTaskManifestMcpServers:
    """Tests for mcp_servers field (P7) — per-task MCP server allowlist."""

    def test_mcp_servers_default_empty(self) -> None:
        m = _make_manifest()
        assert m.mcp_servers == ()

    def test_mcp_servers_set(self) -> None:
        m = _make_manifest(mcp_servers=("context7",))
        assert m.mcp_servers == ("context7",)

    def test_mcp_servers_is_tuple(self) -> None:
        m = _make_manifest(mcp_servers=("context7", "playwright"))
        assert isinstance(m.mcp_servers, tuple)
