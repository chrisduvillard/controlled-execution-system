"""Python interpreter resolution for generated and executed verification commands."""

from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path

PYTHON_EXECUTABLE_ALIASES = {"python", "python3"}


def python_invocation_for_project(project_root: Path) -> str:
    """Return a portable Python invocation for newly generated verification commands."""

    resolved_root = project_root.resolve()
    if (resolved_root / "uv.lock").is_file():
        return "uv run python"
    project_python = project_venv_python(resolved_root)
    if project_python is not None:
        return shlex.quote(project_python.relative_to(resolved_root).as_posix())
    return shlex.quote(sys.executable)


def resolve_python_argv(project_root: Path, argv: list[str]) -> tuple[str, ...]:
    """Resolve fragile Python aliases before launching verification commands."""

    if not argv:
        return ()
    executable = argv[0]
    if executable not in PYTHON_EXECUTABLE_ALIASES or shutil.which(executable) is not None:
        return tuple(argv)
    project_python = project_venv_python(project_root)
    if project_python is not None:
        return (str(project_python), *argv[1:])
    return (sys.executable, *argv[1:])


def rewrite_python_command_text(project_root: Path, command: str) -> str:
    """Rewrite bare Python command text to the resolved project invocation."""

    try:
        argv = shlex.split(command)
    except ValueError:
        return command
    if not argv or argv[0] not in PYTHON_EXECUTABLE_ALIASES:
        return command
    replacement = python_invocation_for_project(project_root)
    remainder = " ".join(shlex.quote(part) for part in argv[1:])
    return f"{replacement} {remainder}" if remainder else replacement


def project_venv_python(project_root: Path) -> Path | None:
    """Return the project-local Python interpreter when a conventional venv exists."""

    resolved_root = project_root.resolve()
    for relative in (Path(".venv") / "bin" / "python", Path(".venv") / "Scripts" / "python.exe"):
        candidate = resolved_root / relative
        try:
            _parents_stay_inside_project(resolved_root, candidate, relative)
        except (OSError, ValueError):
            continue
        if candidate.is_file() and _is_executable(candidate):
            return candidate
    return None


def _parents_stay_inside_project(project_root: Path, candidate: Path, relative: Path) -> None:
    current = project_root
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError("project-local Python parent must not be a symlink")
        current.resolve().relative_to(project_root)
    candidate.parent.resolve().relative_to(project_root)


def _is_executable(candidate: Path) -> bool:
    if os.name == "nt":
        return candidate.is_file()
    return os.access(candidate, os.X_OK)
