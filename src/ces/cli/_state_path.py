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


def validate_ces_state_path(project_root: Path, state_path: Path) -> None:
    """Fail closed if a CES state file or directory can escape the project.

    ``validate_ces_state_dir`` protects the top-level ``.ces`` directory. Write
    paths also need this stricter check because a real ``.ces`` directory can
    still contain symlinked children such as ``.ces/brownfield`` or
    ``.ces/baseline`` that redirect writes outside the project.
    """
    ces_dir = project_root / ".ces"
    validate_ces_state_dir(project_root, ces_dir)

    resolved_project = project_root.resolve()
    resolved_state = state_path.resolve(strict=False)
    try:
        resolved_state.relative_to(resolved_project)
    except ValueError as exc:
        raise ValueError("Refusing to use CES state path outside the project root.") from exc

    current = ces_dir
    target_parent = state_path if state_path.exists() else state_path.parent
    while True:
        if current.exists() and current.is_symlink():
            raise ValueError(f"Refusing to use symlinked CES state path: {current}")
        if current == target_parent:
            break
        try:
            current = current / target_parent.relative_to(current).parts[0]
        except (IndexError, ValueError):
            break


def has_safe_ces_state_dir(project_root: Path) -> bool:
    """Return true only when ``project_root/.ces`` is a real in-root directory."""
    ces_dir = project_root / ".ces"
    if ces_dir.is_symlink():
        validate_ces_state_dir(project_root, ces_dir)
    if not ces_dir.exists():
        return False
    validate_ces_state_dir(project_root, ces_dir)
    return ces_dir.is_dir()
