"""Validation helpers for CES project-local state paths."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _project_absolute_path(project_root: Path, path: Path) -> Path:
    """Return ``path`` as an absolute project-local candidate path.

    Callers often pass either ``project_root / relative`` or just ``relative``.
    Preserve already-root-prefixed relative paths instead of prefixing the root a
    second time.
    """
    resolved_project = project_root.resolve()
    if path.is_absolute():
        return path
    if not project_root.is_absolute() and _parts_start_with(path.parts, project_root.parts):
        return Path.cwd() / path
    return resolved_project / path


def _parts_start_with(parts: tuple[str, ...], prefix: tuple[str, ...]) -> bool:
    return bool(prefix) and parts[: len(prefix)] == prefix


def validate_ces_state_dir(project_root: Path, ces_dir: Path | None = None) -> None:
    """Fail closed if a project's ``.ces`` state directory can escape the root.

    This check is intentionally reusable outside ``ces init`` because project
    discovery and command bootstrap must not accept an already-existing
    symlinked ``.ces`` directory as trusted local state.
    """
    resolved_project = project_root.resolve()
    state_dir = ces_dir if ces_dir is not None else resolved_project / ".ces"
    state_dir = _project_absolute_path(project_root, state_dir)
    if state_dir.is_symlink():
        raise ValueError("Refusing to use symlinked .ces directory.")

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
    resolved_project = project_root.resolve()
    state_path = _project_absolute_path(project_root, state_path)
    ces_dir = resolved_project / ".ces"
    validate_ces_state_dir(resolved_project, ces_dir)

    resolved_state = state_path.resolve(strict=False)
    try:
        resolved_state.relative_to(resolved_project)
    except ValueError as exc:
        raise ValueError("Refusing to use CES state path outside the project root.") from exc

    current = ces_dir
    target_parent = state_path if state_path.exists() or state_path.is_symlink() else state_path.parent
    while True:
        if current.is_symlink():
            raise ValueError(f"Refusing to use symlinked CES state path: {current}")
        if current == target_parent:
            break
        try:
            current = current / target_parent.relative_to(current).parts[0]
        except (IndexError, ValueError):
            break


def validate_project_path(project_root: Path, path: Path) -> None:
    """Fail closed if a project-generated path can escape ``project_root``.

    This is the sibling of ``validate_ces_state_path`` for generated files that
    intentionally live outside ``.ces`` such as docs artifacts. It rejects
    symlinked existing path components and destination files before callers
    create or replace content.
    """
    resolved_project = project_root.resolve()
    path = _project_absolute_path(project_root, path)
    resolved_path = path.resolve(strict=False)
    try:
        resolved_path.relative_to(resolved_project)
    except ValueError as exc:
        raise ValueError("Refusing to use project path outside the project root.") from exc

    relative = path.relative_to(resolved_project)
    current = resolved_project
    components = relative.parts
    target_components = components if path.exists() or path.is_symlink() else components[:-1]
    for part in target_components:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Refusing to use symlinked project path: {current}")
    if path.is_symlink():
        raise ValueError(f"Refusing to use symlinked project path: {path}")


def write_text_project_path(project_root: Path, path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Atomically write text to a validated project-local path.

    The pre/post validation pair catches pre-existing symlinks before directory
    creation and rejects symlinked parents or destination files before the final
    replace. ``os.replace`` replaces a checked destination path instead of
    following a destination symlink.
    """
    path = _project_absolute_path(project_root, path)
    validate_project_path(project_root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    validate_project_path(project_root, path)
    with tempfile.NamedTemporaryFile(
        "w", encoding=encoding, dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as handle:
        tmp_name = handle.name
        handle.write(content)
    os.replace(tmp_name, path)


def read_text_project_path(project_root: Path, path: Path, *, encoding: str = "utf-8") -> str:
    """Read text from a validated project-local path without following symlink escapes."""
    path = _project_absolute_path(project_root, path)
    validate_project_path(project_root, path)
    return path.read_text(encoding=encoding)


def has_safe_ces_state_dir(project_root: Path) -> bool:
    """Return true only when ``project_root/.ces`` is a real in-root directory."""
    ces_dir = project_root / ".ces"
    if ces_dir.is_symlink():
        validate_ces_state_dir(project_root, ces_dir)
    if not ces_dir.exists():
        return False
    validate_ces_state_dir(project_root, ces_dir)
    return ces_dir.is_dir()
