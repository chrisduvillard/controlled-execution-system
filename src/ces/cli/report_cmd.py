"""Report export commands."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.panel import Panel

import ces.cli._output as _output_mod
from ces.cli._async import run_async
from ces.cli._builder_report import export_builder_run_report, serialize_builder_run_report
from ces.cli._context import find_project_root
from ces.cli._errors import handle_error
from ces.cli._factory import get_services
from ces.cli._output import console

report_app = typer.Typer(help="Export concise CES reports.")


@report_app.command("builder")
@run_async
async def export_builder_report(
    output_dir: Path = typer.Option(
        Path(".ces/exports"),
        "--output-dir",
        help="Directory where the builder run report artifacts should be written.",
    ),
) -> None:
    """Export a concise report for the latest builder run."""
    try:
        project_root = find_project_root()
        resolved_output_dir = output_dir if output_dir.is_absolute() else project_root / output_dir

        async with get_services() as services:
            local_store = services.get("local_store")
            get_snapshot = getattr(local_store, "get_latest_builder_session_snapshot", None)
            if not callable(get_snapshot):
                raise RuntimeError("Builder reports are unavailable for this project.")
            snapshot = get_snapshot()
            if snapshot is None or not isinstance(getattr(snapshot, "request", None), str):
                raise RuntimeError("No builder session is recorded yet. Start with `ces build`.")

            artifacts = export_builder_run_report(output_dir=resolved_output_dir, snapshot=snapshot)

            if _output_mod._json_mode:
                typer.echo(
                    json.dumps(
                        {
                            "markdown_path": str(artifacts.markdown_path),
                            "json_path": str(artifacts.json_path),
                            "builder_run": serialize_builder_run_report(artifacts.report),
                        },
                        indent=2,
                    )
                )
                return

            console.print(
                Panel(
                    "\n".join(
                        [
                            f"Markdown: {artifacts.markdown_path}",
                            f"JSON: {artifacts.json_path}",
                            "",
                            f"Request: {artifacts.report.request}",
                            f"Review state: {artifacts.report.review_state}",
                            f"Latest outcome: {artifacts.report.latest_outcome}",
                        ]
                    ),
                    title="[cyan]Builder Run Report Exported[/cyan]",
                    border_style="cyan",
                )
            )
    except (typer.BadParameter, ValueError, RuntimeError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)
