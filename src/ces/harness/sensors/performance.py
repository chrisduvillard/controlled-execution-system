"""Performance sensor pack.

Detects performance anti-patterns via AST analysis: nested loops (O(n^2)),
synchronous I/O in async functions, and global variable mutations.
Uses stdlib only (ast, pathlib).
"""

from __future__ import annotations

import ast

from ces.harness.models.sensor_result import SensorFinding
from ces.harness.sensors._file_reader import filter_by_extension, read_file_safe
from ces.harness.sensors.base import BaseSensor

# Sync I/O calls that should not appear inside async functions
_SYNC_IO_NAMES = {"open", "sleep"}
_SYNC_IO_ATTRS = {"get", "post", "put", "patch", "delete", "head", "options"}
_SYNC_IO_MODULES = {"requests", "urllib", "urllib3"}


class PerformanceSensor(BaseSensor):
    """Performance sensor pack — detects performance anti-patterns.

    Sensor ID: perf_check
    Sensor Pack: performance
    """

    def __init__(self) -> None:
        super().__init__(sensor_id="perf_check", sensor_pack="performance")

    async def _execute(self, context: dict) -> tuple[bool, float, str]:
        affected_files: list[str] = context.get("affected_files", [])
        project_root: str = context.get("project_root", "")

        if not affected_files:
            return (True, 1.0, "No files in scope for performance check")

        py_files = filter_by_extension(affected_files, (".py",))
        if not py_files:
            self._mark_skipped("No Python files in scope")
            return (True, 1.0, "No Python files in scope for performance check")

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
            nested = self._check_nested_loops(fpath, tree)
            for issue in nested:
                self._findings.append(
                    SensorFinding(
                        category="nested_loop",
                        severity="medium",
                        location=issue.split(":")[0] + ":" + issue.split(":")[1] if ":" in issue else fpath,
                        message=issue,
                        suggestion="Consider refactoring to reduce algorithmic complexity",
                    )
                )
            findings.extend(nested)

            sync_issues = self._check_sync_in_async(fpath, tree)
            for issue in sync_issues:
                self._findings.append(
                    SensorFinding(
                        category="sync_in_async",
                        severity="high",
                        location=issue.split(":")[0] + ":" + issue.split(":")[1] if ":" in issue else fpath,
                        message=issue,
                        suggestion="Use async equivalent (e.g., asyncio.sleep, httpx.AsyncClient)",
                    )
                )
            findings.extend(sync_issues)

            global_issues = self._check_global_usage(fpath, tree)
            for issue in global_issues:
                self._findings.append(
                    SensorFinding(
                        category="global_usage",
                        severity="low",
                        location=issue.split(":")[0] + ":" + issue.split(":")[1] if ":" in issue else fpath,
                        message=issue,
                        suggestion="Avoid global state; pass values as arguments or use dependency injection",
                    )
                )
            findings.extend(global_issues)

        if findings:
            score = max(0.5, 1.0 - 0.1 * len(findings))
            details = f"Found {len(findings)} performance warning(s): " + "; ".join(findings)
            # Performance issues are warnings, not hard failures
            return (True, score, details)

        return (
            True,
            1.0,
            f"No performance issues detected ({files_checked} file(s) checked)",
        )

    @staticmethod
    def _check_nested_loops(filepath: str, tree: ast.Module) -> list[str]:
        """Detect nested for-loops (O(n^2) patterns)."""
        issues: list[str] = []
        reported_inner: set[int] = set()  # Track inner loop node ids to avoid duplicates
        for node in ast.walk(tree):
            if isinstance(node, ast.For) and id(node) not in reported_inner:
                for child in ast.walk(node):
                    if child is node:
                        continue
                    if isinstance(child, ast.For):
                        issues.append(f"{filepath}:{node.lineno}: nested for-loop (potential O(n^2))")
                        reported_inner.add(id(child))
                        break  # One finding per outer loop
        return issues

    @staticmethod
    def _check_sync_in_async(filepath: str, tree: ast.Module) -> list[str]:
        """Detect synchronous I/O calls inside async functions."""
        issues: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        func = child.func
                        # time.sleep() but NOT asyncio.sleep()
                        if isinstance(func, ast.Attribute):
                            if (
                                func.attr in _SYNC_IO_NAMES
                                and isinstance(func.value, ast.Name)
                                and func.value.id not in ("asyncio", "aiofiles")
                            ):
                                issues.append(
                                    f"{filepath}:{child.lineno}: "
                                    f"sync call '{func.value.id}.{func.attr}' in async function '{node.name}'"
                                )
                            elif (
                                func.attr in _SYNC_IO_ATTRS
                                and isinstance(func.value, ast.Name)
                                and func.value.id in _SYNC_IO_MODULES
                            ):
                                issues.append(
                                    f"{filepath}:{child.lineno}: "
                                    f"sync HTTP '{func.value.id}.{func.attr}' in async function '{node.name}'"
                                )
                        elif isinstance(func, ast.Name) and func.id in _SYNC_IO_NAMES:
                            issues.append(
                                f"{filepath}:{child.lineno}: sync call '{func.id}()' in async function '{node.name}'"
                            )
        return issues

    @staticmethod
    def _check_global_usage(filepath: str, tree: ast.Module) -> list[str]:
        """Detect global keyword usage."""
        issues: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Global):
                issues.append(f"{filepath}:{node.lineno}: 'global' keyword usage")
        return issues
