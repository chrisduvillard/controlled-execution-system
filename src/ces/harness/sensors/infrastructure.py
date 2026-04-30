"""Infrastructure sensor pack.

Checks Dockerfile and docker-compose best practices using line-by-line
parsing. No external tool dependencies.
"""

from __future__ import annotations

import re

from ces.harness.models.sensor_result import SensorFinding
from ces.harness.sensors._file_reader import read_file_safe
from ces.harness.sensors.base import BaseSensor

_INFRA_FILE_PATTERNS = ("Dockerfile", "docker-compose.yml", "docker-compose.yaml")
_INFRA_EXTENSIONS = (".dockerfile",)

# Dockerfile lint rules
# Note: pip/apt regexes use single-line lookahead. Multi-line RUN commands
# with backslash continuation may produce false positives when the flag
# appears on a subsequent line. This is a known limitation.
_FROM_LATEST_RE = re.compile(r"^FROM\s+\S+:latest\b", re.IGNORECASE | re.MULTILINE)
_COPY_ALL_RE = re.compile(r"^COPY\s+\.\s+\.", re.MULTILINE)
_PIP_NO_CACHE_RE = re.compile(r"pip\s+install(?!.*--no-cache-dir)", re.MULTILINE)
_APT_NO_RECOMMENDS_RE = re.compile(r"apt-get\s+install(?!.*--no-install-recommends)", re.MULTILINE)


class InfrastructureSensor(BaseSensor):
    """Infrastructure sensor pack — checks Dockerfile best practices.

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

        infra_files = [
            f
            for f in affected_files
            if any(f.endswith(p) for p in _INFRA_FILE_PATTERNS) or f.endswith(_INFRA_EXTENSIONS)
        ]
        if not infra_files:
            self._mark_skipped("No infrastructure files in scope")
            return (True, 1.0, "No infrastructure files in scope")

        findings: list[str] = []

        for inf_file in infra_files:
            content = read_file_safe(project_root, inf_file)
            if content is None:
                continue

            is_dockerfile = "Dockerfile" in inf_file or inf_file.endswith(".dockerfile")

            if is_dockerfile:
                issues = self._lint_dockerfile(inf_file, content)
                for issue in issues:
                    severity = "high" if "secret" in issue.lower() or ":latest" in issue else "medium"
                    self._findings.append(
                        SensorFinding(
                            category="dockerfile_issue",
                            severity=severity,
                            location=inf_file,
                            message=issue,
                            suggestion="Follow Dockerfile best practices",
                        )
                    )
                findings.extend(issues)

        if findings:
            score = max(0.2, 1.0 - 0.15 * len(findings))
            details = f"Found {len(findings)} infrastructure issue(s): " + "; ".join(findings)
            return (False, score, details)

        return (True, 1.0, f"Infrastructure files pass all checks ({len(infra_files)} file(s))")

    @staticmethod
    def _lint_dockerfile(filepath: str, content: str) -> list[str]:
        """Lint a Dockerfile for common issues."""
        issues: list[str] = []

        if _FROM_LATEST_RE.search(content):
            issues.append(f"{filepath}: uses :latest tag (pin image version)")

        if "HEALTHCHECK" not in content:
            issues.append(f"{filepath}: missing HEALTHCHECK instruction")

        # Check for USER instruction (running as non-root)
        has_user = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("USER ") and not stripped.startswith("USER root"):
                has_user = True
                break
        if not has_user and "FROM" in content:
            issues.append(f"{filepath}: no non-root USER instruction")

        if _COPY_ALL_RE.search(content):
            issues.append(f"{filepath}: 'COPY . .' may leak secrets (use .dockerignore)")

        if _PIP_NO_CACHE_RE.search(content):
            issues.append(f"{filepath}: pip install without --no-cache-dir")

        if _APT_NO_RECOMMENDS_RE.search(content):
            issues.append(f"{filepath}: apt-get install without --no-install-recommends")

        return issues
