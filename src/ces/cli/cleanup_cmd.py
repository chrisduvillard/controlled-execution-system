"""Safe cleanup command for removing local CES state from a project."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from shlex import quote

import typer
from rich.panel import Panel

from ces.cli._context import find_project_root
from ces.cli._output import console
from ces.cli._state_path import validate_ces_state_dir

_CES_GITIGNORE_HEADER = "# CES local state and generated artifacts"
_CES_GITIGNORE_ENTRIES = (
    ".ces/",
    ".venv/",
    ".coverage",
    "coverage.json",
    "*.egg-info/",
    "dist/",
    "build/",
)


@dataclass(frozen=True)
class CleanupPlan:
    """Concrete cleanup actions for one project root."""

    project_root: Path
    ces_dir: Path
    remove_ces_dir: bool
    gitignore_path: Path
    gitignore_before: str | None
    gitignore_after: str | None

    @property
    def updates_gitignore(self) -> bool:
        return (
            self.gitignore_before is not None
            and self.gitignore_after is not None
            and self.gitignore_before != self.gitignore_after
        )

    @property
    def has_actions(self) -> bool:
        return self.remove_ces_dir or self.updates_gitignore


def _remove_ces_gitignore_block(text: str) -> str:
    """Remove only the CES-managed gitignore block, preserving user-authored lines."""
    lines = text.splitlines()
    output: list[str] = []
    index = 0
    changed = False
    while index < len(lines):
        if lines[index].strip() != _CES_GITIGNORE_HEADER:
            output.append(lines[index])
            index += 1
            continue
        probe = index + 1
        while probe < len(lines) and lines[probe].strip() in _CES_GITIGNORE_ENTRIES:
            probe += 1
        if probe > index + 1:
            changed = True
            if probe < len(lines) and lines[probe].strip() == "":
                probe += 1
            index = probe
            continue
        output.append(lines[index])
        index += 1
    if not changed:
        return text
    rendered = "\n".join(output).rstrip()
    return f"{rendered}\n" if rendered else ""


def build_cleanup_plan(project_root: Path) -> CleanupPlan:
    """Return the cleanup plan without mutating the project."""
    resolved = project_root.resolve()
    ces_dir = resolved / ".ces"
    if ces_dir.is_symlink() or ces_dir.exists():
        validate_ces_state_dir(resolved, ces_dir)
    gitignore_path = resolved / ".gitignore"
    if gitignore_path.is_symlink():
        raise ValueError(
            "Refusing to clean a symlinked .gitignore. Replace the symlink with a regular project-local "
            ".gitignore before running `ces cleanup --yes`."
        )
    before = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else None
    after = _remove_ces_gitignore_block(before) if before is not None else None
    return CleanupPlan(
        project_root=resolved,
        ces_dir=ces_dir,
        remove_ces_dir=ces_dir.exists(),
        gitignore_path=gitignore_path,
        gitignore_before=before,
        gitignore_after=after,
    )


def _render_plan(plan: CleanupPlan, *, dry_run: bool) -> str:
    lines = [f"Project root: {plan.project_root}", ""]
    if not plan.has_actions:
        lines.append("No CES local state or CES-managed .gitignore block found.")
        return "\n".join(lines)
    lines.append("Planned actions:" if dry_run else "Completed actions:")
    if plan.remove_ces_dir:
        lines.append(f"- Remove local CES state directory: {plan.ces_dir}")
    if plan.updates_gitignore:
        lines.append(f"- Remove only the CES-managed block from: {plan.gitignore_path}")
    if dry_run:
        apply_command = f"ces cleanup --project-root {quote(str(plan.project_root))} --yes"
        lines.extend(["", f"Run `{apply_command}` to apply these local cleanup actions."])
    else:
        lines.extend(["", "Review `git status` if .gitignore was tracked in this repo."])
    return "\n".join(lines)


def cleanup_project(
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Repo/CES project root to clean; defaults to cwd/.ces discovery.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Apply cleanup. Without --yes, cleanup is a dry-run preview.",
    ),
) -> None:
    """Preview or remove local CES state from a project.

    This command only targets CES-managed local artifacts: `.ces/` and the
    `.gitignore` block headed `# CES local state and generated artifacts`. It
    is a dry-run unless `--yes` is passed. It does not uninstall the Python
    package, remove user-authored files, or follow symlinked `.ces`/`.gitignore`
    paths outside the project.
    """
    try:
        root = find_project_root(project_root) if project_root is not None else find_project_root()
    except typer.BadParameter:
        root = (project_root or Path.cwd()).resolve()
    try:
        plan = build_cleanup_plan(root)
    except ValueError as exc:
        console.print(Panel(str(exc), title="[red]Security Error[/red]", border_style="red"))
        raise typer.Exit(code=1) from exc
    if not yes:
        console.print(
            Panel(_render_plan(plan, dry_run=True), title="[cyan]Cleanup Preview[/cyan]", border_style="cyan")
        )
        return
    if plan.remove_ces_dir:
        shutil.rmtree(plan.ces_dir)
    if plan.updates_gitignore and plan.gitignore_after is not None:
        plan.gitignore_path.write_text(plan.gitignore_after, encoding="utf-8")
    console.print(
        Panel(_render_plan(plan, dry_run=False), title="[green]Cleanup Complete[/green]", border_style="green")
    )
