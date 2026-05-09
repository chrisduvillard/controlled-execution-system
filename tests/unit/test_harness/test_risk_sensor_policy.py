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


def test_missing_coverage_artifact_is_advisory_for_builder_policy() -> None:
    """RunLens dogfood: absent coverage.json should not block if coverage was not requested."""
    from datetime import datetime, timezone

    from ces.harness.models.sensor_result import SensorFinding, SensorResult
    from ces.harness.services.risk_sensor_policy import evaluate_sensor_policy
    from ces.shared.enums import RiskTier

    result = SensorResult(
        sensor_id="test_coverage",
        sensor_pack="test_coverage",
        passed=False,
        score=0.0,
        details="No coverage data found",
        findings=(
            SensorFinding(
                category="missing_artifact",
                severity="high",
                location="coverage.json",
                message="Required coverage artifact is missing: coverage.json",
                suggestion="Run coverage json",
            ),
        ),
        timestamp=datetime.now(timezone.utc),
    )

    decision = evaluate_sensor_policy(RiskTier.B, [result])

    assert decision.blocking is False
    assert decision.blocking_findings == ()
    assert len(decision.advisory_findings) == 1


def test_missing_artifact_blocks_only_when_profile_marks_required() -> None:
    finding = SensorFinding(
        category="missing_artifact",
        severity="high",
        location="ruff-report.json",
        message="Required verification artifact is missing: ruff-report.json",
        suggestion="Run ruff",
    )
    optional = SensorResult(
        sensor_id="lint",
        sensor_pack="completion_gate",
        passed=False,
        score=0.0,
        details="missing",
        findings=(finding,),
        timestamp=datetime.now(timezone.utc),
        configured=True,
        required=False,
        reason="ruff optional",
    )
    required = SensorResult(
        sensor_id="lint",
        sensor_pack="completion_gate",
        passed=False,
        score=0.0,
        details="missing",
        findings=(finding,),
        timestamp=datetime.now(timezone.utc),
        configured=True,
        required=True,
        reason="ruff required",
    )

    optional_decision = evaluate_sensor_policy(RiskTier.B, [optional])
    required_decision = evaluate_sensor_policy(RiskTier.B, [required])

    assert optional_decision.blocking is False
    assert required_decision.blocking is True
