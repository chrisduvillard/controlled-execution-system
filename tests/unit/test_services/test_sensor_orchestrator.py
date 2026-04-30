"""Tests for SensorOrchestrator service.

Covers:
- SENS-01: run_all groups results by sensor pack and computes pass rates
- SENS-03: results_to_evidence_format produces correct dict structure
- Register sensor: sensor_count increases, TypeError for non-protocol
- run_pack: filters by pack_name correctly
- Kill switch: blocks run_all when halted
- Empty orchestrator: returns empty list
"""

from __future__ import annotations

from typing import Optional

import pytest

from ces.harness.models.sensor_result import SensorPackResult, SensorResult
from ces.harness.protocols import SensorProtocol
from ces.harness.sensors.base import BaseSensor
from ces.harness.sensors.security import SecuritySensor
from ces.harness.services.sensor_orchestrator import SensorOrchestrator

# ---------------------------------------------------------------------------
# Test helpers: mock sensors and kill switch
# ---------------------------------------------------------------------------


class _PassingSensor(BaseSensor):
    """Test sensor that always passes."""

    def __init__(self, sensor_id: str = "test_pass", sensor_pack: str = "test") -> None:
        super().__init__(sensor_id=sensor_id, sensor_pack=sensor_pack)

    async def _execute(self, context: dict) -> tuple[bool, float, str]:
        return (True, 1.0, "passed")


class _FailingSensor(BaseSensor):
    """Test sensor that always fails."""

    def __init__(self, sensor_id: str = "test_fail", sensor_pack: str = "test") -> None:
        super().__init__(sensor_id=sensor_id, sensor_pack=sensor_pack)

    async def _execute(self, context: dict) -> tuple[bool, float, str]:
        return (False, 0.0, "failed")


class _MockKillSwitch:
    """Mock kill switch for testing."""

    def __init__(self, halted: bool = False) -> None:
        self._halted = halted

    def is_halted(self, activity_class: str) -> bool:
        return self._halted


class _MockAuditLedger:
    """Mock audit ledger that records events."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def append_event(self, **kwargs: object) -> None:
        self.events.append(dict(kwargs))


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


def test_register_sensor_increases_count() -> None:
    """Registering a sensor should increase sensor_count."""
    orch = SensorOrchestrator()
    assert orch.sensor_count == 0
    orch.register_sensor(SecuritySensor())
    assert orch.sensor_count == 1


def test_register_non_protocol_raises_type_error() -> None:
    """Registering an object that doesn't implement SensorProtocol raises TypeError."""
    orch = SensorOrchestrator()
    with pytest.raises(TypeError):
        orch.register_sensor("not a sensor")  # type: ignore[arg-type]


def test_register_multiple_sensors() -> None:
    """Registering multiple sensors with different IDs should add all."""
    orch = SensorOrchestrator()
    orch.register_sensor(_PassingSensor(sensor_id="s1", sensor_pack="p1"))
    orch.register_sensor(_PassingSensor(sensor_id="s2", sensor_pack="p2"))
    assert orch.sensor_count == 2


def test_constructor_accepts_sensor_list() -> None:
    """Constructor with sensors list should register all of them."""
    sensors = [
        _PassingSensor(sensor_id="s1"),
        _PassingSensor(sensor_id="s2"),
    ]
    orch = SensorOrchestrator(sensors=sensors)
    assert orch.sensor_count == 2


# ---------------------------------------------------------------------------
# run_all tests (SENS-01)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_all_groups_by_pack() -> None:
    """run_all should group results by sensor_pack and return SensorPackResult per pack."""
    s1 = _PassingSensor(sensor_id="s1", sensor_pack="pack_a")
    s2 = _PassingSensor(sensor_id="s2", sensor_pack="pack_b")
    orch = SensorOrchestrator(sensors=[s1, s2])

    results = await orch.run_all({})
    assert len(results) == 2
    pack_names = {r.pack_name for r in results}
    assert pack_names == {"pack_a", "pack_b"}


@pytest.mark.asyncio
async def test_run_all_computes_pass_rate() -> None:
    """run_all should compute correct pass_rate with mix of passing/failing sensors."""
    s_pass = _PassingSensor(sensor_id="s_pass", sensor_pack="mixed")
    s_fail = _FailingSensor(sensor_id="s_fail", sensor_pack="mixed")
    orch = SensorOrchestrator(sensors=[s_pass, s_fail])

    results = await orch.run_all({})
    assert len(results) == 1
    pack_result = results[0]
    assert pack_result.pack_name == "mixed"
    assert pack_result.pass_rate == pytest.approx(0.5)
    assert pack_result.all_passed is False


