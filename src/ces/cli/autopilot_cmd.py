"""Production Autopilot CLI report commands."""

from __future__ import annotations

import json
import re
import shlex
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


def _guided_start_payload(project_root: Path, objective: str) -> dict:
    ship_plan = build_ship_plan(project_root, objective=objective)
    ship_command = f"ces ship -- {shlex.quote(objective)}"
    build_command = next(
        (command for command in ship_plan.recommended_commands if command.startswith("ces build ")), None
    )
    if build_command and "--from-scratch" not in build_command:
        stages = [
            {
                "name": "Plan",
                "command": ship_command,
                "purpose": "Turn the brownfield objective into a read-only delivery plan before launching any runtime.",
            },
            {
                "name": "Inspect",
                "command": "ces mri && ces next",
                "purpose": "Diagnose the existing project and choose the next bounded readiness step before runtime execution.",
            },
            {
                "name": "Build",
                "command": build_command,
                "purpose": "Make one bounded brownfield change while preserving existing behavior and readiness evidence.",
            },
            {
                "name": "Verify",
                "command": "ces verify",
                "purpose": "Run the project's persisted verification policy and save local evidence.",
            },
            {
                "name": "Prove",
                "command": "ces proof",
                "purpose": "Produce a compact evidence-backed ship/no-ship proof card.",
            },
        ]
    else:
        next_command = next(
            (command for command in ship_plan.recommended_commands if command not in {"ces doctor", ship_command}),
            ship_plan.recommended_command,
        )
        action_stage_name = "Build" if "ces build" in next_command else "Inspect"
        action_stage_purpose = (
            "Create or update the project with README, tests, run instructions, and a handoff contract."
            if action_stage_name == "Build"
            else "Diagnose the existing project and generate the next bounded readiness step before runtime execution."
        )
        stages = [
            {
                "name": "Plan",
                "command": ship_command,
                "purpose": "Turn the idea into a read-only delivery plan before launching any runtime.",
            },
            {
                "name": action_stage_name,
                "command": next_command,
                "purpose": action_stage_purpose,
            },
            {
                "name": "Verify",
                "command": "ces verify",
                "purpose": "Run the project's persisted verification policy and save local evidence.",
            },
            {
                "name": "Prove",
                "command": "ces proof",
                "purpose": "Produce a compact evidence-backed ship/no-ship proof card.",
            },
        ]
    return {
        "schema_version": 1,
        "project_root": str(project_root),
        "objective": objective,
        "execution_mode": "interactive-read-only-guide",
        "current_maturity": ship_plan.current_maturity,
        "target_maturity": ship_plan.target_maturity,
        "recommended_command": ship_plan.recommended_command,
        "recommended_commands": list(ship_plan.recommended_commands),
        "stages": stages,
        "safety_notes": [
            "`ces start` is read-only; it only collects the objective and prints the guided path.",
            "Only runtime commands such as `ces build` may launch an AI runtime, and runtime launch still requires the existing consent gates.",
            "Run `ces proof` only after verification evidence exists; proof cards must not overclaim unverified work.",
        ],
    }


def _guided_start_markdown(payload: dict) -> str:
    lines = [
        "# CES Guided Start",
        "",
        f"Project root: `{payload['project_root']}`",
        f"Objective: {payload['objective']}",
        f"Execution mode: **{payload['execution_mode']}**",
        "",
        "This is a beginner-safe guided path from idea to proof-backed delivery. It is read-only and does not create `.ces/`, edit files, or launch Codex or Claude Code.",
        "",
        "## Guided path",
        "",
    ]
    for index, stage in enumerate(payload["stages"], start=1):
        lines.extend(
            [
                f"### Step {index}: {stage['name']}",
                "",
                f"Command: `{stage['command']}`",
                "",
                stage["purpose"],
                "",
            ]
        )
    lines.extend(["## Safety notes", "", *_bullet(payload["safety_notes"])])
    return "\n".join(lines).rstrip() + "\n"


def _bullet(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items] or ["- None."]


