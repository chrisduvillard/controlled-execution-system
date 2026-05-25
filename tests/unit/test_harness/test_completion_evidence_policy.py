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
    ExplorationEvidence,
    VerificationCommandEvidence,
)
from ces.harness.sensors.completion_gate import (
    LintSensor,
    TestPassSensor,
    TypeCheckSensor,
    _command_invokes_marker,
    _has_successful_completion_command,
)
from ces.harness.sensors.test_coverage import CoverageSensor
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


def test_reduced_evidence_command_invocation_parser_rejects_spoofed_arguments(tmp_path) -> None:
    assert _command_invokes_marker("python -m pytest -q", ("pytest",)) is True
    assert _command_invokes_marker("uv run --no-sync pytest -q", ("pytest",)) is True
    assert _command_invokes_marker("uv run python -m pytest -q", ("pytest",)) is True
    assert _command_invokes_marker("echo -m pytest", ("pytest",)) is False
    assert _command_invokes_marker("'unterminated", ("pytest",)) is False
    assert _has_successful_completion_command(
        {
            "project_root": str(tmp_path),
            "completion_verification_commands": (
                {"command": "env CI=1 uv run --no-sync pytest -q", "exit_code": 0, "summary": "1 passed"},
            ),
        },
        ("pytest",),
    )


def test_reduced_evidence_coverage_requires_local_artifact_and_reported_threshold(tmp_path) -> None:
    artifact_dir = tmp_path / ".coverage-trace"
    artifact_dir.mkdir()
    assert _has_successful_completion_command(
        {
            "project_root": str(tmp_path),
            "completion_verification_commands": (
                {
                    "command": "python -m trace --count --summary --coverdir .coverage-trace --module pytest -q",
                    "exit_code": 0,
                    "summary": "trace summary reported app at 100%.",
                    "artifact_path": ".coverage-trace",
                },
            ),
        },
        ("trace-coverage",),
        require_artifact_path=True,
        summary_percent_min=90.0,
    )
    assert not _has_successful_completion_command(
        {
            "project_root": str(tmp_path),
            "completion_verification_commands": (
                {
                    "command": "python -m trace --count --summary --coverdir .coverage-trace --module pytest -q",
                    "exit_code": 0,
                    "summary": "trace summary reported app at 80%.",
                    "artifact_path": ".coverage-trace",
                },
            ),
        },
        ("trace-coverage",),
        require_artifact_path=True,
        summary_percent_min=90.0,
    )
    assert not _has_successful_completion_command(
        {
            "project_root": str(tmp_path),
            "completion_verification_commands": (
                {
                    "command": "python -m trace --count --summary --coverdir .coverage-trace --module pytest -q",
                    "exit_code": 0,
                    "summary": "trace summary reported app at 100%.",
                    "artifact_path": "../outside",
                },
            ),
        },
        ("trace-coverage",),
        require_artifact_path=True,
        summary_percent_min=90.0,
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
            ExplorationEvidence(
                path="src/app.py",
                reason="existing application pattern",
                observation="handlers return plain dicts",
            ),
        ),
        verification_commands=(
            VerificationCommandEvidence(
                command="pytest tests/test_app.py -q",
                exit_code=0,
                summary="1 passed",
            ),
        ),
        open_questions=("Need product confirmation on edge behavior",),
    )

    result = await CompletionVerifier(sensors={}).verify(_manifest(), claim, tmp_path)

    assert result.passed is False
    assert any("open question" in finding.message for finding in result.findings)


@pytest.mark.asyncio
async def test_informational_tooling_caveat_open_question_does_not_block_completion(tmp_path) -> None:
    claim = CompletionClaim(
        task_id="M-evidence",
        summary="Added behavior",
        files_changed=("src/app.py", "tests/test_app.py"),
        criteria_satisfied=(_criterion(),),
        exploration_evidence=(
            ExplorationEvidence(
                path="src/app.py",
                reason="existing application pattern",
                observation="handlers return plain dicts",
            ),
        ),
        verification_commands=(
            VerificationCommandEvidence(
                command="pytest tests/test_app.py -q",
                exit_code=0,
                summary="1 passed",
            ),
        ),
        open_questions=(
            "ruff, mypy, and coverage were not installed; stdlib tabnanny, py_compile, "
            "and trace were used as reduced local evidence.",
        ),
        complexity_notes=ComplexityNotes(),
    )

    result = await CompletionVerifier(sensors={}).verify(_manifest(), claim, tmp_path)

    assert result.passed is True


