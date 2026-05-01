"""Infrastructure sensor pack.

Checks repository infrastructure configuration using line-by-line parsing. No
external tool dependencies.
"""

from __future__ import annotations

import re

from ces.harness.models.sensor_result import SensorFinding
from ces.harness.sensors._file_reader import read_file_safe
from ces.harness.sensors.base import BaseSensor

_INFRA_FILE_PATTERNS = (
    ".github/workflows/",
    "pyproject.toml",
    "uv.lock",
)
_FLOATING_GITHUB_ACTION_RE = re.compile(r"uses:\s+[^@\s]+@(main|master|latest)\b", re.IGNORECASE)
_UNPINNED_PYTHON_RE = re.compile(r"python-version:\s*['\"]?(3|3\.x)['\"]?\s*$", re.IGNORECASE | re.MULTILINE)


class InfrastructureSensor(BaseSensor):
    """Infrastructure sensor pack for repo configuration hygiene.

    Sensor ID: infra_check
    Sensor Pack: infrastructure
    """

    def __init__(self) -> None:
        super().__init__(sensor_id="infra_check", sensor_pack="infrastructure")

    async def _execute(self, context: dict) -> tuple[bool, float, str]:
        affected_files: list[str] = context.get("affected_files", [])
        project_root: str = context.get("project_root", "")

        if not affected_files:
            return (True, 1.0, "No files in scope for infrastructure check")

        infra_files = [f for f in affected_files if any(f == p or f.startswith(p) for p in _INFRA_FILE_PATTERNS)]
        if not infra_files:
            self._mark_skipped("No infrastructure files in scope")
            return (True, 1.0, "No infrastructure files in scope")

        findings: list[str] = []

        for inf_file in infra_files:
            content = read_file_safe(project_root, inf_file)
            if content is None:
                continue

            issues = self._lint_infrastructure_file(inf_file, content)
            for issue in issues:
                self._findings.append(
                    SensorFinding(
                        category="infrastructure_issue",
                        severity="medium",
                        location=inf_file,
                        message=issue,
                        suggestion="Pin infrastructure configuration to explicit versions",
                    )
                )
            findings.extend(issues)

        if findings:
            score = max(0.2, 1.0 - 0.15 * len(findings))
            details = f"Found {len(findings)} infrastructure issue(s): " + "; ".join(findings)
            return (False, score, details)

        return (True, 1.0, f"Infrastructure files pass all checks ({len(infra_files)} file(s))")

    @staticmethod
    def _lint_infrastructure_file(filepath: str, content: str) -> list[str]:
        """Lint repository infrastructure files for common drift risks."""
        issues: list[str] = []

        if filepath.startswith(".github/workflows/"):
            if _FLOATING_GITHUB_ACTION_RE.search(content):
                issues.append(f"{filepath}: action reference uses a floating ref")
            if _UNPINNED_PYTHON_RE.search(content):
                issues.append(f"{filepath}: Python version is not pinned to a minor release")

        if filepath == "pyproject.toml" and "[project]" not in content:
            issues.append(f"{filepath}: missing [project] metadata")

        if filepath == "uv.lock" and "[[package]]" not in content:
            issues.append(f"{filepath}: lockfile has no package entries")

        return issues
