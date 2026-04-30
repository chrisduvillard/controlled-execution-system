"""Resilience sensor pack.

Detects resilience anti-patterns via AST analysis: bare except clauses
and HTTP calls without timeout parameters.
Uses stdlib only (ast, pathlib).
"""

from __future__ import annotations

import ast

from ces.harness.models.sensor_result import SensorFinding
from ces.harness.sensors._file_reader import filter_by_extension, read_file_safe
from ces.harness.sensors.base import BaseSensor

# HTTP client modules and their call methods
_HTTP_MODULES = {"httpx", "requests"}
_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "request"}


class ResilienceSensor(BaseSensor):
    """Resilience sensor pack — detects resilience anti-patterns.

    Sensor ID: resilience_check
    Sensor Pack: resilience
    """

    def __init__(self) -> None:
        super().__init__(sensor_id="resilience_check", sensor_pack="resilience")

    async def _execute(self, context: dict) -> tuple[bool, float, str]:
        affected_files: list[str] = context.get("affected_files", [])
        project_root: str = context.get("project_root", "")

        if not affected_files:
            return (True, 1.0, "No files in scope for resilience check")

        py_files = filter_by_extension(affected_files, (".py",))
        if not py_files:
            self._mark_skipped("No Python files in scope")
            return (True, 1.0, "No Python files in scope for resilience check")

        findings: list[str] = []
        files_checked = 0

        for fpath in py_files:
            content = read_file_safe(project_root, fpath)
            if content is None:
                continue

            try:
                tree = ast.parse(content)
            except SyntaxError:
                continue

            files_checked += 1

            bare_except_issues = self._check_bare_except(fpath, tree)
            for issue in bare_except_issues:
                self._findings.append(
                    SensorFinding(
                        category="bare_except",
                        severity="medium",
                        location=issue.split(":")[0] + ":" + issue.split(":")[1] if ":" in issue else fpath,
                        message=issue,
                        suggestion="Specify exception type (e.g., except ValueError:)",
                    )
                )
            findings.extend(bare_except_issues)

            timeout_issues = self._check_missing_timeout(fpath, tree)
            for issue in timeout_issues:
                self._findings.append(
                    SensorFinding(
                        category="missing_timeout",
                        severity="high",
                        location=issue.split(":")[0] + ":" + issue.split(":")[1] if ":" in issue else fpath,
                        message=issue,
                        suggestion="Add timeout parameter to prevent indefinite blocking",
                    )
                )
            findings.extend(timeout_issues)

        if findings:
            score = max(0.3, 1.0 - 0.2 * len(findings))
            details = f"Found {len(findings)} resilience issue(s): " + "; ".join(findings)
            return (False, score, details)

        return (
            True,
            1.0,
            f"No resilience issues detected ({files_checked} file(s) checked)",
        )

    @staticmethod
    def _check_bare_except(filepath: str, tree: ast.Module) -> list[str]:
        """Detect bare except: clauses (no exception type specified)."""
        issues: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                issues.append(f"{filepath}:{node.lineno}: bare 'except:' clause (specify exception type)")
        return issues

    @staticmethod
    def _check_missing_timeout(filepath: str, tree: ast.Module) -> list[str]:
        """Detect HTTP client calls without timeout parameter."""
        issues: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr not in _HTTP_METHODS:
                continue
            # Check if the object is an HTTP module or known client
            if isinstance(func.value, ast.Name) and func.value.id in _HTTP_MODULES:
                has_timeout = any(kw.arg == "timeout" for kw in node.keywords)
                if not has_timeout:
                    issues.append(
                        f"{filepath}:{node.lineno}: '{func.value.id}.{func.attr}()' without timeout parameter"
                    )
        return issues