@pytest.mark.asyncio
async def test_material_caveat_open_question_still_blocks_completion(tmp_path) -> None:
    claim = CompletionClaim(
        task_id="M-evidence",
        summary="Added behavior",
        files_changed=("src/app.py", "tests/test_app.py"),
        criteria_satisfied=(_criterion(),),
        exploration_evidence=(
            ExplorationEvidence(
                path="src/app.py",
                reason="existing application pattern",
                observation="handlers return plain dicts",
            ),
        ),
        verification_commands=(
            VerificationCommandEvidence(
                command="pytest tests/test_app.py -q",
                exit_code=0,
                summary="1 passed",
            ),
        ),
        open_questions=("ruff unavailable; fallback used instead. Need operator confirmation?",),
        complexity_notes=ComplexityNotes(),
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
            ExplorationEvidence(
                path="src/app.py",
                reason="existing application pattern",
                observation="handlers return plain dicts",
            ),
        ),
        verification_commands=(
            VerificationCommandEvidence(
                command="pytest tests/test_app.py -q",
                exit_code=0,
                summary="1 passed",
            ),
        ),
        complexity_notes=ComplexityNotes(),
    )

    result = await CompletionVerifier(sensors={}).verify(_manifest(), claim, tmp_path)

    assert result.passed is True


@pytest.mark.asyncio
async def test_equivalent_successful_commands_prevent_missing_artifact_false_negative(tmp_path) -> None:
    (tmp_path / ".coverage-trace").mkdir()
    claim = CompletionClaim(
        task_id="M-evidence",
        summary="Added behavior",
        files_changed=("src/app.py", "tests/test_app.py"),
        criteria_satisfied=(_criterion(),),
        exploration_evidence=(
            ExplorationEvidence(
                path="src/app.py",
                reason="existing application pattern",
                observation="handlers return plain dicts",
            ),
        ),
        verification_commands=(
            VerificationCommandEvidence(
                command="python -m pytest -q",
                exit_code=0,
                summary="1 passed",
            ),
            VerificationCommandEvidence(
                command="python -m tabnanny src/app.py tests/test_app.py",
                exit_code=0,
                summary="No indentation issues reported.",
            ),
            VerificationCommandEvidence(
                command="python -m py_compile src/app.py tests/test_app.py",
                exit_code=0,
                summary="Files compiled successfully.",
            ),
            VerificationCommandEvidence(
                command="python -m trace --count --summary --coverdir .coverage-trace --module pytest -q",
                exit_code=0,
                summary="1 passed; trace summary reported app at 100%.",
                artifact_path=".coverage-trace",
            ),
        ),
        complexity_notes=ComplexityNotes(),
    )

    result = await CompletionVerifier(
        sensors={
            "test_pass": TestPassSensor(),
            "lint": LintSensor(),
            "typecheck": TypeCheckSensor(),
            "test_coverage": CoverageSensor(),
        }
    ).verify(
        _manifest(verification_sensors=("test_pass", "lint", "typecheck", "test_coverage")),
        claim,
        tmp_path,
    )

    assert result.passed is True
    assert all(sensor_result.passed for sensor_result in result.sensor_results)


@pytest.mark.asyncio
async def test_reduced_evidence_ignores_spoofed_summary_without_matching_command(tmp_path) -> None:
    (tmp_path / ".coverage-trace").mkdir()
    claim = CompletionClaim(
        task_id="M-evidence",
        summary="Added behavior",
        files_changed=("src/app.py", "tests/test_app.py"),
        criteria_satisfied=(_criterion(),),
        exploration_evidence=(
            ExplorationEvidence(
                path="src/app.py",
                reason="existing application pattern",
                observation="handlers return plain dicts",
            ),
        ),
        verification_commands=(
            VerificationCommandEvidence(
                command="echo -m pytest ruff mypy",
                exit_code=0,
                summary="pytest ruff mypy coverage 100% passed",
                artifact_path=".coverage-trace",
            ),
        ),
        complexity_notes=ComplexityNotes(),
    )

    result = await CompletionVerifier(
        sensors={"test_pass": TestPassSensor(), "lint": LintSensor(), "typecheck": TypeCheckSensor()}
    ).verify(
        _manifest(verification_sensors=("test_pass", "lint", "typecheck")),
        claim,
        tmp_path,
    )

    assert result.passed is False
    assert any(finding.related_sensor in {"test_pass", "lint", "typecheck"} for finding in result.findings)


