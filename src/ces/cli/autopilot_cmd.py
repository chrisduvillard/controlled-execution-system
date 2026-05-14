"""Production Autopilot CLI report commands."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from ces.cli import _output as _output_mod
from ces.verification.mri import (
    build_launch_rehearsal,
    build_next_action,
    build_next_prompt,
    build_production_passport,
    build_promotion_plan,
    build_ship_plan,
    build_slop_scan,
    mine_project_invariants,
)
from ces.verification.proof_card import build_proof_card

launch_app = typer.Typer(help="Production launch-readiness planning commands.")


def _format_option(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"markdown", "json"}:
        raise typer.BadParameter("format must be 'markdown' or 'json'")
    return normalized


def next_action(
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Repo/CES project root to inspect; defaults to the current working directory.",
    ),
    output_format: str = typer.Option("markdown", "--format", help="Output format: markdown or json."),
) -> None:
    """Show the next safest production-readiness action."""

    report = build_next_action(project_root or Path.cwd())
    if _format_option(output_format) == "json":
        typer.echo(report.to_json(), nl=False)
        return
    typer.echo(report.to_markdown(), nl=False)


def next_prompt(
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Repo/CES project root to inspect; defaults to the current working directory.",
    ),
    output_format: str = typer.Option("markdown", "--format", help="Output format: markdown or json."),
) -> None:
    """Generate a guardrailed agent prompt for the next readiness step."""

    report = build_next_prompt(project_root or Path.cwd())
    if _format_option(output_format) == "json":
        typer.echo(report.to_json(), nl=False)
        return
    typer.echo(report.to_markdown(), nl=False)


def passport(
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Repo/CES project root to inspect; defaults to the current working directory.",
    ),
    output_format: str = typer.Option("markdown", "--format", help="Output format: markdown or json."),
) -> None:
    """Produce a local evidence-backed Production Passport."""

    report = build_production_passport(project_root or Path.cwd())
    if _format_option(output_format) == "json":
        typer.echo(report.to_json(), nl=False)
        return
    typer.echo(report.to_markdown(), nl=False)


def proof(
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Repo/CES project root to inspect; defaults to the current working directory.",
    ),
    output_format: str = typer.Option("markdown", "--format", help="Output format: markdown or json."),
) -> None:
    """Produce a compact shareable proof card from local CES evidence."""

    report = build_proof_card(project_root or Path.cwd())
    if _output_mod._json_mode or _format_option(output_format) == "json":
        typer.echo(report.to_json(), nl=False)
        return
    typer.echo(report.to_markdown(), nl=False)


def ship(
    objective: str | None = typer.Argument(
        None,
        help="Optional project objective, e.g. 'Create a task tracker app'.",
    ),
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Repo/CES project root to inspect; defaults to the current working directory.",
    ),
    output_format: str = typer.Option("markdown", "--format", help="Output format: markdown or json."),
) -> None:
    """Plan the safe path from idea/current repo to proof-backed delivery."""

    report = build_ship_plan(project_root or Path.cwd(), objective=objective)
    if _format_option(output_format) == "json":
        typer.echo(report.to_json(), nl=False)
        return
    typer.echo(report.to_markdown(), nl=False)


def promote(
    target_level: str = typer.Argument(
        ..., help="Target maturity: shareable-app, production-candidate, or production-ready."
    ),
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Repo/CES project root to inspect; defaults to the current working directory.",
    ),
    output_format: str = typer.Option("markdown", "--format", help="Output format: markdown or json."),
) -> None:
    """Plan a safe one-checkpoint-at-a-time maturity promotion."""

    try:
        report = build_promotion_plan(project_root or Path.cwd(), target_level)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if _format_option(output_format) == "json":
        typer.echo(report.to_json(), nl=False)
        return
    typer.echo(report.to_markdown(), nl=False)


def invariants(
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Repo/CES project root to inspect; defaults to the current working directory.",
    ),
    output_format: str = typer.Option("markdown", "--format", help="Output format: markdown or json."),
) -> None:
    """Mine conservative evidence-backed project invariants."""

    report = mine_project_invariants(project_root or Path.cwd())
    if _format_option(output_format) == "json":
        typer.echo(report.to_json(), nl=False)
        return
    typer.echo(report.to_markdown(), nl=False)


def slop_scan(
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Repo/CES project root to inspect; defaults to the current working directory.",
    ),
    output_format: str = typer.Option("markdown", "--format", help="Output format: markdown or json."),
) -> None:
    """Report deterministic AI-native slop/failure findings."""

    payload = build_slop_scan(project_root or Path.cwd())
    if _format_option(output_format) == "json":
        typer.echo(json.dumps(payload, indent=2) + "\n", nl=False)
        return
    lines = ["# AI-Native Slop Scan", "", f"Project root: `{payload['project_root']}`", "", "## Findings", ""]
    findings = payload["findings"]
    if findings:
        lines.extend(f"- **{item['severity']} / {item['title']}** — {item['evidence']}" for item in findings)
    else:
        lines.append("- No AI-native slop findings detected by the current deterministic scan.")
    typer.echo("\n".join(lines).rstrip() + "\n", nl=False)


@launch_app.command(name="rehearsal", help="Plan non-destructive launch-readiness checks.")
def launch_rehearsal(
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Repo/CES project root to inspect; defaults to the current working directory.",
    ),
    output_format: str = typer.Option("markdown", "--format", help="Output format: markdown or json."),
) -> None:
    """Produce a read-only launch rehearsal plan."""

    report = build_launch_rehearsal(project_root or Path.cwd())
    if _format_option(output_format) == "json":
        typer.echo(report.to_json(), nl=False)
        return
    typer.echo(report.to_markdown(), nl=False)
