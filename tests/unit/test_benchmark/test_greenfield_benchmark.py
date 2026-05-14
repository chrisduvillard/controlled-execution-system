"""Greenfield benchmark harness and friction metric regressions."""

from __future__ import annotations

import sys
from pathlib import Path

from ces.benchmark.greenfield import (
    BUILTIN_GREENFIELD_SCENARIOS,
    BenchmarkEvent,
    BenchmarkVerificationCommand,
    FakeRuntimeStep,
    GreenfieldBenchmarkScenario,
    calculate_friction_metrics,
    run_greenfield_benchmark,
)


def test_builtin_scenarios_are_deterministic_and_verifiable() -> None:
    scenario = BUILTIN_GREENFIELD_SCENARIOS["python-cli"]

    assert scenario.scenario_id == "python-cli"
    assert scenario.request.startswith("Build")
    assert scenario.acceptance_criteria
    assert scenario.expected_artifacts == ("pyproject.toml", "src/hello_cli/__init__.py")
    assert scenario.verification_commands[0].name == "import-package"


def test_fake_runtime_materializes_expected_project_and_scorecard(tmp_path: Path) -> None:
    scenario = BUILTIN_GREENFIELD_SCENARIOS["python-cli"]

    result = run_greenfield_benchmark(scenario, project_root=tmp_path)

    assert result.passed is True
    assert (tmp_path / "pyproject.toml").is_file()
    assert (tmp_path / "src" / "hello_cli" / "__init__.py").is_file()
    assert result.metrics.success_rate == 1.0
    assert result.metrics.intervention_count == 0
    assert result.score >= 90
    assert result.scorecard_path == tmp_path / ".ces" / "benchmarks" / "python-cli-scorecard.json"
    assert result.scorecard_path.is_file()


def test_greenfield_gauntlet_records_full_ship_build_verify_proof_loop(tmp_path: Path) -> None:
    scenario = BUILTIN_GREENFIELD_SCENARIOS["python-cli"]

    result = run_greenfield_benchmark(scenario, project_root=tmp_path)

    command_names = [event.name for event in result.events if event.kind == "command"]
    assert command_names[0].startswith("ces ship")
    assert "ces build --gsd" in command_names[1]
    assert "ces verify" in command_names
    assert command_names[-1] == "ces proof"

    scorecard = result.scorecard_payload
    assert scorecard["gauntlet_loop"] == ["ship", "build", "verify", "proof"]
    assert scorecard["independent_project_verification"]["passed"] is True
    assert scorecard["independent_project_verification"]["commands"] == ["import-package", "cli-help"]


def test_friction_metrics_count_failed_commands_interventions_and_recovery_suggestions() -> None:
    events = (
        BenchmarkEvent(kind="command", name="ces build --gsd", status="passed"),
        BenchmarkEvent(kind="command", name="ces verify", status="failed", friction_points=2),
        BenchmarkEvent(kind="intervention", name="manual fix", status="required", friction_points=3),
        BenchmarkEvent(kind="recovery", name="ces recover --dry-run", status="suggested", friction_points=1),
    )

    metrics = calculate_friction_metrics(events)

    assert metrics.command_count == 2
    assert metrics.failed_command_count == 1
    assert metrics.intervention_count == 1
    assert metrics.recovery_suggestion_count == 1
    assert metrics.friction_points == 6
    assert metrics.success_rate == 0.5


def test_benchmark_fails_when_expected_artifact_is_missing(tmp_path: Path) -> None:
    scenario = GreenfieldBenchmarkScenario(
        scenario_id="broken",
        name="Broken fixture",
        request="Build a broken app",
        acceptance_criteria=("README exists",),
        runtime_steps=(FakeRuntimeStep(path="README.md", content="# Broken\n"),),
        expected_artifacts=("README.md", "missing.txt"),
        verification_commands=(),
    )

    result = run_greenfield_benchmark(scenario, project_root=tmp_path)

    assert result.passed is False
    assert result.metrics.intervention_count == 1
    assert result.metrics.friction_points >= 3
    assert any(event.name == "expected artifact: missing.txt" for event in result.events)
    command_status = {event.name: event.status for event in result.events if event.kind == "command"}
    assert command_status["ces verify"] == "failed"
    assert command_status["ces proof"] == "failed"
    assert result.scorecard_payload["independent_project_verification"]["passed"] is False


def test_benchmark_separates_failing_independent_verification_from_artifact_checks(tmp_path: Path) -> None:
    scenario = GreenfieldBenchmarkScenario(
        scenario_id="broken-verification",
        name="Broken verification fixture",
        request="Build an app with failing verification",
        acceptance_criteria=("README exists",),
        runtime_steps=(FakeRuntimeStep(path="README.md", content="# Broken verification\n"),),
        expected_artifacts=("README.md",),
        verification_commands=(
            BenchmarkVerificationCommand(
                name="forced-failure",
                command=f'{sys.executable} -c "raise SystemExit(1)"',
            ),
        ),
    )

    result = run_greenfield_benchmark(scenario, project_root=tmp_path)

    assert result.passed is False
    assert result.scorecard_payload["independent_project_verification"] == {
        "passed": False,
        "commands": ["forced-failure"],
    }
    verification_status = {event.name: event.status for event in result.events if event.kind == "verification"}
    assert verification_status["forced-failure"] == "failed"
    command_status = {event.name: event.status for event in result.events if event.kind == "command"}
    assert command_status["ces verify"] == "failed"
    assert command_status["ces proof"] == "failed"


def test_benchmark_converts_verification_timeouts_to_no_ship_scorecard(tmp_path: Path) -> None:
    scenario = GreenfieldBenchmarkScenario(
        scenario_id="timeout-verification",
        name="Timeout verification fixture",
        request="Build an app with slow verification",
        acceptance_criteria=("README exists",),
        runtime_steps=(FakeRuntimeStep(path="README.md", content="# Timeout verification\n"),),
        expected_artifacts=("README.md",),
        verification_commands=(
            BenchmarkVerificationCommand(
                name="slow-check",
                command=f'{sys.executable} -c "import time; time.sleep(5)"',
                timeout_seconds=1,
            ),
        ),
    )

    result = run_greenfield_benchmark(scenario, project_root=tmp_path)

    assert result.passed is False
    assert result.scorecard_payload["independent_project_verification"] == {
        "passed": False,
        "commands": ["slow-check"],
    }
    timeout_event = next(event for event in result.events if event.name == "slow-check")
    assert timeout_event.status == "failed"
    assert "timed out" in (timeout_event.detail or "")
    command_status = {event.name: event.status for event in result.events if event.kind == "command"}
    assert command_status["ces verify"] == "failed"
    assert command_status["ces proof"] == "failed"