@pytest.mark.asyncio
async def test_required_profile_blocks_reduced_lint_evidence(tmp_path) -> None:
    profile_dir = tmp_path / ".ces"
    profile_dir.mkdir()
    (profile_dir / "verification-profile.json").write_text(
        '{"version":1,"checks":{"ruff":{"status":"required","configured":true,"reason":"release lint required"}}}\n',
        encoding="utf-8",
    )
    claim = CompletionClaim(
        task_id="M-evidence",
        summary="Added behavior",
        files_changed=("src/app.py", "tests/test_app.py"),
        criteria_satisfied=(_criterion(),),
        exploration_evidence=(
            ExplorationEvidence(
                path="src/app.py",
                reason="existing application pattern",
                observation="handlers return plain dicts",
            ),
        ),
        verification_commands=(
            VerificationCommandEvidence(
                command="python -m tabnanny src/app.py tests/test_app.py",
                exit_code=0,
                summary="No indentation issues reported.",
            ),
        ),
        complexity_notes=ComplexityNotes(),
    )

    result = await CompletionVerifier(sensors={"lint": LintSensor()}).verify(
        _manifest(verification_sensors=("lint",)),
        claim,
        tmp_path,
    )

    assert result.passed is False
    assert any(
        finding.related_sensor == "lint" and "ruff-report.json" in finding.message for finding in result.findings
    )


@pytest.mark.asyncio
async def test_nonzero_reduced_evidence_command_does_not_satisfy_missing_artifact(tmp_path) -> None:
    claim = CompletionClaim(
        task_id="M-evidence",
        summary="Added behavior",
        files_changed=("src/app.py", "tests/test_app.py"),
        criteria_satisfied=(_criterion(),),
        exploration_evidence=(
            ExplorationEvidence(
                path="src/app.py",
                reason="existing application pattern",
                observation="handlers return plain dicts",
            ),
        ),
        verification_commands=(
            VerificationCommandEvidence(
                command="python -m pytest -q",
                exit_code=1,
                summary="failing tests",
            ),
        ),
        complexity_notes=ComplexityNotes(),
    )

    result = await CompletionVerifier(sensors={"test_pass": TestPassSensor()}).verify(
        _manifest(verification_sensors=("test_pass",)),
        claim,
        tmp_path,
    )

    assert result.passed is False
    assert any(finding.related_sensor == "test_pass" for finding in result.findings)


@pytest.mark.asyncio
async def test_missing_coverage_artifact_needs_artifact_path_and_threshold_summary(tmp_path) -> None:
    claim = CompletionClaim(
        task_id="M-evidence",
        summary="Added behavior",
        files_changed=("src/app.py", "tests/test_app.py"),
        criteria_satisfied=(_criterion(),),
        exploration_evidence=(
            ExplorationEvidence(
                path="src/app.py",
                reason="existing application pattern",
                observation="handlers return plain dicts",
            ),
        ),
        verification_commands=(
            VerificationCommandEvidence(
                command="python -m trace --count --summary --coverdir .coverage-trace --module pytest -q",
                exit_code=0,
                summary="1 passed; trace summary reported app at 80%.",
                artifact_path=".coverage-trace",
            ),
        ),
        complexity_notes=ComplexityNotes(),
    )

    result = await CompletionVerifier(sensors={"test_coverage": CoverageSensor()}).verify(
        _manifest(verification_sensors=("test_coverage",)),
        claim,
        tmp_path,
    )

    assert result.passed is False
    assert any(finding.related_sensor == "test_coverage" for finding in result.findings)


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
async def test_unsafe_existing_verification_artifact_paths_block_completion(tmp_path) -> None:
    outside_path = tmp_path.parent / "outside-report.json"
    outside_path.write_text("{}\n", encoding="utf-8")
    symlink_path = tmp_path / "symlink-report.json"
    symlink_path.symlink_to(outside_path)

    for artifact_path in (str(outside_path), "../outside-report.json", r"C:\\Temp\\report.json", "symlink-report.json"):
        claim = CompletionClaim(
            task_id="M-evidence",
            summary="Added behavior",
            files_changed=("src/app.py", "tests/test_app.py"),
            criteria_satisfied=(_criterion(),),
            exploration_evidence=(
                ExplorationEvidence(
                    path="src/app.py",
                    reason="existing application pattern",
                    observation="handlers return plain dicts",
                ),
            ),
            verification_commands=(
                VerificationCommandEvidence(
                    command="pytest --json-report-file=pytest-results.json",
                    exit_code=0,
                    summary="1 passed",
                    artifact_path=artifact_path,
                ),
            ),
            complexity_notes=ComplexityNotes(),
        )

        result = await CompletionVerifier(sensors={}).verify(_manifest(), claim, tmp_path)

        assert result.passed is False, artifact_path
        assert any("unsafe verification artifact path" in finding.message for finding in result.findings)


