"""Implementation of the ``ces mri`` repository diagnostic command."""

from __future__ import annotations

from pathlib import Path

import typer

from ces.verification.mri import scan_project_mri


def mri(
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Repo/CES project root to inspect; defaults to the current working directory.",
    ),
    output_format: str = typer.Option(
        "markdown",
        "--format",
        help="Output format: markdown or json.",
    ),
) -> None:
    """Run a read-only Project MRI health scan for a repository."""

    normalized_format = output_format.strip().lower()
    if normalized_format not in {"markdown", "json"}:
        raise typer.BadParameter("format must be 'markdown' or 'json'")
    report = scan_project_mri(project_root or Path.cwd())
    if normalized_format == "json":
        typer.echo(report.to_json(), nl=False)
        return
    typer.echo(report.to_markdown(), nl=False)
