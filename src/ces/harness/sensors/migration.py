"""Migration sensor pack.

Validates database migration files for safety: checks for downgrade methods,
empty downgrades, and destructive operations. Uses ast module for Python
migration file analysis.
"""

from __future__ import annotations

import ast

from ces.harness.models.sensor_result import SensorFinding
from ces.harness.sensors._file_reader import read_file_safe
from ces.harness.sensors.base import BaseSensor

_MIGRATION_PATH_PATTERNS = ("alembic/versions/", "migrations/versions/", "migrations/")
_DESTRUCTIVE_OPS = ("drop_table", "drop_column", "drop_index", "drop_constraint")


class MigrationSensor(BaseSensor):
    """Migration sensor pack — validates migration file safety.

    Sensor ID: migration_check
    Sensor Pack: migration
    """

    def __init__(self) -> None:
        super().__init__(sensor_id="migration_check", sensor_pack="migration")

    async def _execute(self, context: dict) -> tuple[bool, float, str]:
        affected_files: list[str] = context.get("affected_files", [])
        project_root: str = context.get("project_root", "")

        if not affected_files:
            return (True, 1.0, "No files in scope for migration check")

        # Find migration files
        migration_files = [
            f
            for f in affected_files
            if f.endswith(".py") and any(p in f.replace("\\", "/") for p in _MIGRATION_PATH_PATTERNS)
        ]
        if not migration_files:
            self._mark_skipped("No migration files in scope")
            return (True, 1.0, "No migration files in scope")

        findings: list[str] = []

        for mig_file in migration_files:
            content = read_file_safe(project_root, mig_file)
            if content is None:
                continue

            try:
                tree = ast.parse(content)
            except SyntaxError:
                findings.append(f"{mig_file}: unparseable Python file")
                self._findings.append(
                    SensorFinding(
                        category="migration_issue",
                        severity="high",
                        location=mig_file,
                        message=f"{mig_file}: unparseable Python file",
                        suggestion="Fix syntax errors in migration file",
                    )
                )
                continue

            has_upgrade = False
            has_downgrade = False
            downgrade_is_empty = False
            destructive_ops: list[str] = []

            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.FunctionDef):
                    if node.name == "upgrade":
                        has_upgrade = True
                        destructive_ops.extend(self._find_destructive_ops(node))
                    elif node.name == "downgrade":
                        has_downgrade = True
                        downgrade_is_empty = self._is_empty_body(node)

            if has_upgrade and not has_downgrade:
                msg = f"{mig_file}: missing downgrade() method"
                findings.append(msg)
                self._findings.append(
                    SensorFinding(
                        category="migration_issue",
                        severity="high",
                        location=mig_file,
                        message=msg,
                        suggestion="Add a downgrade() method for rollback safety",
                    )
                )
            elif has_downgrade and downgrade_is_empty:
                msg = f"{mig_file}: downgrade() body is empty (pass-only)"
                findings.append(msg)
                self._findings.append(
                    SensorFinding(
                        category="migration_issue",
                        severity="medium",
                        location=mig_file,
                        message=msg,
                        suggestion="Implement downgrade() to reverse the migration",
                    )
                )
            if destructive_ops:
                ops_str = ", ".join(destructive_ops)
                msg = f"{mig_file}: destructive operation(s) in upgrade: {ops_str}"
                findings.append(msg)
                self._findings.append(
                    SensorFinding(
                        category="migration_issue",
                        severity="high",
                        location=mig_file,
                        message=msg,
                        suggestion="Review destructive operations; ensure rollback is possible",
                    )
                )

        if findings:
            # Missing downgrade is severe; destructive ops are warnings
            has_missing = any("missing downgrade" in f for f in findings)
            score = 0.3 if has_missing else max(0.5, 1.0 - 0.15 * len(findings))
            details = f"Found {len(findings)} migration issue(s): " + "; ".join(findings)
            return (False, score, details)

        return (True, 1.0, f"All {len(migration_files)} migration(s) have downgrade methods")

    @staticmethod
    def _find_destructive_ops(func_node: ast.FunctionDef) -> list[str]:
        """Find destructive operations (drop_table, etc.) in a function."""
        ops: list[str] = []
        for node in ast.walk(func_node):
            if isinstance(node, ast.Attribute) and node.attr in _DESTRUCTIVE_OPS:
                ops.append(node.attr)
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in _DESTRUCTIVE_OPS:
                    ops.append(func.attr)
        return ops

    @staticmethod
    def _is_empty_body(func_node: ast.FunctionDef) -> bool:
        """Check if a function body is effectively empty (only pass, Ellipsis, or docstring)."""
        for stmt in func_node.body:
            if isinstance(stmt, ast.Pass):
                continue
            if isinstance(stmt, ast.Expr):
                if isinstance(stmt.value, ast.Constant):
                    # String constant (docstring) or Ellipsis
                    continue
            return False
        return True
