"""Beginner-facing proof card reports for CES-built projects."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ces.shared.artifact_paths import project_artifact_exists, resolve_project_artifact_path
from ces.shared.secrets import scrub_secrets_recursive
from ces.verification.completion_contract import (
    BehaviorDelta,
    CompletionContract,
    RiskTrack,
    VerificationCommand,
    verification_commands_for_contract,
)
from ces.verification.proof_binding import proof_binding_hash

_SCHEMA_VERSION = "1.0"
_VERIFICATION_RESULT_PATH = Path(".ces") / "latest-verification.json"


@dataclass(frozen=True)
class ProofCardReport:
    """Compact shareable proof summary for a local project."""

    project_root: Path
    objective: str | None
    evidence_status: str
    proof_status: str
    approval_safety: str
    ship_recommendation: str
    changed_files: tuple[str, ...]
    commands_run: tuple[dict[str, Any], ...]
    verification_commands: tuple[VerificationCommand, ...]
    evidence_provenance: dict[str, Any]
    behavior_delta: BehaviorDelta
    risk_track: RiskTrack
    missing_required_artifacts: tuple[str, ...]
    unproven_areas: tuple[str, ...]
    review_summary: dict[str, Any]
    next_command: str
    execution_contract_id: str | None = None
    execution_contract_objective: str | None = None
    semantic_review: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "project_root": self.project_root.name or ".",
            "objective": self.objective,
            "evidence_status": self.evidence_status,
            "proof_status": self.proof_status,
            "approval_safety": self.approval_safety,
            "ship_recommendation": self.ship_recommendation,
            "changed_files": list(self.changed_files),
            "commands_run": list(self.commands_run),
            "verification_commands": [
                _shareable_verification_command(command) for command in self.verification_commands
            ],
            "evidence_provenance": self.evidence_provenance,
            "behavior_delta": _behavior_delta_dict(self.behavior_delta),
            "risk_track": _risk_track_dict(self.risk_track),
            "missing_required_artifacts": list(self.missing_required_artifacts),
            "unproven_areas": list(self.unproven_areas),
            "review_summary": self.review_summary,
            "next_command": self.next_command,
            "execution_contract": {
                "contract_id": self.execution_contract_id,
                "objective": self.execution_contract_objective,
            },
            "semantic_review": self.semantic_review,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"

    def to_markdown(self) -> str:
        payload = self.to_dict()
        command_lines = _bullet(
            f"`{command['command']}` — {command['kind']} / {command['id']}" for command in payload["commands_run"]
        )
        warnings = payload["review_summary"].get("reality_boundary_warnings", [])
        warning_lines = ["", "## Reality Boundary warnings", "", *_bullet(warnings)] if warnings else []
        return (
            "\n".join(
                [
                    "# CES Proof Card",
                    "",
                    f"Project root: `{payload['project_root']}`",
                    f"Objective: {payload['objective'] or 'No completion contract found.'}",
                    f"Evidence status: **{payload['evidence_status']}**",
                    f"Proof status: **{payload['proof_status']}**",
                    f"Approval safety: **{payload['approval_safety']}**",
                    f"Ship recommendation: **{payload['ship_recommendation']}**",
                    f"Next command: `{payload['next_command']}`",
                    f"Semantic review: {_semantic_review_markdown_line(payload['semantic_review'])}",
                    f"Execution contract: {payload['execution_contract']['contract_id'] or 'None'}",
                    "",
                    "## Review decision",
                    "",
                    f"Decision: **{payload['review_summary']['decision']}**",
                    f"Approval gate: **{payload['review_summary']['approval_gate']}**",
                    f"Primary blocker: {payload['review_summary']['primary_blocker'] or 'None'}",
                    f"Evidence freshness: {payload['review_summary']['freshness']}",
                    f"Command coverage: {payload['review_summary']['command_coverage']}",
                    f"Artifact coverage: {payload['review_summary']['artifact_coverage']}",
                    f"Behavior delta coverage: {payload['review_summary']['behavior_delta_coverage']}",
                    f"Risk track: {payload['review_summary']['risk_track']}",
                    f"Risk evidence: {payload['review_summary']['risk_evidence']}",
                    f"Evidence provenance: {_evidence_provenance_markdown_line(payload['evidence_provenance'])}",
                    *warning_lines,
                    "Next steps:",
                    *_bullet(payload["review_summary"]["next_steps"]),
                    "",
                    "## Changed files",
                    "",
                    *_bullet(payload["changed_files"]),
                    "",
                    "## Commands / evidence",
                    "",
                    *command_lines,
                    "",
                    "## Behavior delta",
                    "",
                    *_behavior_delta_markdown(self.behavior_delta),
                    "",
                    "## Missing required artifacts",
                    "",
                    *_bullet(payload["missing_required_artifacts"]),
                    "",
                    "## Unproven areas",
                    "",
                    *_bullet(payload["unproven_areas"]),
                ]
            ).rstrip()
            + "\n"
        )


def build_proof_card(project_root: str | Path) -> ProofCardReport:
    """Build a read-only proof card from local CES evidence and project files."""

    root = Path(project_root).resolve()
    contract_path = root / ".ces" / "completion-contract.json"
    contract = CompletionContract.read(contract_path) if contract_path.is_file() else None
    execution_contract = _load_execution_contract(root)
    verification = _load_latest_verification(root)
    verification_fresh = _verification_is_fresh(root, contract_path, verification)
    binding_status = _proof_binding_status(contract, verification)
    changed_files = _changed_files(root)
    reality_boundary_warnings = _reality_boundary_warnings(contract, changed_files)
    missing = _missing_required_artifacts(root, contract, verification)
    behavior_delta = _behavior_delta(contract, execution_contract)
    risk_track = contract.risk_track if contract else RiskTrack()
    unproven = _unproven_areas(
        contract,
        missing,
        verification,
        root=root,
        behavior_delta=behavior_delta,
        binding_status=binding_status,
    )
    verification_passed = _verification_passed(verification)
    verification_matches = _verification_matches_contract(contract, verification, root) and binding_status == "matched"
    status = (
        "candidate"
        if contract
        and verification_passed
        and verification_fresh
        and verification_matches
        and not missing
        and not unproven
        else "incomplete"
    )
    proof_status = _proof_status(
        contract=contract,
        verification=verification,
        verification_passed=verification_passed,
        verification_fresh=verification_fresh,
        verification_matches=verification_matches,
        missing=missing,
        unproven=unproven,
    )
    approval_safety = _approval_safety(
        proof_status,
        verification=verification,
        verification_fresh=verification_fresh,
        verification_matches=verification_matches,
        binding_status=binding_status,
    )
    recommendation = "candidate" if status == "candidate" else "no-ship"
    review_summary = _review_summary(
        contract=contract,
        proof_status=proof_status,
        approval_safety=approval_safety,
        verification=verification,
        verification_fresh=verification_fresh,
        missing=missing,
        unproven=unproven,
        behavior_delta=behavior_delta,
        risk_track=risk_track,
        binding_status=binding_status,
        reality_boundary_warnings=reality_boundary_warnings,
    )
    semantic_review = _semantic_review_summary(root)
    verification_evidence_class = _verification_evidence_class(
        verification,
        verification_fresh=verification_fresh,
        verification_matches=verification_matches,
        binding_status=binding_status,
    )
    return ProofCardReport(
        project_root=root,
        objective=contract.request if contract else None,
        evidence_status=status,
        proof_status=proof_status,
        approval_safety=approval_safety,
        ship_recommendation=recommendation,
        changed_files=changed_files,
        commands_run=_commands_run(verification, evidence_class=verification_evidence_class),
        verification_commands=verification_commands_for_contract(contract) if contract else (),
        evidence_provenance=_evidence_provenance(
            contract,
            verification,
            evidence_class=verification_evidence_class,
        ),
        behavior_delta=behavior_delta,
        risk_track=risk_track,
        missing_required_artifacts=tuple(missing),
        unproven_areas=tuple(unproven),
        review_summary=review_summary,
        next_command=contract.next_ces_command if contract else "ces ship",
        execution_contract_id=execution_contract.get("contract_id") if execution_contract else None,
        execution_contract_objective=execution_contract.get("objective") if execution_contract else None,
        semantic_review=semantic_review,
    )


def _missing_required_artifacts(
    root: Path,
    contract: CompletionContract | None,
    verification: dict[str, Any] | None,
) -> list[str]:
    if contract is None:
        return ["completion contract"]
    missing: list[str] = []
    known_artifacts = {"readme.md", "run command", "test command", "verification evidence", "regression-evidence.md"}
    for artifact in _required_artifacts(contract):
        normalized = artifact.strip().lower()
        known_missing = (
            (normalized == "readme.md" and not _safe_project_artifact_exists(root, "README.md"))
            or (normalized == "run command" and not _readme_has_instruction(root, ("run", "start")))
            or (normalized == "test command" and not _readme_has_instruction(root, ("test", "pytest", "npm test")))
            or (normalized == "verification evidence" and not _verification_passed(verification))
            or (normalized == "regression-evidence.md" and not _safe_project_artifact_exists(root, artifact))
        )
        if known_missing or (normalized not in known_artifacts and not _safe_project_artifact_exists(root, artifact)):
            missing.append(artifact)
    return missing


def _unproven_areas(
    contract: CompletionContract | None,
    missing: list[str],
    verification: dict[str, Any] | None,
    *,
    root: Path,
    behavior_delta: BehaviorDelta,
    binding_status: str,
) -> list[str]:
    if contract is None:
        message = "No completion contract found; run `ces build --from-scratch ...` or `ces ship ...` first."
        if (root / ".ces" / "contracts" / "latest.json").is_file():
            message = "Execution contract exists but completion contract is missing."
        return [message]
    areas: list[str] = []
    if missing:
        areas.append("Required beginner handoff artifacts are incomplete.")
    if not verification_commands_for_contract(contract):
        areas.append("No verification commands are recorded.")
    if verification is None:
        areas.append("No persisted verification run found; run `ces verify --json` before treating this as proof.")
    elif not _verification_passed(verification):
        areas.append("Latest persisted verification run did not pass.")
    elif not _verification_is_fresh(root, root / ".ces" / "completion-contract.json", verification):
        areas.append("Latest persisted verification run is not fresh for the current completion contract.")
    elif binding_status == "missing":
        areas.append("Latest persisted verification run is missing a proof binding hash; rerun `ces verify --json`.")
    elif binding_status == "mismatched":
        areas.append("Latest persisted verification run was produced for a different objective context.")
    elif not _verification_matches_contract(contract, verification, root):
        areas.append("Latest persisted verification run does not match the current completion contract.")
    if contract.proof_requirements and missing:
        areas.extend(contract.proof_requirements)
    risk_missing = [item for item in missing if item in contract.risk_track.required_artifacts]
    if risk_missing:
        areas.extend(contract.risk_track.proof_requirements)
    for item in behavior_delta.unknown:
        areas.append(f"Unresolved behavior ambiguity remains: {item}")
    return areas


def _load_latest_verification(root: Path) -> dict[str, Any] | None:
    path = resolve_project_artifact_path(root, _VERIFICATION_RESULT_PATH)
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _verification_is_fresh(root: Path, contract_path: Path, verification: dict[str, Any] | None) -> bool:
    """Return True when the persisted verification is at least as new as the contract."""

    if verification is None or not contract_path.is_file():
        return False
    verification_path = resolve_project_artifact_path(root, _VERIFICATION_RESULT_PATH)
    if verification_path is None or not verification_path.is_file():
        return False
    try:
        return verification_path.stat().st_mtime >= contract_path.stat().st_mtime
    except OSError:
        return False


def _proof_status(
    *,
    contract: CompletionContract | None,
    verification: dict[str, Any] | None,
    verification_passed: bool,
    verification_fresh: bool,
    verification_matches: bool,
    missing: list[str],
    unproven: list[str],
) -> str:
    """Collapse contract/evidence state into operator-facing proof status."""

    if contract is None:
        return "unproven"
    if verification is None:
        return "unproven"
    if not verification_passed:
        return "contradicted"
    if not verification_fresh or not verification_matches:
        return "unproven"
    if missing or unproven:
        return "partially_proven"
    return "proven"


def _approval_safety(
    proof_status: str,
    *,
    verification: dict[str, Any] | None,
    verification_fresh: bool,
    verification_matches: bool,
    binding_status: str,
) -> str:
    """Return a compact approval safety hint for the current proof state."""

    if proof_status == "proven":
        return "safe-to-review"
    if proof_status == "contradicted":
        return "blocked"
    if (
        verification is None
        or not verification_fresh
        or not verification_matches
        or binding_status in {"missing", "mismatched"}
    ):
        return "needs-fresh-verification"
    return "needs-evidence"


def _reality_boundary_warnings(contract: CompletionContract | None, changed_files: tuple[str, ...]) -> tuple[str, ...]:
    """Return warn-only evidence when changed files touch protected reality-boundary paths."""

    if contract is None or not changed_files:
        return ()
    warnings: list[str] = []
    changed = tuple(_normalize_reality_boundary_path(path) for path in changed_files if path.strip())
    for surface in contract.reality_boundary.protected_surfaces:
        protected_candidates = _reality_boundary_path_candidates(surface.path)
        if not protected_candidates:
            continue
        for path in changed:
            if _reality_boundary_path_matches(path, protected_candidates):
                warnings.append(f"Protected reality-boundary surface changed: {path}.")
    denied_candidates = tuple(
        candidate
        for denied_path in contract.reality_boundary.denied_test_paths
        for candidate in _reality_boundary_path_candidates(denied_path)
    )
    for path in changed:
        if _reality_boundary_path_matches(path, denied_candidates):
            warnings.append(f"Denied reality-boundary test path changed: {path}.")
    return tuple(dict.fromkeys(scrub_secrets_recursive(warnings)))


def _normalize_reality_boundary_path(path: str) -> str:
    """Return a stable POSIX-ish path for reality-boundary path comparisons."""

    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    parts: list[str] = []
    absolute = normalized.startswith("/")
    for part in normalized.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    joined = "/".join(parts).rstrip("/")
    return f"/{joined}" if absolute and joined else joined


def _reality_boundary_path_candidates(path: str) -> tuple[str, ...]:
    if path.strip() in {".", "./", "/"}:
        return ("",)
    normalized = _normalize_reality_boundary_path(path)
    if normalized in {"", "."}:
        return ("",)
    candidates = [normalized.lstrip("/")]
    if normalized.startswith("/"):
        parts = normalized.strip("/").split("/")
        candidates.extend("/".join(parts[index:]) for index in range(1, len(parts)))
    return tuple(dict.fromkeys(candidate for candidate in candidates if candidate))


def _reality_boundary_path_matches(path: str, candidates: tuple[str, ...]) -> bool:
    return any(candidate in {"", path} or path.startswith(f"{candidate}/") for candidate in candidates)


def _review_summary(
    *,
    contract: CompletionContract | None,
    proof_status: str,
    approval_safety: str,
    verification: dict[str, Any] | None,
    verification_fresh: bool,
    missing: list[str],
    unproven: list[str],
    behavior_delta: BehaviorDelta,
    risk_track: RiskTrack,
    binding_status: str,
    reality_boundary_warnings: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Return reviewer-facing decision metadata for the proof card."""

    return {
        "decision": _review_decision(proof_status, approval_safety),
        "approval_gate": "open" if proof_status == "proven" and approval_safety == "safe-to-review" else "closed",
        "primary_blocker": _primary_blocker(proof_status, missing, unproven),
        "freshness": _freshness_label(contract, verification, verification_fresh, binding_status),
        "binding_status": binding_status,
        "command_coverage": _command_coverage(contract, verification),
        "artifact_coverage": _artifact_coverage(contract, missing),
        "behavior_delta_coverage": _behavior_delta_coverage(behavior_delta),
        "risk_track": risk_track.tier,
        "risk_evidence": _risk_evidence_coverage(risk_track, missing),
        "reality_boundary_warnings": list(reality_boundary_warnings),
        "next_steps": _review_next_steps(
            proof_status,
            approval_safety,
            behavior_delta=behavior_delta,
            reality_boundary_warnings=reality_boundary_warnings,
        ),
    }


