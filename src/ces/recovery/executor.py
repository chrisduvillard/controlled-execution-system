"""Execute safe self-recovery actions for blocked builder sessions."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ces.recovery.planner import build_recovery_plan
from ces.verification.completion_contract import CompletionContract
from ces.verification.runner import VerificationRunResult, run_verification_commands


@dataclass(frozen=True)
class RecoveryExecutionResult:
    verification: VerificationRunResult
    completed: bool
    dry_run: bool
    new_evidence_packet_id: str | None
    manifest_id: str | None
    session_id: str | None
    next_action: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["verification"] = self.verification.to_dict()
        return data


def run_auto_evidence_recovery(
    *,
    project_root: Path,
    local_store: Any,
    dry_run: bool = False,
    auto_complete: bool = False,
) -> RecoveryExecutionResult:
    """Rerun completion-contract verification and optionally complete safely.

    Completion is intentionally narrow: it only happens when independent
    verification passes and the caller explicitly asks for ``auto_complete``.
    Existing runtime/evidence metadata is copied under ``superseded_evidence`` in
    the recovered evidence packet instead of being overwritten.
    """
    plan = build_recovery_plan(project_root=project_root, local_store=local_store)
    if not plan.session_id:
        raise RuntimeError("No builder session found. Start with `ces build`.")
    if not plan.contract_path:
        raise RuntimeError("No completion contract found. Run `ces verify --json` first.")

    contract = CompletionContract.read(Path(plan.contract_path))
    verification = run_verification_commands(project_root, contract.inferred_commands)
    if dry_run:
        return RecoveryExecutionResult(
            verification=verification,
            completed=False,
            dry_run=True,
            new_evidence_packet_id=None,
            manifest_id=plan.manifest_id,
            session_id=plan.session_id,
            next_action="recover_auto_complete" if verification.passed else "fix_verification",
            message="Dry run only; no CES state was changed.",
        )

    if not verification.passed:
        _update_session(
            local_store,
            plan.session_id,
            stage="blocked",
            next_action="fix_verification",
            last_action="recovery_verification_failed",
            recovery_reason="verification_failed",
            last_error="self-recovery verification commands failed",
        )
        return RecoveryExecutionResult(
            verification=verification,
            completed=False,
            dry_run=False,
            new_evidence_packet_id=None,
            manifest_id=plan.manifest_id,
            session_id=plan.session_id,
            next_action="fix_verification",
            message="Independent verification failed; builder session remains blocked.",
        )

    if not plan.manifest_id:
        raise RuntimeError(
            "Cannot attach recovered evidence without a manifest id; pass through manual completion instead."
        )

    old_evidence = _existing_evidence(local_store, plan.evidence_packet_id, plan.manifest_id)
    packet_id = _save_recovery_evidence(
        local_store=local_store,
        manifest_id=plan.manifest_id,
        packet_id=f"EP-recovery-{uuid.uuid4().hex[:12]}",
        source_evidence_packet_id=plan.evidence_packet_id,
        contract_path=plan.contract_path,
        contract=contract,
        verification=verification,
        old_evidence=old_evidence,
        auto_complete=auto_complete,
    )

    if not auto_complete:
        _update_session(
            local_store,
            plan.session_id,
            stage="awaiting_review",
            next_action="review_evidence",
            last_action="self_recovery_evidence_ready",
            recovery_reason="recovered_evidence_ready",
            last_error=None,
            evidence_packet_id=packet_id,
        )
        return RecoveryExecutionResult(
            verification=verification,
            completed=False,
            dry_run=False,
            new_evidence_packet_id=packet_id,
            manifest_id=plan.manifest_id,
            session_id=plan.session_id,
            next_action="review_evidence",
            message="Independent verification passed and recovered evidence is ready for review.",
        )

    local_store.save_approval(
        plan.manifest_id,
        decision="approve",
        rationale="Self-recovery auto-completed after independent verification passed.",
    )
    _update_session(
        local_store,
        plan.session_id,
        stage="completed",
        next_action="start_new_session",
        last_action="self_recovery_completed",
        recovery_reason=None,
        last_error=None,
        evidence_packet_id=packet_id,
        approval_manifest_id=plan.manifest_id,
    )
    return RecoveryExecutionResult(
        verification=verification,
        completed=True,
        dry_run=False,
        new_evidence_packet_id=packet_id,
        manifest_id=plan.manifest_id,
        session_id=plan.session_id,
        next_action="start_new_session",
        message="Builder session completed with recovered independent verification evidence.",
    )


def _save_recovery_evidence(
    *,
    local_store: Any,
    manifest_id: str,
    packet_id: str,
    source_evidence_packet_id: str | None,
    contract_path: str | None,
    contract: CompletionContract,
    verification: VerificationRunResult,
    old_evidence: dict[str, Any] | None,
    auto_complete: bool,
) -> str:
    local_store.save_evidence(
        manifest_id,
        packet_id=packet_id,
        summary="Self-recovery independent verification passed.",
        challenge="Recovered by rerunning completion-contract commands after the original builder run blocked.",
        triage_color="green",
        content={
            "recovery": {
                "auto_evidence": True,
                "auto_complete": auto_complete,
                "dry_run": False,
                "source_evidence_packet_id": source_evidence_packet_id,
                "completion_contract_path": contract_path,
            },
            "independent_verification": verification.to_dict(),
            "completion_contract": contract.to_dict(),
            "superseded_evidence": old_evidence,
        },
    )
    return packet_id


def _existing_evidence(local_store: Any, packet_id: str | None, manifest_id: str | None) -> dict[str, Any] | None:
    if packet_id:
        get_by_packet = getattr(local_store, "get_evidence_by_packet_id", None)
        if callable(get_by_packet):
            evidence = get_by_packet(packet_id)
            if isinstance(evidence, dict):
                return evidence
    if manifest_id:
        get_evidence = getattr(local_store, "get_evidence", None)
        if callable(get_evidence):
            evidence = get_evidence(manifest_id)
            if isinstance(evidence, dict):
                return evidence
    return None


def _update_session(local_store: Any, session_id: str | None, **kwargs: Any) -> None:
    if not session_id:
        return
    updater = getattr(local_store, "update_builder_session", None)
    if callable(updater):
        updater(session_id, **kwargs)
