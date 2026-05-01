"""Local actor and CODEOWNERS helpers for advisory ownership surfacing."""

from __future__ import annotations

import fnmatch
import getpass
import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class CodeownersEntry:
    pattern: str
    owners: tuple[str, ...]


def resolve_actor() -> str:
    """Resolve the local human actor without requiring hosted identity."""
    explicit = os.environ.get("CES_ACTOR", "").strip()
    if explicit:
        return explicit
    for key in ("user.email", "user.name"):
        value = _git_config(key)
        if value:
            return value
    return getpass.getuser() or "cli-user"


def parse_codeowners(content: str) -> tuple[CodeownersEntry, ...]:
    """Parse CODEOWNERS content into structured entries."""
    entries: list[CodeownersEntry] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        pattern, *owners = line.split()
        if owners:
            entries.append(CodeownersEntry(pattern=pattern, owners=tuple(owners)))
    return tuple(entries)


def matching_codeowners(path: str, entries: tuple[CodeownersEntry, ...]) -> tuple[str, ...]:
    """Return owners for the last matching CODEOWNERS-style pattern."""
    normalized = path.replace("\\", "/")
    matched: tuple[str, ...] = ()
    for entry in entries:
        pattern = entry.pattern
        if _matches(pattern, normalized):
            matched = entry.owners
    return matched


def _matches(pattern: str, path: str) -> bool:
    if pattern.endswith("/"):
        return path.startswith(pattern)
    if "/" not in pattern:
        return fnmatch.fnmatch(path.rsplit("/", 1)[-1], pattern)
    return fnmatch.fnmatch(path, pattern)


def _git_config(key: str) -> str | None:
    git_binary = shutil.which("git")
    if git_binary is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - fixed git config query with internal key names only
            [git_binary, "config", "--get", key],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None
