"""Tests for sensor pack implementations and ALL_SENSORS registry.

Covers:
- Parametrized run() test for all 7 sensors
- ALL_SENSORS list has exactly 7 entries
- Each sensor in ALL_SENSORS is a valid class
- SensorResult correctness per sensor pack
"""

from __future__ import annotations

import pytest

from ces.harness.models.sensor_result import SensorResult
from ces.harness.sensors import (
    ALL_SENSORS,
    AccessibilitySensor,
    CoverageSensor,
    DependencySensor,
    InfrastructureSensor,
    MigrationSensor,
    PerformanceSensor,
    ResilienceSensor,
    SecuritySensor,
)

# ---------------------------------------------------------------------------
# ALL_SENSORS registry tests
# ---------------------------------------------------------------------------


def test_all_sensors_has_eight_entries() -> None:
    """ALL_SENSORS list must contain exactly 8 sensor classes."""
    assert len(ALL_SENSORS) == 8


def test_all_sensors_contains_expected_classes() -> None:
    """ALL_SENSORS must contain all 8 expected sensor classes."""
    expected = {
        SecuritySensor,
        PerformanceSensor,
        DependencySensor,
        MigrationSensor,
        InfrastructureSensor,
        AccessibilitySensor,
        ResilienceSensor,
        CoverageSensor,
    }
    assert set(ALL_SENSORS) == expected


def test_all_sensors_entries_are_classes() -> None:
    """Each entry in ALL_SENSORS must be a class (type), not an instance."""
    for entry in ALL_SENSORS:
        assert isinstance(entry, type), f"{entry} is not a class"


# ---------------------------------------------------------------------------
# Parametrized run() tests for all sensor packs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sensor_cls",
    ALL_SENSORS,
    ids=lambda cls: cls.__name__,
)
async def test_sensor_run_returns_sensor_result(sensor_cls: type) -> None:
    """Instantiate each sensor, call run(), verify SensorResult returned."""
    sensor = sensor_cls()
    result = await sensor.run({})
    assert isinstance(result, SensorResult)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sensor_cls",
    ALL_SENSORS,
    ids=lambda cls: cls.__name__,
)
async def test_sensor_run_result_has_correct_sensor_id(sensor_cls: type) -> None:
    """SensorResult.sensor_id must match the sensor's sensor_id property."""
    sensor = sensor_cls()
    result = await sensor.run({})
    assert result.sensor_id == sensor.sensor_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sensor_cls",
    ALL_SENSORS,
    ids=lambda cls: cls.__name__,
)
async def test_sensor_run_result_has_correct_sensor_pack(sensor_cls: type) -> None:
    """SensorResult.sensor_pack must match the sensor's sensor_pack property."""
    sensor = sensor_cls()
    result = await sensor.run({})
    assert result.sensor_pack == sensor.sensor_pack


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sensor_cls",
    ALL_SENSORS,
    ids=lambda cls: cls.__name__,
)
async def test_sensor_stub_passes(sensor_cls: type) -> None:
    """Stub sensors should all return passed=True."""
    sensor = sensor_cls()
    result = await sensor.run({})
    assert result.passed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sensor_cls",
    ALL_SENSORS,
    ids=lambda cls: cls.__name__,
)
async def test_sensor_stub_score_is_one(sensor_cls: type) -> None:
    """Stub sensors should all return score=1.0."""
    sensor = sensor_cls()
    result = await sensor.run({})
    assert result.score == 1.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sensor_cls",
    ALL_SENSORS,
    ids=lambda cls: cls.__name__,
)
async def test_sensor_stub_has_details(sensor_cls: type) -> None:
    """Stub sensors should return non-empty details string."""
    sensor = sensor_cls()
    result = await sensor.run({})
    assert isinstance(result.details, str)
    assert len(result.details) > 0


# ---------------------------------------------------------------------------
# CoverageSensor / TestCoverageSensor deprecation alias
# ---------------------------------------------------------------------------


def test_test_coverage_sensor_is_deprecated_alias_of_coverage_sensor() -> None:
    """TestCoverageSensor (the legacy name) must remain importable as a subclass
    of CoverageSensor and emit DeprecationWarning on instantiation."""
    from ces.harness.sensors import CoverageSensor as Canonical
    from ces.harness.sensors.test_coverage import TestCoverageSensor

    assert issubclass(TestCoverageSensor, Canonical)
    with pytest.warns(DeprecationWarning, match="TestCoverageSensor is deprecated"):
        legacy = TestCoverageSensor()
    # Must remain functionally identical to the canonical sensor
    assert legacy.sensor_id == "test_coverage"
    assert legacy.sensor_pack == "test_coverage"


def test_coverage_sensor_no_longer_needs_test_underscore_dunder() -> None:
    """The canonical CoverageSensor name no longer triggers pytest collection,
    so the __test__ = False escape hatch should not appear on it (it would mask
    a future regression where someone re-introduces a Test-prefixed class)."""
    from ces.harness.sensors import CoverageSensor

    # Either the attribute is missing entirely or it is True (pytest's default).
    # The escape hatch (False) is only required on the deprecated alias.
    assert getattr(CoverageSensor, "__test__", True) is True


def test_all_sensors_uses_canonical_coverage_sensor() -> None:
    """ALL_SENSORS must register CoverageSensor (not the deprecated alias) to
    avoid emitting DeprecationWarning on every sensor orchestrator construction."""
    from ces.harness.sensors import CoverageSensor
    from ces.harness.sensors.test_coverage import TestCoverageSensor

    assert CoverageSensor in ALL_SENSORS
    assert TestCoverageSensor not in ALL_SENSORS