@pytest.mark.asyncio
async def test_brownfield_impacted_flow_evidence_is_required_when_manifest_says_so(tmp_path) -> None:
    claim = CompletionClaim(
        task_id="M-evidence",
        summary="Added behavior",
        files_changed=("src/app.py", "tests/test_app.py"),
        criteria_satisfied=(_criterion(),),
        exploration_evidence=(
            ExplorationEvidence(
                path="src/app.py",
                reason="existing application pattern",
                observation="handlers return plain dicts",
            ),
        ),
        verification_commands=(
            VerificationCommandEvidence(
                command="pytest tests/test_app.py -q",
                exit_code=0,
                summary="1 passed",
            ),
        ),
    )

    result = await CompletionVerifier(sensors={}).verify(
        _manifest(requires_impacted_flow_evidence=True),
        claim,
        tmp_path,
    )

    assert result.passed is False
    assert any("impacted-flow evidence" in finding.message for finding in result.findings)


@pytest.mark.asyncio
async def test_public_api_compatibility_counts_as_impacted_flow_evidence(tmp_path) -> None:
    claim = CompletionClaim(
        task_id="M-evidence",
        summary="Preserved public API while fixing parser behavior",
        files_changed=("parserlib.py",),
        criteria_satisfied=(_criterion(),),
        exploration_evidence=(
            ExplorationEvidence(
                path="README.md",
                reason="public API compatibility is preserved",
                observation="README documents parse_tags(text) as the public API and existing tests cover compatibility.",
            ),
        ),
        verification_commands=(
            VerificationCommandEvidence(
                command="python -m pytest -q",
                exit_code=0,
                summary="2 passed",
            ),
        ),
        complexity_notes=ComplexityNotes(),
    )

    result = await CompletionVerifier(sensors={}).verify(
        _manifest(
            affected_files=("CLI/API",),
            requires_impacted_flow_evidence=True,
        ),
        claim,
        tmp_path,
    )

    assert result.passed is True


@pytest.mark.asyncio
async def test_semantic_scope_does_not_bypass_forbidden_normalized_paths(tmp_path) -> None:
    claim = CompletionClaim(
        task_id="M-evidence",
        summary="Changed forbidden file using parent traversal spelling",
        files_changed=("src/../src/secret.py",),
        criteria_satisfied=(_criterion(),),
        exploration_evidence=(
            ExplorationEvidence(
                path="src/secret.py",
                reason="existing application pattern",
                observation="forbidden file should remain blocked",
            ),
        ),
        verification_commands=(
            VerificationCommandEvidence(
                command="python -m pytest -q",
                exit_code=0,
                summary="2 passed",
            ),
        ),
        complexity_notes=ComplexityNotes(),
    )

    result = await CompletionVerifier(sensors={}).verify(
        _manifest(affected_files=("CLI/API",), forbidden_files=("src/secret.py",)),
        claim,
        tmp_path,
    )

    assert result.passed is False
    assert any("outside manifest scope" in finding.message for finding in result.findings)


@pytest.mark.asyncio
async def test_semantic_scope_does_not_bypass_windows_forbidden_patterns(tmp_path) -> None:
    claim = CompletionClaim(
        task_id="M-evidence",
        summary="Changed forbidden file",
        files_changed=("src/parserlib.py",),
        criteria_satisfied=(_criterion(),),
        exploration_evidence=(
            ExplorationEvidence(
                path="src/parserlib.py",
                reason="existing application pattern",
                observation="forbidden file should remain blocked",
            ),
        ),
        verification_commands=(
            VerificationCommandEvidence(
                command="python -m pytest -q",
                exit_code=0,
                summary="2 passed",
            ),
        ),
        complexity_notes=ComplexityNotes(),
    )

    result = await CompletionVerifier(sensors={}).verify(
        _manifest(affected_files=("CLI/API",), forbidden_files=(r"src\parserlib.py",)),
        claim,
        tmp_path,
    )

    assert result.passed is False
    assert any("outside manifest scope" in finding.message for finding in result.findings)