def _review_decision(proof_status: str, approval_safety: str) -> str:
    if proof_status == "proven" and approval_safety == "safe-to-review":
        return "ready-for-review"
    if proof_status == "contradicted" or approval_safety == "blocked":
        return "blocked"
    if approval_safety == "needs-fresh-verification":
        return "needs-verification"
    return "needs-evidence"


def _primary_blocker(proof_status: str, missing: list[str], unproven: list[str]) -> str | None:
    if proof_status == "contradicted":
        for area in unproven:
            if "verification" in area.lower() and "did not pass" in area.lower():
                return area
    return unproven[0] if unproven else (missing[0] if missing else None)


def _freshness_label(
    contract: CompletionContract | None,
    verification: dict[str, Any] | None,
    verification_fresh: bool,
    binding_status: str,
) -> str:
    if contract is None:
        return "no-contract"
    if verification is None:
        return "missing-verification"
    if not verification_fresh:
        return "stale"
    if binding_status == "mismatched":
        return "stale-objective"
    if binding_status == "missing":
        return "missing-binding"
    return "fresh"


def _command_coverage(contract: CompletionContract | None, verification: dict[str, Any] | None) -> str:
    if contract is None:
        return "0/0 required commands verified"
    required = tuple(command for command in verification_commands_for_contract(contract) if command.required)
    payload = _verification_payload(verification)
    commands = payload.get("commands", []) if payload else []
    verified = 0
    if isinstance(commands, list):
        by_id = {command.get("id"): command for command in commands if isinstance(command, dict)}
        for expected in required:
            actual = by_id.get(expected.id)
            if actual and actual.get("passed") is True:
                verified += 1
    return f"{verified}/{len(required)} required commands verified"


