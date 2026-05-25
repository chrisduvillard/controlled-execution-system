"""Builder-flow evidence helpers kept out of the Typer command module."""

from __future__ import annotations

import posixpath
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from ces.execution.workspace_delta import WorkspaceDelta
from ces.harness.models.completion_claim import VerificationFinding, VerificationFindingKind, VerificationResult


def missing_completion_result() -> VerificationResult:
    """Build a blocking verifier result for a missing completion claim."""
    return VerificationResult(
        passed=False,
        findings=(
            VerificationFinding(
                kind=VerificationFindingKind.SCHEMA_VIOLATION,
                severity="critical",
                message="Agent did not emit a ces:completion block",
                hint="Re-run with a completion claim that lists files changed and evidence for every acceptance criterion.",
            ),
        ),
        sensor_results=(),
        timestamp=datetime.now(timezone.utc),
    )


def serialize_model(value: Any) -> Any:
    """Serialize Pydantic-like models for evidence packet content."""
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


_IGNORED_CES_RUNTIME_STATE_FILES = {
    ".ces/state.db",
    ".ces/state.db-shm",
    ".ces/state.db-wal",
    ".ces/state.db.lock",
    ".ces/latest-verification.json",
}
_IGNORED_CES_RUNTIME_STATE_PREFIXES = (".ces/artifacts/",)


def _is_ignored_ces_runtime_state(path: str) -> bool:
    """Return whether a changed `.ces` path is expected local runtime state.

    Product-scope enforcement should ignore noisy SQLite/report byproducts, but
    it must still surface governance-sensitive `.ces` mutations such as config,
    keys, policies, and profiles instead of treating the whole directory as a
    safe scratch area.
    """
    return path in _IGNORED_CES_RUNTIME_STATE_FILES or path.startswith(_IGNORED_CES_RUNTIME_STATE_PREFIXES)


def workspace_scope_violations(manifest: object, delta: WorkspaceDelta) -> tuple[str, ...]:
    """Return actual changed files outside manifest boundaries."""
    affected = tuple(_normalize_scope_path(str(item)) for item in (getattr(manifest, "affected_files", ()) or ()))
    forbidden = tuple(_normalize_scope_path(str(item)) for item in (getattr(manifest, "forbidden_files", ()) or ()))
    violations: list[str] = []
    for path in delta.changed_files:
        normalized = _normalize_scope_path(path)
        if any(fnmatch(path, pattern) or fnmatch(normalized, pattern) for pattern in forbidden):
            violations.append(path)
            continue
        if not _is_safe_relative_scope_path(path):
            violations.append(path)
            continue
        if _is_ignored_ces_runtime_state(normalized):
            continue
        if (
            affected
            and not any(fnmatch(normalized, pattern) for pattern in affected)
            and not _semantic_scope_allows(normalized, affected)
        ):
            violations.append(path)
    return tuple(violations)


_SOURCE_SCOPE_LABELS = {
    "api",
    "cli",
    "cli/api",
    "command line",
    "implementation",
    "runtime code",
    "source",
    "source code",
}
_SOURCE_EXTENSIONS = {
    ".cs",
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".swift",
    ".ts",
    ".tsx",
}


def _semantic_scope_allows(path: str, affected: tuple[str, ...]) -> bool:
    labels = {item.replace("\\", "/").strip().strip("'\"` ").casefold() for item in affected}
    if not labels.intersection(_SOURCE_SCOPE_LABELS):
        return False
    normalized = _normalize_scope_path(path)
    if not _is_safe_relative_scope_path(path):
        return False
    parts = tuple(part.casefold() for part in normalized.split("/"))
    if not normalized or normalized.startswith((".ces/", "tests/", "docs/")):
        return False
    if any(part in {"tests", "docs", "documentation", "examples"} for part in parts):
        return False
    return Path(normalized).suffix.casefold() in _SOURCE_EXTENSIONS


def _normalize_scope_path(path: str) -> str:
    return posixpath.normpath(path.replace("\\", "/").strip())


def _is_safe_relative_scope_path(path: str) -> bool:
    raw = path.replace("\\", "/").strip()
    if not raw or raw.startswith("/") or _looks_like_windows_absolute_path(raw):
        return False
    if any(part == ".." for part in raw.split("/")):
        return False
    normalized = posixpath.normpath(raw)
    return normalized not in {".", ".."} and not normalized.startswith("../")


def _looks_like_windows_absolute_path(path: str) -> bool:
    return len(path) >= 3 and path[1] == ":" and path[2] == "/" and path[0].isalpha()
