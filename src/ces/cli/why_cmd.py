"""Explain why the latest builder-first CES run is blocked and what to do next."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.panel import Panel

from ces.cli import _output as _output_mod
from ces.cli._async import run_async
from ces.cli._blocker_diagnostics import diagnose_builder_report
from ces.cli._builder_report import load_builder_run_report, serialize_builder_run_report
from ces.cli._context import find_project_root
from ces.cli._errors import handle_error
from ces.cli._factory import get_services
from ces.cli._output import console, set_json_mode


@run_async
async def explain_blocker(
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Repo/CES project root to inspect; defaults to cwd/.ces discovery.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output blocker diagnostics as JSON. Equivalent to `ces --json why`.",
    ),
) -> None:
    """Explain the current builder blocker and the next best command."""
    if json_output:
        set_json_mode(True)
    try:
        resolved_root = project_root.resolve() if project_root is not None else find_project_root()
        async with get_services(project_root=resolved_root) as services:
            local_store = services.get("local_store")
            report = load_builder_run_report(local_store)
            if report is None:
                raise RuntimeError("No builder session is recorded yet. Start with `ces build`.")
            diagnostic = diagnose_builder_report(report)

            if _output_mod._json_mode:
                typer.echo(
                    json.dumps(
                        {
                            "project_root": str(resolved_root),
                            "diagnostic": diagnostic.to_dict(),
                            "builder_run": serialize_builder_run_report(report),
                        },
                        indent=2,
                    )
                )
                return

            lines = [
                f"Request: {report.request}",
                f"State: {report.review_state} / {report.latest_outcome}",
                f"Category: {diagnostic.category}",
                f"Blocked because: {diagnostic.reason}" if diagnostic.category != "none" else diagnostic.reason,
            ]
            if diagnostic.evidence:
                lines.append("Evidence:")
                lines.extend(f"- {item}" for item in diagnostic.evidence[:5])
            lines.append(f"Product may be complete: {diagnostic.product_may_be_complete}")
            lines.append(f"Next: {diagnostic.next_command}")
            console.print(
                Panel(
                    "\n".join(lines),
                    title="[cyan]CES Why[/cyan]",
                    border_style="cyan" if diagnostic.category == "none" else "yellow",
                )
            )
    except (typer.BadParameter, RuntimeError, ValueError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)
