"""Unit tests for ManifestManager service.

Tests cover the full manifest lifecycle orchestrated by ManifestManager:
- Create with hash computation and TTL
- Validate against truth artifacts (hash, expiry, DRAFT rejection per MODEL-16)
- Sign with Ed25519 and verify round-trip
- Classify with deterministic decision table and MANIF-07 enforcement
- Invalidate on upstream truth artifact changes
- Audit ledger integration (event recording)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ces.control.models.audit_entry import AuditScope
from ces.control.services.audit_ledger import AuditLedgerService
from ces.control.services.classification import ClassificationEngine
from ces.control.services.manifest_manager import ManifestManager
from ces.shared.crypto import generate_keypair, sha256_hash
from ces.shared.enums import (
    ArtifactStatus,
    BehaviorConfidence,
    ChangeClass,
    RiskTier,
    WorkflowState,
)
from tests.integration._compat.control_db.repository import ManifestRepository, _manifest_to_row
from tests.integration._compat.control_db.tables import ManifestRow

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def keypair() -> tuple[bytes, bytes]:
    """Generate fresh Ed25519 keypair."""
    return generate_keypair()


@pytest.fixture()
def audit_service() -> AuditLedgerService:
    """Create an in-memory audit ledger (no DB repo)."""
    return AuditLedgerService(secret_key=b"test-secret-key-32-bytes-long!!!")


@pytest.fixture()
def manager(keypair: tuple[bytes, bytes], audit_service: AuditLedgerService) -> ManifestManager:
    """Create a ManifestManager with real crypto keys and audit."""
    private_key, public_key = keypair
    return ManifestManager(
        private_key=private_key,
        public_key=public_key,
        audit_ledger=audit_service,
    )


@pytest.fixture()
def manager_no_audit(keypair: tuple[bytes, bytes]) -> ManifestManager:
    """Create a ManifestManager without audit ledger."""
    private_key, public_key = keypair
    return ManifestManager(
        private_key=private_key,
        public_key=public_key,
    )


@pytest.fixture()
def sample_truth_artifacts() -> dict[str, dict]:
    """Sample truth artifacts for testing."""
    return {
        "VA-001": {
            "schema_type": "vision_anchor",
            "anchor_id": "VA-001",
            "status": "approved",
            "data": "vision content",
        },
        "PRL-001": {
            "schema_type": "prl_item",
            "item_id": "PRL-001",
            "status": "approved",
            "data": "prl content",
        },
    }


# ---------------------------------------------------------------------------
# Create manifest tests
# ---------------------------------------------------------------------------


class TestCreateManifest:
    """Tests for ManifestManager.create_manifest."""

    async def test_create_manifest_generates_id(self, manager: ManifestManager) -> None:
        """create_manifest returns a manifest with generated ID."""
        manifest = await manager.create_manifest(
            description="Add a new internal utility function",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/utils/helper.py",),
            token_budget=5000,
            owner="developer",
        )
        assert manifest.manifest_id.startswith("M-")
        assert len(manifest.manifest_id) == 14  # M- + 12 hex chars

    async def test_create_manifest_sets_correct_fields(self, manager: ManifestManager) -> None:
        """create_manifest populates all MANIF-02 fields correctly."""
        manifest = await manager.create_manifest(
            description="Fix a typo",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_2,
            affected_files=("src/ui/strings.py",),
            token_budget=2000,
            owner="dev-1",
            forbidden_files=("src/core/*.py",),
            allowed_tools=("git", "pytest"),
            forbidden_tools=("rm",),
            implementer_id="agent-1",
            max_retries=5,
        )
        assert manifest.description == "Fix a typo"
        assert manifest.risk_tier == RiskTier.C
        assert manifest.behavior_confidence == BehaviorConfidence.BC1
        assert manifest.change_class == ChangeClass.CLASS_2
        assert manifest.affected_files == ("src/ui/strings.py",)
        assert manifest.forbidden_files == ("src/core/*.py",)
        assert manifest.allowed_tools == ("git", "pytest")
        assert manifest.forbidden_tools == ("rm",)
        assert manifest.token_budget == 2000
        assert manifest.implementer_id == "agent-1"
        assert manifest.max_retries == 5
        assert manifest.owner == "dev-1"

    async def test_create_manifest_computes_truth_artifact_hashes(
        self,
        manager: ManifestManager,
        sample_truth_artifacts: dict[str, dict],
    ) -> None:
        """create_manifest computes SHA-256 hashes for all truth artifacts."""
        manifest = await manager.create_manifest(
            description="A task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
            truth_artifacts=sample_truth_artifacts,
        )
        assert len(manifest.truth_artifact_hashes) == 2
        assert "VA-001" in manifest.truth_artifact_hashes
        assert "PRL-001" in manifest.truth_artifact_hashes
        # Verify hashes match what sha256_hash would produce
        expected_va = sha256_hash(sample_truth_artifacts["VA-001"])
        assert manifest.truth_artifact_hashes["VA-001"] == expected_va

    async def test_create_manifest_sets_ttl_tier_a(self, manager: ManifestManager) -> None:
        """Tier A manifest gets 48h TTL (D-15)."""
        before = datetime.now(timezone.utc)
        manifest = await manager.create_manifest(
            description="High risk task",
            risk_tier=RiskTier.A,
            behavior_confidence=BehaviorConfidence.BC2,
            change_class=ChangeClass.CLASS_2,
            affected_files=("src/auth.py",),
            token_budget=10000,
            owner="dev",
        )
        expected_ttl = timedelta(hours=48)
        # expires_at should be approximately now + 48h
        assert manifest.expires_at >= before + expected_ttl - timedelta(seconds=5)
        assert manifest.expires_at <= before + expected_ttl + timedelta(seconds=5)

    async def test_create_manifest_sets_ttl_tier_b(self, manager: ManifestManager) -> None:
        """Tier B manifest gets 7d TTL (D-15)."""
        before = datetime.now(timezone.utc)
        manifest = await manager.create_manifest(
            description="Medium risk task",
            risk_tier=RiskTier.B,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/api.py",),
            token_budget=5000,
            owner="dev",
        )
        expected_ttl = timedelta(days=7)
        assert manifest.expires_at >= before + expected_ttl - timedelta(seconds=5)
        assert manifest.expires_at <= before + expected_ttl + timedelta(seconds=5)

    async def test_create_manifest_sets_ttl_tier_c(self, manager: ManifestManager) -> None:
        """Tier C manifest gets 14d TTL (D-15)."""
        before = datetime.now(timezone.utc)
        manifest = await manager.create_manifest(
            description="Low risk task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/utils.py",),
            token_budget=3000,
            owner="dev",
        )
        expected_ttl = timedelta(days=14)
        assert manifest.expires_at >= before + expected_ttl - timedelta(seconds=5)
        assert manifest.expires_at <= before + expected_ttl + timedelta(seconds=5)

    async def test_create_manifest_sets_workflow_state_queued(self, manager: ManifestManager) -> None:
        """create_manifest sets workflow_state to QUEUED."""
        manifest = await manager.create_manifest(
            description="A task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
        )
        assert manifest.workflow_state == WorkflowState.QUEUED

    async def test_create_manifest_sets_status_draft(self, manager: ManifestManager) -> None:
        """create_manifest sets status to DRAFT."""
        manifest = await manager.create_manifest(
            description="A task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
        )
        assert manifest.status == ArtifactStatus.DRAFT

    async def test_create_manifest_logs_to_audit_ledger(
        self, manager: ManifestManager, audit_service: AuditLedgerService
    ) -> None:
        """create_manifest logs creation event to audit ledger."""
        manifest = await manager.create_manifest(
            description="Audited task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
        )
        # Verify audit chain integrity
        assert await audit_service.verify_integrity()

    async def test_create_manifest_dependencies_populated(
        self,
        manager: ManifestManager,
        sample_truth_artifacts: dict[str, dict],
    ) -> None:
        """create_manifest populates dependencies list from truth artifacts."""
        manifest = await manager.create_manifest(
            description="A task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
            truth_artifacts=sample_truth_artifacts,
        )
        assert len(manifest.dependencies) == 2
        dep_ids = {d.artifact_id for d in manifest.dependencies}
        assert "VA-001" in dep_ids
        assert "PRL-001" in dep_ids

    async def test_create_manifest_emits_governance_telemetry(
        self,
        manager: ManifestManager,
    ) -> None:
        """create_manifest emits governance telemetry and OTel metrics."""
        mock_collector = MagicMock()
        mock_counters = MagicMock()
        mock_metrics = MagicMock()

        with (
            patch(
                "ces.control.services.manifest_manager.get_collector",
                return_value=mock_collector,
                create=True,
            ),
            patch(
                "ces.control.services.manifest_manager.get_counters",
                return_value=mock_counters,
                create=True,
            ),
            patch(
                "ces.control.services.manifest_manager.get_ces_metrics",
                return_value=mock_metrics,
                create=True,
            ),
            patch(
                "ces.control.services.manifest_manager.attach_governance_to_current_span",
                create=True,
            ) as mock_attach,
        ):
            manifest = await manager.create_manifest(
                description="Emit telemetry on create",
                risk_tier=RiskTier.B,
                behavior_confidence=BehaviorConfidence.BC2,
                change_class=ChangeClass.CLASS_2,
                affected_files=("src/foo.py",),
                token_budget=5000,
                owner="dev",
            )

        mock_collector.emit.assert_called_once()
        emit_kwargs = mock_collector.emit.call_args.kwargs
        assert emit_kwargs["level"] == "control_plane"
        assert emit_kwargs["data"]["project_id"] == "default"
        assert emit_kwargs["data"]["manifest_issuance_rate"] == 1.0
        assert emit_kwargs["data"]["approval_queue_depth"] == 1
        mock_counters.increment.assert_any_call("manifest_issued")
        mock_counters.increment.assert_any_call("manifest_issuance_rate")
        mock_metrics.manifest_issued.add.assert_called_once_with(1)
        mock_attach.assert_called_once_with(
            manifest_id=manifest.manifest_id,
            risk_tier=manifest.risk_tier.value,
            change_class=manifest.change_class.value,
            project_id="default",
        )

    async def test_create_manifest_persists_manifest_row_for_sql_repository(
        self,
        keypair: tuple[bytes, bytes],
    ) -> None:
        """SQL-backed repositories receive an ORM row rather than a domain model."""
        private_key, public_key = keypair
        session = MagicMock()
        session.flush = AsyncMock()
        repository = ManifestRepository(session)
        manager = ManifestManager(
            private_key=private_key,
            public_key=public_key,
            repository=repository,
        )

        manifest = await manager.create_manifest(
            description="Persist me",
            risk_tier=RiskTier.B,
            behavior_confidence=BehaviorConfidence.BC2,
            change_class=ChangeClass.CLASS_2,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
        )

        saved_row = session.add.call_args.args[0]
        assert isinstance(saved_row, ManifestRow)
        assert saved_row.manifest_id == manifest.manifest_id
        assert saved_row.content["manifest_id"] == manifest.manifest_id
        assert saved_row.status == "draft"


# ---------------------------------------------------------------------------
# Validate manifest tests
# ---------------------------------------------------------------------------


class TestValidateManifest:
    """Tests for ManifestManager.validate_manifest."""

    async def test_validate_manifest_matching_hashes(
        self,
        manager: ManifestManager,
        sample_truth_artifacts: dict[str, dict],
    ) -> None:
        """validate_manifest returns True when all artifact hashes match."""
        manifest = await manager.create_manifest(
            description="A task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
            truth_artifacts=sample_truth_artifacts,
        )
        is_valid, issues = await manager.validate_manifest(manifest, sample_truth_artifacts)
        assert is_valid is True
        assert len(issues) == 0

    async def test_validate_manifest_mismatched_hashes(
        self,
        manager: ManifestManager,
        sample_truth_artifacts: dict[str, dict],
    ) -> None:
        """validate_manifest returns False with details when hashes mismatch."""
        manifest = await manager.create_manifest(
            description="A task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
            truth_artifacts=sample_truth_artifacts,
        )
        # Modify an artifact after manifest creation
        modified_artifacts = {
            "VA-001": {
                "schema_type": "vision_anchor",
                "anchor_id": "VA-001",
                "status": "approved",
                "data": "CHANGED content",
            },
            "PRL-001": sample_truth_artifacts["PRL-001"],
        }
        is_valid, issues = await manager.validate_manifest(manifest, modified_artifacts)
        assert is_valid is False
        assert len(issues) >= 1
        assert any("VA-001" in issue for issue in issues)

    async def test_validate_manifest_rejects_expired(self, manager: ManifestManager) -> None:
        """validate_manifest rejects expired manifests."""
        manifest = await manager.create_manifest(
            description="A task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
        )
        # Force expired by setting expires_at in the past
        expired = manifest.model_copy(update={"expires_at": datetime.now(timezone.utc) - timedelta(hours=1)})
        is_valid, issues = await manager.validate_manifest(expired, {})
        assert is_valid is False
        assert any("expired" in issue.lower() for issue in issues)

    async def test_validate_manifest_rejects_draft_artifacts(
        self,
        manager: ManifestManager,
    ) -> None:
        """validate_manifest rejects manifests referencing DRAFT truth artifacts (MODEL-16)."""
        draft_artifacts = {
            "VA-001": {
                "schema_type": "vision_anchor",
                "anchor_id": "VA-001",
                "status": "draft",
                "data": "draft content",
            },
        }
        manifest = await manager.create_manifest(
            description="A task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
            truth_artifacts=draft_artifacts,
        )
        is_valid, issues = await manager.validate_manifest(manifest, draft_artifacts)
        assert is_valid is False
        assert any("DRAFT" in issue for issue in issues)


# ---------------------------------------------------------------------------
# Sign and verify manifest tests
# ---------------------------------------------------------------------------


class TestSignAndVerifyManifest:
    """Tests for sign_manifest and verify_manifest."""

    async def test_sign_manifest_sets_signature_and_approved(self, manager: ManifestManager) -> None:
        """sign_manifest sets signature and status to APPROVED."""
        manifest = await manager.create_manifest(
            description="A task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
        )
        signed = await manager.sign_manifest(manifest)
        assert signed.signature is not None
        assert signed.status == ArtifactStatus.APPROVED

    async def test_sign_manifest_computes_content_hash(self, manager: ManifestManager) -> None:
        """sign_manifest computes content_hash before signing."""
        manifest = await manager.create_manifest(
            description="A task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
        )
        signed = await manager.sign_manifest(manifest)
        assert signed.content_hash is not None
        assert len(signed.content_hash) == 64  # SHA-256 hex string

    async def test_sign_manifest_logs_to_audit_ledger(
        self, manager: ManifestManager, audit_service: AuditLedgerService
    ) -> None:
        """sign_manifest logs signing event to audit ledger."""
        manifest = await manager.create_manifest(
            description="A task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
        )
        await manager.sign_manifest(manifest)
        assert await audit_service.verify_integrity()


class TestRepositoryRoundTrip:
    """Tests for persistence round-tripping through repository rows."""

    async def test_row_to_manifest_preserves_full_governance_fields(
        self,
        manager: ManifestManager,
        sample_truth_artifacts: dict[str, dict],
    ) -> None:
        """Repository reload keeps signature, hash, boundaries, actors, and retries."""
        manifest = await manager.create_manifest(
            description="Round trip this manifest",
            risk_tier=RiskTier.B,
            behavior_confidence=BehaviorConfidence.BC2,
            change_class=ChangeClass.CLASS_2,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
            truth_artifacts=sample_truth_artifacts,
            forbidden_files=("src/secrets.py",),
            allowed_tools=("python", "pytest"),
            forbidden_tools=("rm",),
            implementer_id="agent-1",
            max_retries=5,
        )
        manifest = await manager.classify_manifest(manifest, "classifier-1")
        signed = await manager.sign_manifest(manifest)
        signed = signed.model_copy(update={"retry_count": 2, "workflow_state": WorkflowState.IN_FLIGHT})
        row = _manifest_to_row(signed)

        repo = MagicMock()
        repo.get_by_id = AsyncMock(return_value=row)
        round_trip_manager = ManifestManager(repository=repo)

        loaded = await round_trip_manager.get_manifest(signed.manifest_id)

        assert loaded is not None
        assert loaded.signature == signed.signature
        assert loaded.content_hash == signed.content_hash
        assert loaded.dependencies == signed.dependencies
        assert loaded.allowed_tools == signed.allowed_tools
        assert loaded.forbidden_files == signed.forbidden_files
        assert loaded.classifier_id == "classifier-1"
        assert loaded.implementer_id == "agent-1"
        assert loaded.max_retries == 5
        assert loaded.retry_count == 2

    async def test_get_active_manifests_filters_terminal_repository_rows(
        self,
        manager: ManifestManager,
    ) -> None:
        """Repo-backed active manifest view excludes merged, failed, cancelled, and expired rows."""
        now = datetime.now(timezone.utc)
        base = await manager.create_manifest(
            description="Active task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
        )

        active_manifest = base.model_copy(update={"manifest_id": "M-active", "workflow_state": WorkflowState.IN_FLIGHT})
        merged_manifest = base.model_copy(update={"manifest_id": "M-merged", "workflow_state": WorkflowState.MERGED})
        failed_manifest = base.model_copy(update={"manifest_id": "M-failed", "workflow_state": WorkflowState.FAILED})
        cancelled_manifest = base.model_copy(
            update={"manifest_id": "M-cancelled", "workflow_state": WorkflowState.CANCELLED}
        )
        expired_manifest = base.model_copy(
            update={"manifest_id": "M-expired", "expires_at": now - timedelta(minutes=1)}
        )

        repo = MagicMock()
        repo.get_active = AsyncMock(
            return_value=[
                _manifest_to_row(active_manifest),
                _manifest_to_row(merged_manifest),
                _manifest_to_row(failed_manifest),
                _manifest_to_row(cancelled_manifest),
                _manifest_to_row(expired_manifest),
            ]
        )
        repo_manager = ManifestManager(repository=repo)

        active = await repo_manager.get_active_manifests()

        assert [manifest.manifest_id for manifest in active] == ["M-active"]

    async def test_sign_manifest_records_approval_latency_telemetry(
        self,
        manager: ManifestManager,
    ) -> None:
        """sign_manifest emits approval latency telemetry and OTel histogram data."""
        manifest = await manager.create_manifest(
            description="A task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
        )
        manifest = manifest.model_copy(update={"created_at": datetime.now(timezone.utc) - timedelta(seconds=12)})

        mock_collector = MagicMock()
        mock_metrics = MagicMock()

        with (
            patch(
                "ces.control.services.manifest_manager.get_collector",
                return_value=mock_collector,
                create=True,
            ),
            patch(
                "ces.control.services.manifest_manager.get_ces_metrics",
                return_value=mock_metrics,
                create=True,
            ),
            patch(
                "ces.control.services.manifest_manager.attach_governance_to_current_span",
                create=True,
            ) as mock_attach,
        ):
            signed = await manager.sign_manifest(manifest)

        mock_collector.emit.assert_called_once()
        emit_kwargs = mock_collector.emit.call_args.kwargs
        assert emit_kwargs["level"] == "control_plane"
        assert emit_kwargs["data"]["project_id"] == "default"
        assert emit_kwargs["data"]["approval_latency_seconds"] >= 10.0
        mock_metrics.approval_latency.record.assert_called_once()
        mock_attach.assert_called_once_with(
            manifest_id=signed.manifest_id,
            risk_tier=signed.risk_tier.value,
            change_class=signed.change_class.value,
            review_outcome="approved",
            project_id="default",
        )

    async def test_verify_manifest_valid_signature(self, manager: ManifestManager) -> None:
        """verify_manifest returns True for valid Ed25519 signature."""
        manifest = await manager.create_manifest(
            description="A task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
        )
        signed = await manager.sign_manifest(manifest)
        assert await manager.verify_manifest(signed) is True

    async def test_verify_manifest_tampered_content(self, manager: ManifestManager) -> None:
        """verify_manifest returns False for tampered content."""
        manifest = await manager.create_manifest(
            description="A task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
        )
        signed = await manager.sign_manifest(manifest)
        # Tamper with the description after signing
        tampered = signed.model_copy(update={"description": "TAMPERED"})
        assert await manager.verify_manifest(tampered) is False

    async def test_sign_manifest_requires_private_key(self) -> None:
        """sign_manifest raises ValueError without private key."""
        mgr = ManifestManager(private_key=None, public_key=None)
        manifest = await mgr.create_manifest(
            description="A task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
        )
        with pytest.raises(ValueError, match="Private key required"):
            await mgr.sign_manifest(manifest)

    async def test_verify_manifest_without_public_key(self) -> None:
        """verify_manifest returns False without public key."""
        mgr = ManifestManager(private_key=None, public_key=None)
        manifest = await mgr.create_manifest(
            description="A task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
        )
        assert await mgr.verify_manifest(manifest) is False


# ---------------------------------------------------------------------------
# Check expiry tests
# ---------------------------------------------------------------------------


class TestCheckExpiry:
    """Tests for ManifestManager.check_expiry."""

    async def test_check_expiry_not_expired(self, manager: ManifestManager) -> None:
        """check_expiry returns False for non-expired manifest."""
        manifest = await manager.create_manifest(
            description="A task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
        )
        assert await manager.check_expiry(manifest) is False

    async def test_check_expiry_expired(self, manager: ManifestManager) -> None:
        """check_expiry returns True for expired manifest."""
        manifest = await manager.create_manifest(
            description="A task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
        )
        expired = manifest.model_copy(update={"expires_at": datetime.now(timezone.utc) - timedelta(hours=1)})
        assert await manager.check_expiry(expired) is True


# ---------------------------------------------------------------------------
# Invalidation tests
# ---------------------------------------------------------------------------


class TestOnTruthArtifactChanged:
    """Tests for ManifestManager.on_truth_artifact_changed."""

    async def test_invalidation_returns_affected_manifests(
        self,
        manager: ManifestManager,
        sample_truth_artifacts: dict[str, dict],
    ) -> None:
        """on_truth_artifact_changed returns affected manifest IDs."""
        manifest = await manager.create_manifest(
            description="A task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
            truth_artifacts=sample_truth_artifacts,
        )
        affected = await manager.on_truth_artifact_changed(
            "VA-001",
            {manifest.manifest_id: manifest.truth_artifact_hashes},
        )
        assert manifest.manifest_id in affected

    async def test_invalidation_not_affected(
        self,
        manager: ManifestManager,
        sample_truth_artifacts: dict[str, dict],
    ) -> None:
        """on_truth_artifact_changed returns empty list for unrelated artifact."""
        manifest = await manager.create_manifest(
            description="A task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
            truth_artifacts=sample_truth_artifacts,
        )
        affected = await manager.on_truth_artifact_changed(
            "UNRELATED-001",
            {manifest.manifest_id: manifest.truth_artifact_hashes},
        )
        assert len(affected) == 0

    async def test_invalidation_logs_to_audit_ledger(
        self,
        manager: ManifestManager,
        audit_service: AuditLedgerService,
        sample_truth_artifacts: dict[str, dict],
    ) -> None:
        """invalidation logs event to audit ledger with affected manifests."""
        manifest = await manager.create_manifest(
            description="A task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
            truth_artifacts=sample_truth_artifacts,
        )
        await manager.on_truth_artifact_changed(
            "VA-001",
            {manifest.manifest_id: manifest.truth_artifact_hashes},
        )
        assert await audit_service.verify_integrity()

    async def test_invalidation_emits_control_plane_telemetry(
        self,
        manager: ManifestManager,
        sample_truth_artifacts: dict[str, dict],
    ) -> None:
        """on_truth_artifact_changed emits invalidation telemetry for downstream observability."""
        manifest = await manager.create_manifest(
            description="A task",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
            truth_artifacts=sample_truth_artifacts,
        )
        mock_collector = MagicMock()
        mock_counters = MagicMock()
        mock_metrics = MagicMock()

        with (
            patch(
                "ces.control.services.manifest_manager.get_collector",
                return_value=mock_collector,
                create=True,
            ),
            patch(
                "ces.control.services.manifest_manager.get_counters",
                return_value=mock_counters,
                create=True,
            ),
            patch(
                "ces.control.services.manifest_manager.get_ces_metrics",
                return_value=mock_metrics,
                create=True,
            ),
        ):
            affected = await manager.on_truth_artifact_changed(
                "VA-001",
                {manifest.manifest_id: manifest.truth_artifact_hashes},
            )

        assert affected == [manifest.manifest_id]
        mock_collector.emit.assert_called_once()
        emit_kwargs = mock_collector.emit.call_args.kwargs
        assert emit_kwargs["level"] == "control_plane"
        assert emit_kwargs["data"]["invalidation_rate"] == 1.0
        mock_counters.increment.assert_called_once_with("invalidation_rate")
        mock_metrics.manifest_invalidated.add.assert_called_once_with(1)


# ---------------------------------------------------------------------------
# Classification integration tests
# ---------------------------------------------------------------------------


class TestClassifyManifest:
    """Tests for ManifestManager.classify_manifest."""

    async def test_classify_manifest_updates_risk_tier(self, manager: ManifestManager) -> None:
        """classify_manifest uses ClassificationEngine to set risk_tier, BC, change_class."""
        manifest = await manager.create_manifest(
            description="Add a new internal utility function",
            risk_tier=RiskTier.A,  # Initially set to A
            behavior_confidence=BehaviorConfidence.BC3,
            change_class=ChangeClass.CLASS_5,
            affected_files=("src/utils.py",),
            token_budget=5000,
            owner="dev",
            implementer_id="agent-1",
        )
        classified = await manager.classify_manifest(manifest, "classifier-1")
        # Should match Row 1 of classification table: C/BC1/Class1
        assert classified.risk_tier == RiskTier.C
        assert classified.behavior_confidence == BehaviorConfidence.BC1
        assert classified.change_class == ChangeClass.CLASS_1
        assert classified.classifier_id == "classifier-1"

    async def test_classify_manifest_logs_to_audit(
        self,
        manager: ManifestManager,
        audit_service: AuditLedgerService,
    ) -> None:
        """classify_manifest logs classification to audit ledger."""
        manifest = await manager.create_manifest(
            description="Add a new internal utility function",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/utils.py",),
            token_budget=5000,
            owner="dev",
            implementer_id="agent-1",
        )
        await manager.classify_manifest(manifest, "classifier-1")
        assert await audit_service.verify_integrity()

    async def test_classify_manifest_enforces_manif07(self, manager: ManifestManager) -> None:
        """classify_manifest enforces MANIF-07: classifier != implementer."""
        manifest = await manager.create_manifest(
            description="Add a new internal utility function",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=("src/utils.py",),
            token_budget=5000,
            owner="dev",
            implementer_id="same-person",
        )
        with pytest.raises(ValueError, match="MANIF-07"):
            await manager.classify_manifest(manifest, "same-person")

    async def test_classify_manifest_no_match_returns_unmodified(self, manager: ManifestManager) -> None:
        """classify_manifest with no table match preserves original classification."""
        manifest = await manager.create_manifest(
            description="This description matches nothing in the table",
            risk_tier=RiskTier.B,
            behavior_confidence=BehaviorConfidence.BC2,
            change_class=ChangeClass.CLASS_3,
            affected_files=("src/foo.py",),
            token_budget=5000,
            owner="dev",
            implementer_id="agent-1",
        )
        classified = await manager.classify_manifest(manifest, "classifier-1")
        # Should keep original values when no match
        assert classified.risk_tier == RiskTier.B
        assert classified.behavior_confidence == BehaviorConfidence.BC2
        assert classified.change_class == ChangeClass.CLASS_3

    async def test_classify_manifest_without_implementer_id(self, manager: ManifestManager) -> None:
        """classify_manifest works when implementer_id is None (no MANIF-07 check)."""
        manifest = await manager.create_manifest(
            description="Add a new internal utility function",
            risk_tier=RiskTier.A,
            behavior_confidence=BehaviorConfidence.BC3,
            change_class=ChangeClass.CLASS_5,
            affected_files=("src/utils.py",),
            token_budget=5000,
            owner="dev",
        )
        classified = await manager.classify_manifest(manifest, "classifier-1")
        assert classified.risk_tier == RiskTier.C


# ---------------------------------------------------------------------------
# Spec-provenance fields on TaskManifest (Phase 0 — schema foundations)
# ---------------------------------------------------------------------------


from ces.control.models.manifest import TaskManifest


def test_taskmanifest_accepts_spec_provenance_fields(sample_manifest_kwargs):
    mf = TaskManifest(
        **sample_manifest_kwargs,
        parent_spec_id="SP-01HX",
        parent_story_id="ST-01HX",
        acceptance_criteria=("returns 200", "p95 under 50ms"),
    )
    assert mf.parent_spec_id == "SP-01HX"
    assert mf.parent_story_id == "ST-01HX"
    assert mf.acceptance_criteria == ("returns 200", "p95 under 50ms")


def test_taskmanifest_defaults_provenance_fields_when_missing(sample_manifest_kwargs):
    mf = TaskManifest(**sample_manifest_kwargs)
    assert mf.parent_spec_id is None
    assert mf.parent_story_id is None
    assert mf.acceptance_criteria == ()


# ---------------------------------------------------------------------------
# list_by_spec: project spec-driven queries back onto manifests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_by_spec_returns_only_matching_manifests(manager: ManifestManager, sample_manifest_kwargs) -> None:
    """list_by_spec returns manifests whose parent_spec_id matches."""
    spec_a = TaskManifest(
        **sample_manifest_kwargs,
        parent_spec_id="SP-A",
        parent_story_id="ST-A1",
    )
    other_spec = TaskManifest(
        **{**sample_manifest_kwargs, "manifest_id": sample_manifest_kwargs["manifest_id"] + "-2"},
        parent_spec_id="SP-B",
        parent_story_id="ST-B1",
    )
    no_spec = TaskManifest(
        **{**sample_manifest_kwargs, "manifest_id": sample_manifest_kwargs["manifest_id"] + "-3"},
    )
    for mf in (spec_a, other_spec, no_spec):
        await manager.save_manifest(mf)

    results = await manager.list_by_spec("SP-A")
    assert len(results) == 1
    assert results[0].parent_spec_id == "SP-A"


@pytest.mark.asyncio
async def test_list_by_spec_returns_empty_when_none_match(manager: ManifestManager) -> None:
    """list_by_spec returns an empty list when no manifest references the spec."""
    results = await manager.list_by_spec("SP-DOES-NOT-EXIST")
    assert results == []
