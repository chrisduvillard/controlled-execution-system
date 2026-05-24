"""CLI commands for deterministic CES benchmark harnesses."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.panel import Panel
from rich.table import Table

from ces.benchmark.compare import load_comparison_spec, run_comparison
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


@benchmark_app.command(name="compare")
def run_compare(
    project_spec: Path = typer.Option(
        ...,
        "--project-spec",
        help="JSON A/B gauntlet spec containing vanilla and CES workflow metrics.",
    ),
    out: Path = typer.Option(
        Path(".ces/benchmarks/latest"),
        "--out",
        help="Directory where comparison-report.json and comparison-report.md are written.",
    ),
) -> None:
    """Compare measured CES and vanilla workflow metrics side by side."""

    try:
        spec = load_comparison_spec(project_spec)
        report = run_comparison(spec, output_dir=out)
        payload = report.to_dict()
        if is_json_mode():
            typer.echo(json.dumps(payload, indent=2, default=str))
            return
        _print_compare_result(payload)
    except typer.Exit:
        raise
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        handle_error(exc)


def _print_compare_result(payload: dict) -> None:
    summary = payload["summary"]
    console.print(
        Panel(
            f"Recommendation: [bold]{summary['recommendation']}[/bold]\n"
            f"Measured scenarios: {summary['measured_scenario_count']} / {summary['scenario_count']}\n"
            f"Comparable completion scenarios: {summary['comparable_scenario_count']}\n"
            f"Inferred scenarios: {summary['inferred_scenario_count']}\n"
            f"Missing-data scenarios: {summary['missing_scenario_count']}\n"
            f"CES completed scenarios: {summary['ces_completed_scenarios']}\n"
            f"Vanilla completed scenarios: {summary['vanilla_completed_scenarios']}\n"
            f"CES metric wins: {summary['ces_metric_wins']}\n"
            f"Vanilla metric wins: {summary['vanilla_metric_wins']}\n"
            f"Markdown: {payload.get('markdown_report_path', '')}",
            title="A/B Benchmark Comparison",
            border_style="green" if summary["recommendation"] == "ces-adds-measured-value" else "yellow",
        )
    )
    if payload.get("markdown_report_path"):
        typer.echo(f"Markdown report: {payload['markdown_report_path']}")
    if payload.get("json_report_path"):
        typer.echo(f"JSON report: {payload['json_report_path']}")
    table = Table(title="Scenario Summary")
    table.add_column("Scenario")
    table.add_column("Type")
    table.add_column("Measured")
    table.add_column("Comparable")
    table.add_column("CES wins")
    table.add_column("Vanilla wins")
    for row in payload["rows"]:
        deltas = row["deltas"].values()
        ces_wins = sum(1 for delta in deltas if delta["advantage"] == "ces")
        vanilla_wins = sum(1 for delta in row["deltas"].values() if delta["advantage"] == "vanilla")
        measured = any(delta["advantage"] != "unmeasured" for delta in row["deltas"].values())
        table.add_row(
            row["scenario_id"],
            row["scenario_type"],
            str(measured),
            str(row["recommendation_comparable"]),
            str(ces_wins),
            str(vanilla_wins),
        )
    console.print(table)


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