def _artifact_coverage(contract: CompletionContract | None, missing: list[str]) -> str:
    if contract is None:
        return "0/1 required artifacts present"
    required = _required_artifacts(contract)
    total = len(required)
    present = max(total - len(missing), 0)
    return f"{present}/{total} required artifacts present"


def _required_artifacts(contract: CompletionContract) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*contract.required_artifacts, *contract.risk_track.required_artifacts)))


def _risk_track_dict(track: RiskTrack) -> dict[str, Any]:
    return {
        "tier": track.tier,
        "required_artifacts": list(track.required_artifacts),
        "proof_requirements": list(track.proof_requirements),
        "evidence_requirements": list(track.evidence_requirements),
    }


def _risk_evidence_coverage(track: RiskTrack, missing: list[str]) -> str:
    if not track.required_artifacts:
        return "low-risk: no additional risk evidence required"
    missing_count = sum(1 for item in track.required_artifacts if item in missing)
    present = max(len(track.required_artifacts) - missing_count, 0)
    return f"{present}/{len(track.required_artifacts)} risk artifacts present"


def _review_next_steps(
    proof_status: str,
    approval_safety: str,
    *,
    behavior_delta: BehaviorDelta,
    reality_boundary_warnings: tuple[str, ...] = (),
) -> list[str]:
    if reality_boundary_warnings:
        return [
            "Review reality-boundary warnings before approval; rerun `ces verify --json` after intentional changes.",
            "Regenerate `ces proof` before approval.",
        ]
    if behavior_delta.unknown:
        return [
            "Resolve unresolved behavior ambiguity or attach explicit evidence for it, then rerun `ces verify --json`.",
            "Regenerate `ces proof` before approval.",
        ]
    if proof_status == "proven" and approval_safety == "safe-to-review":
        return ["Review changed files and evidence, then run `ces approve` if satisfied."]
    if proof_status == "contradicted" or approval_safety == "blocked":
        return ["Fix the failing verification, rerun `ces verify --json`, then regenerate `ces proof`."]
    if approval_safety == "needs-fresh-verification":
        return ["Run `ces verify --json` against the current contract, then regenerate `ces proof`."]
    return [
        "Repair missing evidence/artifacts, then rerun `ces verify --json`.",
        "Regenerate `ces proof` before approval.",
    ]


