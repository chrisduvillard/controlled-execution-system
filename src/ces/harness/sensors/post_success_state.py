"""Post-success state protection sensor.

This sensor detects protected evidence/state artifacts that were deleted or
modified after a successful verification point. It is intentionally passive:
callers provide snapshots of files that should remain stable once the harness
has observed a green state. A deliberate override may pass only when paired
with explicit revalidation, preventing quiet post-success drift.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from ces.harness.models.sensor_result import SensorFinding
from ces.harness.sensors.base import BaseSensor

_SHA256_RE = re.compile(r"^[A-Fa-f0-9]{64}$")


def _relative_to_root(project_root: Path, path: Path) -> str:
    """Return a POSIX relative path, rejecting paths outside the project root."""
    root = project_root.resolve()
    resolved = path.resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        msg = f"protected file is outside project root: {path}"
        raise ValueError(msg) from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_file_snapshot(project_root: Path, path: Path) -> dict[str, str]:
    """Build a protected-file snapshot from a file path.

    The snapshot is deliberately small and deterministic: relative POSIX path
    plus SHA-256 digest. Raw file contents are never embedded.
    """
    if not path.is_file():
        msg = f"protected file does not exist: {path}"
        raise FileNotFoundError(msg)
    return {"path": _relative_to_root(project_root, path), "sha256": _sha256_file(path)}


class PostSuccessStateSensor(BaseSensor):
    """Detect protected evidence/state artifacts mutated after success."""

    def __init__(self) -> None:
        super().__init__(sensor_id="post_success_state", sensor_pack="harness_evolution")

    async def _execute(self, context: dict) -> tuple[bool, float, str]:
        root_raw = context.get("project_root", "")
        snapshots = context.get("post_success_protected_files", ()) or ()
        if not root_raw:
            self._mark_skipped("No project_root in context")
            return (True, 1.0, "No project root provided; skipping post-success state check")
        if not snapshots:
            self._mark_skipped("No post-success protected files in context")
            return (True, 1.0, "No protected post-success files provided; skipping state check")

        project_root = Path(root_raw).resolve()
        drift_findings = self._find_drift(project_root, snapshots)
        if not drift_findings:
            return (True, 1.0, f"{len(snapshots)} protected files unchanged")

        invalid_findings = [finding for finding in drift_findings if finding.category == "invalid_snapshot"]
        protected_drift_findings = [
            finding for finding in drift_findings if finding.category == "post_success_state_drift"
        ]
        if invalid_findings:
            self._findings.extend(invalid_findings)
            if protected_drift_findings:
                self._findings.extend(protected_drift_findings)
            return (False, 0.0, "Invalid post-success protected file snapshot")

        override = context.get("post_success_state_override") is True
        revalidated = context.get("post_success_revalidated") is True
        if override and revalidated:
            self._findings.extend(
                SensorFinding(
                    category="post_success_state_override",
                    severity="medium",
                    location=finding.location,
                    message=f"Post-success drift intentionally overridden after revalidation: {finding.message}",
                    suggestion="Ensure the new green evidence is archived before completing the task",
                )
                for finding in protected_drift_findings
            )
            return (True, 1.0, f"{len(protected_drift_findings)} protected changes overridden after revalidation")

        if override and not revalidated:
            self._findings.append(
                SensorFinding(
                    category="override_requires_revalidation",
                    severity="critical",
                    location="",
                    message="Post-success state override was requested without explicit revalidation",
                    suggestion="Re-run validation and set post_success_revalidated only after green evidence is regenerated",
                )
            )
            self._findings.extend(drift_findings)
            return (False, 0.0, "Post-success override requires revalidation")

        self._findings.extend(drift_findings)
        unchanged_count = max(len(snapshots) - len(drift_findings), 0)
        score = unchanged_count / len(snapshots) if snapshots else 0.0
        return (False, score, f"{len(drift_findings)} protected files changed after successful verification")

    def _find_drift(self, project_root: Path, snapshots: Any) -> list[SensorFinding]:
        findings: list[SensorFinding] = []
        for snapshot in snapshots:
            if not isinstance(snapshot, dict):
                findings.append(
                    SensorFinding(
                        category="invalid_snapshot",
                        severity="critical",
                        location="",
                        message="Protected file snapshot is not an object",
                        suggestion="Provide snapshots with path and sha256 fields",
                    )
                )
                continue

            rel_path = str(snapshot.get("path", ""))
            expected_sha = str(snapshot.get("sha256", ""))
            if Path(rel_path).is_absolute():
                findings.append(
                    SensorFinding(
                        category="invalid_snapshot",
                        severity="critical",
                        location=rel_path,
                        message="Protected file snapshot path must be project-relative",
                        suggestion="Use project-relative protected file paths only",
                    )
                )
                continue
            if not rel_path or not expected_sha:
                findings.append(
                    SensorFinding(
                        category="invalid_snapshot",
                        severity="critical",
                        location=rel_path,
                        message="Protected file snapshot is missing path or sha256",
                        suggestion="Recreate the protected file snapshot from the verified artifact",
                    )
                )
                continue
            if _SHA256_RE.fullmatch(expected_sha) is None:
                findings.append(
                    SensorFinding(
                        category="invalid_snapshot",
                        severity="critical",
                        location=rel_path,
                        message="Protected file snapshot sha256 is not a valid SHA-256 hex digest",
                        suggestion="Recreate the protected file snapshot from the verified artifact",
                    )
                )
                continue

            target = (project_root / rel_path).resolve()
            try:
                target.relative_to(project_root)
            except ValueError:
                findings.append(
                    SensorFinding(
                        category="invalid_snapshot",
                        severity="critical",
                        location=rel_path,
                        message="Protected file snapshot path escapes the project root",
                        suggestion="Use project-relative protected file paths only",
                    )
                )
                continue

            if not target.is_file():
                findings.append(
                    SensorFinding(
                        category="post_success_state_drift",
                        severity="critical",
                        location=rel_path,
                        message=f"Protected file was deleted after successful verification: {rel_path}",
                        suggestion="Restore the verified artifact or re-run validation before claiming completion",
                    )
                )
                continue

            actual_sha = _sha256_file(target)
            if actual_sha != expected_sha:
                findings.append(
                    SensorFinding(
                        category="post_success_state_drift",
                        severity="critical",
                        location=rel_path,
                        message=f"Protected file was modified after successful verification: {rel_path}",
                        suggestion="Re-run validation and regenerate green evidence for the modified artifact",
                    )
                )
        return findings
