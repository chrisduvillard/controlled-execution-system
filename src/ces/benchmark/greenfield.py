"""Deterministic greenfield benchmark harness and friction metrics."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

EventKind = Literal["command", "artifact", "verification", "intervention", "recovery"]
EventStatus = Literal["passed", "failed", "required", "suggested"]


@dataclass(frozen=True)
class FakeRuntimeStep:
    """A deterministic fake-runtime filesystem mutation."""

    path: str
    content: str


@dataclass(frozen=True)
class BenchmarkVerificationCommand:
    """A local command that verifies fake-runtime benchmark output."""

    name: str
    command: str
    timeout_seconds: int = 120


@dataclass(frozen=True)
class GreenfieldBenchmarkScenario:
    """A deterministic 0→100 greenfield benchmark scenario."""

    scenario_id: str
    name: str
    request: str
    acceptance_criteria: tuple[str, ...]
    runtime_steps: tuple[FakeRuntimeStep, ...]
    expected_artifacts: tuple[str, ...]
    verification_commands: tuple[BenchmarkVerificationCommand, ...]


@dataclass(frozen=True)
class BenchmarkEvent:
    """One observable benchmark event used to score friction."""

    kind: EventKind
    name: str
    status: EventStatus
    friction_points: int = 0
    detail: str | None = None


@dataclass(frozen=True)
class FrictionMetrics:
    """Aggregate metrics for a benchmark run."""

    command_count: int
    failed_command_count: int
    intervention_count: int
    recovery_suggestion_count: int
    friction_points: int
    success_rate: float


@dataclass(frozen=True)
class GreenfieldBenchmarkResult:
    """Result and persisted scorecard metadata for one benchmark run."""

    scenario_id: str
    passed: bool
    score: int
    metrics: FrictionMetrics
    events: tuple[BenchmarkEvent, ...]
    scorecard_path: Path
    scorecard_payload: dict

    def to_dict(self) -> dict:
        payload = dict(self.scorecard_payload)
        payload["scorecard_path"] = str(self.scorecard_path)
        return payload


PYTHON_CLI_SCENARIO = GreenfieldBenchmarkScenario(
    scenario_id="python-cli",
    name="Python CLI hello app",
    request="Build a Python CLI that prints a greeting.",
    acceptance_criteria=(
        "Package can be imported",
        "CLI help command exits successfully",
    ),
    runtime_steps=(
        FakeRuntimeStep(
            path="pyproject.toml",
            content=(
                "[project]\n"
                'name = "hello-cli"\n'
                'version = "0.1.0"\n'
                'requires-python = ">=3.11"\n\n'
                "[project.scripts]\n"
                'hello-cli = "hello_cli:main"\n'
            ),
        ),
        FakeRuntimeStep(
            path="src/hello_cli/__init__.py",
            content=("def main() -> None:\n    print('hello from CES benchmark')\n"),
        ),
        FakeRuntimeStep(path="README.md", content="# Hello CLI\n\nDeterministic CES benchmark fixture.\n"),
    ),
    expected_artifacts=("pyproject.toml", "src/hello_cli/__init__.py"),
    verification_commands=(
        BenchmarkVerificationCommand(
            name="import-package",
            command=f"{shlex.quote(sys.executable)} -c \"import sys; sys.path.insert(0, 'src'); import hello_cli\"",
            timeout_seconds=10,
        ),
        BenchmarkVerificationCommand(
            name="cli-help",
            command=f"{shlex.quote(sys.executable)} -c \"import sys; sys.path.insert(0, 'src'); import hello_cli; hello_cli.main()\"",
            timeout_seconds=10,
        ),
    ),
)

BUILTIN_GREENFIELD_SCENARIOS: dict[str, GreenfieldBenchmarkScenario] = {
    PYTHON_CLI_SCENARIO.scenario_id: PYTHON_CLI_SCENARIO,
}


def calculate_friction_metrics(events: tuple[BenchmarkEvent, ...]) -> FrictionMetrics:
    """Calculate benchmark friction metrics from observable events."""

    command_events = [event for event in events if event.kind == "command"]
    failed_commands = [event for event in command_events if event.status == "failed"]
    interventions = [event for event in events if event.kind == "intervention"]
    recovery_suggestions = [event for event in events if event.kind == "recovery"]
    command_count = len(command_events)
    success_count = command_count - len(failed_commands)
    success_rate = success_count / command_count if command_count else 1.0
    return FrictionMetrics(
        command_count=command_count,
        failed_command_count=len(failed_commands),
        intervention_count=len(interventions),
        recovery_suggestion_count=len(recovery_suggestions),
        friction_points=sum(max(0, event.friction_points) for event in events),
        success_rate=round(success_rate, 4),
    )


def run_greenfield_benchmark(
    scenario: GreenfieldBenchmarkScenario,
    *,
    project_root: Path,
) -> GreenfieldBenchmarkResult:
    """Run a deterministic fake-runtime greenfield benchmark scenario."""

    project_root.mkdir(parents=True, exist_ok=True)
    events: list[BenchmarkEvent] = [
        BenchmarkEvent(kind="command", name=f"ces ship {shlex.quote(scenario.request)}", status="passed"),
        BenchmarkEvent(kind="command", name=f"ces build --gsd {shlex.quote(scenario.request)}", status="passed"),
    ]

    for step in scenario.runtime_steps:
        destination = project_root / step.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(step.content, encoding="utf-8")
        events.append(BenchmarkEvent(kind="artifact", name=step.path, status="passed"))

    for artifact in scenario.expected_artifacts:
        if (project_root / artifact).is_file():
            events.append(BenchmarkEvent(kind="artifact", name=f"expected artifact: {artifact}", status="passed"))
        else:
            events.append(
                BenchmarkEvent(
                    kind="artifact",
                    name=f"expected artifact: {artifact}",
                    status="failed",
                    friction_points=2,
                    detail="Expected artifact was not produced by fake runtime.",
                )
            )
            events.append(
                BenchmarkEvent(
                    kind="intervention",
                    name="manual artifact repair",
                    status="required",
                    friction_points=3,
                )
            )

    independent_verification_commands: list[str] = []
    independent_verification_failed = False
    for command in scenario.verification_commands:
        independent_verification_commands.append(command.name)
        try:
            completed = subprocess.run(  # noqa: S603 - benchmark commands are built-in deterministic fixtures
                shlex.split(command.command),
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=command.timeout_seconds,
                check=False,
            )
            returncode = completed.returncode
            failure_detail = (completed.stderr or completed.stdout).strip()[:500]
        except subprocess.TimeoutExpired as exc:
            returncode = 124
            failure_detail = f"Verification command timed out after {exc.timeout} seconds."
        if returncode == 0:
            events.append(BenchmarkEvent(kind="verification", name=command.name, status="passed"))
        else:
            independent_verification_failed = True
            events.append(
                BenchmarkEvent(
                    kind="verification",
                    name=command.name,
                    status="failed",
                    friction_points=2,
                    detail=failure_detail,
                )
            )
            events.append(
                BenchmarkEvent(
                    kind="recovery",
                    name="ces recover --dry-run",
                    status="suggested",
                    friction_points=1,
                )
            )

    artifact_failed = any(event.kind == "artifact" and event.status == "failed" for event in events)
    independent_verification_sufficient = (
        bool(independent_verification_commands) and not independent_verification_failed
    )
    verify_passed = not artifact_failed and independent_verification_sufficient
    events.append(
        BenchmarkEvent(
            kind="command",
            name="ces verify",
            status="passed" if verify_passed else "failed",
            friction_points=0 if verify_passed else 2,
            detail=None if verify_passed else "Verification found missing artifacts or failing project checks.",
        )
    )
    events.append(
        BenchmarkEvent(
            kind="command",
            name="ces proof",
            status="passed" if verify_passed else "failed",
            friction_points=0 if verify_passed else 1,
            detail=None if verify_passed else "Proof card must recommend no-ship until evidence is green.",
        )
    )
    event_tuple = tuple(events)
    metrics = calculate_friction_metrics(event_tuple)
    passed = not any(event.status in {"failed", "required"} for event in event_tuple)
    score = _score(metrics=metrics, passed=passed)
    scorecard_payload = _scorecard_payload(
        scenario=scenario,
        passed=passed,
        score=score,
        metrics=metrics,
        events=event_tuple,
        independent_verification_commands=tuple(independent_verification_commands),
        independent_verification_passed=independent_verification_sufficient,
    )
    scorecard_path = _write_scorecard(project_root=project_root, scenario=scenario, payload=scorecard_payload)
    return GreenfieldBenchmarkResult(
        scenario_id=scenario.scenario_id,
        passed=passed,
        score=score,
        metrics=metrics,
        events=event_tuple,
        scorecard_path=scorecard_path,
        scorecard_payload=scorecard_payload,
    )


def _score(*, metrics: FrictionMetrics, passed: bool) -> int:
    base = 100 if passed else 70
    penalty = metrics.friction_points * 5 + metrics.failed_command_count * 10 + metrics.intervention_count * 15
    return max(0, min(100, base - penalty))


def _scorecard_payload(
    *,
    scenario: GreenfieldBenchmarkScenario,
    passed: bool,
    score: int,
    metrics: FrictionMetrics,
    events: tuple[BenchmarkEvent, ...],
    independent_verification_commands: tuple[str, ...],
    independent_verification_passed: bool,
) -> dict:
    return {
        "scenario_id": scenario.scenario_id,
        "scenario_name": scenario.name,
        "request": scenario.request,
        "gauntlet_loop": ["ship", "build", "verify", "proof"],
        "acceptance_criteria": list(scenario.acceptance_criteria),
        "passed": passed,
        "score": score,
        "metrics": asdict(metrics),
        "independent_project_verification": {
            "passed": independent_verification_passed,
            "commands": list(independent_verification_commands),
        },
        "events": [asdict(event) for event in events],
    }


def _write_scorecard(
    *,
    project_root: Path,
    scenario: GreenfieldBenchmarkScenario,
    payload: dict,
) -> Path:
    scorecard_dir = project_root / ".ces" / "benchmarks"
    scorecard_dir.mkdir(parents=True, exist_ok=True)
    scorecard_path = scorecard_dir / f"{scenario.scenario_id}-scorecard.json"
    scorecard_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    latest_path = scorecard_dir / "latest.json"
    latest_path.write_text(json.dumps(payload | {"scorecard_path": str(scorecard_path)}, indent=2), encoding="utf-8")
    return scorecard_path