def _load_execution_contract(root: Path) -> dict[str, Any] | None:
    path = root / ".ces" / "contracts" / "latest.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    contract_id = payload.get("contract_id")
    objective = payload.get("objective")
    behavior_delta = payload.get("behavior_delta")
    return {
        "contract_id": contract_id if isinstance(contract_id, str) else "",
        "objective": objective if isinstance(objective, str) else "",
        "behavior_delta": behavior_delta if isinstance(behavior_delta, dict) else {},
    }


def _behavior_delta(contract: CompletionContract | None, execution_contract: dict[str, Any] | None) -> BehaviorDelta:
    if contract is not None and contract.behavior_delta.has_signal():
        return contract.behavior_delta
    if execution_contract:
        return BehaviorDelta.from_dict(_dict_or_none(execution_contract.get("behavior_delta")))
    return BehaviorDelta()


def _behavior_delta_dict(delta: BehaviorDelta) -> dict[str, list[str]]:
    return {
        "added": list(delta.added),
        "modified": list(delta.modified),
        "removed": list(delta.removed),
        "preserved": list(delta.preserved),
        "unknown": list(delta.unknown),
    }


def _behavior_delta_coverage(delta: BehaviorDelta) -> str:
    recorded = len(delta.added) + len(delta.modified) + len(delta.removed) + len(delta.preserved) + len(delta.unknown)
    return f"{recorded} recorded / {len(delta.unknown)} unresolved ambiguity"


