"""Run independent local product verification."""

from __future__ import annotations

import json
import os
import tempfile
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
                _write_contract_safely(resolved_root, resolved_contract_path, contract)
                contract_persisted = True
        verification = run_verification_commands(resolved_root, contract.inferred_commands)
        payload = {
            "project_root": str(resolved_root),
            "contract_path": str(resolved_contract_path),
            "contract_persisted": contract_persisted,
            "project_type": contract.project_type,
            "verification": verification.to_dict(),
        }
        _write_latest_verification(resolved_root, payload)
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


def _write_latest_verification(project_root: Path, payload: dict[str, object]) -> Path:
    ces_dir = _safe_ces_state_dir(project_root)
    path = _safe_project_write_path(project_root, ces_dir / "latest-verification.json", "verification evidence")
    _write_json_atomic(path, payload)
    return path


def _write_contract_safely(project_root: Path, path: Path, contract: CompletionContract) -> Path:
    safe_path = _safe_project_write_path(project_root, path, "completion contract")
    _write_json_atomic(safe_path, contract.to_dict())
    return safe_path


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        tmp_name = handle.name
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    os.replace(tmp_name, path)


def _safe_project_write_path(project_root: Path, path: Path, description: str) -> Path:
    """Return a project-local output path, rejecting symlink escapes and final symlinks."""

    resolved_root = project_root.resolve()
    candidate = path if path.is_absolute() else resolved_root / path
    if candidate.is_symlink():
        raise ValueError(f"Refusing to write {description} through a symlinked file")
    try:
        resolved_parent = candidate.parent.resolve()
        resolved_parent.relative_to(resolved_root)
        resolved_candidate = resolved_parent / candidate.name
    except (OSError, ValueError) as exc:
        raise ValueError(f"{description.capitalize()} path must stay inside the project root") from exc
    return resolved_candidate


def _safe_ces_state_dir(project_root: Path) -> Path:
    """Return the project-local .ces directory, rejecting symlink escapes."""

    resolved_root = project_root.resolve()
    ces_dir = resolved_root / ".ces"
    if ces_dir.is_symlink():
        raise ValueError("Refusing to write verification evidence through a symlinked .ces directory")
    try:
        ces_dir.resolve().relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise ValueError("Verification evidence path must stay inside the project root") from exc
    return ces_dir


def _resolve_contract_path(project_root: Path, contract_path: Path | None) -> Path:
    if contract_path is None:
        return project_root / ".ces" / "completion-contract.json"
    return contract_path if contract_path.is_absolute() else project_root / contract_path
