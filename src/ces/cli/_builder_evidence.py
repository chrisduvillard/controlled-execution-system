"""Builder-flow evidence helpers kept out of the Typer command module."""

from __future__ import annotations

from datetime import datetime, timezone
from fnmatch import fnmatch
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


def workspace_scope_violations(manifest: object, delta: WorkspaceDelta) -> tuple[str, ...]:
    """Return actual changed files outside manifest boundaries."""
    affected = tuple(getattr(manifest, "affected_files", ()) or ())
    forbidden = tuple(getattr(manifest, "forbidden_files", ()) or ())
    violations: list[str] = []
    for path in delta.changed_files:
        if any(fnmatch(path, pattern) for pattern in forbidden):
            violations.append(path)
            continue
        if affected and not any(fnmatch(path, pattern) for pattern in affected):
            violations.append(path)
    return tuple(violations)