def _behavior_delta_markdown(delta: BehaviorDelta) -> list[str]:
    rows: list[str] = []
    for label, values in (
        ("Added", delta.added),
        ("Modified", delta.modified),
        ("Removed", delta.removed),
        ("Preserved", delta.preserved),
        ("Unresolved ambiguity", delta.unknown),
    ):
        if values:
            rows.append(f"- {label}: " + "; ".join(values))
    return rows or ["- None recorded."]


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _verification_payload(verification: dict[str, Any] | None) -> dict[str, Any] | None:
    if verification is None:
        return None
    payload = verification.get("verification", verification)
    return payload if isinstance(payload, dict) else None


def _verification_passed(verification: dict[str, Any] | None) -> bool:
    payload = _verification_payload(verification)
    return bool(payload and payload.get("passed") is True)


def _proof_binding_status(contract: CompletionContract | None, verification: dict[str, Any] | None) -> str:
    """Return whether persisted verification is bound to the current objective context."""

    if contract is None:
        return "no-contract"
    if verification is None:
        return "missing"
    recorded = verification.get("proof_binding_hash")
    if not isinstance(recorded, str) or not recorded:
        return "missing"
    return "matched" if recorded == proof_binding_hash(contract) else "mismatched"


def _verification_matches_contract(
    contract: CompletionContract | None,
    verification: dict[str, Any] | None,
    root: Path,
) -> bool:
    """Return True when persisted verification belongs to this contract."""

    if contract is None:
        return False
    payload = _verification_payload(verification)
    if payload is None:
        return False
    expected_contract_path = root / ".ces" / "completion-contract.json"
    recorded_contract_path = verification.get("contract_path") if verification else None
    if isinstance(recorded_contract_path, str) and recorded_contract_path:
        try:
            if Path(recorded_contract_path).resolve() != expected_contract_path.resolve():
                return False
        except OSError:
            return False
    commands = payload.get("commands", [])
    if not isinstance(commands, list):
        return False
    by_id = {command.get("id"): command for command in commands if isinstance(command, dict)}
    return all(
        _actual_command_matches_expected(expected, by_id.get(expected.id))
        for expected in verification_commands_for_contract(contract)
    )


