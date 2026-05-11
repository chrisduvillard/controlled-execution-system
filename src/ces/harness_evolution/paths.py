"""Deterministic local paths for harness evolution artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

HARNESS_RELATIVE_ROOT = Path(".ces") / "harness"
INDEX_FILENAME = "index.json"
COMPONENT_DIR_NAMES = (
    "prompts",
    "tool_descriptions",
    "tool_policies",
    "middleware",
    "skills",
    "subagents",
    "memory",
    "runtime_profiles",
    "change_manifests",
    "analysis",
    "verdicts",
)
INDEX_SCHEMA = "ces.harness.index.v1"


@dataclass(frozen=True)
class HarnessPaths:
    """Resolved paths for the local `.ces/harness/` substrate."""

    project_root: Path
    root: Path
    index: Path
    prompts: Path
    tool_descriptions: Path
    tool_policies: Path
    middleware: Path
    skills: Path
    subagents: Path
    memory: Path
    runtime_profiles: Path
    change_manifests: Path
    analysis: Path
    verdicts: Path

    @classmethod
    def for_project(cls, project_root: Path) -> HarnessPaths:
        project_root = project_root.resolve()
        root = project_root / HARNESS_RELATIVE_ROOT
        kwargs = {name: root / name for name in COMPONENT_DIR_NAMES}
        return cls(
            project_root=project_root,
            root=root,
            index=root / INDEX_FILENAME,
            **kwargs,
        )

    @property
    def component_dirs(self) -> tuple[Path, ...]:
        return tuple(getattr(self, name) for name in COMPONENT_DIR_NAMES)


def _reject_symlink(path: Path) -> None:
    """Reject symlinks before creating or writing local harness paths."""

    if path.is_symlink():
        msg = f"Harness path must not be a symlink: {path}"
        raise ValueError(msg)


def _ensure_local_path(project_root: Path, path: Path) -> None:
    """Ensure ``path`` resolves inside ``project_root``."""

    resolved_root = project_root.resolve()
    resolved_path = path.resolve(strict=False)
    if not resolved_path.is_relative_to(resolved_root):
        msg = f"Harness path escapes project root: {path}"
        raise ValueError(msg)


def _validate_harness_layout_boundary(paths: HarnessPaths) -> None:
    """Reject symlink escapes for every existing harness path component."""

    ces_root = paths.project_root / ".ces"
    for path in (ces_root, paths.root, *paths.component_dirs, paths.index):
        _ensure_local_path(paths.project_root, path)
        if path.exists() or path.is_symlink():
            _reject_symlink(path)


def expected_layout(project_root: Path) -> tuple[Path, ...]:
    """Return every path that `ces harness init` would create or ensure."""

    paths = HarnessPaths.for_project(project_root)
    return (paths.index, *paths.component_dirs)


def relative_layout_entries(project_root: Path) -> list[str]:
    """Return human-friendly relative layout entries with directory suffixes."""

    paths = HarnessPaths.for_project(project_root)
    entries = [paths.index.relative_to(paths.project_root).as_posix()]
    entries.extend(f"{path.relative_to(paths.project_root).as_posix()}/" for path in paths.component_dirs)
    return entries


def create_harness_layout(project_root: Path) -> HarnessPaths:
    """Create the local harness directory layout and index file only."""

    paths = HarnessPaths.for_project(project_root)
    _validate_harness_layout_boundary(paths)
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.root.chmod(0o700)
    for directory in paths.component_dirs:
        _validate_harness_layout_boundary(paths)
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
    if not paths.index.exists():
        _validate_harness_layout_boundary(paths)
        payload = {
            "schema": INDEX_SCHEMA,
            "version": 1,
            "components": {},
            "changes": [],
            "note": "Local harness substrate only; no runtime prompt injection is enabled by this index.",
        }
        paths.index.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        paths.index.chmod(0o600)
    return paths
