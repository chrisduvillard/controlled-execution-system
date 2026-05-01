"""Tests for dependency-change evidence in completion claims."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ces.control.models.manifest import TaskManifest
from ces.harness.models.completion_claim import CompletionClaim, CriterionEvidence, EvidenceKind
from ces.harness.services.completion_verifier import CompletionVerifier
from ces.shared.enums import ArtifactStatus, BehaviorConfidence, ChangeClass, RiskTier, WorkflowState


def _manifest() -> TaskManifest:
    now = datetime.now(timezone.utc)
    return TaskManifest(
        manifest_id="M1",
        description="Add dependency",
        version=1,
        status=ArtifactStatus.APPROVED,
        owner="owner",
        created_at=now,
        last_confirmed=now,
        signature="sig",
        risk_tier=RiskTier.B,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_2,
        affected_files=("pyproject.toml", "uv.lock"),
        token_budget=1000,
        expires_at=now.replace(year=2099),
        workflow_state=WorkflowState.IN_FLIGHT,
        acceptance_criteria=("dependency is justified",),
    )


@pytest.mark.asyncio
async def test_dependency_file_change_requires_dependency_evidence(tmp_path) -> None:
    claim = CompletionClaim(
        task_id="M1",
        summary="Added a dependency",
        files_changed=("pyproject.toml", "uv.lock"),
        criteria_satisfied=(
            CriterionEvidence(
                criterion="dependency is justified",
                evidence="inspected pyproject",
                evidence_kind=EvidenceKind.MANUAL_INSPECTION,
            ),
        ),
    )

    result = await CompletionVerifier(sensors={}).verify(_manifest(), claim, tmp_path)

    assert result.passed is False
    assert any("dependency evidence" in finding.message for finding in result.findings)


@pytest.mark.asyncio
async def test_dependency_evidence_allows_dependency_file_change(tmp_path) -> None:
    claim = CompletionClaim(
        task_id="M1",
        summary="Added a dependency",
        files_changed=("pyproject.toml", "uv.lock"),
        criteria_satisfied=(
            CriterionEvidence(
                criterion="dependency is justified",
                evidence="inspected pyproject",
                evidence_kind=EvidenceKind.MANUAL_INSPECTION,
            ),
        ),
        dependency_changes=(
            {
                "file_path": "pyproject.toml",
                "package": "rich",
                "rationale": "Already used by the CLI output layer",
                "existing_alternative_considered": "stdlib output would lose current Rich UI behavior",
                "lockfile_evidence": "uv.lock updated",
                "audit_evidence": "pip-audit passed",
            },
        ),
    )

    result = await CompletionVerifier(sensors={}).verify(_manifest(), claim, tmp_path)

    assert result.passed is True
