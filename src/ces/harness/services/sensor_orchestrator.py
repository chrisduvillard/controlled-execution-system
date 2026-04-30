"""Sensor orchestrator service for running and aggregating sensor packs.

Implements:
- SENS-01: Runs all registered sensors and groups results by sensor pack
- SENS-02: Plugin-based sensor registration via SensorProtocol
- SENS-03: Maps sensor results into evidence packet format

The SensorOrchestrator accepts sensors implementing SensorProtocol,
runs them, and produces SensorPackResult aggregations suitable for
evidence synthesis.

Threat mitigations:
- T-03-11: isinstance check on registration; only SensorProtocol accepted
- T-03-13: Kill switch checked before sensor execution
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from ces.harness.models.sensor_result import SensorPackResult, SensorResult
from ces.harness.protocols import SensorProtocol
from ces.shared.enums import ActorType, EventType

if TYPE_CHECKING:
    from ces.control.services.kill_switch import KillSwitchProtocol


class SensorOrchestrator:
    """Orchestrator for running registered sensors and aggregating results.

    Accepts sensors implementing SensorProtocol, validates them at
    registration time, runs them individually or by pack, and maps
    results into evidence packet format.

    Args:
        sensors: Optional initial list of sensors to register.
        kill_switch: Optional kill switch protocol for halting checks.
        audit_ledger: Optional audit ledger for logging sensor run events.
    """

    def __init__(
        self,
        sensors: list[SensorProtocol] | None = None,
        kill_switch: KillSwitchProtocol | None = None,
        audit_ledger: object | None = None,
    ) -> None:
        self._sensors: dict[str, SensorProtocol] = {}
        self._kill_switch = kill_switch
        self._audit_ledger = audit_ledger

        if sensors is not None:
            for sensor in sensors:
                self.register_sensor(sensor)

    # ---- Registration (SENS-02, T-03-11) ----

    def register_sensor(self, sensor: SensorProtocol) -> None:
        """Register a sensor with the orchestrator.

        Validates that the sensor implements SensorProtocol via isinstance
        check (T-03-11 mitigation).

        Args:
            sensor: Sensor implementing SensorProtocol.

        Raises:
            TypeError: If sensor does not implement SensorProtocol.
        """
        if not isinstance(sensor, SensorProtocol):
            msg = f"sensor must implement SensorProtocol, got {type(sensor).__name__}"
            raise TypeError(msg)
        self._sensors[sensor.sensor_id] = sensor

    @property
    def sensor_count(self) -> int:
        """Number of registered sensors."""
        return len(self._sensors)

    # ---- Run all sensors (SENS-01) ----

    async def run_all(self, context: dict) -> list[SensorPackResult]:
        """Run all registered sensors and group results by sensor pack.

        Checks kill switch before executing. Groups sensor results by
        sensor_pack, computes pass_rate and all_passed for each pack.

        Args:
            context: Dictionary with execution context for sensors.

        Returns:
            List of SensorPackResult, one per unique sensor pack.

        Raises:
            RuntimeError: If kill switch is halted for task_issuance.
        """
        # T-03-13: Check kill switch before running
        if self._kill_switch is not None and self._kill_switch.is_halted("task_issuance"):
            msg = "Kill switch halted for task_issuance -- sensor execution blocked"
            raise RuntimeError(msg)

        if not self._sensors:
            return []

        # Run all sensors and collect results
        results: list[SensorResult] = []
        for sensor in self._sensors.values():
            result = await sensor.run(context)
            results.append(result)

        # Group by sensor_pack
        pack_results = self._group_by_pack(results)

        # Log to audit ledger
        if self._audit_ledger is not None:
            await self._audit_ledger.append_event(  # type: ignore[attr-defined]
                event_type=EventType.SENSOR_RUN,
                actor="sensor_orchestrator",
                actor_type=ActorType.CONTROL_PLANE,
                action_summary=(f"Sensor run complete: {len(pack_results)} packs, {len(results)} sensors"),
                decision="complete",
                rationale="All registered sensors executed",
            )

        return pack_results

    # ---- Run single pack ----

    async def run_pack(self, pack_name: str, context: dict) -> SensorPackResult:
        """Run only sensors belonging to a specific pack.

        Args:
            pack_name: Name of the sensor pack to run.
            context: Dictionary with execution context for sensors.

        Returns:
            SensorPackResult for the specified pack.
        """
        # Filter sensors by pack
        pack_sensors = [s for s in self._sensors.values() if s.sensor_pack == pack_name]

        results: list[SensorResult] = []
        for sensor in pack_sensors:
            result = await sensor.run(context)
            results.append(result)

        if not results:
            return SensorPackResult(
                pack_name=pack_name,
                results=(),
                pass_rate=0.0,
                all_passed=True,
            )

        pass_rate = sum(1 for r in results if r.passed) / len(results)
        all_passed = all(r.passed for r in results)

        return SensorPackResult(
            pack_name=pack_name,
            results=tuple(results),
            pass_rate=pass_rate,
            all_passed=all_passed,
        )

    # ---- Evidence format mapping (SENS-03) ----

    def results_to_evidence_format(self, pack_results: list[SensorPackResult]) -> dict:
        """Convert pack results to evidence packet format.

        Produces a dictionary suitable for inclusion in evidence packets.

        Args:
            pack_results: List of SensorPackResult from run_all or run_pack.

        Returns:
            Dict with "sensor_packs" key containing serialized results.
        """
        sensor_packs = []
        for pack in pack_results:
            pack_entry = {
                "pack_name": pack.pack_name,
                "pass_rate": pack.pass_rate,
                "all_passed": pack.all_passed,
                "results": [
                    {
                        "sensor_id": r.sensor_id,
                        "sensor_pack": r.sensor_pack,
                        "passed": r.passed,
                        "score": r.score,
                        "details": r.details,
                        "timestamp": r.timestamp.isoformat(),
                        "skipped": getattr(r, "skipped", False),
                        "skip_reason": getattr(r, "skip_reason", None),
                        "findings": [
                            {
                                "category": f.category,
                                "severity": f.severity,
                                "location": f.location,
                                "message": f.message,
                                "suggestion": f.suggestion,
                            }
                            for f in getattr(r, "findings", ())
                        ],
                    }
                    for r in pack.results
                ],
            }
            sensor_packs.append(pack_entry)

        return {"sensor_packs": sensor_packs}

    # ---- Internal helpers ----

    def _group_by_pack(self, results: list[SensorResult]) -> list[SensorPackResult]:
        """Group sensor results by sensor_pack and compute aggregates."""
        groups: dict[str, list[SensorResult]] = defaultdict(list)
        for result in results:
            groups[result.sensor_pack].append(result)

        pack_results: list[SensorPackResult] = []
        for pack_name, pack_sensors in groups.items():
            pass_rate = sum(1 for r in pack_sensors if r.passed) / len(pack_sensors)
            all_passed = all(r.passed for r in pack_sensors)
            pack_results.append(
                SensorPackResult(
                    pack_name=pack_name,
                    results=tuple(pack_sensors),
                    pass_rate=pass_rate,
                    all_passed=all_passed,
                )
            )

        return pack_results
