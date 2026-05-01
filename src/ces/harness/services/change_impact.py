"""Deterministic change-impact helpers for evidence policy."""

from __future__ import annotations

PUBLIC_BEHAVIOR_PREFIXES = (
    "src/ces/cli/",
    "src/ces/execution/",
    "src/ces/control/models/",
    "src/ces/harness/models/",
)
PUBLIC_DOC_PATHS = ("README.md", "docs/", "CHANGELOG", "CHANGELOG.md")
API_SERVICE_MARKERS = ("/api/", "/services/", "_cmd.py", "src/ces/cli/")


def _norm(path: str) -> str:
    return path.replace("\\", "/")


def detects_public_behavior_impact(changed_files: list[str] | tuple[str, ...]) -> bool:
    """Return True when paths likely affect user-facing or public contracts."""
    return any(_norm(path).startswith(PUBLIC_BEHAVIOR_PREFIXES) for path in changed_files)


def has_docs_evidence(changed_files: list[str] | tuple[str, ...]) -> bool:
    """Return True when changed files include maintained docs evidence."""
    return any(_norm(path).startswith(PUBLIC_DOC_PATHS) for path in changed_files)


def detects_docs_impact(
    changed_files: list[str] | tuple[str, ...],
    docs_evidence: list[str] | tuple[str, ...],
) -> bool:
    """Return True when public behavior changed without docs evidence."""
    return detects_public_behavior_impact(changed_files) and not has_docs_evidence(docs_evidence)


def build_observability_acceptance_template(changed_files: list[str] | tuple[str, ...]) -> str:
    """Return a short checklist for service/API changes, or an empty string."""
    if not any(any(marker in _norm(path) for marker in API_SERVICE_MARKERS) for path in changed_files):
        return ""
    return (
        "Observability acceptance: name the logging, metric, status output, or error message "
        "that lets an operator detect failure; include the command or artifact that verifies it."
    )