def _actual_command_matches_expected(expected: VerificationCommand, actual: Any) -> bool:
    if not isinstance(actual, dict):
        return False
    expected_codes = tuple(expected.expected_exit_codes or (0,))
    actual_codes = _int_tuple(actual.get("expected_exit_codes"))
    actual_timeout = _optional_int(actual.get("timeout_seconds"))
    if (
        actual.get("command") != scrub_secrets_recursive(expected.command)
        or actual.get("kind") != expected.kind
        or actual.get("required") is not expected.required
        or actual.get("cwd", ".") != expected.cwd
        or actual_timeout != expected.timeout_seconds
        or actual_codes != expected_codes
    ):
        return False
    if actual.get("exit_code") not in expected_codes:
        return False
    return not (expected.required and actual.get("passed") is not True)


def _int_tuple(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list | tuple):
        return ()
    try:
        return tuple(int(item) for item in value)
    except (TypeError, ValueError):
        return ()


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _commands_run(
    verification: dict[str, Any] | None, *, evidence_class: str = "ces_executed"
) -> tuple[dict[str, Any], ...]:
    payload = _verification_payload(verification)
    if payload is None:
        return ()
    commands = payload.get("commands", [])
    if not isinstance(commands, list):
        return ()
    return tuple(
        _shareable_command(command, evidence_class=evidence_class) for command in commands if isinstance(command, dict)
    )


def _shareable_command(command: dict[str, Any], *, evidence_class: str) -> dict[str, Any]:
    """Return command evidence safe for a compact shareable proof card."""

    allowed = (
        "id",
        "kind",
        "command",
        "required",
        "cwd",
        "timeout_seconds",
        "exit_code",
        "expected_exit_codes",
        "passed",
    )
    payload = {key: command[key] for key in allowed if key in command}
    payload["evidence_class"] = evidence_class
    return scrub_secrets_recursive(payload)


def _verification_evidence_class(
    verification: dict[str, Any] | None,
    *,
    verification_fresh: bool,
    verification_matches: bool,
    binding_status: str,
) -> str:
    """Classify trust provenance for persisted verification evidence."""

    if verification is None:
        return "missing"
    if not verification_fresh or not verification_matches or binding_status in {"missing", "mismatched"}:
        return "stale"
    return "ces_executed"


def _evidence_provenance(
    contract: CompletionContract | None,
    verification: dict[str, Any] | None,
    *,
    evidence_class: str,
) -> dict[str, Any]:
    """Return compact evidence provenance counters for proof consumers."""

    payload = _verification_payload(verification)
    commands = payload.get("commands", []) if payload else []
    persisted_count = len(commands) if isinstance(commands, list) else 0
    matched_count = _matched_planned_command_count(contract, commands)
    command_classes = {evidence_class: matched_count} if matched_count else {}
    return {
        "verification": evidence_class,
        "commands": command_classes,
        "planned_commands": len(verification_commands_for_contract(contract)) if contract else 0,
        "planned_commands_matched": matched_count,
        "persisted_commands": persisted_count,
    }


