"""Tests for risk-aware sensor policy evaluation."""

from __future__ import annotations

from datetime import datetime, timezone

from ces.harness.models.sensor_result import SensorFinding, SensorResult
from ces.harness.services.risk_sensor_policy import evaluate_sensor_policy
from ces.shared.enums import RiskTier


def _result(severity: str, *, sensor_id: str = "perf_check") -> SensorResult:
    return SensorResult(
        sensor_id=sensor_id,
        sensor_pack="performance",
        passed=True,
        score=0.7,
        details="warning",
        timestamp=datetime.now(timezone.utc),
        findings=(
            SensorFinding(
                category="sync_in_async",
                severity=severity,  # type: ignore[arg-type]
                location="src/app.py:1",
                message="sync call in async",
                suggestion="use async equivalent",
            ),
        ),
    )


def test_tier_a_blocks_medium_performance_findings() -> None:
    decision = evaluate_sensor_policy(RiskTier.A, [_result("medium")])

    assert decision.blocking is True
    assert decision.blocking_findings[0].severity == "medium"


def test_tier_c_keeps_performance_findings_advisory() -> None:
    decision = evaluate_sensor_policy(RiskTier.C, [_result("medium")])

    assert decision.blocking is False
    assert decision.advisory_findings[0].severity == "medium"
