"""Verification and proof evidence summarization for semantic review."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ces.review.models import VerificationCommandResult, VerificationSummary
from ces.shared.secrets import scrub_secrets_from_text


def verification_evidence_fingerprint(project_root: Path) -> str:
    """Return a stable fingerprint for persisted verification evidence inputs."""

    root = project_root.resolve()
    path = root / ".ces" / "latest-verification.json"
    if path.is_symlink():
        return "latest-verification:symlinked"
    if not path.is_file():
        return "latest-verification:absent"
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "latest-verification:unreadable"
    return f"latest-verification:sha256:{digest}"


def load_verification_summary(project_root: Path) -> VerificationSummary:
    """Load latest CES verification/proof evidence without running commands."""

    root = project_root.resolve()
    path = root / ".ces" / "latest-verification.json"
    if not path.is_file() or path.is_symlink():
        proof = _proof_summary(root)
        return VerificationSummary(
            status="not_run",
            proof_status=proof.get("proof_status"),
            approval_safety=proof.get("approval_safety"),
            missing_required_artifacts=tuple(str(item) for item in proof.get("missing_required_artifacts", ())),
            unproven_areas=tuple(str(item) for item in proof.get("unproven_areas", ())),
            evidence_sources=tuple(filter(None, ["proof_card" if proof else None])),
            warnings=("No .ces/latest-verification.json record found.",),
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return VerificationSummary(status="unknown", warnings=(f"Could not read latest verification: {exc}",))
    verification = payload.get("verification") if isinstance(payload, dict) else {}
    if not isinstance(verification, dict):
        verification = {}
    commands = tuple(_command_result(item) for item in _as_list(verification.get("commands")))
    passed = bool(verification.get("passed"))
    skipped = bool(commands) and all(command.status == "skipped" for command in commands)
    status = "passed" if passed else ("skipped" if skipped else "failed" if commands else "unknown")
    proof = _proof_summary(root)
    return VerificationSummary(
        status=status,
        fresh=True,
        proof_status=proof.get("proof_status"),
        approval_safety=proof.get("approval_safety"),
        binding_status=proof.get("review_summary", {}).get("proof_binding")
        if isinstance(proof.get("review_summary"), dict)
        else None,
        commands=commands,
        missing_required_artifacts=tuple(str(item) for item in proof.get("missing_required_artifacts", ())),
        unproven_areas=tuple(str(item) for item in proof.get("unproven_areas", ())),
        evidence_sources=(".ces/latest-verification.json", "proof_card"),
    )


def _command_result(item: object) -> VerificationCommandResult:
    if not isinstance(item, dict):
        return VerificationCommandResult(command=str(item), status="unknown")
    command = scrub_secrets_from_text(str(item.get("command") or item.get("cmd") or "unknown"))
    passed = item.get("passed")
    exit_code = item.get("exit_code")
    if passed is True or exit_code == 0:
        status = "passed"
    elif item.get("skipped") is True:
        status = "skipped"
    elif passed is False or (isinstance(exit_code, int) and exit_code != 0):
        status = "failed"
    else:
        status = "unknown"
    summary = str(item.get("summary") or item.get("stdout_summary") or item.get("stderr_summary") or "")[:500]
    return VerificationCommandResult(
        command=command,
        status=status,
        duration_seconds=_duration(item.get("duration_seconds") or item.get("duration")),
        summary=scrub_secrets_from_text(summary),
        evidence_ref=str(item.get("id") or item.get("evidence_ref"))
        if item.get("id") or item.get("evidence_ref")
        else None,
    )


def _duration(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _proof_summary(root: Path) -> dict[str, Any]:
    try:
        from ces.verification.proof_card import build_proof_card

        return build_proof_card(root).to_dict()
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
        return {}