def _matched_planned_command_count(contract: CompletionContract | None, commands: Any) -> int:
    if contract is None or not isinstance(commands, list):
        return 0
    by_id = {command.get("id"): command for command in commands if isinstance(command, dict)}
    return sum(
        1
        for expected in verification_commands_for_contract(contract)
        if _actual_command_matches_expected(expected, by_id.get(expected.id))
    )


def _evidence_provenance_markdown_line(provenance: dict[str, Any]) -> str:
    label = str(provenance.get("verification") or "missing")
    labels = {
        "ces_executed": "CES-executed verification",
        "ces_observed": "CES-observed runtime evidence",
        "agent_claimed": "agent-claimed evidence",
        "stale": "stale verification evidence",
        "missing": "missing verification evidence",
    }
    command_classes = provenance.get("commands")
    matched = provenance.get("planned_commands_matched", 0)
    if not isinstance(matched, int):
        try:
            matched = int(matched)
        except (TypeError, ValueError):
            matched = 0
    if isinstance(command_classes, dict) and not matched:
        try:
            matched = sum(int(value) for value in command_classes.values())
        except (TypeError, ValueError):
            matched = 0
    planned = provenance.get("planned_commands", 0)
    persisted = provenance.get("persisted_commands", matched)
    return f"{labels.get(label, label)} ({matched}/{planned} planned commands matched; {persisted} persisted command records)"


def _shareable_verification_command(command: VerificationCommand) -> dict[str, Any]:
    """Return contract command metadata without leaking inline secrets."""

    payload = asdict(command)
    payload["evidence_class"] = "planned"
    return scrub_secrets_recursive(payload)


def _readme_has_instruction(root: Path, verbs: tuple[str, ...]) -> bool:
    readme = resolve_project_artifact_path(root, "README.md")
    if readme is None or not readme.is_file():
        return False
    text = readme.read_text(encoding="utf-8", errors="ignore")
    for verb in verbs:
        escaped = re.escape(verb)
        label_match = re.search(rf"(?im)^\s*(?:[-*]\s*)?{escaped}\s*:\s*`?([^`\n]+)`?", text)
        if label_match and _readme_command_satisfies(label_match.group(1), verbs, context=verb):
            return True
        shell_match = re.search(rf"(?im)^\s*(?:```(?:bash|sh|shell)?\s*)?\$\s*(\S*{escaped}\S*\b.*)$", text)
        if shell_match and _readme_command_satisfies(shell_match.group(1), verbs, context=verb):
            return True
    if _readme_has_inline_command(text, verbs):
        return True
    return _readme_has_sectioned_command(text, verbs)


_COMMAND_START_RE = re.compile(
    r"^\s*(?:\$\s*)?(?:python(?:3)?\b|uv\b|pytest\b|npm\b|pnpm\b|yarn\b|node\b|deno\b|go\b|cargo\b|make\b)"
)
_TEST_COMMAND_RE = re.compile(
    r"\b(pytest|unittest|npm\s+(?:run\s+)?test|pnpm\s+(?:run\s+)?test|yarn\s+(?:run\s+)?test|go\s+test|cargo\s+test|make\s+test)\b"
)
_INLINE_BACKTICK_COMMAND_RE = re.compile(r"(?i)\b(run|start|execute|use|test|verify|check)\b[^`\n]{0,80}`([^`\n]+)`")


def _readme_has_inline_command(text: str, verbs: tuple[str, ...]) -> bool:
    for match in _INLINE_BACKTICK_COMMAND_RE.finditer(text):
        lead_verb = match.group(1).casefold()
        command = match.group(2).casefold()
        if _readme_command_satisfies(command, verbs, context=lead_verb):
            return True
    return False


def _readme_command_satisfies(command: str, verbs: tuple[str, ...], *, context: str = "") -> bool:
    wants_test = any(verb in {"test", "pytest", "npm test"} for verb in verbs)
    wants_run = any(verb in {"run", "start"} for verb in verbs)
    folded_command = command.casefold().strip()
    folded_context = context.casefold()
    is_executable_command = bool(_COMMAND_START_RE.search(folded_command))
    if not is_executable_command:
        return False
    is_test_command = bool(_TEST_COMMAND_RE.search(folded_command))
    if wants_test and (is_test_command or any(marker in folded_context for marker in ("test", "verify", "check"))):
        return True
    return bool(
        wants_run
        and not is_test_command
        and any(marker in folded_context for marker in ("run", "start", "execute", "use", "usage", "quickstart"))
    )


