"""Unit tests for ``ces.harness.sensors.test_coverage``.

Covers both the parser (``_parse_coverage_json``) and the dispatch shell
(``_execute``). Before 0.1.3 the module was only covered at ~47 % — ironic
given it's the sensor powering CES's own dogfooding — so these tests
exercise the JSON shapes, severity bands, and error paths end-to-end.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ces.harness.sensors import test_coverage as coverage_sensor_module
from ces.harness.sensors.test_coverage import CoverageSensor


def test_test_coverage_sensor_is_marked_non_collectable() -> None:
    """Pytest must not treat the sensor class as a test class."""
    assert getattr(coverage_sensor_module.TestCoverageSensor, "__test__", True) is False


def _write_coverage_json(project_root: Path, totals: dict) -> Path:
    path = project_root / "coverage.json"
    path.write_text(json.dumps({"totals": totals}), encoding="utf-8")
    return path


class TestCoverageSensorExecuteDispatch:
    """`_execute` handles the three dispatch cases: no root, no file, parse."""

    @pytest.mark.asyncio
    async def test_missing_project_root_skips(self) -> None:
        sensor = CoverageSensor()
        passed, score, details = await sensor._execute({})
        assert passed is True
        assert score == 1.0
        assert "No project root" in details
        assert sensor._skipped_flag is True

    @pytest.mark.asyncio
    async def test_empty_project_root_skips(self) -> None:
        sensor = CoverageSensor()
        passed, score, details = await sensor._execute({"project_root": ""})
        assert passed is True
        assert "No project root" in details
        assert sensor._skipped_flag is True

    @pytest.mark.asyncio
    async def test_no_coverage_json_skips(self, tmp_path: Path) -> None:
        sensor = CoverageSensor()
        passed, score, details = await sensor._execute({"project_root": str(tmp_path)})
        assert passed is True
        assert score == 1.0
        assert "No coverage data" in details
        assert sensor._skipped_flag is True

    @pytest.mark.asyncio
    async def test_present_coverage_json_is_parsed(self, tmp_path: Path) -> None:
        _write_coverage_json(tmp_path, {"percent_covered": 91.0, "num_statements": 100, "missing_lines": 9})
        sensor = CoverageSensor()
        passed, score, details = await sensor._execute({"project_root": str(tmp_path)})
        assert passed is True
        assert score == pytest.approx(0.91)
        assert "91.0%" in details


class TestCoverageSensorSeverityBands:
    """Severity / score / pass-fail depend on the line-coverage percentage."""

    @pytest.mark.asyncio
    async def test_90_percent_is_info_and_target_met(self, tmp_path: Path) -> None:
        _write_coverage_json(tmp_path, {"percent_covered": 90.0, "num_statements": 100, "missing_lines": 10})
        sensor = CoverageSensor()
        passed, _, _ = await sensor._execute({"project_root": str(tmp_path)})
        assert passed is True
        (finding,) = sensor._findings
        assert finding.severity == "info"
        assert "Coverage target met" in finding.suggestion

    @pytest.mark.asyncio
    async def test_80_to_89_percent_is_info_with_increase_suggestion(self, tmp_path: Path) -> None:
        _write_coverage_json(tmp_path, {"percent_covered": 85.0, "num_statements": 100, "missing_lines": 15})
        sensor = CoverageSensor()
        await sensor._execute({"project_root": str(tmp_path)})
        (finding,) = sensor._findings
        assert finding.severity == "info"
        assert "Increase test coverage" in finding.suggestion

    @pytest.mark.asyncio
    async def test_60_to_79_percent_is_medium(self, tmp_path: Path) -> None:
        _write_coverage_json(tmp_path, {"percent_covered": 70.0, "num_statements": 100, "missing_lines": 30})
        sensor = CoverageSensor()
        passed, _, _ = await sensor._execute({"project_root": str(tmp_path)})
        assert passed is True  # 70 >= 60 passing threshold
        (finding,) = sensor._findings
        assert finding.severity == "medium"

    @pytest.mark.asyncio
    async def test_below_60_percent_is_high_and_fails(self, tmp_path: Path) -> None:
        _write_coverage_json(tmp_path, {"percent_covered": 55.0, "num_statements": 100, "missing_lines": 45})
        sensor = CoverageSensor()
        passed, score, _ = await sensor._execute({"project_root": str(tmp_path)})
        assert passed is False
        assert score == pytest.approx(0.55)
        (finding,) = sensor._findings
        assert finding.severity == "high"

    @pytest.mark.asyncio
    async def test_exactly_60_percent_is_passing_boundary(self, tmp_path: Path) -> None:
        """60.0 is the threshold: passing=True, severity=medium."""
        _write_coverage_json(tmp_path, {"percent_covered": 60.0, "num_statements": 100, "missing_lines": 40})
        sensor = CoverageSensor()
        passed, _, _ = await sensor._execute({"project_root": str(tmp_path)})
        assert passed is True
        assert sensor._findings[0].severity == "medium"


class TestCoverageSensorBranchReporting:
    """Optional branch coverage is appended to the finding message when present."""

    @pytest.mark.asyncio
    async def test_branch_coverage_included_when_present(self, tmp_path: Path) -> None:
        _write_coverage_json(
            tmp_path,
            {
                "percent_covered": 92.0,
                "percent_covered_branches": 85.4,
                "num_statements": 100,
                "missing_lines": 8,
            },
        )
        sensor = CoverageSensor()
        _, _, details = await sensor._execute({"project_root": str(tmp_path)})
        assert "Branch coverage: 85.4%" in details

    @pytest.mark.asyncio
    async def test_branch_coverage_omitted_when_absent(self, tmp_path: Path) -> None:
        _write_coverage_json(tmp_path, {"percent_covered": 92.0, "num_statements": 100, "missing_lines": 8})
        sensor = CoverageSensor()
        _, _, details = await sensor._execute({"project_root": str(tmp_path)})
        assert "Branch coverage" not in details


class TestCoverageSensorErrorHandling:
    """Malformed or unreadable coverage.json surfaces a structured finding."""

    @pytest.mark.asyncio
    async def test_malformed_json_produces_error_finding(self, tmp_path: Path) -> None:
        (tmp_path / "coverage.json").write_text("{not json", encoding="utf-8")
        sensor = CoverageSensor()
        passed, score, details = await sensor._execute({"project_root": str(tmp_path)})
        assert passed is False
        assert score == 0.5
        assert "Failed to parse coverage.json" in details
        (finding,) = sensor._findings
        assert finding.category == "coverage_error"
        assert finding.severity == "medium"
        assert "coverage json" in finding.suggestion

    @pytest.mark.asyncio
    async def test_unreadable_file_produces_error_finding(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulate OSError during read_text (permission denied, race)."""
        path = tmp_path / "coverage.json"
        path.write_text("{}", encoding="utf-8")

        def _raise_oserror(self: Path, *args, **kwargs) -> str:
            raise OSError("simulated read error")

        monkeypatch.setattr(Path, "read_text", _raise_oserror)
        sensor = CoverageSensor()
        passed, score, details = await sensor._execute({"project_root": str(tmp_path)})
        assert passed is False
        assert score == 0.5
        assert "Failed to parse coverage.json" in details

    @pytest.mark.asyncio
    async def test_empty_totals_defaults_to_zero_percent(self, tmp_path: Path) -> None:
        """A coverage.json missing the `totals` key defaults to 0 % (high severity, fail)."""
        (tmp_path / "coverage.json").write_text("{}", encoding="utf-8")
        sensor = CoverageSensor()
        passed, score, _ = await sensor._execute({"project_root": str(tmp_path)})
        assert passed is False
        assert score == 0.0
        (finding,) = sensor._findings
        assert finding.severity == "high"


class TestDeprecatedAliasBehaviour:
    """The 0.2.x removal candidate alias keeps working with a warning."""

    @pytest.mark.asyncio
    async def test_deprecated_alias_still_executes(self, tmp_path: Path) -> None:
        """Invoking the deprecated alias should still run the parser."""
        _write_coverage_json(tmp_path, {"percent_covered": 95.0, "num_statements": 100, "missing_lines": 5})
        with pytest.warns(DeprecationWarning, match="TestCoverageSensor is deprecated"):
            sensor = coverage_sensor_module.TestCoverageSensor()
        passed, score, _ = await sensor._execute({"project_root": str(tmp_path)})
        assert passed is True
        assert score == pytest.approx(0.95)
