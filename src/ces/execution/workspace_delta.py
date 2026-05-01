"""Capture file changes made during an agent runtime invocation."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ces.shared.base import CESBaseModel

_EXCLUDED_DIRS = {
    ".ces",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "build",
}


class WorkspaceDelta(CESBaseModel):
    """Created, modified, and deleted files between two snapshots."""

    created_files: tuple[str, ...] = ()
    modified_files: tuple[str, ...] = ()
    deleted_files: tuple[str, ...] = ()

    @property
    def changed_files(self) -> tuple[str, ...]:
        return tuple(sorted({*self.created_files, *self.modified_files, *self.deleted_files}))


class WorkspaceSnapshot(CESBaseModel):
    """Stable file hash snapshot for a project workspace."""

    root: str
    files: dict[str, str]

    @classmethod
    def capture(cls, root: Path) -> WorkspaceSnapshot:
        resolved = root.resolve()
        files: dict[str, str] = {}
        for path in resolved.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(resolved)
            if any(part in _EXCLUDED_DIRS for part in rel.parts):
                continue
            files[rel.as_posix()] = _hash_file(path)
        return cls(root=str(resolved), files=files)

    def diff(self, after: WorkspaceSnapshot) -> WorkspaceDelta:
        before_files = self.files
        after_files = after.files
        created = sorted(path for path in after_files if path not in before_files)
        deleted = sorted(path for path in before_files if path not in after_files)
        modified = sorted(
            path for path in after_files if path in before_files and after_files[path] != before_files[path]
        )
        return WorkspaceDelta(
            created_files=tuple(created),
            modified_files=tuple(modified),
            deleted_files=tuple(deleted),
        )


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
