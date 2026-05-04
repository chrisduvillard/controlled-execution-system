"""Greenfield benchmark harness and friction metric regressions."""

from __future__ import annotations

from pathlib import Path

from ces.benchmark.greenfield import (
    BUILTIN_GREENFIELD_SCENARIOS,
    BenchmarkEvent,
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
