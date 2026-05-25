"""Shared project-local artifact path validation helpers."""

from __future__ import annotations

import re
from pathlib import Path

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def resolve_project_artifact_path(project_root: str | Path, artifact_path: str | Path) -> Path | None:
    """Return a safe project-local artifact path, or None when unsafe.

    Artifact evidence is operator-trust input. It must be relative to the
    project root, must not traverse outside that root, must not use Unix or
    Windows absolute syntax, and must not pass through symlinked path
    components. Missing but otherwise safe paths resolve to their intended
    project-local location so callers can distinguish unsafe from absent.
    """

    raw = str(artifact_path).strip()
    if not raw:
        return None
    normalized = raw.replace("\\", "/")
    if normalized.startswith("/") or _WINDOWS_DRIVE_RE.match(raw) or _WINDOWS_DRIVE_RE.match(normalized):
        return None
    parts = tuple(normalized.split("/"))
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None
    try:
        resolved_root = Path(project_root).resolve()
        candidate = resolved_root.joinpath(*parts)
        if _contains_symlink(candidate, resolved_root):
            return None
        resolved_candidate = candidate.resolve(strict=False)
        resolved_candidate.relative_to(resolved_root)
    except (OSError, ValueError):
        return None
    return resolved_candidate


def project_artifact_exists(project_root: str | Path, artifact_path: str | Path) -> bool:
    """Return True only for an existing safe project-local artifact path."""

    resolved = resolve_project_artifact_path(project_root, artifact_path)
    return resolved is not None and resolved.exists()


def _contains_symlink(candidate: Path, resolved_root: Path) -> bool:
    """Return True when any existing path component under root is a symlink."""

    try:
        relative_parts = candidate.relative_to(resolved_root).parts
    except ValueError:
        return True
    current = resolved_root
    for part in relative_parts:
        current = current / part
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
    return False
