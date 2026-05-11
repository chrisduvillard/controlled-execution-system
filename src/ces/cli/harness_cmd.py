"""Implementation of the conservative `ces harness` command group."""

from __future__ import annotations

from pathlib import Path

import typer
from pydantic import ValidationError
from rich.table import Table

from ces.cli._output import console
from ces.execution.secrets import scrub_secrets_from_text
from ces.harness_evolution.manifest_io import read_manifest
from ces.harness_evolution.paths import HarnessPaths, create_harness_layout, relative_layout_entries

harness_app = typer.Typer(
    help="Inspect and initialize local harness evolution artifacts.",
    rich_markup_mode="rich",
)
changes_app = typer.Typer(
    help="Validate local harness change manifests.",
    rich_markup_mode="rich",
)


def _project_root(project_root: Path | None = None) -> Path:
    return (project_root or Path.cwd()).resolve()


def _project_root_option() -> Path | None:
    return typer.Option(
        None,
        "--project-root",
        help="Repo/CES project root to inspect; defaults to the current working directory.",
    )


@harness_app.callback(invoke_without_command=True)
def harness_root(ctx: typer.Context) -> None:
    """Show help when no harness subcommand is provided."""

    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit


@harness_app.command(name="init")
def init_harness(
    project_root: Path | None = _project_root_option(),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show the intended `.ces/harness/` layout without writing files.",
    ),
) -> None:
    """Initialize the local `.ces/harness/` substrate."""

    root = _project_root(project_root)
    entries = relative_layout_entries(root)
    if dry_run:
        console.print("Harness init dry-run: would ensure these local paths:")
        for entry in entries:
            console.print(f"- {entry}")
        console.print("No files were written. Runtime prompt injection remains disabled.")
        return

    paths = create_harness_layout(root)
    console.print(f"Initialized local harness substrate at {paths.root.relative_to(root)}")
    console.print("Created/ensured:")
    for entry in entries:
        console.print(f"- {entry}")
    console.print("Runtime prompt injection remains disabled.")


@harness_app.command(name="inspect")
def inspect_harness(project_root: Path | None = _project_root_option()) -> None:
    """Inspect whether the local harness substrate is initialized."""

    root = _project_root(project_root)
    paths = HarnessPaths.for_project(root)
    if not paths.index.exists():
        console.print("Harness substrate is not initialized.")
        console.print("Next action: run `ces harness init --dry-run`, then `ces harness init`.")
        raise typer.Exit(code=1)

    table = Table(title="Harness substrate")
    table.add_column("Path")
    table.add_column("Status")
    for entry in relative_layout_entries(root):
        path = root / entry.rstrip("/")
        table.add_row(entry, "present" if path.exists() else "missing")
    console.print(table)
    console.print("Runtime prompt injection: disabled")


@changes_app.command(name="validate")
def validate_change_manifest(manifest_path: Path) -> None:
    """Validate a harness change manifest without persisting it."""

    try:
        manifest = read_manifest(manifest_path)
    except (OSError, ValueError, ValidationError) as exc:
        safe_error = scrub_secrets_from_text(str(exc))
        console.print(f"Invalid harness change manifest: {safe_error}")
        raise typer.Exit(code=1) from exc

    console.print(f"Valid harness change manifest: {manifest.change_id}")
    console.print(f"component: {manifest.component_type.value}")
    console.print(f"predicted fixes: {len(manifest.predicted_fixes)}")
    console.print(f"predicted regressions: {len(manifest.predicted_regressions)}")


harness_app.add_typer(changes_app, name="changes")