def _readme_has_sectioned_command(text: str, verbs: tuple[str, ...]) -> bool:
    wants_test = any(verb in {"test", "pytest", "npm test"} for verb in verbs)
    wants_run = any(verb in {"run", "start"} for verb in verbs)
    current_heading = ""
    recent_text: list[str] = []
    in_fence = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        heading_match = re.match(r"^#{1,6}\s+(.*)$", line)
        if heading_match:
            current_heading = heading_match.group(1).casefold()
            recent_text.clear()
            continue
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence and _COMMAND_START_RE.search(line):
            command = line.casefold()
            context = "\n".join([current_heading, *recent_text[-3:]]).casefold()
            is_test_command = bool(_TEST_COMMAND_RE.search(command))
            if wants_test and (is_test_command or "test" in context or "verify" in context):
                return True
            if (
                wants_run
                and not is_test_command
                and any(marker in context for marker in ("usage", "run", "start", "install", "quickstart"))
            ):
                return True
        if not in_fence and line:
            recent_text.append(line)
    return False


def _safe_project_artifact_exists(root: Path, artifact: str) -> bool:
    return project_artifact_exists(root, artifact)


def _changed_files(root: Path) -> tuple[str, ...]:
    git = shutil.which("git")
    if git is None:
        return ()
    try:
        result = subprocess.run(  # noqa: S603
            [git, "--no-optional-locks", "status", "--porcelain=v1", "-z"],
            cwd=root,
            check=False,
            capture_output=True,
            text=False,
            timeout=5,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    if result.returncode != 0:
        return ()
    files: list[str] = []
    entries = [entry for entry in result.stdout.split(b"\0") if entry]
    skip_next = False
    for raw in entries:
        if skip_next:
            skip_next = False
            continue
        entry = raw.decode("utf-8", errors="replace")
        if len(entry) < 4:
            continue
        status = entry[:2]
        path = entry[3:]
        if status.startswith(("R", "C")):
            # Porcelain -z emits the source path as a second entry; the first path is the destination.
            skip_next = True
        if path:
            files.append(path)
    return tuple(files)


def _bullet(items: list[str] | tuple[str, ...] | Any) -> list[str]:
    values = list(items)
    if not values:
        return ["- None recorded."]
    return [f"- {item}" for item in values]


def _semantic_review_summary(root: Path) -> dict[str, Any]:
    """Return a compact latest semantic review summary for the proof card."""

    try:
        from ces.review.artifacts import SemanticReviewArtifactStore

        store = SemanticReviewArtifactStore(root)
        metadata = store.latest_bundle_metadata()
        if metadata is None:
            return {
                "status": "missing",
                "review_id": None,
                "warning": "No semantic review artifact found; run `ces review generate` before approval.",
            }
        bundle = store.load_bundle(metadata.review_id)
        stale = store.is_stale(metadata)
        review_brief = _relative_artifact(root, bundle.review_brief_path)
        return scrub_secrets_recursive(
            {
                "status": "stale" if stale else "current",
                "review_id": metadata.review_id,
                "review_brief": review_brief,
                "risk_level": bundle.risk_map.overall_level,
                "risk_score": bundle.risk_map.overall_score,
                "intent_coverage": dict(bundle.intent_coverage.summary),
                "diff_fingerprint": metadata.diff_fingerprint,
                "stale": stale,
            }
        )
    except (OSError, RuntimeError, ValueError):
        return {
            "status": "unavailable",
            "review_id": None,
            "warning": "Semantic review artifact could not be read safely.",
        }


def _semantic_review_markdown_line(summary: dict[str, Any]) -> str:
    status = summary.get("status") or "missing"
    review_id = summary.get("review_id")
    if not review_id:
        return str(summary.get("warning") or "No semantic review artifact found.")
    path = summary.get("review_brief") or ".ces/reviews"
    risk = summary.get("risk_level") or "unknown"
    stale = " stale" if summary.get("stale") else ""
    return f"`{path}` ({status}{stale}, risk: {risk}, id: {review_id})"


def _relative_artifact(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except (OSError, ValueError):
        return path.name
