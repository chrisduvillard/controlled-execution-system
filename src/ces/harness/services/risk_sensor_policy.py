"""Risk-aware interpretation of deterministic sensor findings."""

from __future__ import annotations

from ces.harness.models.sensor_result import SensorFinding, SensorResult
from ces.shared.base import CESBaseModel
from ces.shared.enums import RiskTier

_BLOCKING_PACKS = {"performance", "resilience"}
_SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


class SensorPolicyDecision(CESBaseModel):
    """Blocking/advisory split for sensor findings."""

    blocking: bool
    blocking_findings: tuple[SensorFinding, ...] = ()
    advisory_findings: tuple[SensorFinding, ...] = ()


def evaluate_sensor_policy(risk_tier: RiskTier | str, sensor_results: list[SensorResult]) -> SensorPolicyDecision:
    """Promote sensor findings to blocking according to task risk."""
    risk = risk_tier.value if isinstance(risk_tier, RiskTier) else str(risk_tier)
    blocking: list[SensorFinding] = []
    advisory: list[SensorFinding] = []

    for result in sensor_results:
        for finding in result.findings:
            if _is_blocking(risk, result, finding):
                blocking.append(finding)
            else:
                advisory.append(finding)

    return SensorPolicyDecision(
        blocking=bool(blocking),
        blocking_findings=tuple(blocking),
        advisory_findings=tuple(advisory),
    )


def _is_blocking(risk: str, result: SensorResult, finding: SensorFinding) -> bool:
    if result.sensor_id == "test_coverage" and finding.category == "missing_artifact":
        # Coverage is advisory because coverage generation is not a universal
        # acceptance criterion for greenfield builds.
        return False
    if result.sensor_pack not in _BLOCKING_PACKS and result.sensor_id not in {"perf_check", "resilience_check"}:
        return not result.passed and _SEVERITY_RANK[finding.severity] >= _SEVERITY_RANK["high"]
    severity = _SEVERITY_RANK[finding.severity]
    if risk == RiskTier.A.value:
        return severity >= _SEVERITY_RANK["medium"]
    if risk == RiskTier.B.value:
        return severity >= _SEVERITY_RANK["high"]
    return severity >= _SEVERITY_RANK["critical"]
