"""Dependency sensor pack.

Checks dependency file hygiene: unpinned versions, missing lockfiles.
Parses requirements.txt and pyproject.toml using stdlib only.
"""

from __future__ import annotations

import re

from ces.harness.models.sensor_result import SensorFinding
from ces.harness.sensors._file_reader import read_file_safe
from ces.harness.sensors.base import BaseSensor

_DEP_FILE_PATTERNS = (
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-test.txt",
    "requirements_dev.txt",
    "requirements_test.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "Pipfile",
)

_LOCKFILE_NAMES = {
    "requirements.txt": {"requirements.lock", "uv.lock", "poetry.lock"},
    "pyproject.toml": {"uv.lock", "poetry.lock", "pdm.lock"},
    "Pipfile": {"Pipfile.lock"},
}

# Pattern for version-pinned requirement lines (==, >=, <=, ~=, !=, >)
_PINNED_RE = re.compile(r"[><=!~]=")


class DependencySensor(BaseSensor):
    """Dependency sensor pack -- checks dependency file hygiene.

    Sensor ID: dep_audit
    Sensor Pack: dependency
    """

    def __init__(self) -> None:
        super().__init__(sensor_id="dep_audit", sensor_pack="dependency")

    async def _execute(self, context: dict) -> tuple[bool, float, str]:
        affected_files: list[str] = context.get("affected_files", [])
        project_root: str = context.get("project_root", "")

        if not affected_files:
            return (True, 1.0, "No files in scope for dependency audit")

        # Find dependency files in affected_files
        dep_files = [f for f in affected_files if any(f.endswith(p) for p in _DEP_FILE_PATTERNS)]
        if not dep_files:
            self._mark_skipped("No dependency files in scope")
            return (True, 1.0, "No dependency files in scope")

        findings: list[str] = []
        total_deps = 0
        unpinned_count = 0

        affected_set = set(affected_files)

        for dep_file in dep_files:
            # Lockfile drift check
            base_name = dep_file.rsplit("/", 1)[-1] if "/" in dep_file else dep_file
            expected_locks = _LOCKFILE_NAMES.get(base_name, set())
            if expected_locks and not any(any(af.endswith(lock) for af in affected_set) for lock in expected_locks):
                msg = f"{dep_file} modified but no lockfile update found"
                findings.append(msg)
                self._findings.append(
                    SensorFinding(
                        category="lockfile_drift",
                        severity="medium",
                        location=dep_file,
                        message=msg,
                        suggestion="Run package manager to update lockfile",
                    )
                )

            content = read_file_safe(project_root, dep_file)
            if content is None:
                continue

            base_dep = dep_file.rsplit("/", 1)[-1] if "/" in dep_file else dep_file
            if base_dep in (
                "requirements.txt",
                "requirements-dev.txt",
                "requirements-test.txt",
                "requirements_dev.txt",
                "requirements_test.txt",
            ):
                unpinned, total = self._check_requirements_txt(content)
                total_deps += total
                unpinned_count += unpinned
                if unpinned:
                    msg = f"{dep_file}: {unpinned}/{total} dependencies unpinned"
                    findings.append(msg)
                    self._findings.append(
                        SensorFinding(
                            category="unpinned_dependency",
                            severity="medium",
                            location=dep_file,
                            message=msg,
                            suggestion="Pin dependency versions for reproducible builds",
                        )
                    )

            elif dep_file.endswith("pyproject.toml"):
                unpinned, total = self._check_pyproject_toml(content)
                total_deps += total
                unpinned_count += unpinned
                if unpinned:
                    msg = f"{dep_file}: {unpinned}/{total} dependencies unpinned"
                    findings.append(msg)
                    self._findings.append(
                        SensorFinding(
                            category="unpinned_dependency",
                            severity="medium",
                            location=dep_file,
                            message=msg,
                            suggestion="Pin dependency versions for reproducible builds",
                        )
                    )

        if findings:
            score = max(0.3, 1.0 - (unpinned_count / max(total_deps, 1)) * 0.5)
            details = f"Found {len(findings)} issue(s): " + "; ".join(findings)
            return (False, score, details)

        return (True, 1.0, f"All dependencies properly managed ({total_deps} checked in {len(dep_files)} file(s))")

    @staticmethod
    def _check_requirements_txt(content: str) -> tuple[int, int]:
        """Check requirements.txt for unpinned deps. Returns (unpinned, total)."""
        unpinned = 0
        total = 0
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            total += 1
            if not _PINNED_RE.search(line):
                unpinned += 1
        return unpinned, total

    @staticmethod
    def _check_pyproject_toml(content: str) -> tuple[int, int]:
        """Check pyproject.toml dependencies for unpinned entries. Returns (unpinned, total)."""
        unpinned = 0
        total = 0
        in_deps = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("[") and "dependencies" in stripped.lower():
                in_deps = True
                continue
            if stripped.startswith("[") and in_deps:
                in_deps = False
                continue
            if in_deps and stripped.startswith('"'):
                total += 1
                # Extract the dependency string
                dep_str = stripped.strip('",')
                if not _PINNED_RE.search(dep_str):
                    unpinned += 1
        return unpinned, total
