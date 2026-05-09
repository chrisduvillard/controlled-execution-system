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

import posixpath
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
from ces.harness.services.change_impact import detects_docs_impact
from ces.verification.profile import PROFILE_RELATIVE_PATH

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
        findings.extend(_check_dependency_evidence(claim))
        findings.extend(_check_required_evidence(manifest, claim, project_root))
        findings.extend(_check_profile_governance(claim))
        findings.extend(_check_open_questions(claim))

        sensor_results = await self._run_sensors(manifest, claim, project_root, findings)

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
        claim: CompletionClaim,
        project_root: Path,
        findings: list[VerificationFinding],
    ) -> list[SensorResult]:
        """Execute every sensor listed in the manifest and emit findings on failure."""
        results: list[SensorResult] = []
        context = {"project_root": str(project_root), "profile_trusted": not _profile_changed(claim)}

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
        hint = "Reissue the completion claim with the correct task_id"
        if claim.task_id.startswith("OLB-"):
            hint = (
                "OLB-* values identify reviewed legacy behavior, not the active task manifest. "
                f"Reissue the completion claim with task_id={manifest.manifest_id!r}; keep legacy behavior IDs "
                "only in evidence notes or related legacy context."
            )
        findings.append(
            VerificationFinding(
                kind=VerificationFindingKind.SCHEMA_VIOLATION,
                severity="high",
                message=(
                    f"Claim.task_id={claim.task_id!r} does not match manifest.manifest_id={manifest.manifest_id!r}"
                ),
                hint=hint,
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


_DEPENDENCY_FILE_NAMES = {
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-test.txt",
    "requirements_dev.txt",
    "requirements_test.txt",
    "package.json",
    "Cargo.toml",
    "go.mod",
}

_DEPENDENCY_LOCKFILE_NAMES = {
    "uv.lock",
    "poetry.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "Cargo.lock",
    "go.sum",
}


def _check_dependency_evidence(claim: CompletionClaim) -> list[VerificationFinding]:
    dep_files = [path for path in claim.files_changed if path.rsplit("/", 1)[-1] in _DEPENDENCY_FILE_NAMES]
    if not dep_files:
        return []

    evidence_files = {entry.file_path for entry in claim.dependency_changes}
    missing = [path for path in dep_files if path not in evidence_files]
    if not missing:
        return []

    return [
        VerificationFinding(
            kind=VerificationFindingKind.EVIDENCE_MISMATCH,
            severity="high",
            message=f"Dependency file changes require dependency evidence: {', '.join(missing)}",
            hint=(
                "Add dependency_changes entries with package, rationale, existing alternative, "
                "lockfile evidence, and audit evidence."
            ),
        )
    ]


def _check_required_evidence(
    manifest: TaskManifest,
    claim: CompletionClaim,
    project_root: Path | None = None,
) -> list[VerificationFinding]:
    findings: list[VerificationFinding] = []
    if getattr(manifest, "requires_exploration_evidence", False) and not claim.exploration_evidence:
        findings.append(
            VerificationFinding(
                kind=VerificationFindingKind.EVIDENCE_MISMATCH,
                severity="high",
                message="Manifest requires exploration evidence, but the completion claim did not include any.",
                hint="Add exploration_evidence entries listing files, tests, docs, or conventions inspected before editing.",
            )
        )
    if getattr(manifest, "requires_verification_commands", False) and not claim.verification_commands:
        findings.append(
            VerificationFinding(
                kind=VerificationFindingKind.EVIDENCE_MISMATCH,
                severity="high",
                message="Manifest requires verification command evidence, but the completion claim did not include any.",
                hint="Add verification_commands entries with command, exit_code, summary, and artifact path when available.",
            )
        )
    if getattr(manifest, "requires_impacted_flow_evidence", False) and not _has_impacted_flow_evidence(claim):
        findings.append(
            VerificationFinding(
                kind=VerificationFindingKind.EVIDENCE_MISMATCH,
                severity="high",
                message="Manifest requires impacted-flow evidence, but the completion claim did not include it.",
                hint="Add exploration_evidence that names critical flows, impacted callers, or must-not-break behavior inspected.",
            )
        )
    docs_evidence = [entry.path for entry in claim.exploration_evidence if _is_docs_path(entry.path)]
    if getattr(manifest, "requires_docs_evidence_for_public_changes", False) and detects_docs_impact(
        list(claim.files_changed), docs_evidence
    ):
        findings.append(
            VerificationFinding(
                kind=VerificationFindingKind.EVIDENCE_MISMATCH,
                severity="medium",
                message="Public behavior changed without documentation evidence.",
                hint="Update maintained docs or add exploration_evidence explaining why docs are unaffected.",
            )
        )
    for entry in claim.verification_commands:
        if entry.exit_code != 0 and not _is_expected_nonzero_verification_command(entry, claim):
            findings.append(
                VerificationFinding(
                    kind=VerificationFindingKind.EVIDENCE_MISMATCH,
                    severity="high",
                    message=f"Verification command failed with exit code {entry.exit_code}: {entry.command}",
                    hint="Fix the failure or disclose why the command cannot pass before claiming completion.",
                )
            )
        if project_root is not None and entry.artifact_path and not (project_root / entry.artifact_path).exists():
            findings.append(
                VerificationFinding(
                    kind=VerificationFindingKind.EVIDENCE_MISMATCH,
                    severity="medium",
                    message=f"Verification artifact path does not exist: {entry.artifact_path}",
                    hint="Attach an existing artifact path or omit artifact_path when the command has no artifact output.",
                )
            )
    return findings


_NEGATIVE_EXIT_MARKERS = (
    "nonzero",
    "non-zero",
    "non zero",
    "non-0",
    "non 0",
    "expected failure",
    "expected to fail",
    "should fail",
    "exits with an error",
    "exit with an error",
)


def _is_expected_nonzero_verification_command(entry, claim: CompletionClaim) -> bool:  # type: ignore[no-untyped-def]
    """Return True when a non-zero command is evidence for an expected-negative criterion."""
    if entry.exit_code == 0:
        return False
    command = str(entry.command).strip()
    if not command:
        return False
    command_folded = command.casefold()
    summary_folded = str(entry.summary).casefold()
    for criterion in claim.criteria_satisfied:
        criterion_text = str(criterion.criterion)
        evidence_text = str(criterion.evidence)
        combined = f"{criterion_text}\n{evidence_text}".casefold()
        if command_folded not in combined:
            continue
        if _expects_nonzero_exit(combined) or _expects_nonzero_exit(summary_folded):
            return True
    return False


def _expects_nonzero_exit(text: str) -> bool:
    return any(marker in text for marker in _NEGATIVE_EXIT_MARKERS)


def _has_impacted_flow_evidence(claim: CompletionClaim) -> bool:
    needles = ("critical flow", "impacted flow", "must-not-break", "must not break", "caller", "route")
    for entry in claim.exploration_evidence:
        haystack = f"{entry.path} {entry.reason} {entry.observation}".lower()
        if any(needle in haystack for needle in needles):
            return True
    return False


def _is_docs_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized == "README.md" or normalized.startswith(("docs/", "CHANGELOG"))


def _normalize_claim_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip()
    while normalized.startswith("/"):
        normalized = normalized[1:]
    return posixpath.normpath(normalized)


def _profile_changed(claim: CompletionClaim) -> bool:
    profile_file = str(PROFILE_RELATIVE_PATH).replace("\\", "/")
    return any(_normalize_claim_path(path) == profile_file for path in claim.files_changed)


def _check_profile_governance(claim: CompletionClaim) -> list[VerificationFinding]:
    if not _profile_changed(claim):
        return []
    return [
        VerificationFinding(
            kind=VerificationFindingKind.EVIDENCE_MISMATCH,
            severity="high",
            message="Verification profile changed in this completion claim; current-run profile downgrades are not trusted.",
            hint=(
                "Treat .ces/verification-profile.json as governed policy: review the profile change explicitly and "
                "provide normal verification artifacts for this run. Future runs may use the approved profile."
            ),
        )
    ]


def _check_open_questions(claim: CompletionClaim) -> list[VerificationFinding]:
    if not claim.open_questions:
        return []
    return [
        VerificationFinding(
            kind=VerificationFindingKind.EVIDENCE_MISMATCH,
            severity="high",
            message="Completion claim contains unresolved open questions.",
            hint="Resolve material open questions before completion, or stop and ask the operator for clarification.",
        )
    ]
