"""Tests for completion evidence policy enforcement."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ces.control.models.manifest import TaskManifest
from ces.harness.models.completion_claim import (
    CompletionClaim,
    ComplexityNotes,
    CriterionEvidence,
    EvidenceKind,
)
from ces.harness.services.completion_verifier import CompletionVerifier
from ces.shared.enums import ArtifactStatus, BehaviorConfidence, ChangeClass, RiskTier, WorkflowState


def _manifest(**overrides) -> TaskManifest:
    now = datetime.now(timezone.utc)
    payload = {
        "manifest_id": "M-evidence",
        "description": "Add behavior",
        "version": 1,
        "status": ArtifactStatus.APPROVED,
        "owner": "owner",
        "created_at": now,
        "last_confirmed": now,
        "signature": "sig",
        "risk_tier": RiskTier.B,
        "behavior_confidence": BehaviorConfidence.BC2,
        "change_class": ChangeClass.CLASS_2,
        "affected_files": ("src/app.py", "tests/test_app.py"),
        "token_budget": 1000,
        "expires_at": now.replace(year=2099),
        "workflow_state": WorkflowState.IN_FLIGHT,
        "acceptance_criteria": ("behavior works",),
        "requires_exploration_evidence": True,
        "requires_verification_commands": True,
    }
    payload.update(overrides)
    return TaskManifest(**payload)


def _criterion() -> CriterionEvidence:
    return CriterionEvidence(
        criterion="behavior works",
        evidence="pytest tests/test_app.py -q passed",
        evidence_kind=EvidenceKind.COMMAND_OUTPUT,
    )


@pytest.mark.asyncio
async def test_required_exploration_and_command_evidence_are_blocking(tmp_path) -> None:
    claim = CompletionClaim(
        task_id="M-evidence",
        summary="Added behavior",
        files_changed=("src/app.py", "tests/test_app.py"),
        criteria_satisfied=(_criterion(),),
    )

    result = await CompletionVerifier(sensors={}).verify(_manifest(), claim, tmp_path)

    assert result.passed is False
    messages = [finding.message for finding in result.findings]
    assert any("exploration evidence" in message for message in messages)
    assert any("verification command" in message for message in messages)


@pytest.mark.asyncio
async def test_material_open_questions_block_completion(tmp_path) -> None:
    claim = CompletionClaim(
        task_id="M-evidence",
        summary="Added behavior",
        files_changed=("src/app.py", "tests/test_app.py"),
        criteria_satisfied=(_criterion(),),
        exploration_evidence=(
            {
                "path": "src/app.py",
                "reason": "existing application pattern",
                "observation": "handlers return plain dicts",
            },
        ),
        verification_commands=(
            {
                "command": "pytest tests/test_app.py -q",
                "exit_code": 0,
                "summary": "1 passed",
            },
        ),
        open_questions=("Need product confirmation on edge behavior",),
    )

    result = await CompletionVerifier(sensors={}).verify(_manifest(), claim, tmp_path)

    assert result.passed is False
    assert any("open question" in finding.message for finding in result.findings)


@pytest.mark.asyncio
async def test_required_evidence_allows_completion_when_present(tmp_path) -> None:
    claim = CompletionClaim(
        task_id="M-evidence",
        summary="Added behavior",
        files_changed=("src/app.py", "tests/test_app.py"),
        criteria_satisfied=(_criterion(),),
        exploration_evidence=(
            {
                "path": "src/app.py",
                "reason": "existing application pattern",
                "observation": "handlers return plain dicts",
            },
        ),
        verification_commands=(
            {
                "command": "pytest tests/test_app.py -q",
                "exit_code": 0,
                "summary": "1 passed",
            },
        ),
        complexity_notes=ComplexityNotes(),
    )

    result = await CompletionVerifier(sensors={}).verify(_manifest(), claim, tmp_path)

    assert result.passed is True


@pytest.mark.asyncio
async def test_missing_verification_artifact_path_blocks_completion(tmp_path) -> None:
    claim = CompletionClaim(
        task_id="M-evidence",
        summary="Added behavior",
        files_changed=("src/app.py", "tests/test_app.py"),
        criteria_satisfied=(_criterion(),),
        exploration_evidence=(
            {
                "path": "src/app.py",
                "reason": "existing application pattern",
                "observation": "handlers return plain dicts",
            },
        ),
        verification_commands=(
            {
                "command": "pytest --json-report-file=pytest-results.json",
                "exit_code": 0,
                "summary": "1 passed",
                "artifact_path": "pytest-results.json",
            },
        ),
    )

    result = await CompletionVerifier(sensors={}).verify(_manifest(), claim, tmp_path)

    assert result.passed is False
    assert any("artifact path does not exist" in finding.message for finding in result.findings)


@pytest.mark.asyncio
async def test_brownfield_impacted_flow_evidence_is_required_when_manifest_says_so(tmp_path) -> None:
    claim = CompletionClaim(
        task_id="M-evidence",
        summary="Added behavior",
        files_changed=("src/app.py", "tests/test_app.py"),
        criteria_satisfied=(_criterion(),),
        exploration_evidence=(
            {
                "path": "src/app.py",
                "reason": "existing application pattern",
                "observation": "handlers return plain dicts",
            },
        ),
        verification_commands=(
            {
                "command": "pytest tests/test_app.py -q",
                "exit_code": 0,
                "summary": "1 passed",
            },
        ),
    )

    result = await CompletionVerifier(sensors={}).verify(
        _manifest(requires_impacted_flow_evidence=True),
        claim,
        tmp_path,
    )

    assert result.passed is False
    assert any("impacted-flow evidence" in finding.message for finding in result.findings)
