"""Tests for CompletionVerifier (P1c) — the Completion Gate orchestrator.

Verify covers:
- Schema check (claim task_id matches manifest)
- Criterion-addressed check (every acceptance_criterion is in the claim)
- Scope check (files_changed within manifest.affected_files)
- Sensor execution (only sensors listed in manifest.verification_sensors run)
- Missing sensor finding (sensor_id in manifest is not in registry)
- Kill-switch guard
- Composed pass/fail invariants
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from ces.control.models.manifest import TaskManifest
from ces.harness.models.completion_claim import (
    CompletionClaim,
    CriterionEvidence,
    EvidenceKind,
    VerificationFindingKind,
)
from ces.harness.sensors.base import BaseSensor
from ces.harness.services.completion_verifier import CompletionVerifier
from ces.shared.enums import ArtifactStatus, BehaviorConfidence, ChangeClass, RiskTier

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _StubSensor(BaseSensor):
    """Sensor that returns the configured outcome and no findings."""

    def __init__(self, sensor_id: str, *, passed: bool = True) -> None:
        super().__init__(sensor_id=sensor_id, sensor_pack="completion_gate")
        self._stub_passed = passed

    async def _execute(self, context: dict) -> tuple[bool, float, str]:
        return (self._stub_passed, 1.0 if self._stub_passed else 0.0, f"{self.sensor_id} stub")


class _MockKillSwitch:
    def __init__(self, halted: bool = False) -> None:
        self._halted = halted

    def is_halted(self, activity_class: str) -> bool:
        return self._halted


def _make_manifest(**overrides: Any) -> TaskManifest:
    now = datetime.now(timezone.utc)
    base: dict[str, Any] = {
        "manifest_id": "MANIF-001",
        "description": "Test task",
        "risk_tier": RiskTier.B,
        "behavior_confidence": BehaviorConfidence.BC2,
        "change_class": ChangeClass.CLASS_2,
        "affected_files": ("src/auth/login.py", "src/auth/*.py"),
        "token_budget": 5000,
        "expires_at": now + timedelta(days=7),
        "version": 1,
        "status": ArtifactStatus.DRAFT,
        "owner": "system",
        "created_at": now,
        "last_confirmed": now,
        "acceptance_criteria": (),
        "verification_sensors": (),
    }
    base.update(overrides)
    return TaskManifest(**base)


def _make_claim(**overrides: Any) -> CompletionClaim:
    base: dict[str, Any] = {
        "task_id": "MANIF-001",
        "summary": "Did the work",
        "files_changed": ("src/auth/login.py",),
        "criteria_satisfied": (),
        "open_questions": (),
        "scope_deviations": (),
    }
    base.update(overrides)
    return CompletionClaim(**base)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestVerifierHappyPath:
    @pytest.mark.asyncio
    async def test_no_sensors_no_criteria_passes(self, tmp_path: Path) -> None:
        verifier = CompletionVerifier(sensors={})
        result = await verifier.verify(_make_manifest(), _make_claim(), tmp_path)
        assert result.passed is True
        assert result.findings == ()

    @pytest.mark.asyncio
    async def test_sensors_all_pass_yields_pass(self, tmp_path: Path) -> None:
        verifier = CompletionVerifier(sensors={"test_pass": _StubSensor("test_pass", passed=True)})
        manifest = _make_manifest(verification_sensors=("test_pass",))
        result = await verifier.verify(manifest, _make_claim(), tmp_path)
        assert result.passed is True
        assert len(result.sensor_results) == 1


# ---------------------------------------------------------------------------
# Schema / criterion checks
# ---------------------------------------------------------------------------


class TestVerifierSchemaChecks:
    @pytest.mark.asyncio
    async def test_claim_task_id_mismatch_fails(self, tmp_path: Path) -> None:
        verifier = CompletionVerifier(sensors={})
        manifest = _make_manifest(manifest_id="MANIF-001")
        claim = _make_claim(task_id="MANIF-999")  # wrong
        result = await verifier.verify(manifest, claim, tmp_path)
        assert result.passed is False
        assert any(f.kind == VerificationFindingKind.SCHEMA_VIOLATION for f in result.findings)

    @pytest.mark.asyncio
    async def test_unaddressed_criterion_fails(self, tmp_path: Path) -> None:
        verifier = CompletionVerifier(sensors={})
        manifest = _make_manifest(
            acceptance_criteria=("user can log in", "user can log out"),
        )
        claim = _make_claim(
            criteria_satisfied=(
                CriterionEvidence(
                    criterion="user can log in",
                    evidence="ran integration test; passed",
                    evidence_kind=EvidenceKind.COMMAND_OUTPUT,
                ),
            ),
        )
        result = await verifier.verify(manifest, claim, tmp_path)
        assert result.passed is False
        unaddressed = [f for f in result.findings if f.kind == VerificationFindingKind.CRITERION_UNADDRESSED]
        assert len(unaddressed) == 1
        assert unaddressed[0].related_criterion == "user can log out"

    @pytest.mark.asyncio
    async def test_all_criteria_addressed_passes(self, tmp_path: Path) -> None:
        verifier = CompletionVerifier(sensors={})
        manifest = _make_manifest(acceptance_criteria=("user can log in",))
        claim = _make_claim(
            criteria_satisfied=(
                CriterionEvidence(
                    criterion="user can log in",
                    evidence="ran login test; passed",
                    evidence_kind=EvidenceKind.COMMAND_OUTPUT,
                ),
            ),
        )
        result = await verifier.verify(manifest, claim, tmp_path)
        assert result.passed is True


# ---------------------------------------------------------------------------
# Scope check
# ---------------------------------------------------------------------------


class TestVerifierScopeCheck:
    @pytest.mark.asyncio
    async def test_in_scope_change_passes(self, tmp_path: Path) -> None:
        verifier = CompletionVerifier(sensors={})
        manifest = _make_manifest(affected_files=("src/auth/*.py",))
        claim = _make_claim(files_changed=("src/auth/login.py", "src/auth/logout.py"))
        result = await verifier.verify(manifest, claim, tmp_path)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_out_of_scope_change_fails(self, tmp_path: Path) -> None:
        verifier = CompletionVerifier(sensors={})
        manifest = _make_manifest(affected_files=("src/auth/*.py",))
        claim = _make_claim(files_changed=("src/auth/login.py", "src/payment/charge.py"))
        result = await verifier.verify(manifest, claim, tmp_path)
        assert result.passed is False
        scope = [f for f in result.findings if f.kind == VerificationFindingKind.SCOPE_VIOLATION]
        assert len(scope) == 1
        assert "src/payment/charge.py" in scope[0].message


# ---------------------------------------------------------------------------
# Sensor failures
# ---------------------------------------------------------------------------


class TestVerifierSensorFailures:
    @pytest.mark.asyncio
    async def test_failing_sensor_yields_finding(self, tmp_path: Path) -> None:
        verifier = CompletionVerifier(sensors={"test_pass": _StubSensor("test_pass", passed=False)})
        manifest = _make_manifest(verification_sensors=("test_pass",))
        result = await verifier.verify(manifest, _make_claim(), tmp_path)
        assert result.passed is False
        sensor_findings = [f for f in result.findings if f.kind == VerificationFindingKind.SENSOR_FAILURE]
        assert len(sensor_findings) == 1
        assert sensor_findings[0].related_sensor == "test_pass"

    @pytest.mark.asyncio
    async def test_missing_sensor_yields_finding(self, tmp_path: Path) -> None:
        verifier = CompletionVerifier(sensors={})  # registry is empty
        manifest = _make_manifest(verification_sensors=("test_pass",))
        result = await verifier.verify(manifest, _make_claim(), tmp_path)
        assert result.passed is False
        missing = [
            f
            for f in result.findings
            if f.kind == VerificationFindingKind.SCHEMA_VIOLATION and f.related_sensor == "test_pass"
        ]
        assert len(missing) == 1

    @pytest.mark.asyncio
    async def test_only_listed_sensors_run(self, tmp_path: Path) -> None:
        passing = _StubSensor("test_pass", passed=True)
        unrelated = _StubSensor("unrelated", passed=False)
        verifier = CompletionVerifier(sensors={"test_pass": passing, "unrelated": unrelated})
        manifest = _make_manifest(verification_sensors=("test_pass",))  # unrelated not listed
        result = await verifier.verify(manifest, _make_claim(), tmp_path)
        assert result.passed is True
        # Only one sensor result captured
        assert len(result.sensor_results) == 1
        assert result.sensor_results[0].sensor_id == "test_pass"


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


class TestVerifierKillSwitch:
    @pytest.mark.asyncio
    async def test_halted_kill_switch_raises(self, tmp_path: Path) -> None:
        verifier = CompletionVerifier(
            sensors={},
            kill_switch=_MockKillSwitch(halted=True),
        )
        with pytest.raises(RuntimeError, match="kill switch"):
            await verifier.verify(_make_manifest(), _make_claim(), tmp_path)

    @pytest.mark.asyncio
    async def test_unhalted_kill_switch_proceeds(self, tmp_path: Path) -> None:
        verifier = CompletionVerifier(
            sensors={},
            kill_switch=_MockKillSwitch(halted=False),
        )
        result = await verifier.verify(_make_manifest(), _make_claim(), tmp_path)
        assert result.passed is True
