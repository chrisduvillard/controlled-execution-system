"""Tests for deterministic sensor artifact policy."""

from __future__ import annotations

import json

import pytest

from ces.harness.sensors.completion_gate import LintSensor, TestPassSensor, TypeCheckSensor
from ces.harness.sensors.test_coverage import CoverageSensor


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sensor, expected_detail",
    [
        (TestPassSensor(), "pytest-results.json"),
        (LintSensor(), "ruff-report.json"),
        (TypeCheckSensor(), "mypy-report.txt"),
    ],
)
async def test_missing_configured_command_artifacts_fail(sensor, expected_detail, tmp_path) -> None:
    result = await sensor.run({"project_root": str(tmp_path)})

    assert result.passed is False
    assert result.skipped is False
    assert expected_detail in result.details
    assert result.findings
    assert result.findings[0].category == "missing_artifact"


@pytest.mark.asyncio
async def test_missing_coverage_artifact_fails_when_sensor_is_configured(tmp_path) -> None:
    result = await CoverageSensor().run({"project_root": str(tmp_path)})

    assert result.passed is False
    assert result.skipped is False
    assert "coverage.json" in result.details
    assert result.findings[0].category == "missing_artifact"


@pytest.mark.asyncio
async def test_coverage_below_ninety_percent_fails(tmp_path) -> None:
    (tmp_path / "coverage.json").write_text(
        json.dumps(
            {
                "totals": {
                    "percent_covered": 89.9,
                    "percent_covered_branches": 91.0,
                    "num_statements": 100,
                    "missing_lines": 10,
                }
            }
        ),
        encoding="utf-8",
    )

    result = await CoverageSensor().run({"project_root": str(tmp_path)})

    assert result.passed is False
    assert result.findings[0].severity == "medium"


@pytest.mark.asyncio
async def test_coverage_at_ninety_percent_passes(tmp_path) -> None:
    (tmp_path / "coverage.json").write_text(
        json.dumps(
            {
                "totals": {
                    "percent_covered": 90.0,
                    "percent_covered_branches": 90.0,
                    "num_statements": 100,
                    "missing_lines": 10,
                }
            }
        ),
        encoding="utf-8",
    )

    result = await CoverageSensor().run({"project_root": str(tmp_path)})

    assert result.passed is True
