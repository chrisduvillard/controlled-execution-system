"""CLI commands for deterministic CES benchmark harnesses."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.panel import Panel
from rich.table import Table

from ces.benchmark.compare import load_comparison_spec, run_comparison
from ces.benchmark.greenfield import BUILTIN_GREENFIELD_SCENARIOS, run_greenfield_benchmark
from ces.benchmark.runtime_preflight import run_runtime_preflight
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


@benchmark_app.command(name="preflight")
def run_preflight(
    runtime: str = typer.Option(
        "codex",
        "--runtime",
        help="Runtime to check before a measured A/B benchmark: codex or claude.",
    ),
    project_root: Path = typer.Option(
        Path("."),
        "--project-root",
        help="Isolated benchmark workspace where the optional write probe may run.",
    ),
    probe_runtime: bool = typer.Option(
        False,
        "--probe-runtime",
        help="Ask the runtime to create a single probe file. May contact the runtime provider.",
    ),
    timeout_seconds: int = typer.Option(
        90,
        "--timeout-seconds",
        min=10,
        max=600,
        help="Timeout for --probe-runtime.",
    ),
) -> None:
    """Check whether a benchmark runtime can safely produce measured evidence."""

    try:
        normalized_runtime = runtime.lower().strip()
        if normalized_runtime not in {"codex", "claude"}:
            raise typer.BadParameter("--runtime must be one of: codex, claude")
        payload = run_runtime_preflight(
            runtime=normalized_runtime,  # type: ignore[arg-type]
            project_root=project_root,
            probe_runtime=probe_runtime,
            timeout_seconds=timeout_seconds,
        )
        if is_json_mode():
            typer.echo(json.dumps(payload, indent=2, default=str))
        else:
            _print_preflight_result(payload)
        if payload["recommendation"] in {"runtime-missing", "runtime-blocked"}:
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


def _print_preflight_result(payload: dict) -> None:
    recommendation = payload["recommendation"]
    border_style = "green" if recommendation == "runtime-ready" else "yellow"
    if recommendation in {"runtime-missing", "runtime-blocked"}:
        border_style = "red"
    console.print(
        Panel(
            f"Runtime: [bold]{payload['runtime']}[/bold]\n"
            f"Recommendation: [bold]{recommendation}[/bold]\n"
            f"Project root: {payload['project_root']}\n"
            f"Probe runtime: {payload['probe_runtime']}",
            title="Benchmark Runtime Preflight",
            border_style=border_style,
        )
    )
    table = Table(title="Preflight Checks")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for check in payload["checks"]:
        ok = check.get("ok")
        status = "PASS" if ok is True else "FAIL" if ok is False else "NOT RUN"
        detail = str(check.get("detail", ""))
        if "exit_code" in check:
            detail = f"{detail} exit_code={check['exit_code']}"
        for stream_key in ("stderr_tail", "stdout_tail"):
            stream_tail = str(check.get(stream_key) or "").strip()
            if stream_tail:
                detail = f"{detail}\n{stream_key}: {stream_tail}"
        table.add_row(check["name"], status, detail)
    console.print(table)


def _print_compare_result(payload: dict) -> None:
    summary = payload["summary"]
    console.print(
        Panel(
            f"Recommendation: [bold]{summary['recommendation']}[/bold]\n"
            f"Measured scenarios: {summary['measured_scenario_count']} / {summary['scenario_count']}\n"
            f"Comparable completion scenarios: {summary['comparable_scenario_count']}\n"
            f"Secondary counted scenarios: {summary['secondary_metric_counted_scenario_count']}\n"
            f"Inferred scenarios: {summary['inferred_scenario_count']}\n"
            f"Missing-data scenarios: {summary['missing_scenario_count']}\n"
            f"CES completed scenarios: {summary['ces_completed_scenarios']}\n"
            f"Vanilla completed scenarios: {summary['vanilla_completed_scenarios']}\n"
            f"Counted CES wins: {summary['decision_ces_metric_wins']}\n"
            f"Counted vanilla wins: {summary['decision_vanilla_metric_wins']}\n"
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
    table.add_column("Secondary counted")
    table.add_column("Counted CES wins")
    table.add_column("Counted vanilla wins")
    table.add_column("Reason")
    for row in payload["rows"]:
        measured = any(delta["advantage"] != "unmeasured" for delta in row["deltas"].values())
        counted_deltas = (
            [delta for metric, delta in row["deltas"].items() if metric != "completion"]
            if row["secondary_metrics_counted"]
            else []
        )
        ces_wins = sum(1 for delta in counted_deltas if delta["advantage"] == "ces")
        vanilla_wins = sum(1 for delta in counted_deltas if delta["advantage"] == "vanilla")
        table.add_row(
            row["scenario_id"],
            row["scenario_type"],
            str(measured),
            str(row["recommendation_comparable"]),
            str(row["secondary_metrics_counted"]),
            str(ces_wins),
            str(vanilla_wins),
            str(row.get("recommendation_exclusion_reason") or ""),
        )
    console.print(table)
    typer.echo(
        "Recommendation gate: completion must be measured for both arms; "
        "secondary metrics count only when both arms completed successfully."
    )
    excluded = [row for row in payload["rows"] if row.get("recommendation_exclusion_reason")]
    if excluded:
        typer.echo("Recommendation exclusions:")
        for row in excluded:
            typer.echo(f"- {row['scenario_id']}: {row['recommendation_exclusion_reason']}")


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
