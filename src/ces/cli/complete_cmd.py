"""Manual builder-session completion/reconciliation command."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.panel import Panel

from ces.cli._async import run_async
from ces.cli._context import find_project_root
from ces.cli._errors import handle_error
from ces.cli._factory import get_services
from ces.cli._output import console
from ces.shared.enums import WorkflowState


def _manifest_id_from_session(session: Any, explicit_manifest_id: str | None) -> str:
    manifest_id = explicit_manifest_id or getattr(session, "approval_manifest_id", None)
    manifest_id = manifest_id or getattr(session, "runtime_manifest_id", None)
    manifest_id = manifest_id or getattr(session, "manifest_id", None)
    if not manifest_id:
        raise RuntimeError("No manifest id found for the latest builder session; pass --manifest-id.")
    return str(manifest_id)


@run_async
async def complete_builder_session(
    manifest_id: str | None = typer.Option(
        None,
        "--manifest-id",
        "-m",
        help="Manifest to reconcile; defaults to the latest builder session manifest.",
    ),
    evidence: Path | None = typer.Option(
        None,
        "--evidence",
        help="Path to operator-supplied verification evidence for externally completed work.",
    ),
    rationale: str = typer.Option(
        "Completed externally by operator",
        "--rationale",
        help="Audit rationale for marking the builder session complete.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt.",
    ),
) -> None:
    """Mark externally completed builder work complete with an audit trail."""
    try:
        project_root = find_project_root()
        async with get_services(project_root=project_root) as services:
            local_store = services["local_store"]
            session = local_store.get_latest_builder_session()
            if session is None:
                raise RuntimeError("No builder session found. Start with `ces build`.")
            resolved_manifest_id = _manifest_id_from_session(session, manifest_id)
            evidence_packet_id = getattr(session, "evidence_packet_id", None)
            if evidence is not None:
                evidence_path = evidence.resolve()
                if not evidence_path.exists():
                    raise typer.BadParameter(f"Evidence path does not exist: {evidence_path}")
                evidence_packet_id = f"EP-manual-{session.session_id}"
                local_store.save_evidence(
                    resolved_manifest_id,
                    packet_id=evidence_packet_id,
                    summary="Manual completion evidence attached by operator.",
                    challenge="External/manual recovery path; runtime did not produce this evidence.",
                    triage_color="green",
                    content={
                        "manual_completion": True,
                        "evidence_path": str(evidence_path),
                        "evidence_text": evidence_path.read_text(encoding="utf-8", errors="replace"),
                        "rationale": rationale,
                    },
                )
            if not yes and not typer.confirm(
                f"Mark builder session {session.session_id} complete for {resolved_manifest_id}?",
                default=False,
            ):
                raise typer.Abort
            local_store.save_approval(resolved_manifest_id, decision="approve", rationale=rationale)
            manifest_manager = services.get("manifest_manager")
            if manifest_manager is not None and hasattr(manifest_manager, "get_manifest"):
                manifest = await manifest_manager.get_manifest(resolved_manifest_id)
                if manifest is not None:
                    updated_manifest = manifest.model_copy(update={"workflow_state": WorkflowState.APPROVED})
                    await manifest_manager.save_manifest(updated_manifest)
            audit_ledger = services.get("audit_ledger")
            if audit_ledger is not None and hasattr(audit_ledger, "record_approval"):
                await audit_ledger.record_approval(
                    manifest_id=resolved_manifest_id,
                    actor="operator",
                    decision="approve",
                    rationale=rationale,
                )
            local_store.update_builder_session(
                session.session_id,
                stage="completed",
                next_action="start_new_session",
                last_action="manual_completion_reconciled",
                recovery_reason=None,
                last_error=None,
                evidence_packet_id=evidence_packet_id,
                approval_manifest_id=resolved_manifest_id,
            )
            console.print(
                Panel(
                    f"Builder session {session.session_id} reconciled as complete.\n"
                    f"Manifest: {resolved_manifest_id}\n"
                    f"Evidence packet: {evidence_packet_id or '(existing/none)'}",
                    title="[green]Manual Completion Reconciled[/green]",
                    border_style="green",
                )
            )
    except typer.Abort:
        raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as exc:
        handle_error(exc)
