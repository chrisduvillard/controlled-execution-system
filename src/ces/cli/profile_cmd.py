"""Implementation of the ``ces profile`` command group."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from ces.cli._output import console
from ces.verification.profile import PROFILE_RELATIVE_PATH, VerificationProfile, load_verification_profile, profile_path
from ces.verification.profile_detector import detect_verification_profile, write_verification_profile

profile_app = typer.Typer(
    help="Inspect and maintain project-aware verification requirements.",
    rich_markup_mode="rich",
)


def _project_root() -> Path:
    return Path.cwd().resolve()


def _render_profile(profile: VerificationProfile, *, path: Path, project_root: Path, written: bool = True) -> None:
    table = Table(title="Verification profile")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Configured")
    table.add_column("Required")
    table.add_column("Reason")
    for name, requirement in sorted(profile.checks.items()):
        table.add_row(
            name,
            requirement.status.value,
            "yes" if requirement.configured else "no",
            "yes" if requirement.required else "no",
            requirement.reason,
        )
    console.print(table)
    suffix = "" if written else " (not written; use --write to persist)"
    console.print(f"profile: {path.relative_to(project_root)}{suffix}")


def _load_existing_or_exit(project_root: Path) -> tuple[VerificationProfile, Path]:
    path = profile_path(project_root)
    profile = load_verification_profile(project_root)
    if profile is None:
        console.print(f"No verification profile found at {PROFILE_RELATIVE_PATH}")
        raise typer.Exit(code=1)
    return profile, path


@profile_app.callback(invoke_without_command=True)
def profile_root(ctx: typer.Context) -> None:
    """Show help when no profile subcommand is provided."""

    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit


@profile_app.command(name="show")
def show_profile() -> None:
    """Show the existing ``.ces/verification-profile.json``."""

    project_root = _project_root()
    profile, path = _load_existing_or_exit(project_root)
    _render_profile(profile, path=path, project_root=project_root)


@profile_app.command(name="detect")
def detect_profile(
    write: bool = typer.Option(
        False,
        "--write",
        help="Persist the detected profile to .ces/verification-profile.json.",
    ),
) -> None:
    """Detect verification requirements from the current project."""

    project_root = _project_root()
    profile = detect_verification_profile(project_root)
    path = profile_path(project_root)
    if write:
        path = write_verification_profile(project_root, profile)
    _render_profile(profile, path=path, project_root=project_root, written=write)


@profile_app.command(name="doctor")
def doctor_profile() -> None:
    """Explain whether a verification profile exists and how checks are classified."""

    project_root = _project_root()
    profile = load_verification_profile(project_root)
    if profile is None:
        console.print(f"No verification profile found at {PROFILE_RELATIVE_PATH}")
        console.print("Run `ces profile detect --write` to create one.")
        raise typer.Exit(code=1)
    _render_profile(profile, path=profile_path(project_root), project_root=project_root)
    required = sorted(name for name, requirement in profile.checks.items() if requirement.required)
    advisory = sorted(name for name, requirement in profile.checks.items() if not requirement.required)
    console.print(f"required checks: {', '.join(required) if required else 'none'}")
    console.print(f"non-blocking checks: {', '.join(advisory) if advisory else 'none'}")


# Backward-compatible callable for older tests/imports; prefer ``profile_app``.
def profile(
    check: bool = typer.Option(
        False,
        "--check",
        help="Read and explain the existing verification profile instead of regenerating it.",
    ),
) -> None:
    """Detect/write a profile, or show an existing profile with ``--check``."""

    project_root = _project_root()
    if check:
        existing, path = _load_existing_or_exit(project_root)
        _render_profile(existing, path=path, project_root=project_root)
        return
    path = write_verification_profile(project_root)
    written = load_verification_profile(project_root)
    if written is None:  # defensive: write succeeded but load did not
        raise typer.Exit(code=1)
    _render_profile(written, path=path, project_root=project_root)