@pytest.mark.asyncio
async def test_run_all_all_passed_true_when_all_pass() -> None:
    """run_all should set all_passed=True when every sensor in pack passes."""
    s1 = _PassingSensor(sensor_id="s1", sensor_pack="good")
    s2 = _PassingSensor(sensor_id="s2", sensor_pack="good")
    orch = SensorOrchestrator(sensors=[s1, s2])

    results = await orch.run_all({})
    assert len(results) == 1
    assert results[0].all_passed is True
    assert results[0].pass_rate == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_run_all_returns_sensor_pack_result_types() -> None:
    """run_all should return list of SensorPackResult instances."""
    orch = SensorOrchestrator(sensors=[SecuritySensor()])
    results = await orch.run_all({})
    assert all(isinstance(r, SensorPackResult) for r in results)


# ---------------------------------------------------------------------------
# run_pack tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_pack_filters_correctly() -> None:
    """run_pack should only run sensors in the specified pack."""
    s1 = _PassingSensor(sensor_id="s1", sensor_pack="target")
    s2 = _PassingSensor(sensor_id="s2", sensor_pack="other")
    orch = SensorOrchestrator(sensors=[s1, s2])

    result = await orch.run_pack("target", {})
    assert result.pack_name == "target"
    assert len(result.results) == 1
    assert result.results[0].sensor_id == "s1"


@pytest.mark.asyncio
async def test_run_pack_empty_when_no_match() -> None:
    """run_pack with non-existent pack name returns empty results."""
    s1 = _PassingSensor(sensor_id="s1", sensor_pack="other")
    orch = SensorOrchestrator(sensors=[s1])

    result = await orch.run_pack("nonexistent", {})
    assert result.pack_name == "nonexistent"
    assert len(result.results) == 0


# ---------------------------------------------------------------------------
# results_to_evidence_format tests (SENS-03)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_results_to_evidence_format_structure() -> None:
    """results_to_evidence_format should produce dict with sensor_packs key."""
    orch = SensorOrchestrator(sensors=[SecuritySensor()])
    pack_results = await orch.run_all({})
    evidence = orch.results_to_evidence_format(pack_results)

    assert "sensor_packs" in evidence
    assert isinstance(evidence["sensor_packs"], list)
    assert len(evidence["sensor_packs"]) == 1

    pack_entry = evidence["sensor_packs"][0]
    assert "pack_name" in pack_entry
    assert "pass_rate" in pack_entry
    assert "all_passed" in pack_entry
    assert "results" in pack_entry


@pytest.mark.asyncio
async def test_results_to_evidence_format_values() -> None:
    """Evidence format entries should contain correct values from pack results."""
    orch = SensorOrchestrator(sensors=[SecuritySensor()])
    pack_results = await orch.run_all({})
    evidence = orch.results_to_evidence_format(pack_results)

    pack_entry = evidence["sensor_packs"][0]
    assert pack_entry["pack_name"] == "security"
    assert pack_entry["pass_rate"] == pytest.approx(1.0)
    assert pack_entry["all_passed"] is True
    assert len(pack_entry["results"]) == 1


# ---------------------------------------------------------------------------
# Kill switch tests (T-03-13)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kill_switch_blocks_run_all() -> None:
    """When kill switch is halted for task_issuance, run_all should raise."""
    ks = _MockKillSwitch(halted=True)
    orch = SensorOrchestrator(sensors=[SecuritySensor()], kill_switch=ks)

    with pytest.raises(RuntimeError, match="[Kk]ill switch"):
        await orch.run_all({})


@pytest.mark.asyncio
async def test_kill_switch_not_halted_allows_run() -> None:
    """When kill switch is not halted, run_all should execute normally."""
    ks = _MockKillSwitch(halted=False)
    orch = SensorOrchestrator(sensors=[SecuritySensor()], kill_switch=ks)

    results = await orch.run_all({})
    assert len(results) == 1


# ---------------------------------------------------------------------------
# Empty orchestrator tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_orchestrator_returns_empty() -> None:
    """Orchestrator with no sensors returns empty list from run_all."""
    orch = SensorOrchestrator()
    results = await orch.run_all({})
    assert results == []


# ---------------------------------------------------------------------------
# Audit ledger integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_ledger_logs_sensor_run() -> None:
    """After run_all completes, audit ledger should record a sensor run event."""
    audit = _MockAuditLedger()
    orch = SensorOrchestrator(
        sensors=[SecuritySensor()],
        audit_ledger=audit,
    )
    await orch.run_all({})
    assert len(audit.events) >= 1
