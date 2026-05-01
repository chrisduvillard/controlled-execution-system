"""Coverage sensor pack.

Parses coverage data (coverage.json or .coverage SQLite) from the project
root and reports line/branch coverage percentages as structured findings.
Does not require affected_files -- reads coverage data from project root.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

from ces.harness.models.sensor_result import SensorFinding
from ces.harness.sensors.base import BaseSensor


class CoverageSensor(BaseSensor):
    """Coverage sensor pack -- reports test-coverage metrics.

    Sensor ID: test_coverage
    Sensor Pack: test_coverage

    Reads ``coverage.json`` (preferred) from ``context["project_root"]``.
    Reports line coverage percentage and branch coverage if available.
    Gracefully skips when no coverage data exists.
    """

    def __init__(self) -> None:
        super().__init__(sensor_id="test_coverage", sensor_pack="test_coverage")

    async def _execute(self, context: dict) -> tuple[bool, float, str]:
        project_root: str = context.get("project_root", "")

        if not project_root:
            self._mark_skipped("No project_root in context")
            return (True, 1.0, "No project root provided; skipping coverage check")

        root = Path(project_root)

        # Try coverage.json first (produced by `coverage json`)
        coverage_json = root / "coverage.json"
        if coverage_json.is_file():
            return self._parse_coverage_json(coverage_json)

        # No coverage data found
        self._findings.append(
            SensorFinding(
                category="missing_artifact",
                severity="high",
                location="coverage.json",
                message="Required coverage artifact is missing: coverage.json",
                suggestion="Run tests with coverage and generate coverage.json before claiming completion",
            )
        )
        return (
            False,
            0.0,
            "No coverage data found; run 'coverage json' to generate coverage.json",
        )

    def _parse_coverage_json(self, path: Path) -> tuple[bool, float, str]:
        """Parse coverage.json and produce findings."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            self._findings.append(
                SensorFinding(
                    category="coverage_error",
                    severity="medium",
                    location=str(path),
                    message=f"Failed to parse coverage.json: {exc}",
                    suggestion="Regenerate coverage data with 'coverage json'",
                )
            )
            return (False, 0.5, f"Failed to parse coverage.json: {exc}")

        totals = data.get("totals", {})
        line_pct = totals.get("percent_covered", 0.0)
        branch_pct = totals.get("percent_covered_branches")
        num_statements = totals.get("num_statements", 0)
        missing = totals.get("missing_lines", 0)

        # Determine severity based on coverage level
        if line_pct < 60:
            severity: str = "high"
        elif line_pct < 90:
            severity = "medium"
        else:
            severity = "info"

        msg = f"Line coverage: {line_pct:.1f}% ({num_statements} statements, {missing} missing)"
        if branch_pct is not None:
            msg += f", Branch coverage: {branch_pct:.1f}%"

        self._findings.append(
            SensorFinding(
                category="coverage_report",
                severity=severity,
                location="",
                message=msg,
                suggestion="Increase test coverage to meet the 90% target" if line_pct < 90 else "Coverage target met",
            )
        )

        # Score: normalize coverage percentage to 0.0-1.0
        score = min(1.0, max(0.0, line_pct / 100.0))
        passed = line_pct >= 90  # Minimum passing threshold matches repo/product gate

        details = msg
        return (passed, score, details)


class TestCoverageSensor(CoverageSensor):
    """Deprecated alias for :class:`CoverageSensor`.

    The original class was named ``TestCoverageSensor``, which collided with
    pytest's class collection (any class starting with ``Test`` is treated as a
    test case). The ``__test__ = False`` workaround silenced the warning but
    obscured intent. The canonical name is now :class:`CoverageSensor`; this
    subclass remains for one minor-release cycle so external consumers of
    ``ces.harness.sensors`` keep importing successfully. Scheduled for removal
    in 0.2.x.
    """

    # Keep the pytest-collection escape hatch: pytest still sees a class
    # whose name starts with ``Test`` and would try to instantiate it.
    __test__ = False

    def __init__(self) -> None:
        warnings.warn(
            "TestCoverageSensor is deprecated; use CoverageSensor instead. "
            "The deprecated alias will be removed in 0.2.x.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__()
