"""Implementation of the ``ces setup-ci`` command.

Writes a CES gating workflow into the current repository so CES can
run as a CI check on pull requests / merge requests.

Supported providers:
    * ``github`` → ``.github/workflows/ces-gating.yml``
    * ``gitlab`` → ``.gitlab-ci.yml``

Refuses to clobber an existing target file unless ``--force`` is passed.
Templates are shipped under ``src/ces/cli/templates/ci/``.

Exports:
    setup_ci: Typer command function for ``ces setup-ci``.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import typer
from rich.panel import Panel

from ces.cli._output import console

_VALID_PROVIDERS = ("github", "gitlab")

_PROVIDER_TARGETS: dict[str, tuple[Path, str]] = {
    "github": (Path(".github") / "workflows" / "ces-gating.yml", "github.yml"),
    "gitlab": (Path(".gitlab-ci.yml"), "gitlab-ci.yml"),
}


def _read_template(resource_name: str) -> str:
    """Return the bundled CI template text by resource filename."""
    return resources.files("ces.cli.templates.ci").joinpath(resource_name).read_text(encoding="utf-8")


def setup_ci(
    provider: str = typer.Option(
        ...,
        "--provider",
        help=f"CI provider: one of {', '.join(_VALID_PROVIDERS)}",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite an existing workflow file if present.",
    ),
) -> None:
    """Generate a CES gating workflow for the chosen CI provider.

    Writes ``.github/workflows/ces-gating.yml`` for GitHub, or
    ``.gitlab-ci.yml`` for GitLab, into the current working directory.
    """
    if provider not in _PROVIDER_TARGETS:
        raise typer.BadParameter(f"Unknown provider '{provider}'. Valid choices: {', '.join(_VALID_PROVIDERS)}.")

    relative_target, template_resource = _PROVIDER_TARGETS[provider]
    target_path = Path.cwd() / relative_target

    if target_path.exists() and not force:
        console.print(
            Panel(
                f"[bold]{target_path}[/bold] already exists. Re-run with [cyan]--force[/cyan] to overwrite.",
                title="[yellow]CI workflow already present[/yellow]",
                border_style="yellow",
            )
        )
        raise typer.Exit(code=1)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(_read_template(template_resource), encoding="utf-8")

    console.print(
        Panel(
            f"Wrote CES gating workflow to:\n  [bold]{target_path}[/bold]\n\n"
            "Next steps:\n"
            f"  1. Commit the file and open a pull request\n"
            f"  2. Install/authenticate [cyan]claude[/cyan] or [cyan]codex[/cyan] on the CI runner for real reviews\n"
            f"  3. Otherwise keep [cyan]CES_DEMO_MODE=1[/cyan] for demo-mode trial runs",
            title="[green]CI workflow ready[/green]",
            border_style="green",
        )
    )
