"""Run independent local product verification."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.panel import Panel
from rich.table import Table

from ces.cli import _output as _output_mod
from ces.cli._context import find_project_root
from ces.cli._errors import handle_error
from ces.cli._output import console, set_json_mode
from ces.verification.build_contract import build_completion_contract
from ces.verification.completion_contract import CompletionContract
from ces.verification.runner import run_verification_commands


def verify_project(
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Repo/CES project root to verify; defaults to cwd/.ces discovery.",
    ),
    contract_path: Path | None = typer.Option(
        None,
        "--contract",
        help="Path to a completion contract JSON file. Defaults to .ces/completion-contract.json or inferred.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output verification results as JSON. Equivalent to `ces --json verify`.",
    ),
    write_contract: bool = typer.Option(
        False,
        "--write-contract",
        help="Persist an inferred completion contract when --contract/default contract path is missing.",
    ),
) -> None:
    """Independently verify the current project using inferred or contracted commands."""
    if json_output:
        set_json_mode(True)
    try:
        resolved_root = project_root.resolve() if project_root is not None else find_project_root()
        resolved_contract_path = _resolve_contract_path(resolved_root, contract_path)
        contract_persisted = resolved_contract_path.is_file()
        if contract_persisted:
            contract = CompletionContract.read(resolved_contract_path)
        else:
            contract = build_completion_contract(
                project_root=resolved_root,
                request="Independent verification",
                acceptance_criteria=(),
                runtime_name="manual",
            )
            if write_contract:
                contract.write(resolved_contract_path)
                contract_persisted = True
        verification = run_verification_commands(resolved_root, contract.inferred_commands)
        payload = {
            "project_root": str(resolved_root),
            "contract_path": str(resolved_contract_path),
            "contract_persisted": contract_persisted,
            "project_type": contract.project_type,
            "verification": verification.to_dict(),
        }
        if _output_mod._json_mode:
            typer.echo(json.dumps(payload, indent=2))
            if not verification.passed:
                raise typer.Exit(code=1)
            return
        table = Table(title="Independent Verification")
        table.add_column("Command")
        table.add_column("Exit")
        table.add_column("Result")
        for result in verification.commands:
            table.add_row(result.command, str(result.exit_code), "PASS" if result.passed else "FAIL")
        console.print(table)
        console.print(
            Panel(
                f"Project type: {contract.project_type}\n"
                f"Contract persisted: {contract_persisted}\n"
                f"Passed: {verification.passed}\nNext: ces why",
                title="[green]Verification Complete[/green]"
                if verification.passed
                else "[red]Verification Failed[/red]",
                border_style="green" if verification.passed else "red",
            )
        )
        if not verification.passed:
            raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except (typer.BadParameter, RuntimeError, ValueError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)


def _resolve_contract_path(project_root: Path, contract_path: Path | None) -> Path:
    if contract_path is None:
        return project_root / ".ces" / "completion-contract.json"
    return contract_path if contract_path.is_absolute() else project_root / contract_path
