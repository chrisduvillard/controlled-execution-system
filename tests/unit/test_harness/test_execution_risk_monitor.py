"""Tests for cross-step execution risk monitoring."""

from __future__ import annotations

from ces.harness.models.execution_risk import (
    ExecutionCommandEvent,
    ExecutionRiskFinding,
    ExecutionRiskKind,
    ExecutionRiskSeverity,
)
from ces.harness.services.evidence_synthesizer import EvidenceSynthesizer
from ces.harness.services.execution_risk_monitor import ExecutionRiskMonitor


def _event(command: str, *, exit_code: int = 0, output: str = "", after_success: bool = False) -> ExecutionCommandEvent:
    return ExecutionCommandEvent(
        command=command,
        exit_code=exit_code,
        output_excerpt=output,
        after_success=after_success,
    )


def test_monitor_detects_repeated_same_failing_command() -> None:
    findings = ExecutionRiskMonitor().analyze(
        [
            _event("uv run pytest tests/unit -q", exit_code=1, output="failed"),
            _event("uv run pytest tests/unit -q", exit_code=1, output="failed again"),
            _event("uv run pytest tests/unit -q", exit_code=1, output="still failed"),
        ]
    )

    assert findings[0].kind is ExecutionRiskKind.REPEATED_FAILURE
    assert findings[0].severity is ExecutionRiskSeverity.HIGH
    assert "stop retrying" in findings[0].recommended_action.lower()


def test_monitor_detects_proxy_and_shallow_validation() -> None:
    findings = ExecutionRiskMonitor().analyze(
        [
            _event("python -m py_compile src/app.py", output="compiles"),
            _event("python scripts/check_import.py", output="import ok"),
            _event("echo validation passed", output="validation passed"),
        ],
        changed_files=["src/app.py"],
        behavioral_change=True,
    )

    kinds = {finding.kind for finding in findings}
    assert ExecutionRiskKind.PROXY_VALIDATION in kinds
    assert ExecutionRiskKind.COMPILE_ONLY_VALIDATION in kinds
    assert ExecutionRiskKind.SHALLOW_VALIDATION in kinds


def test_monitor_detects_timeout_loop_and_destructive_after_success() -> None:
    findings = ExecutionRiskMonitor().analyze(
        [
            _event("pytest -q", exit_code=124, output="timeout after 30s"),
            _event("pytest -q", exit_code=124, output="timed out again"),
            _event("rm -rf dist", output="", after_success=True),
        ]
    )

    kinds = {finding.kind for finding in findings}
    assert ExecutionRiskKind.TIMEOUT_LOOP in kinds
    assert ExecutionRiskKind.DESTRUCTIVE_AFTER_SUCCESS in kinds


def test_monitor_emits_stable_sorted_findings() -> None:
    findings = ExecutionRiskMonitor().analyze(
        [
            _event("rm -rf dist", after_success=True),
            _event("pytest -q", exit_code=1),
            _event("pytest -q", exit_code=1),
            _event("pytest -q", exit_code=1),
        ]
    )

    assert [finding.kind.value for finding in findings] == sorted(finding.kind.value for finding in findings)


def test_monitor_materializes_changed_files_once_for_generators() -> None:
    findings = ExecutionRiskMonitor().analyze(
        [
            _event("python scripts/check_import.py", output="import ok"),
        ],
        changed_files=(path for path in ["src/app.py"]),
        behavioral_change=True,
    )

    assert {finding.kind for finding in findings} == {
        ExecutionRiskKind.PROXY_VALIDATION,
        ExecutionRiskKind.SHALLOW_VALIDATION,
    }


def test_monitor_scrubs_secret_like_values_from_findings() -> None:
    findings = ExecutionRiskMonitor().analyze(
        [
            _event("TOKEN=sk-live-secret pytest -q", exit_code=1),
            _event("TOKEN=sk-live-secret pytest -q", exit_code=1),
            _event("TOKEN=sk-live-secret pytest -q", exit_code=1),
        ]
    )

    assert "sk-live-secret" not in findings[0].command
    assert "sk-live-secret" not in findings[0].message
    assert "TOKEN=<REDACTED>" in findings[0].command


def test_failed_test_command_does_not_suppress_compile_only_validation() -> None:
    findings = ExecutionRiskMonitor().analyze(
        [
            _event("python -m py_compile src/app.py", output="compiles"),
            _event("pytest -q", exit_code=1, output="failed"),
        ],
        changed_files=["src/app.py"],
        behavioral_change=True,
    )

    assert ExecutionRiskKind.COMPILE_ONLY_VALIDATION in {finding.kind for finding in findings}


def test_common_test_command_variants_count_as_real_tests() -> None:
    findings = ExecutionRiskMonitor().analyze(
        [
            _event("python -m py_compile src/app.py", output="compiles"),
            _event("npm run test -- --runInBand", output="passed"),
        ],
        changed_files=["src/app.py"],
        behavioral_change=True,
    )

    assert ExecutionRiskKind.COMPILE_ONLY_VALIDATION not in {finding.kind for finding in findings}


def test_evidence_synthesizer_defensively_scrubs_external_risk_findings() -> None:
    result = EvidenceSynthesizer().execution_risk_sensor_result(
        [
            ExecutionRiskFinding(
                kind=ExecutionRiskKind.REPEATED_FAILURE,
                severity=ExecutionRiskSeverity.HIGH,
                command="TOKEN=sk-external-secret pytest -q",
                message="Command failed: TOKEN=sk-external-secret pytest -q",
                recommended_action="Inspect TOKEN=sk-external-secret before retrying",
            )
        ]
    )

    assert "sk-external-secret" not in result.findings[0].location
    assert "sk-external-secret" not in result.findings[0].message
    assert "sk-external-secret" not in result.findings[0].suggestion


def test_evidence_synthesizer_converts_execution_risks_to_sensor_result() -> None:
    findings = ExecutionRiskMonitor().analyze([_event("rm -rf dist", after_success=True)])

    result = EvidenceSynthesizer().execution_risk_sensor_result(findings)

    assert result.sensor_id == "execution_risk_monitor"
    assert result.sensor_pack == "harness_evolution"
    assert result.passed is False
    assert result.findings[0].category == "destructive_after_success"
    assert result.findings[0].severity == "critical"
    assert "re-run validation" in result.findings[0].suggestion.lower()


def test_evidence_synthesizer_passes_when_no_execution_risks() -> None:
    result = EvidenceSynthesizer().execution_risk_sensor_result([])

    assert result.passed is True
    assert result.score == 1.0
    assert result.details == "No cross-step execution risks detected"
