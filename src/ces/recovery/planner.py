"""Build user-facing recovery plans for blocked builder sessions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ces.recovery.reconciler import reconcile_stale_builder_session


@dataclass(frozen=True)
class RecoveryPlan:
    session_id: str | None
    manifest_id: str | None
    evidence_packet_id: str | None
    blocked: bool
    can_run_auto_evidence: bool
    can_auto_complete: bool
    contract_path: str | None
    explanation: str
    next_commands: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["next_commands"] = list(self.next_commands)
        return data


def build_recovery_plan(project_root: Path, local_store: Any, *, mutate_stale: bool = True) -> RecoveryPlan:
    """Inspect the latest builder session and explain safe recovery actions."""
    reconciliation = reconcile_stale_builder_session(
        project_root=project_root,
        local_store=local_store,
        mutate=mutate_stale,
    )
    session = _latest_session(local_store)
    if session is None:
        return RecoveryPlan(
            session_id=None,
            manifest_id=None,
            evidence_packet_id=None,
            blocked=False,
            can_run_auto_evidence=False,
            can_auto_complete=False,
            contract_path=None,
            explanation='No builder session found. Start with `ces build --from-scratch "..."`.',
            next_commands=('ces build --from-scratch "describe the product"',),
        )

    manifest_id = _manifest_id_from_session(session)
    evidence_packet_id = getattr(session, "evidence_packet_id", None)
    stage = str(getattr(session, "stage", ""))
    blocked = stage == "blocked"
    contract_path = project_root / ".ces" / "completion-contract.json"
    contract_exists = contract_path.is_file()
    next_commands: list[str] = []
    explanation_parts: list[str] = []

    if reconciliation.stale:
        return RecoveryPlan(
            session_id=str(getattr(session, "session_id", "")),
            manifest_id=manifest_id,
            evidence_packet_id=evidence_packet_id,
            blocked=True,
            can_run_auto_evidence=False,
            can_auto_complete=False,
            contract_path=str(contract_path) if contract_exists else None,
            explanation=reconciliation.message or "Latest builder session was interrupted and is ready to retry.",
            next_commands=("ces continue", "ces status"),
        )

    if not blocked:
        explanation_parts.append(f"Latest builder session is not blocked; stage is `{stage or 'unknown'}`.")
        if stage != "completed":
            next_commands.append("ces status")
        return RecoveryPlan(
            session_id=str(getattr(session, "session_id", "")),
            manifest_id=manifest_id,
            evidence_packet_id=evidence_packet_id,
            blocked=False,
            can_run_auto_evidence=False,
            can_auto_complete=False,
            contract_path=str(contract_path) if contract_exists else None,
            explanation=" ".join(explanation_parts),
            next_commands=tuple(next_commands),
        )

    if _is_approved_merge_validation_block(session, local_store, manifest_id):
        return RecoveryPlan(
            session_id=str(getattr(session, "session_id", "")),
            manifest_id=manifest_id,
            evidence_packet_id=evidence_packet_id,
            blocked=False,
            can_run_auto_evidence=False,
            can_auto_complete=False,
            contract_path=str(contract_path) if contract_exists else None,
            explanation="Latest builder session is approved; merge validation did not apply a merge, but recovery is not required.",
            next_commands=("ces report builder",),
        )

    if contract_exists:
        explanation_parts.append(
            f"Latest builder session is blocked, but a completion contract exists at {contract_path}."
        )
        explanation_parts.append("CES can rerun independent verification and attach recovered evidence.")
        next_commands.append("ces recover --auto-evidence")
        next_commands.append("ces recover --auto-evidence --auto-complete")
    else:
        explanation_parts.append(
            "Latest builder session is blocked and no completion contract was found. "
            "Run `ces verify --json` to infer/write one, then rerun recovery."
        )
        next_commands.append("ces verify --json")
        next_commands.append("ces recover --dry-run")

    next_commands.append("ces why")
    return RecoveryPlan(
        session_id=str(getattr(session, "session_id", "")),
        manifest_id=manifest_id,
        evidence_packet_id=evidence_packet_id,
        blocked=True,
        can_run_auto_evidence=contract_exists,
        # Whether it actually can complete is only known after verification passes.
        can_auto_complete=False,
        contract_path=str(contract_path) if contract_exists else None,
        explanation=" ".join(explanation_parts),
        next_commands=tuple(next_commands),
    )


def _latest_session(local_store: Any) -> Any | None:
    ensure_latest = getattr(local_store, "ensure_latest_builder_session", None)
    if callable(ensure_latest):
        return ensure_latest()
    get_latest = getattr(local_store, "get_latest_builder_session", None)
    if callable(get_latest):
        return get_latest()
    return None


def _manifest_id_from_session(session: Any) -> str | None:
    for attr in ("approval_manifest_id", "runtime_manifest_id", "manifest_id"):
        value = getattr(session, attr, None)
        if value:
            return str(value)
    return None


def _is_approved_merge_validation_block(session: Any, local_store: Any, manifest_id: str | None) -> bool:
    """Return True only for legacy approved review-state merge blocks."""
    if getattr(session, "last_action", None) != "merge_blocked":
        return False
    if not manifest_id:
        return False
    last_error = str(getattr(session, "last_error", "")).casefold()
    if last_error not in {"workflow state has not reached merge-ready", "review_complete"}:
        return False
    get_approval = getattr(local_store, "get_approval", None)
    if not callable(get_approval):
        return False
    approval = get_approval(manifest_id)
    return str(getattr(approval, "decision", "")).casefold() == "approve"
