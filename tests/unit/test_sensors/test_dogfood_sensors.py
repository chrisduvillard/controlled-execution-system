"""Tests for SensorFinding model, extended SensorResult fields, BaseSensor findings,
and integration dogfood tests running all sensors against the CES repo.

Task 1 TDD: Verifies the restored SensorFinding model, extended SensorResult with
findings/skipped/skip_reason fields, and BaseSensor._findings population.

Task 2: Integration tests running all 8 sensors against the CES repository itself.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from ces.harness.models.sensor_result import SensorFinding, SensorResult
from ces.harness.sensors import ALL_SENSORS
from ces.harness.sensors.base import BaseSensor
from ces.harness.services.sensor_orchestrator import SensorOrchestrator

# ---------------------------------------------------------------------------
# Test 1: SensorFinding instantiation
# ---------------------------------------------------------------------------


class TestSensorFinding:
    """SensorFinding model tests."""

    def test_instantiation_with_all_fields(self) -> None:
        """SensorFinding can be instantiated with category, severity, location, message, suggestion."""
        finding = SensorFinding(
            category="secret_detected",
            severity="critical",
            location="src/app.py:42",
            message="AWS access key found",
            suggestion="Remove secret and rotate credentials",
        )
        assert finding.category == "secret_detected"
        assert finding.severity == "critical"
        assert finding.location == "src/app.py:42"
        assert finding.message == "AWS access key found"
        assert finding.suggestion == "Remove secret and rotate credentials"

    # Test 2: severity Literal validation
    @pytest.mark.parametrize("severity", ["critical", "high", "medium", "low", "info"])
    def test_severity_accepts_valid_values(self, severity: str) -> None:
        """SensorFinding.severity accepts all valid Literal values."""
        finding = SensorFinding(
            category="test",
            severity=severity,
            location="",
            message="test",
            suggestion="test",
        )
        assert finding.severity == severity

    def test_severity_rejects_invalid_value(self) -> None:
        """SensorFinding.severity rejects values outside the Literal type."""
        with pytest.raises(ValidationError):
            SensorFinding(
                category="test",
                severity="invalid_severity",
                location="",
                message="test",
                suggestion="test",
            )

    def test_frozen(self) -> None:
        """SensorFinding should be frozen (immutable)."""
        finding = SensorFinding(
            category="test",
            severity="info",
            location="",
            message="test",
            suggestion="test",
        )
        with pytest.raises(ValidationError):
            finding.category = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Test 3: SensorResult backward compatibility
# ---------------------------------------------------------------------------


class TestSensorResultExtended:
    """Extended SensorResult field tests."""

    def test_backward_compatible_no_findings(self) -> None:
        """SensorResult with findings=() is backward-compatible."""
        sr = SensorResult(
            sensor_id="sec-001",
            sensor_pack="security",
            passed=True,
            score=0.95,
            details="All checks passed",
            timestamp=datetime.now(timezone.utc),
        )
        assert sr.findings == ()
        assert sr.skipped is False
        assert sr.skip_reason is None

    # Test 4: SensorResult skipped support
    def test_skipped_with_reason(self) -> None:
        """SensorResult with skipped=True and skip_reason works."""
        sr = SensorResult(
            sensor_id="a11y_check",
            sensor_pack="accessibility",
            passed=True,
            score=1.0,
            details="Skipped",
            timestamp=datetime.now(timezone.utc),
            skipped=True,
            skip_reason="no files",
        )
        assert sr.skipped is True
        assert sr.skip_reason == "no files"

    def test_findings_tuple_populated(self) -> None:
        """SensorResult accepts a tuple of SensorFinding objects."""
        finding = SensorFinding(
            category="test",
            severity="info",
            location="file.py:1",
            message="test finding",
            suggestion="fix it",
        )
        sr = SensorResult(
            sensor_id="test",
            sensor_pack="test",
            passed=True,
            score=1.0,
            details="test",
            timestamp=datetime.now(timezone.utc),
            findings=(finding,),
        )
        assert len(sr.findings) == 1
        assert sr.findings[0].category == "test"


# ---------------------------------------------------------------------------
# Test 5: BaseSensor populates findings from _execute
# ---------------------------------------------------------------------------


class _FindingSensor(BaseSensor):
    """Test sensor that populates self._findings during _execute."""

    def __init__(self) -> None:
        super().__init__(sensor_id="test_finding", sensor_pack="test")

    async def _execute(self, context: dict) -> tuple[bool, float, str]:
        self._findings.append(
            SensorFinding(
                category="test_cat",
                severity="medium",
                location="test.py:10",
                message="Test finding message",
                suggestion="Fix this",
            )
        )
        return (True, 0.9, "Found 1 issue")


class _EmptyFindingSensor(BaseSensor):
    """Test sensor that produces no findings."""

    def __init__(self) -> None:
        super().__init__(sensor_id="test_empty", sensor_pack="test")

    async def _execute(self, context: dict) -> tuple[bool, float, str]:
        return (True, 1.0, "All clean")


class TestBaseSensorFindings:
    """BaseSensor._findings population tests."""

    @pytest.mark.asyncio
    async def test_findings_populated_in_result(self) -> None:
        """BaseSensor subclass that populates self._findings has those findings in SensorResult."""
        sensor = _FindingSensor()
        result = await sensor.run({})
        assert len(result.findings) == 1
        assert result.findings[0].category == "test_cat"
        assert result.findings[0].severity == "medium"

    @pytest.mark.asyncio
    async def test_findings_cleared_between_runs(self) -> None:
        """Findings should be cleared between consecutive run() calls."""
        sensor = _FindingSensor()
        result1 = await sensor.run({})
        assert len(result1.findings) == 1
        result2 = await sensor.run({})
        assert len(result2.findings) == 1  # Not 2

    @pytest.mark.asyncio
    async def test_empty_findings(self) -> None:
        """Sensor producing no findings has empty findings tuple."""
        sensor = _EmptyFindingSensor()
        result = await sensor.run({})
        assert result.findings == ()


# ---------------------------------------------------------------------------
# Integration: run all sensors against the CES repository itself
# ---------------------------------------------------------------------------


class TestDogfoodSensorsOnCESRepo:
    """Integration: run all sensors against the CES repository itself."""

    @pytest.fixture
    def ces_project_root(self) -> str:
        """Return the CES project root directory."""
        return str(Path(__file__).resolve().parents[3])

    @pytest.fixture
    def ces_python_files(self, ces_project_root: str) -> list[str]:
        """Return a sample of CES Python source files."""
        src = Path(ces_project_root) / "src"
        files = [str(p.relative_to(ces_project_root)) for p in src.rglob("*.py")]
        return files[:50]  # Cap at 50 for test speed

    @pytest.mark.asyncio
    async def test_all_sensors_fire_on_ces_repo(self, ces_project_root: str, ces_python_files: list[str]) -> None:
        """All 8 sensors fire and produce SensorResult with details != empty."""
        orchestrator = SensorOrchestrator()
        for sensor_cls in ALL_SENSORS:
            orchestrator.register_sensor(sensor_cls())
        assert orchestrator.sensor_count == 8

        context = {
            "affected_files": ces_python_files,
            "project_root": ces_project_root,
            "manifest_id": "test-dogfood",
            "description": "Self-dogfooding test",
        }
        pack_results = await orchestrator.run_all(context)
        assert len(pack_results) >= 7  # at least 7 unique packs

        for pack in pack_results:
            for result in pack.results:
                assert result.details, f"Sensor {result.sensor_id} produced empty details"

    @pytest.mark.asyncio
    async def test_fewer_than_3_false_positives(self, ces_project_root: str, ces_python_files: list[str]) -> None:
        """CES repo should produce fewer than 3 critical/high false-positive findings."""
        orchestrator = SensorOrchestrator()
        for sensor_cls in ALL_SENSORS:
            orchestrator.register_sensor(sensor_cls())
        context = {
            "affected_files": ces_python_files,
            "project_root": ces_project_root,
        }
        pack_results = await orchestrator.run_all(context)
        critical_findings = []
        for pack in pack_results:
            for result in pack.results:
                for finding in result.findings:
                    if finding.severity in ("critical", "high"):
                        critical_findings.append(finding)
        # Success criteria: fewer than 3 false positives
        assert len(critical_findings) < 3, (
            f"Found {len(critical_findings)} critical/high findings on CES repo "
            f"(expected <3): {[f.message for f in critical_findings]}"
        )
