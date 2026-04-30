"""CompletionVerifier — Completion Gate orchestrator (P1c).

Closes the "ask if done, ask to finish, verify" loop by deterministically
verifying an agent's :class:`CompletionClaim` against:

1. Schema   — claim.task_id matches manifest.manifest_id.
2. Criteria — every manifest.acceptance_criterion appears in claim.criteria_satisfied.
3. Scope    — every file in claim.files_changed is allowed by manifest.affected_files.
4. Sensors  — every sensor_id in manifest.verification_sensors resolves and passes.

The result is a :class:`VerificationResult` that the caller (workflow engine
glue) uses to choose ``verification_passed`` or ``verification_failed``. On
failure the findings drive the repair-prompt loop (P2).

This service is deterministic and contains no LLM calls (LLM-05).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from ces.control.services.policy_engine import PolicyEngine
from ces.harness.models.completion_claim import (
    CompletionClaim,
    VerificationFinding,
    VerificationFindingKind,
    VerificationResult,
)
from ces.harness.models.sensor_result import SensorResult
from ces.harness.sensors.base import BaseSensor

if TYPE_CHECKING:
    from ces.control.models.manifest import TaskManifest
    from ces.control.services.kill_switch import KillSwitchProtocol


class CompletionVerifier:
    """Deterministic gate between agent claim-of-done and review.

    Args:
        sensors: Registry mapping sensor_id -> BaseSensor. The verifier runs
            only the sensors listed in ``manifest.verification_sensors``;
            unlisted sensors in the registry are ignored.
        kill_switch: Optional kill-switch protocol. When halted on
            ``task_issuance``, ``verify`` raises RuntimeError.
    """

    _ACTIVITY_CLASS = "task_issuance"

    def __init__(
        self,
        sensors: dict[str, BaseSensor],
        kill_switch: KillSwitchProtocol | None = None,
    ) -> None:
        self._sensors = dict(sensors)
        self._kill_switch = kill_switch

    async def verify(
        self,
        manifest: TaskManifest,
        claim: CompletionClaim,
        project_root: Path,
    ) -> VerificationResult:
        """Run the full verification pipeline and return a structured result."""
        if self._kill_switch is not None and self._kill_switch.is_halted(self._ACTIVITY_CLASS):
            msg = f"Verification blocked: kill switch halted for {self._ACTIVITY_CLASS}"
            raise RuntimeError(msg)

        findings: list[VerificationFinding] = []

        findings.extend(_check_schema(manifest, claim))
        findings.extend(_check_criteria(manifest, claim))
        findings.extend(_check_scope(manifest, claim))

        sensor_results = await self._run_sensors(manifest, project_root, findings)

        passed = len(findings) == 0
        return VerificationResult(
            passed=passed,
            findings=tuple(findings),
            sensor_results=tuple(sensor_results),
            timestamp=datetime.now(timezone.utc),
        )

    async def _run_sensors(
        self,
        manifest: TaskManifest,
        project_root: Path,
        findings: list[VerificationFinding],
    ) -> list[SensorResult]:
        """Execute every sensor listed in the manifest and emit findings on failure."""
        results: list[SensorResult] = []
        context = {"project_root": str(project_root)}

        for sensor_id in manifest.verification_sensors:
            sensor = self._sensors.get(sensor_id)
            if sensor is None:
                findings.append(
                    VerificationFinding(
                        kind=VerificationFindingKind.SCHEMA_VIOLATION,
                        severity="high",
                        message=f"Manifest requires sensor '{sensor_id}' but it is not registered",
                        hint=(
                            "Register the sensor with the CompletionVerifier or remove "
                            f"'{sensor_id}' from manifest.verification_sensors"
                        ),
                        related_sensor=sensor_id,
                    )
                )
                continue

            result = await sensor.run(context)
            results.append(result)
            if not result.passed:
                # Inline each sensor-level finding so the repair prompt carries
                # the actual error (e.g. "F401: unused import at src/foo.py:3"),
                # not just the summary count.
                detail_findings = result.findings or ()
                if detail_findings:
                    for sf in detail_findings:
                        findings.append(
                            VerificationFinding(
                                kind=VerificationFindingKind.SENSOR_FAILURE,
                                severity=_severity_from_sensor(sensor_id, sf.severity),
                                message=_format_sensor_finding(sensor_id, sf),
                                hint=sf.suggestion or _default_hint(sensor_id),
                                related_sensor=sensor_id,
                            )
                        )
                else:
                    findings.append(
                        VerificationFinding(
                            kind=VerificationFindingKind.SENSOR_FAILURE,
                            severity="critical" if sensor_id == "test_pass" else "high",
                            message=f"Sensor '{sensor_id}' failed: {result.details}",
                            hint=_default_hint(sensor_id),
                            related_sensor=sensor_id,
                        )
                    )

        return results


def _format_sensor_finding(sensor_id: str, sf) -> str:  # type: ignore[no-untyped-def]
    """Render a SensorFinding into a single-line message for the repair prompt."""
    location = f" @ {sf.location}" if sf.location else ""
    return f"[{sensor_id}] {sf.message}{location}"


def _severity_from_sensor(sensor_id: str, raw: str) -> str:
    """Map sensor severities to VerificationFinding severities (drop 'info')."""
    if sensor_id == "test_pass":
        return "critical"
    if raw in ("critical", "high", "medium", "low"):
        return raw
    # 'info' or unknown collapses to 'low' so the agent still sees it.
    return "low"


def _default_hint(sensor_id: str) -> str:
    return f"Review the sensor findings, fix the underlying issue, and re-run '{sensor_id}' before claiming completion"


# ---------------------------------------------------------------------------
# Stateless check helpers (kept module-level for testability + clarity)
# ---------------------------------------------------------------------------


def _check_schema(manifest: TaskManifest, claim: CompletionClaim) -> list[VerificationFinding]:
    findings: list[VerificationFinding] = []
    if claim.task_id != manifest.manifest_id:
        findings.append(
            VerificationFinding(
                kind=VerificationFindingKind.SCHEMA_VIOLATION,
                severity="high",
                message=(
                    f"Claim.task_id={claim.task_id!r} does not match manifest.manifest_id={manifest.manifest_id!r}"
                ),
                hint="Reissue the completion claim with the correct task_id",
            )
        )
    return findings


def _check_criteria(manifest: TaskManifest, claim: CompletionClaim) -> list[VerificationFinding]:
    addressed = {entry.criterion for entry in claim.criteria_satisfied}
    findings: list[VerificationFinding] = []
    for criterion in manifest.acceptance_criteria:
        if criterion not in addressed:
            findings.append(
                VerificationFinding(
                    kind=VerificationFindingKind.CRITERION_UNADDRESSED,
                    severity="critical",
                    message=f"Acceptance criterion has no evidence: {criterion!r}",
                    hint=(
                        f"Add a CriterionEvidence with criterion={criterion!r} and "
                        "concrete evidence (command output or file artifact) to the claim"
                    ),
                    related_criterion=criterion,
                )
            )
    return findings


def _check_scope(manifest: TaskManifest, claim: CompletionClaim) -> list[VerificationFinding]:
    findings: list[VerificationFinding] = []
    affected = list(manifest.affected_files)
    forbidden = list(manifest.forbidden_files)
    for file_path in claim.files_changed:
        if not PolicyEngine.check_file_access(file_path, affected, forbidden):
            findings.append(
                VerificationFinding(
                    kind=VerificationFindingKind.SCOPE_VIOLATION,
                    severity="high",
                    message=(
                        f"Claimed file {file_path!r} is outside manifest scope "
                        f"(allowed={manifest.affected_files}, forbidden={manifest.forbidden_files})"
                    ),
                    hint=(
                        "Either revert the out-of-scope change or amend the manifest's "
                        "affected_files (with proper authorization) before re-claiming completion"
                    ),
                )
            )
    return findings
