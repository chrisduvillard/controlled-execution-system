"""CLI commands for deterministic CES benchmark harnesses."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.panel import Panel
from rich.table import Table

from ces.benchmark.greenfield import BUILTIN_GREENFIELD_SCENARIOS, run_greenfield_benchmark
from ces.cli._errors import handle_error
from ces.cli._output import console, is_json_mode

benchmark_app = typer.Typer(help="Run deterministic benchmark harnesses and emit friction scorecards.")


@benchmark_app.command(name="greenfield")
def run_greenfield(
    scenario_id: str = typer.Option(
        "python-cli",
        "--scenario",
        help="Built-in greenfield scenario id to run.",
    ),
    project_root: Path = typer.Option(
        Path("."),
        "--project-root",
        help="Directory where the fake-runtime project should be materialized.",
    ),
) -> None:
    """Run a deterministic 0→100 greenfield benchmark with a fake runtime."""

    try:
        scenario = BUILTIN_GREENFIELD_SCENARIOS.get(scenario_id)
        if scenario is None:
            available = ", ".join(sorted(BUILTIN_GREENFIELD_SCENARIOS))
            raise typer.BadParameter(f"Unknown benchmark scenario: {scenario_id}. Available: {available}")

        result = run_greenfield_benchmark(scenario, project_root=project_root.resolve())
        payload = result.to_dict()
        if is_json_mode():
            typer.echo(json.dumps(payload, indent=2, default=str))
            if not result.passed:
                raise typer.Exit(1)
            return

        _print_greenfield_result(payload)
        if not result.passed:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        handle_error(exc)


def _print_greenfield_result(payload: dict) -> None:
    metrics = payload["metrics"]
    console.print(
        Panel(
            f"Scenario: [bold]{payload['scenario_id']}[/bold]\n"
            f"Passed: {payload['passed']}\n"
            f"Score: [bold]{payload['score']}[/bold]\n"
            f"Scorecard: {payload['scorecard_path']}",
            title="Greenfield Benchmark",
            border_style="green" if payload["passed"] else "red",
        )
    )
    table = Table(title="Friction Metrics")
    table.add_column("Metric")
    table.add_column("Value")
    for key in (
        "command_count",
        "failed_command_count",
        "intervention_count",
        "recovery_suggestion_count",
        "friction_points",
        "success_rate",
    ):
        table.add_row(key, str(metrics[key]))
    console.print(table)
