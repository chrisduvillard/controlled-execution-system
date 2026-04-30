"""Integration tests for the full manifest lifecycle.

Tests the end-to-end flow: create -> classify -> validate -> sign -> verify
-> workflow transitions -> invalidation -> audit chain integrity.

Uses real services (no mocks) but no database -- in-memory audit ledger.
Does NOT require Docker (no @pytest.mark.integration).
"""

from __future__ import annotations

import pytest

from ces.control.models.audit_entry import AuditScope
from ces.control.services.audit_ledger import AuditLedgerService
from ces.control.services.manifest_manager import ManifestManager
from ces.control.services.workflow_engine import WorkflowEngine
from ces.shared.crypto import generate_keypair
from ces.shared.enums import (
    ActorType,
    ArtifactStatus,
    BehaviorConfidence,
    ChangeClass,
    RiskTier,
    WorkflowState,
)


@pytest.fixture()
def lifecycle_setup() -> tuple[ManifestManager, AuditLedgerService, bytes, bytes]:
    """Set up ManifestManager with real crypto keys and audit ledger."""
    private_key, public_key = generate_keypair()
    audit = AuditLedgerService(secret_key=b"test-secret-key-32-bytes-long!!!")
    manager = ManifestManager(
        private_key=private_key,
        public_key=public_key,
        audit_ledger=audit,
    )
    return manager, audit, private_key, public_key


async def test_full_manifest_lifecycle(
    lifecycle_setup: tuple[ManifestManager, AuditLedgerService, bytes, bytes],
) -> None:
    """End-to-end: create -> classify -> validate -> sign -> verify -> workflow -> invalidate.

    This test exercises the complete manifest lifecycle with all real services
    composed together, verifying they integrate correctly.
    """
    manager, audit, private_key, public_key = lifecycle_setup

    # Create truth artifacts
    vision = {
        "schema_type": "vision_anchor",
        "anchor_id": "VA-001",
        "status": "approved",
        "data": "test vision content",
    }
    prl = {
        "schema_type": "prl_item",
        "item_id": "PRL-001",
        "status": "approved",
        "data": "test prl content",
    }
    truth_artifacts = {"VA-001": vision, "PRL-001": prl}

    # 1. Create manifest
    manifest = await manager.create_manifest(
        description="Add a new internal utility function",
        risk_tier=RiskTier.C,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_1,
        affected_files=("src/utils/helper.py",),
        token_budget=5000,
        owner="developer",
        truth_artifacts=truth_artifacts,
        implementer_id="agent-1",
    )
    assert manifest.manifest_id.startswith("M-")
    assert manifest.workflow_state == WorkflowState.QUEUED
    assert manifest.status == ArtifactStatus.DRAFT
    assert len(manifest.truth_artifact_hashes) == 2

    # 2. Classify manifest (different actor than implementer per MANIF-07)
    classified = await manager.classify_manifest(manifest, "classifier-bot")
    assert classified.risk_tier == RiskTier.C
    assert classified.behavior_confidence == BehaviorConfidence.BC1
    assert classified.change_class == ChangeClass.CLASS_1
    assert classified.classifier_id == "classifier-bot"

    # 3. Validate against truth artifacts
    is_valid, issues = await manager.validate_manifest(classified, truth_artifacts)
    assert is_valid is True
    assert len(issues) == 0

    # 4. Sign manifest
    signed = await manager.sign_manifest(classified)
    assert signed.signature is not None
    assert signed.content_hash is not None
    assert signed.status == ArtifactStatus.APPROVED

    # 5. Verify signature
    assert await manager.verify_manifest(signed) is True

    # 6. Start workflow (queued -> in_flight)
    engine = WorkflowEngine(manifest.manifest_id, audit_ledger=audit)
    state = await engine.start("developer", ActorType.HUMAN)
    assert state == WorkflowState.IN_FLIGHT

    # 7. Simulate truth artifact change -> invalidation
    affected = await manager.on_truth_artifact_changed(
        "VA-001",
        {manifest.manifest_id: manifest.truth_artifact_hashes},
    )
    assert manifest.manifest_id in affected

    # 8. Verify the changed artifact now fails validation
    vision_changed = {
        "schema_type": "vision_anchor",
        "anchor_id": "VA-001",
        "status": "approved",
        "data": "CHANGED content",
    }
    modified_artifacts = {"VA-001": vision_changed, "PRL-001": prl}
    is_valid_after, issues_after = await manager.validate_manifest(classified, modified_artifacts)
    assert is_valid_after is False
    assert any("VA-001" in issue for issue in issues_after)

    # 9. Verify audit chain integrity (all events chained correctly)
    assert await audit.verify_integrity()


