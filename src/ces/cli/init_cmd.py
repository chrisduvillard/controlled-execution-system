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
import shutil
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
    "electron-desktop-app": "electron-desktop-app.yaml",
    "package-artifact-hygiene": "package-artifact-hygiene.yaml",
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


def _has_only_profile_bootstrap_state(ces_dir: Path) -> bool:
    """Return whether ``.ces/`` only contains pre-init verification-profile state."""
    if not ces_dir.is_dir():
        return False
    allowed = {Path("verification-profile.json")}
    children = {path.relative_to(ces_dir) for path in ces_dir.rglob("*") if path.is_file()}
    dirs = {path.relative_to(ces_dir) for path in ces_dir.rglob("*") if path.is_dir()}
    return bool(children) and children <= allowed and not dirs


def _validate_ces_state_path(project_root: Path, ces_dir: Path) -> None:
    """Fail closed if the CES state path can escape the project root."""
    if ces_dir.is_symlink():
        raise ValueError("Refusing to initialize .ces because it is a symlink.")
    resolved_project = project_root.resolve()
    resolved_ces = ces_dir.resolve(strict=False)
    try:
        resolved_ces.relative_to(resolved_project)
    except ValueError as exc:
        raise ValueError("Refusing to initialize .ces outside the project root.") from exc


def initialize_local_project(project_root: Path, *, name: str) -> dict[str, Any]:
    """Create ``.ces/`` local project state and return the written config."""
    if not _PROJECT_NAME_RE.match(name):
        raise ValueError(
            "Project names must start with alphanumeric and contain only "
            "letters, digits, hyphens, underscores, or dots."
        )

    ces_dir = project_root / ".ces"
    _validate_ces_state_path(project_root, ces_dir)
    profile_bootstrap_only = _has_only_profile_bootstrap_state(ces_dir)
    if ces_dir.exists() and not profile_bootstrap_only:
        raise FileExistsError(f"Directory {project_root} is already a CES project.")

    ces_dir.mkdir(mode=0o700, exist_ok=profile_bootstrap_only)
    keys_dir = ces_dir / "keys"
    keys_dir.mkdir(mode=0o700)
    (ces_dir / "artifacts").mkdir()
    (ces_dir / ".gitignore").write_text("*\n", encoding="utf-8")
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


_DEFAULT_GITIGNORE_ENTRIES = (
    ".ces/",
    ".venv/",
    ".coverage",
    "coverage.json",
    "*.egg-info/",
    "dist/",
    "build/",
)


def _ensure_local_gitignore_entries(project_root: Path) -> tuple[str, ...]:
    """Ensure CES local state/secrets and common generated artifacts are ignored."""
    gitignore_path = project_root / ".gitignore"
    existing = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
    existing_lines = {line.strip() for line in existing.splitlines()}
    missing = tuple(entry for entry in _DEFAULT_GITIGNORE_ENTRIES if entry not in existing_lines)
    if not missing:
        return ()
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    block = "\n".join(("# CES local state and generated artifacts", *missing))
    gitignore_path.write_text(f"{existing}{prefix}{block}\n", encoding="utf-8")
    return missing


@run_async
async def init_project(
    name: str | None = typer.Argument(
        None,
        help="Project name; defaults to the current directory/repo name.",
    ),
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Directory to initialize; defaults to the current working directory.",
    ),
    template: str | None = typer.Option(
        None,
        "--template",
        help=("Optional starter manifest template. Available: " + ", ".join(sorted(_MANIFEST_TEMPLATES)) + "."),
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Non-interactive confirmation flag for automation consistency; init has no prompts today.",
    ),
) -> None:
    """Initialize a new CES project in the current directory or --project-root.

    Creates ``.ces/`` with config.yaml, keys/, and artifacts/
    subdirectories.  If the directory is already a CES project,
    exits with an error. When ``--template`` is provided, a starter
    manifest is written to ``.ces/artifacts/manifest-template.yaml``.
    """
    cwd = (project_root or Path.cwd()).resolve()
    if name is None:
        name = derive_project_name(cwd.name)

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

    ces_dir = cwd / ".ces"
    try:
        _validate_ces_state_path(cwd, ces_dir)
    except ValueError as exc:
        console.print(
            Panel(
                str(exc),
                title="[red]Security Error[/red]",
                border_style="red",
            )
        )
        raise typer.Exit(code=1) from exc

    # Check if already initialized. A profile-only .ces/ directory can be
    # created by `ces profile detect --write` before `ces init`; upgrade it in
    # place so profile discovery does not strand the project without keys.
    if ces_dir.exists() and not _has_only_profile_bootstrap_state(ces_dir):
        console.print(
            Panel(
                f"Directory [bold]{cwd}[/bold] is already a CES project.\n"
                "Remove .ces/ directory first if you want to reinitialize.",
                title="[red]User Error[/red]",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)

    del yes
    config = initialize_local_project(cwd, name=name)
    ignored_entries = _ensure_local_gitignore_entries(cwd)

    if template is not None:
        _copy_manifest_template(template, ces_dir / "artifacts" / "manifest-template.yaml")

    # Success message
    console.print(
        Panel(
            f"[green]CES is ready for:[/green] [bold]{name}[/bold]\n"
            f"Project root: {cwd}\n\n"
            f"  .ces/config.yaml   - Project configuration\n"
            f"  .ces/state.db      - Local CES state database\n"
            f"  .ces/keys/         - Ed25519 manifest-signing keypair + audit-ledger HMAC secret (mode 0600)\n"
            f"  .ces/artifacts/    - Draft truth artifacts\n\n"
            f"Git hygiene: {'.gitignore updated for ' + ', '.join(ignored_entries) if ignored_entries else '.gitignore already protects CES local state'}\n\n"
            f"Next steps:\n"
            f'  1. Run [bold]ces build "describe what you want to build"[/bold]\n'
            f"  2. If this repo already exists, capture important legacy behavior with [bold]ces brownfield[/bold]\n"
            f"  3. Use [bold]ces init[/bold] directly only when you want manual setup before the first build\n"
            f'  4. Expert mode is still available via [bold]ces manifest "describe task"[/bold]',
            title="[green]Project Initialized[/green]",
            border_style="green",
        )
    )

    detected = []
    if shutil.which("codex") is not None:
        detected.append("Codex CLI")
    if shutil.which("claude") is not None:
        detected.append("Claude Code")
    if detected:
        runtime_message = (
            f"Local mode is ready. Detected {', '.join(detected)} on PATH; "
            "run `ces doctor --verify-runtime` if you want CES to check authentication."
        )
    else:
        runtime_message = (
            "Local mode is ready. Install/authenticate Codex CLI or Claude Code before running `ces build`."
        )
    console.print(f"\n[dim]{runtime_message}[/dim]")
