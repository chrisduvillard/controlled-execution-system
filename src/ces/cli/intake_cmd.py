"""Implementation of the ``ces intake`` command family.

Top-level ``ces intake`` now turns inline intent, local Markdown PRDs, or GitHub
issues into a canonical execution contract. The legacy phase interview remains
available as ``ces intake interview <phase>``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

import ces.cli._output as _output_mod
from ces.cli._async import run_async
from ces.cli._context import find_project_root, get_project_id
from ces.cli._errors import handle_error
from ces.cli._factory import get_services
from ces.cli._output import console
from ces.intake.contracts import (
    ExecutionContract,
    ExecutionContractRepository,
    IntakeNormalizer,
    ValidationSeverity,
    validate_execution_contract,
)

intake_app = typer.Typer(
    help="Turn intent, PRDs, or GitHub issues into CES execution contracts.",
    no_args_is_help=True,
)


@intake_app.command("create")
def create_contract(
    source: Annotated[
        str | None,
        typer.Argument(help="Inline intent text or path to a local Markdown PRD file."),
    ] = None,
    from_github_issue: Annotated[
        str | None,
        typer.Option("--from-github-issue", help="Read a GitHub issue number or URL via `gh issue view`."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
    project_root: Annotated[
        Path | None,
        typer.Option("--project-root", help="Project root; defaults to current working directory."),
    ] = None,
) -> None:
    """Create an execution contract from a supported intake source."""

    try:
        github_issue = from_github_issue
        root = (project_root or Path.cwd()).resolve()
        if github_issue and source:
            raise ValueError("Provide either SOURCE or --from-github-issue, not both.")
        if not github_issue and not source:
            raise ValueError("Provide inline intent text, a PRD Markdown path, or --from-github-issue.")
        normalizer = IntakeNormalizer()
        if github_issue:
            contract = normalizer.from_github_issue(github_issue, project_root=root)
        elif source and _looks_like_markdown_path(source, root):
            contract = normalizer.from_prd(source, project_root=root)
        else:
            contract = normalizer.from_inline(source or "", project_root=root)
        saved = ExecutionContractRepository(root).save(contract)
        _emit_intake_result(saved.contract, root, json_output=json_output)
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        handle_error(exc)


@intake_app.command("show")
def show_contract(
    contract_id: Annotated[
        str | None,
        typer.Argument(help="Contract ID to show; defaults to latest."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
    project_root: Annotated[
        Path | None,
        typer.Option("--project-root", help="Project root; defaults to current working directory."),
    ] = None,
) -> None:
    """Show the latest or named execution contract."""

    try:
        repo = ExecutionContractRepository((project_root or Path.cwd()).resolve())
        contract = repo.load(contract_id) if contract_id else repo.load_latest()
        if json_output or _output_mod._json_mode:
            typer.echo(json.dumps(contract.model_dump(mode="json"), indent=2))
            return
        console.print(contract.to_markdown())
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        handle_error(exc)


@intake_app.command("review")
def review_contract(
    contract_id: Annotated[
        str | None,
        typer.Argument(help="Contract ID to review; defaults to latest."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
    project_root: Annotated[
        Path | None,
        typer.Option("--project-root", help="Project root; defaults to current working directory."),
    ] = None,
) -> None:
    """Validate an execution contract and show approval-safety findings."""

    try:
        repo = ExecutionContractRepository((project_root or Path.cwd()).resolve())
        contract = repo.load(contract_id) if contract_id else repo.load_latest()
        findings = validate_execution_contract(contract)
        payload = {
            "contract_id": contract.contract_id,
            "objective": contract.objective,
            "approval_safe": not any(f.severity is ValidationSeverity.BLOCKER for f in findings),
            "findings": [finding.model_dump(mode="json") for finding in findings],
            "next_commands": list(contract.next_commands),
        }
        if json_output or _output_mod._json_mode:
            typer.echo(json.dumps(payload, indent=2))
            return
        table = Table(title=f"Execution Contract Review: {contract.contract_id}")
        table.add_column("Severity")
        table.add_column("Field")
        table.add_column("Message")
        for finding in findings:
            table.add_row(finding.severity.value, finding.field or "-", finding.message)
        if not findings:
            table.add_row("info", "-", "No validation findings.")
        console.print(table)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        handle_error(exc)


@intake_app.command("interview")
@run_async
async def run_intake(
    phase: int = typer.Argument(
        ...,
        help="Phase number (1-3)",
    ),
) -> None:
    """Start the legacy interactive intake interview for the given phase.

    Displays questions one at a time and collects answers via prompt.
    Progresses through mandatory, conditional, and completeness stages.
    Shows session summary at the end.
    """
    try:
        find_project_root()
        project_id = get_project_id()

        async with get_services() as services:
            engine = services["intake_engine"]
            project_id = "default"

            session_id = await engine.start_session(phase, project_id)

            if not _output_mod._json_mode:
                console.print(f"[bold]Intake session started:[/bold] {session_id}")
                console.print(f"Phase: {phase}\n")

            while True:
                question = await engine.get_next_question(session_id)

                if question is None:
                    try:
                        new_stage = await engine.advance_stage(session_id)
                        if new_stage == "completed":
                            break
                        if not _output_mod._json_mode:
                            console.print(f"\n[dim]Stage advanced to: {new_stage}[/dim]\n")
                        continue
                    except (ValueError, Exception):
                        break

                if not _output_mod._json_mode:
                    console.print(
                        Panel(
                            question.text,
                            title=f"Question {question.question_id}",
                            border_style="cyan",
                        )
                    )

                answer_text = typer.prompt("Your answer")

                await engine.submit_answer(
                    session_id,
                    question.question_id,
                    answer_text=answer_text,
                    answered_by="cli-user",
                )

            status = await engine.get_session_status(session_id)

            if _output_mod._json_mode:
                typer.echo(json.dumps(status, indent=2, default=str))
                return

            table = Table(title="Intake Session Summary")
            table.add_column("Field")
            table.add_column("Value")
            table.add_row("Session ID", session_id)
            table.add_row("Stage", status["current_stage"])
            table.add_row("Answered", str(status["answered_count"]))
            table.add_row("Total Questions", str(status["total_questions"]))
            if status.get("blocked_questions"):
                table.add_row(
                    "Blocked",
                    ", ".join(status["blocked_questions"]),
                )
            console.print(table)

    except (typer.BadParameter, ValueError) as exc:
        handle_error(exc)
    except (ConnectionError, RuntimeError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)


def _pop_flag(args: list[str], flag: str) -> bool:
    found = flag in args
    while flag in args:
        args.remove(flag)
    return found


def _pop_option(args: list[str], option: str) -> str | None:
    if option not in args:
        return None
    index = args.index(option)
    args.pop(index)
    if index >= len(args):
        raise ValueError(f"{option} requires a value")
    return args.pop(index)


def _looks_like_markdown_path(value: str, root: Path) -> bool:
    path = Path(value).expanduser()
    if path.suffix.lower() not in {".md", ".markdown"}:
        return False
    return path.is_file() or (root / path).is_file()


def _emit_intake_result(contract: ExecutionContract, root: Path, *, json_output: bool) -> None:
    findings = validate_execution_contract(contract)
    payload = {
        "contract": contract.model_dump(mode="json"),
        "approval_safe": not any(f.severity is ValidationSeverity.BLOCKER for f in findings),
        "findings": [finding.model_dump(mode="json") for finding in findings],
        "paths": {
            "json": str(Path(".ces") / "contracts" / f"{contract.contract_id}.json"),
            "markdown": str(Path("docs") / "contracts" / f"{contract.contract_id}.md"),
            "spec": contract.generated_spec_path,
        },
        "next_commands": list(contract.next_commands),
    }
    if json_output or _output_mod._json_mode:
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(f"[bold green]Execution contract created:[/bold green] {contract.contract_id}")
    console.print(f"Objective: {contract.objective}")
    console.print(f"Project root: {root}")
    console.print("\nNext commands:")
    for command in contract.next_commands:
        console.print(f"  {command}")