async def test_lifecycle_draft_artifact_rejection(
    lifecycle_setup: tuple[ManifestManager, AuditLedgerService, bytes, bytes],
) -> None:
    """MODEL-16: Manifests referencing DRAFT truth artifacts fail validation."""
    manager, audit, _, _ = lifecycle_setup

    draft_artifact = {
        "schema_type": "vision_anchor",
        "anchor_id": "VA-002",
        "status": "draft",
        "data": "draft content",
    }

    manifest = await manager.create_manifest(
        description="Task with draft dependency",
        risk_tier=RiskTier.C,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_1,
        affected_files=("src/foo.py",),
        token_budget=5000,
        owner="dev",
        truth_artifacts={"VA-002": draft_artifact},
    )

    is_valid, issues = await manager.validate_manifest(manifest, {"VA-002": draft_artifact})
    assert is_valid is False
    assert any("DRAFT" in issue for issue in issues)


async def test_lifecycle_tamper_detection(
    lifecycle_setup: tuple[ManifestManager, AuditLedgerService, bytes, bytes],
) -> None:
    """D-13: Tampered manifests fail signature verification."""
    manager, audit, _, _ = lifecycle_setup

    manifest = await manager.create_manifest(
        description="Tamper test",
        risk_tier=RiskTier.C,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_1,
        affected_files=("src/foo.py",),
        token_budget=5000,
        owner="dev",
    )

    signed = await manager.sign_manifest(manifest)
    assert await manager.verify_manifest(signed) is True

    # Tamper with description
    tampered = signed.model_copy(update={"description": "TAMPERED"})
    assert await manager.verify_manifest(tampered) is False

    # Tamper with affected files
    tampered2 = signed.model_copy(update={"affected_files": ("src/secrets.py",)})
    assert await manager.verify_manifest(tampered2) is False


async def test_lifecycle_manif07_self_classification_blocked(
    lifecycle_setup: tuple[ManifestManager, AuditLedgerService, bytes, bytes],
) -> None:
    """MANIF-07: Self-classification (implementer == classifier) is blocked."""
    manager, audit, _, _ = lifecycle_setup

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

    with pytest.raises(ValueError, match="MANIF-07"):
        await manager.classify_manifest(manifest, "agent-1")


async def test_lifecycle_multiple_manifests_invalidation(
    lifecycle_setup: tuple[ManifestManager, AuditLedgerService, bytes, bytes],
) -> None:
    """MANIF-05: Multiple manifests invalidated when shared artifact changes."""
    manager, audit, _, _ = lifecycle_setup

    shared_artifact = {
        "schema_type": "vision_anchor",
        "anchor_id": "VA-SHARED",
        "status": "approved",
        "data": "shared content",
    }

    # Create two manifests referencing the same artifact
    m1 = await manager.create_manifest(
        description="Task 1",
        risk_tier=RiskTier.C,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_1,
        affected_files=("src/a.py",),
        token_budget=5000,
        owner="dev",
        truth_artifacts={"VA-SHARED": shared_artifact},
    )
    m2 = await manager.create_manifest(
        description="Task 2",
        risk_tier=RiskTier.B,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_1,
        affected_files=("src/b.py",),
        token_budget=5000,
        owner="dev",
        truth_artifacts={"VA-SHARED": shared_artifact},
    )

    # Change the shared artifact -> both should be affected
    affected = await manager.on_truth_artifact_changed(
        "VA-SHARED",
        {
            m1.manifest_id: m1.truth_artifact_hashes,
            m2.manifest_id: m2.truth_artifact_hashes,
        },
    )
    assert m1.manifest_id in affected
    assert m2.manifest_id in affected
    assert len(affected) == 2

    # Audit chain still valid
    assert await audit.verify_integrity()
