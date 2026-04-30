"""Tests for sensor protocol compliance and BaseSensor behavior.

Covers:
- BaseSensor abstract class implements SensorProtocol
- All 7 sensor packs implement SensorProtocol (isinstance check)
- BaseSensor.run() returns SensorResult with correct fields
- sensor_id and sensor_pack properties return correct values
"""

from __future__ import annotations

import pytest

from ces.harness.models.sensor_result import SensorResult
from ces.harness.protocols import SensorProtocol
from ces.harness.sensors.accessibility import AccessibilitySensor
from ces.harness.sensors.base import BaseSensor
from ces.harness.sensors.dependency import DependencySensor
from ces.harness.sensors.infrastructure import InfrastructureSensor
from ces.harness.sensors.migration import MigrationSensor
from ces.harness.sensors.performance import PerformanceSensor
from ces.harness.sensors.resilience import ResilienceSensor
from ces.harness.sensors.security import SecuritySensor

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


ALL_SENSOR_CLASSES = [
    SecuritySensor,
    PerformanceSensor,
    DependencySensor,
    MigrationSensor,
    InfrastructureSensor,
    AccessibilitySensor,
    ResilienceSensor,
]


# ---------------------------------------------------------------------------
# Protocol compliance tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sensor_cls",
    ALL_SENSOR_CLASSES,
    ids=lambda cls: cls.__name__,
)
def test_sensor_implements_protocol(sensor_cls: type) -> None:
    """Each sensor class instance must pass isinstance(sensor, SensorProtocol)."""
    sensor = sensor_cls()
    assert isinstance(sensor, SensorProtocol)


@pytest.mark.parametrize(
    "sensor_cls",
    ALL_SENSOR_CLASSES,
    ids=lambda cls: cls.__name__,
)
def test_sensor_has_sensor_id_property(sensor_cls: type) -> None:
    """Each sensor must have a non-empty sensor_id string property."""
    sensor = sensor_cls()
    assert isinstance(sensor.sensor_id, str)
    assert len(sensor.sensor_id) > 0


@pytest.mark.parametrize(
    "sensor_cls",
    ALL_SENSOR_CLASSES,
    ids=lambda cls: cls.__name__,
)
def test_sensor_has_sensor_pack_property(sensor_cls: type) -> None:
    """Each sensor must have a non-empty sensor_pack string property."""
    sensor = sensor_cls()
    assert isinstance(sensor.sensor_pack, str)
    assert len(sensor.sensor_pack) > 0


# ---------------------------------------------------------------------------
# BaseSensor.run() behavior tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_base_sensor_run_returns_sensor_result() -> None:
    """BaseSensor.run() should wrap _execute output into a SensorResult."""
    sensor = SecuritySensor()
    result = await sensor.run({})
    assert isinstance(result, SensorResult)


@pytest.mark.asyncio
async def test_base_sensor_run_populates_sensor_id() -> None:
    """SensorResult from run() has the correct sensor_id."""
    sensor = SecuritySensor()
    result = await sensor.run({})
    assert result.sensor_id == sensor.sensor_id


@pytest.mark.asyncio
async def test_base_sensor_run_populates_sensor_pack() -> None:
    """SensorResult from run() has the correct sensor_pack."""
    sensor = SecuritySensor()
    result = await sensor.run({})
    assert result.sensor_pack == sensor.sensor_pack


@pytest.mark.asyncio
async def test_base_sensor_run_populates_timestamp() -> None:
    """SensorResult from run() has a non-None timestamp."""
    sensor = SecuritySensor()
    result = await sensor.run({})
    assert result.timestamp is not None


@pytest.mark.asyncio
async def test_base_sensor_run_score_in_range() -> None:
    """SensorResult score must be between 0.0 and 1.0."""
    sensor = SecuritySensor()
    result = await sensor.run({})
    assert 0.0 <= result.score <= 1.0


# ---------------------------------------------------------------------------
# sensor_id / sensor_pack expected values
# ---------------------------------------------------------------------------


EXPECTED_IDS = {
    SecuritySensor: ("security_scan", "security"),
    PerformanceSensor: ("perf_check", "performance"),
    DependencySensor: ("dep_audit", "dependency"),
    MigrationSensor: ("migration_check", "migration"),
    InfrastructureSensor: ("infra_check", "infrastructure"),
    AccessibilitySensor: ("a11y_check", "accessibility"),
    ResilienceSensor: ("resilience_check", "resilience"),
}


@pytest.mark.parametrize(
    ("sensor_cls", "expected_id", "expected_pack"),
    [(cls, eid, epack) for cls, (eid, epack) in EXPECTED_IDS.items()],
    ids=lambda x: x.__name__ if isinstance(x, type) else str(x),
)
def test_sensor_id_and_pack_values(sensor_cls: type, expected_id: str, expected_pack: str) -> None:
    """Each sensor must have the correct sensor_id and sensor_pack values."""
    sensor = sensor_cls()
    assert sensor.sensor_id == expected_id
    assert sensor.sensor_pack == expected_pack
