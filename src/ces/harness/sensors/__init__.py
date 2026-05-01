"""Harness plane sensor packs.

Re-exports all 8 engineering practice sensor pack implementations
and the ALL_SENSORS registry list.

Sensor packs:
    SecuritySensor: Security checks (vulnerability scans, secret detection)
    PerformanceSensor: Performance checks (benchmarks, resource usage)
    DependencySensor: Dependency checks (outdated packages, license compliance)
    MigrationSensor: Migration checks (schema diffs, rollback safety)
    InfrastructureSensor: Infrastructure checks (repo configuration hygiene)
    AccessibilitySensor: Accessibility checks (WCAG compliance, ARIA validation)
    ResilienceSensor: Resilience checks (retry logic, circuit breakers)
    CoverageSensor: Test-coverage checks (line/branch coverage metrics)

Note: ``TestCoverageSensor`` is exported as a deprecated alias of
``CoverageSensor`` for back-compat; new code should use ``CoverageSensor``.
"""

from ces.harness.sensors.accessibility import AccessibilitySensor
from ces.harness.sensors.base import BaseSensor
from ces.harness.sensors.dependency import DependencySensor
from ces.harness.sensors.infrastructure import InfrastructureSensor
from ces.harness.sensors.migration import MigrationSensor
from ces.harness.sensors.performance import PerformanceSensor
from ces.harness.sensors.resilience import ResilienceSensor
from ces.harness.sensors.security import SecuritySensor
from ces.harness.sensors.test_coverage import CoverageSensor, TestCoverageSensor

ALL_SENSORS: list[type[BaseSensor]] = [
    SecuritySensor,
    PerformanceSensor,
    DependencySensor,
    MigrationSensor,
    InfrastructureSensor,
    AccessibilitySensor,
    ResilienceSensor,
    CoverageSensor,
]

__all__ = [
    "ALL_SENSORS",
    "AccessibilitySensor",
    "BaseSensor",
    "CoverageSensor",
    "DependencySensor",
    "InfrastructureSensor",
    "MigrationSensor",
    "PerformanceSensor",
    "ResilienceSensor",
    "SecuritySensor",
    "TestCoverageSensor",  # deprecated alias — use CoverageSensor in new code
]
