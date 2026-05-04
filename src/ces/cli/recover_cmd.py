"""`ces recover` self-recovery command."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.panel import Panel
from rich.table import Table

from ces.cli import _output as _output_mod
from ces.cli._async import run_async
from ces.cli._context import find_project_root, get_project_config
from ces.cli._errors import handle_error
from ces.cli._output import console, set_json_mode
from ces.local_store import LocalProjectStore
from ces.recovery.executor import run_auto_evidence_recovery
from ces.recovery.planner import build_recovery_plan


@run_async
async def recover_builder_session(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Explain the recovery plan without mutating CES state.",
    ),
    auto_evidence: bool = typer.Option(
        False,
        "--auto-evidence",
        help="Rerun completion-contract verification and attach recovered evidence if it passes.",
    ),
    auto_complete: bool = typer.Option(
        False,
        "--auto-complete",
        help="When auto-evidence verification passes, reconcile the blocked builder session as complete.",
    ),
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Repo/CES project root to recover; defaults to cwd/.ces discovery.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output recovery details as JSON. Equivalent to `ces --json recover`.",
    ),
) -> None:
    """Recover from a blocked builder-first run with explicit, safe actions."""
    if json_output:
        set_json_mode(True)
    try:
        resolved_root = project_root.resolve() if project_root is not None else find_project_root()
        config = get_project_config(resolved_root)
        local_store = LocalProjectStore(
            resolved_root / ".ces" / "state.db",
            project_id=str(config.get("project_id", "default")),
        )
        if auto_complete and not auto_evidence:
            raise typer.BadParameter("--auto-complete requires --auto-evidence.")
        if auto_evidence:
            result = run_auto_evidence_recovery(
                project_root=resolved_root,
                local_store=local_store,
                dry_run=dry_run,
                auto_complete=auto_complete,
            )
            payload = {
                "mode": "auto-evidence",
                "project_root": str(resolved_root),
                "result": result.to_dict(),
            }
            if _output_mod._json_mode:
                typer.echo(json.dumps(payload, indent=2))
                if not result.verification.passed:
                    raise typer.Exit(code=1)
                return
            _print_recovery_result(result)
            if not result.verification.passed:
                raise typer.Exit(code=1)
            return

        plan = build_recovery_plan(project_root=resolved_root, local_store=local_store)
        payload = {"mode": "plan", "project_root": str(resolved_root), "plan": plan.to_dict()}
        if _output_mod._json_mode:
            typer.echo(json.dumps(payload, indent=2))
            return
        _print_plan(plan.to_dict())
    except typer.Exit:
        raise
    except (typer.BadParameter, RuntimeError, ValueError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)


def _print_plan(plan: dict[str, object]) -> None:
    commands = plan.get("next_commands") or []
    table = Table(title="Recovery Plan")
    table.add_column("Field")
    table.add_column("Value")
    for key in ("session_id", "manifest_id", "blocked", "can_run_auto_evidence", "contract_path"):
        table.add_row(key, str(plan.get(key)))
    console.print(table)
    console.print(
        Panel(
            f"{plan.get('explanation')}\n\nNext:\n" + "\n".join(f"- {command}" for command in commands),
            title="[yellow]Self-Recovery Plan[/yellow]",
            border_style="yellow",
        )
    )


def _print_recovery_result(result) -> None:
    table = Table(title="Recovered Verification")
    table.add_column("Command")
    table.add_column("Exit")
    table.add_column("Result")
    for command in result.verification.commands:
        table.add_row(command.command, str(command.exit_code), "PASS" if command.passed else "FAIL")
    console.print(table)
    console.print(
        Panel(
            f"Passed: {result.verification.passed}\n"
            f"Completed: {result.completed}\n"
            f"Evidence packet: {result.new_evidence_packet_id or '(none)'}\n"
            f"Next: {result.next_action}\n\n{result.message}",
            title="[green]Self-Recovery Complete[/green]"
            if result.verification.passed
            else "[red]Self-Recovery Blocked[/red]",
            border_style="green" if result.verification.passed else "red",
        )
    )
