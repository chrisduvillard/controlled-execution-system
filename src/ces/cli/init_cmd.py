"""Implementation of the ``ces init`` command.

Creates the ``.ces/`` project structure in the current working directory,
including config.yaml, keys/, and artifacts/ subdirectories.

Project name is validated to prevent path traversal (T-06-01 mitigation):
only alphanumeric characters, hyphens, and underscores are allowed.

Exports:
    init_project: Typer command function for ``ces init``.
"""

from __future__ import annotations

import os
import re
import secrets
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.panel import Panel

from ces import __version__
from ces.cli._async import run_async
from ces.cli._output import console
from ces.shared.crypto import (
    AUDIT_HMAC_FILENAME,
    generate_audit_hmac_secret,
    generate_keypair,
    save_audit_hmac_secret,
    save_keypair_to_dir,
)

# Manifest templates shipped under ``src/ces/cli/templates/manifests/``.
# Each entry maps a user-facing template name to the bundled filename.
_MANIFEST_TEMPLATES: dict[str, str] = {
    "python-service": "python-service.yaml",
    "python-library": "python-library.yaml",
}


def _copy_manifest_template(template_name: str, destination: Path) -> None:
    """Write the bundled starter manifest for ``template_name`` to ``destination``."""
    if template_name not in _MANIFEST_TEMPLATES:
        valid = ", ".join(sorted(_MANIFEST_TEMPLATES))
        raise typer.BadParameter(f"Unknown template '{template_name}'. Valid choices: {valid}.")
    resource_name = _MANIFEST_TEMPLATES[template_name]
    content = resources.files("ces.cli.templates.manifests").joinpath(resource_name).read_text(encoding="utf-8")
    destination.write_text(content, encoding="utf-8")


# Allowed project name pattern: alphanumeric, hyphens, underscores, dots.
# No path separators, no leading dots (T-06-01).
_PROJECT_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


def derive_project_name(raw_name: str) -> str:
    """Convert a directory name into a CES-safe project name."""
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", raw_name).strip("._-")
    if not normalized:
        normalized = "ces-project"
    if not normalized[0].isalnum():
        normalized = f"project-{normalized.lstrip('._-') or 'ces'}"
    if not _PROJECT_NAME_RE.match(normalized):
        normalized = "ces-project"
    return normalized


def initialize_local_project(project_root: Path, *, name: str) -> dict[str, Any]:
    """Create ``.ces/`` local project state and return the written config."""
    if not _PROJECT_NAME_RE.match(name):
        raise ValueError(
            "Project names must start with alphanumeric and contain only "
            "letters, digits, hyphens, underscores, or dots."
        )

    ces_dir = project_root / ".ces"
    if ces_dir.exists():
        raise FileExistsError(f"Directory {project_root} is already a CES project.")

    ces_dir.mkdir(mode=0o700)
    keys_dir = ces_dir / "keys"
    keys_dir.mkdir(mode=0o700)
    (ces_dir / "artifacts").mkdir()
    try:
        os.chmod(ces_dir, 0o700)
        os.chmod(keys_dir, 0o700)
    except OSError:
        pass
    state_db = ces_dir / "state.db"
    state_db.touch()
    # Tighten state.db perms at init time rather than deferring to the first
    # LocalProjectStore open — `ces doctor --security` runs immediately after
    # init and expects the DB to already be 0o600.
    try:
        os.chmod(state_db, 0o600)
    except OSError:
        pass

    # Persist the Ed25519 manifest-signing keypair and the audit-ledger HMAC
    # secret so that subsequent CLI invocations can verify signatures produced
    # by earlier runs (pre-0.1.2 the keypair was regenerated per-process,
    # which silently defeated D-13 manifest integrity).
    private_key, public_key = generate_keypair()
    save_keypair_to_dir(keys_dir, private_key, public_key)
    save_audit_hmac_secret(keys_dir / AUDIT_HMAC_FILENAME, generate_audit_hmac_secret())

    project_id = f"proj-{secrets.token_hex(12)}"
    config = {
        "project_name": name,
        "project_id": project_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "version": __version__,
        "execution_mode": "local",
        "preferred_runtime": None,
    }
    config_path = ces_dir / "config.yaml"
    with open(config_path, "w") as f:
        yaml.safe_dump(config, f, default_flow_style=False)
    return config


@run_async
async def init_project(
    name: str = typer.Argument(
        ...,
        help="Project name (alphanumeric, hyphens, underscores)",
    ),
    template: str | None = typer.Option(
        None,
        "--template",
        help=("Optional starter manifest template. Available: " + ", ".join(sorted(_MANIFEST_TEMPLATES)) + "."),
    ),
) -> None:
    """Initialize a new CES project in the current directory.

    Creates ``.ces/`` with config.yaml, keys/, and artifacts/
    subdirectories.  If the directory is already a CES project,
    exits with an error. When ``--template`` is provided, a starter
    manifest is written to ``.ces/artifacts/manifest-template.yaml``.
    """
    # Validate project name (T-06-01: no path traversal)
    if not _PROJECT_NAME_RE.match(name):
        console.print(
            Panel(
                f"Invalid project name: [bold]{name}[/bold]\n"
                "Must start with alphanumeric and contain only "
                "letters, digits, hyphens, underscores, or dots.",
                title="[red]User Error[/red]",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)

    # Validate template *before* touching the filesystem so an unknown
    # template doesn't leave a half-bootstrapped .ces/ directory behind.
    if template is not None and template not in _MANIFEST_TEMPLATES:
        valid = ", ".join(sorted(_MANIFEST_TEMPLATES))
        console.print(
            Panel(
                f"Unknown template: [bold]{template}[/bold]\nValid choices: {valid}.",
                title="[red]User Error[/red]",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)

    cwd = Path.cwd().resolve()
    ces_dir = cwd / ".ces"

    # Check if already initialized
    if ces_dir.exists():
        console.print(
            Panel(
                f"Directory [bold]{cwd}[/bold] is already a CES project.\n"
                "Remove .ces/ directory first if you want to reinitialize.",
                title="[red]User Error[/red]",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)

    config = initialize_local_project(cwd, name=name)

    if template is not None:
        _copy_manifest_template(template, ces_dir / "artifacts" / "manifest-template.yaml")

    # Success message
    console.print(
        Panel(
            f"[green]CES is ready for:[/green] [bold]{name}[/bold]\n\n"
            f"  .ces/config.yaml   - Project configuration\n"
            f"  .ces/state.db      - Local CES state database\n"
            f"  .ces/keys/         - Ed25519 manifest-signing keypair + audit-ledger HMAC secret (mode 0600)\n"
            f"  .ces/artifacts/    - Draft truth artifacts\n\n"
            f"Next steps:\n"
            f'  1. Run [bold]ces build "describe what you want to build"[/bold]\n'
            f"  2. If this repo already exists, capture important legacy behavior with [bold]ces brownfield[/bold]\n"
            f"  3. Use [bold]ces init[/bold] directly only when you want manual setup before the first build\n"
            f'  4. Expert mode is still available via [bold]ces manifest "describe task"[/bold]',
            title="[green]Project Initialized[/green]",
            border_style="green",
        )
    )

    console.print(
        "\n[dim]Local mode is ready. Install/authenticate Codex CLI or Claude Code before running `ces build`.[/dim]"
    )