def _project_slug(project_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", project_name.strip().lower()).strip("-")
    return slug or "new-project"


def _create_payload(project_root: Path, project_name: str, objective: str) -> dict:
    slug = _project_slug(project_name)
    target_directory = project_root / slug
    quoted_target = shlex.quote(str(target_directory))
    target_exists = target_directory.exists()
    quoted_objective = shlex.quote(objective)
    ship_command = f"ces ship -- {quoted_objective}"
    build_command = (
        f"ces build --from-scratch={quoted_objective}"
        if objective.startswith("-")
        else f"ces build --from-scratch {quoted_objective}"
    )
    return {
        "schema_version": 1,
        "project_root": str(project_root),
        "project_name": project_name,
        "project_slug": slug,
        "target_directory": str(target_directory),
        "target_exists": target_exists,
        "objective": objective,
        "execution_mode": "interactive-read-only-wizard",
        "commands": [
            f"mkdir -p {quoted_target} && cd {quoted_target}",
            ship_command,
            build_command,
            "ces verify",
            "ces proof",
        ],
        "safety_notes": [
            "`ces create` is read-only; it prints a project creation plan and copy-paste commands without creating files.",
            "Run the mkdir/cd command first so `--from-scratch` starts in a new empty directory.",
            "Only `ces build --from-scratch` launches the governed runtime and creates project files after existing consent gates pass.",
            *(
                [
                    "Target directory already exists; choose a new directory or use brownfield `ces build` instead of `--from-scratch`."
                ]
                if target_exists
                else []
            ),
        ],
    }


def _create_markdown(payload: dict) -> str:
    lines = [
        "# CES Create Plan",
        "",
        f"Project root: `{payload['project_root']}`",
        f"Project name: {payload['project_name']}",
        f"Project slug: `{payload['project_slug']}`",
        f"Target directory: `{payload['target_directory']}`",
        f"Objective: {payload['objective']}",
        f"Execution mode: **{payload['execution_mode']}**",
        "",
        "This is an interactive project creation wizard. It is read-only: it does not create folders, initialize `.ces/`, edit files, or launch Codex or Claude Code.",
        "",
        "## Copy-paste sequence",
        "",
    ]
    for index, command in enumerate(payload["commands"], start=1):
        lines.extend([f"{index}. `{command}`", ""])
    lines.extend(["## Safety notes", "", *_bullet(payload["safety_notes"])])
    return "\n".join(lines).rstrip() + "\n"


def create(
    project_name: str | None = typer.Argument(
        None,
        help="Project name, e.g. 'Calm Notes'. Prompts if omitted in markdown mode.",
    ),
    objective: str | None = typer.Argument(
        None,
        help="What the new project should do. Prompts if omitted in markdown mode.",
    ),
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Directory where the project folder should be created; defaults to the current working directory.",
    ),
    output_format: str = typer.Option("markdown", "--format", help="Output format: markdown or json."),
) -> None:
    """Interactive read-only wizard for starting a new project from scratch."""

    format_name = _format_option(output_format)
    json_requested = _output_mod._json_mode or format_name == "json"
    project_name_text = project_name.strip() if project_name and project_name.strip() else None
    objective_text = objective.strip() if objective and objective.strip() else None
    if project_name_text is None and not json_requested:
        project_name_text = typer.prompt("Project name").strip()
    if objective_text is None and not json_requested:
        objective_text = typer.prompt("What do you want it to do?").strip()
    if not project_name_text:
        raise typer.BadParameter("project name is required; pass it as an argument or run interactive markdown mode")
    if not objective_text:
        raise typer.BadParameter("objective is required; pass it as an argument or run interactive markdown mode")
    payload = _create_payload((project_root or Path.cwd()).resolve(), project_name_text, objective_text)
    if json_requested:
        typer.echo(json.dumps(payload, indent=2) + "\n", nl=False)
        return
    typer.echo(_create_markdown(payload), nl=False)


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


def start(
    objective: str | None = typer.Argument(
        None,
        help="Optional project objective; prompts if omitted in markdown mode.",
    ),
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Repo/CES project root to guide; defaults to the current working directory.",
    ),
    output_format: str = typer.Option("markdown", "--format", help="Output format: markdown or json."),
) -> None:
    """Collect a beginner objective and print the guided ship/build/verify/proof path."""

    format_name = _format_option(output_format)
    json_requested = _output_mod._json_mode or format_name == "json"
    objective_text = objective.strip() if objective and objective.strip() else None
    if objective_text is None and not json_requested:
        objective_text = typer.prompt("What do you want to build?").strip()
    if not objective_text:
        raise typer.BadParameter("objective is required; pass it as an argument or run interactive markdown mode")
    payload = _guided_start_payload((project_root or Path.cwd()).resolve(), objective_text)
    if json_requested:
        typer.echo(json.dumps(payload, indent=2) + "\n", nl=False)
        return
    typer.echo(_guided_start_markdown(payload), nl=False)


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
