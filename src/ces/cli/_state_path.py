"""Validation helpers for CES local state paths."""

from __future__ import annotations

from pathlib import Path


def validate_ces_state_dir(project_root: Path, ces_dir: Path | None = None) -> None:
    """Fail closed if a project's ``.ces`` state directory can escape the root.

    This check is intentionally reusable outside ``ces init`` because project
    discovery and command bootstrap must not accept an already-existing
    symlinked ``.ces`` directory as trusted local state.
    """
    state_dir = ces_dir or project_root / ".ces"
    if state_dir.is_symlink():
        raise ValueError("Refusing to use symlinked .ces directory.")

    resolved_project = project_root.resolve()
    resolved_state = state_dir.resolve(strict=False)
    try:
        resolved_state.relative_to(resolved_project)
    except ValueError as exc:
        raise ValueError("Refusing to use .ces outside the project root.") from exc


def has_safe_ces_state_dir(project_root: Path) -> bool:
    """Return true only when ``project_root/.ces`` is a real in-root directory."""
    ces_dir = project_root / ".ces"
    if ces_dir.is_symlink():
        validate_ces_state_dir(project_root, ces_dir)
    if not ces_dir.exists():
        return False
    validate_ces_state_dir(project_root, ces_dir)
    return ces_dir.is_dir()
