"""Implementation of the ``ces approve`` command.

Shows triage color and evidence summary, then prompts for interactive
approval/rejection. Records the decision in the audit ledger.

Threat mitigations:
- T-06-09: Approval actor recorded from local CES/git/OS identity
- T-06-10: Approval recorded in append-only HMAC-chained audit ledger
- T-06-11: Every approval/rejection logged with timestamp, actor, evidence ID

Exports:
    approve_evidence: Typer command function for ``ces approve``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.panel import Panel
from rich.table import Table

import ces.cli._output as _output_mod
from ces.cli._async import run_async
from ces.cli._builder_handoff import resolve_manifest_id
from ces.cli._builder_report import (
    load_matching_builder_run_report,
    serialize_builder_run_report,
    summarize_builder_run,
)
from ces.cli._context import find_project_root, get_project_id
from ces.cli._errors import GovernanceViolationError, handle_error
from ces.cli._evidence_handoff import load_persisted_evidence_view
from ces.cli._factory import get_services
from ces.cli._output import console, set_json_mode
from ces.cli.ownership import resolve_actor
from ces.control.models.manifest import TaskManifest
from ces.control.services.approval_pipeline import persisted_governance_blocks_merge, required_gate_type_for_risk
from ces.control.services.evidence_integrity import compute_reviewed_evidence_hash
from ces.control.services.workflow_engine import WorkflowEngine
from ces.execution.providers.bootstrap import resolve_primary_provider
from ces.shared.enums import ActorType, GateType, ReviewSubState, WorkflowState

# Color mapping for triage display
_TRIAGE_COLOR_STYLES = {
    "green": "[green]GREEN[/green]",
    "yellow": "[yellow]YELLOW[/yellow]",
    "red": "[red]RED[/red]",
}


def _has_unanimous_zero_findings(review_data: dict | None) -> bool:
    return bool(review_data is not None and review_data.get("unanimous_zero_findings"))


def _persisted_governance_blocks_merge(evidence_payload: dict | None, *, merge_allowed: bool) -> bool:
    return persisted_governance_blocks_merge(evidence_payload, merge_allowed=merge_allowed)


def _coerce_workflow_state_value(value: object) -> str:
    candidate = getattr(value, "value", value)
    if isinstance(candidate, str) and candidate in {state.value for state in WorkflowState}:
        return candidate
    return WorkflowState.QUEUED.value


def _with_workflow_state(manifest: object, workflow_state: object) -> object:
    if isinstance(manifest, TaskManifest):
        return manifest.model_copy(update={"workflow_state": workflow_state})
    try:
        setattr(manifest, "workflow_state", workflow_state)
    except (AttributeError, TypeError):
        pass
    return manifest


async def _ensure_signed_manifest(manager: object, manifest: object) -> object:
    if not isinstance(manifest, TaskManifest):
        return manifest
    if manifest.content_hash and manifest.signature:
        return manifest
    signed_manifest = await manager.sign_manifest(manifest)  # type: ignore[attr-defined]
    await manager.save_manifest(signed_manifest)  # type: ignore[attr-defined]
    return signed_manifest


async def _advance_builder_handoff_to_review(
    *,
    manifest: object,
    manager: object,
    workflow_engine: WorkflowEngine,
    manifest_state: str,
    actor: str,
) -> tuple[object, str]:
    """Recover queued/in_flight builder handoffs before approval.

    Builder-first runs can leave the latest manifest in a default queued state
    inside the local snapshot. When `ces approve` is invoked without an
    explicit evidence ID, advance the workflow the same way the builder flow
    would have: queued -> in_flight -> under_review.
    """
    current_manifest = manifest
    current_state = manifest_state

    if current_state == WorkflowState.QUEUED.value:
        started_state = await workflow_engine.start(actor=actor, actor_type=ActorType.HUMAN)
        if _coerce_workflow_state_value(started_state) == WorkflowState.QUEUED.value:
            started_state = WorkflowState.IN_FLIGHT
        current_manifest = _with_workflow_state(current_manifest, started_state)
        await manager.save_manifest(current_manifest)
        current_state = _coerce_workflow_state_value(started_state)

    if current_state == WorkflowState.IN_FLIGHT.value:
        review_state = await workflow_engine.submit_for_review(actor=actor, actor_type=ActorType.HUMAN)
        if _coerce_workflow_state_value(review_state) != WorkflowState.UNDER_REVIEW.value:
            review_state = WorkflowState.UNDER_REVIEW
        current_manifest = _with_workflow_state(current_manifest, review_state)
        await manager.save_manifest(current_manifest)
        current_state = _coerce_workflow_state_value(review_state)

    return current_manifest, current_state


@run_async
async def approve_evidence(
    evidence_packet_id: str | None = typer.Argument(
        None,
        help="Evidence packet ID to approve or reject. Defaults to the current builder session evidence when omitted.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt and approve",
    ),
    reason: str = typer.Option(
        "",
        "--reason",
        "-r",
        help="Rejection reason (used when rejecting)",
    ),
    refresh: bool = typer.Option(
        False,
        "--refresh",
        help="Rerun sensors/provider summary instead of reading persisted evidence where available.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output approval result as JSON. Equivalent to `ces --json approve`.",
    ),
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Repo/CES project root to operate on; defaults to cwd/.ces discovery.",
    ),
) -> None:
    """Review and approve or reject evidence.

    Shows the triage color, evidence summary, and prompts for
    approval. Records the decision in the audit ledger.
    """
    if json_output:
        set_json_mode(True)
    try:
        resolved_project_root = find_project_root(project_root)
        project_id = get_project_id(resolved_project_root)

        services_context = (
            get_services(project_root=resolved_project_root) if project_root is not None else get_services()
        )
        async with services_context as services:
            actor = resolve_actor()
            manager = services["manifest_manager"]
            evidence_synthesizer = services["evidence_synthesizer"]
            audit_ledger = services.get("audit_ledger")
            local_store = services.get("local_store")
            resolved_manifest_id, handoff_context = resolve_manifest_id(
                provided_ref=evidence_packet_id,
                local_store=local_store,
                missing_message=("Evidence packet ID is required when CES cannot resolve a current builder session."),
            )
            builder_handoff = evidence_packet_id is None
            resolved_evidence_packet_id = (
                evidence_packet_id
                or (handoff_context.evidence_packet_id if handoff_context is not None else None)
                or resolved_manifest_id
            )
            builder_run = load_matching_builder_run_report(
                local_store,
                manifest_id=resolved_manifest_id,
            )

            # Load persisted review findings from previous ces review
            review_data = None
            if local_store is not None:
                review_data = local_store.get_review_findings(resolved_manifest_id)

            # Look up evidence packet and manifest
            manifest = await manager.get_manifest(resolved_manifest_id)
            if manifest is None:
                raise typer.BadParameter(f"Evidence packet not found: {resolved_evidence_packet_id}")
            manifest = await _ensure_signed_manifest(manager, manifest)
            manifest_state = _coerce_workflow_state_value(getattr(manifest, "workflow_state", None))
            if manifest_state == WorkflowState.MERGED.value:
                raise ValueError(
                    "Manifest is already merged; approval has already completed for this builder run. "
                    "Use ces report builder for historical evidence; use ces status for current state; "
                    "use ces audit for the governance ledger."
                )

            # Run triage for color display
            risk_tier = manifest.risk_tier
            trust_status = getattr(manifest, "trust_status", None)
            if trust_status is None:
                from ces.shared.enums import TrustStatus

                trust_status = TrustStatus.CANDIDATE

            persisted_evidence = None
            persisted_evidence_payload = None
            if not refresh:
                persisted_evidence = load_persisted_evidence_view(
                    local_store=local_store,
                    manifest_id=manifest.manifest_id,
                    evidence_packet_id=resolved_evidence_packet_id,
                )
                if local_store is not None:
                    if resolved_evidence_packet_id:
                        get_by_packet = getattr(local_store, "get_evidence_by_packet_id", None)
                        if callable(get_by_packet):
                            persisted_evidence_payload = get_by_packet(resolved_evidence_packet_id)
                    if persisted_evidence_payload is None:
                        get_evidence = getattr(local_store, "get_evidence", None)
                        if callable(get_evidence):
                            persisted_evidence_payload = get_evidence(manifest.manifest_id)

            if persisted_evidence is not None:
                color_value = persisted_evidence.triage_color
                summary_preview = persisted_evidence.summary
            else:
                # Run sensors for triage input (EVID-06 fix)
                sensor_orchestrator = services["sensor_orchestrator"]
                sensor_project_root = find_project_root(project_root)
                sensor_context = {
                    "manifest_id": manifest.manifest_id,
                    "risk_tier": risk_tier.value if hasattr(risk_tier, "value") else str(risk_tier),
                    "affected_files": getattr(manifest, "affected_files", []) or [],
                    "project_root": str(sensor_project_root),
                    "description": getattr(manifest, "description", ""),
                    "change_class": str(getattr(manifest.change_class, "value", ""))
                    if hasattr(manifest, "change_class")
                    else "",
                }
                try:
                    pack_results = await sensor_orchestrator.run_all(sensor_context)
                    sensor_results: list = []
                    for pack in pack_results:
                        sensor_results.extend(pack.results)
                except RuntimeError:
                    # Kill switch active -- fall back to empty sensor results
                    sensor_results = []

                triage_result = await evidence_synthesizer.triage(
                    risk_tier=risk_tier,
                    trust_status=trust_status,
                    sensor_results=sensor_results,
                )

                # Resolve LLM provider for summary generation (EVID-04 fix)
                provider_registry = services.get("provider_registry")
                settings = services["settings"]
                llm_provider = (
                    resolve_primary_provider(provider_registry, settings.default_model_id)
                    if provider_registry is not None
                    else None
                )

                evidence_context: dict = {
                    "manifest_id": manifest.manifest_id,
                    "description": getattr(manifest, "description", "N/A"),
                    "risk_tier": risk_tier.value if hasattr(risk_tier, "value") else str(risk_tier),
                    "triage_color": triage_result.color.value,
                }
                # Enrich evidence context with review findings
                if review_data is not None:
                    evidence_context["review_findings"] = review_data["findings"]
                    evidence_context["critical_count"] = review_data["critical_count"]
                    evidence_context["high_count"] = review_data["high_count"]

                # Get evidence summary
                summary_slots = await evidence_synthesizer.format_summary_slots(
                    provider=llm_provider,
                    model_id=settings.default_model_id,
                    evidence_context=evidence_context,
                )
                summary_lines = summary_slots.summary.strip().split("\n")
                summary_preview = "\n".join(summary_lines[:5])
                color_value = triage_result.color.value

            # Triage color display
            color_display = _TRIAGE_COLOR_STYLES.get(color_value, f"[bold]{color_value.upper()}[/bold]")

            manifest_id = manifest.manifest_id
            description = getattr(manifest, "description", "N/A")
            unanimous_zero_findings = _has_unanimous_zero_findings(review_data)

            # Determine approval decision
            if yes:
                if unanimous_zero_findings:
                    raise GovernanceViolationError(
                        "Cannot use --yes after a unanimous-zero review escalation. "
                        "Rerun `ces approve` without --yes and make an explicit human decision."
                    )
                approved = True
            else:
                # Show evidence panel for review
                if not _output_mod._json_mode:
                    review_content = (
                        f"Triage: {color_display}\n"
                        f"Manifest: {manifest_id}\n"
                        f"Description: {description}\n\n"
                        f"Evidence Summary:\n{summary_preview}"
                    )
                    if builder_run is not None:
                        review_content += "\n\n" + "\n".join(summarize_builder_run(builder_run))
                    console.print(
                        Panel(
                            review_content,
                            title="Evidence Review",
                            border_style=color_value if color_value in ("green", "yellow", "red") else "white",
                        )
                    )

                    # Display persisted review findings from ces review
                    if review_data is not None and review_data["findings"]:
                        severity_styles = {
                            "critical": "bold red",
                            "high": "red",
                            "medium": "yellow",
                            "low": "cyan",
                            "info": "dim",
                        }
                        findings_table = Table(
                            title=f"Review Findings ({len(review_data['findings'])})",
                        )
                        findings_table.add_column("Sev", width=8)
                        findings_table.add_column("File", width=30)
                        findings_table.add_column("Title", width=40)
                        findings_table.add_column("Role", width=12)
                        for f in review_data["findings"]:
                            style = severity_styles.get(f["severity"], "")
                            location = f["file_path"] or ""
                            if f["line_number"] is not None:
                                location += f":{f['line_number']}"
                            findings_table.add_row(
                                f["severity"].upper(),
                                location,
                                f["title"],
                                f["reviewer_role"],
                                style=style,
                            )
                        console.print(findings_table)
                    elif review_data is not None:
                        console.print("[green]No review findings.[/green]")
                    if unanimous_zero_findings:
                        console.print(
                            "[yellow]Warning: all reviewers reported zero findings. "
                            "Explicit human review is still required before approval.[/yellow]"
                        )

                prompt = "Approve this evidence?"
                if unanimous_zero_findings:
                    prompt = "Approve this evidence after explicit human review of the unanimous-zero escalation?"
                approved = typer.confirm(prompt, default=False)

            # Resolve workflow state before recording any irreversible audit decision.
            decision_str = "approved" if approved else "rejected"
            rationale = reason if not approved and reason else ("Approved via CLI" if approved else "Rejected via CLI")
            engine = WorkflowEngine(
                manifest_id=manifest_id,
                audit_ledger=audit_ledger,
                initial_state=manifest_state,
                initial_review_sub_state=None,
            )

            if approved:
                if builder_handoff and manifest_state in {
                    WorkflowState.QUEUED.value,
                    WorkflowState.IN_FLIGHT.value,
                }:
                    manifest, manifest_state = await _advance_builder_handoff_to_review(
                        manifest=manifest,
                        manager=manager,
                        workflow_engine=engine,
                        manifest_state=manifest_state,
                        actor=actor,
                    )
                if manifest_state == WorkflowState.MERGED.value:
                    raise ValueError(
                        "Manifest is already merged; approval has already completed for this builder run. "
                        "Use ces report builder for historical evidence; use ces status for current state; "
                        "use ces audit for the governance ledger."
                    )
                if manifest_state not in {WorkflowState.UNDER_REVIEW.value, WorkflowState.APPROVED.value}:
                    raise ValueError(
                        f"Manifest must be under_review or approved before CLI approval; got {manifest_state}"
                    )
            else:
                if builder_handoff and manifest_state in {
                    WorkflowState.QUEUED.value,
                    WorkflowState.IN_FLIGHT.value,
                }:
                    manifest, manifest_state = await _advance_builder_handoff_to_review(
                        manifest=manifest,
                        manager=manager,
                        workflow_engine=engine,
                        manifest_state=manifest_state,
                        actor=actor,
                    )
                if manifest_state == WorkflowState.APPROVED.value:
                    raise ValueError(f"Manifest must be under_review to reject via CLI approval; got {manifest_state}")
                if manifest_state != WorkflowState.UNDER_REVIEW.value:
                    raise ValueError(f"Manifest must be under_review to reject via CLI approval; got {manifest_state}")

            # Record decision in audit ledger (T-06-09, T-06-10, T-06-11)
            await audit_ledger.record_approval(
                manifest_id=manifest_id,
                actor=actor,
                decision=decision_str,
                rationale=rationale,
                project_id=project_id,
            )

            # Merge validation and workflow transitions
            merge_decision = None
            governance_blocks_merge = False
            if approved:
                review_sub_state_value = (
                    ReviewSubState.DECISION.value if review_data is not None else ReviewSubState.PENDING_REVIEW.value
                )
                workflow_state_for_merge = manifest_state
                if (
                    manifest_state == WorkflowState.UNDER_REVIEW.value
                    and review_sub_state_value == ReviewSubState.DECISION.value
                ):
                    approved_state = await engine.complete_review(actor=actor, actor_type=ActorType.HUMAN)
                    manifest = _with_workflow_state(manifest, approved_state)
                    await manager.save_manifest(manifest)
                    workflow_state_for_merge = _coerce_workflow_state_value(approved_state)

                # MergeController: validate merge preconditions (MERGE-01, MERGE-02, MERGE-03)
                merge_controller = services.get("merge_controller")

                # Derive gate type from risk tier
                risk_value = risk_tier.value if hasattr(risk_tier, "value") else str(risk_tier)
                required_gate = required_gate_type_for_risk(risk_value)
                if unanimous_zero_findings and required_gate == GateType.AGENT:
                    required_gate = GateType.HYBRID
                actual_gate = GateType.HUMAN

                if persisted_evidence_payload is not None:
                    evidence_packet_dict = dict(persisted_evidence_payload)
                else:
                    evidence_packet_dict = {
                        "manifest_id": manifest_id,
                        "manifest_hash": getattr(manifest, "content_hash", ""),
                        "summary": summary_preview,
                        "triage_color": color_value,
                    }
                # Populate decision views from review findings when building a fresh reviewed packet.
                if persisted_evidence_payload is None and review_data is not None:
                    decision_views = evidence_synthesizer.assemble_decision_views_from_review(review_data)
                    evidence_packet_dict["decision_views"] = {v.position: v.content for v in decision_views}
                if "reviewed_evidence_hash" not in evidence_packet_dict:
                    evidence_packet_dict["reviewed_evidence_hash"] = compute_reviewed_evidence_hash(
                        evidence_packet_dict
                    )
                merge_decision = await merge_controller.validate_merge(
                    manifest_id=manifest_id,
                    manifest_expires_at=getattr(manifest, "expires_at", datetime.now(timezone.utc)),
                    manifest_content_hash=getattr(manifest, "content_hash", ""),
                    manifest_risk_tier=risk_value,
                    manifest_bc=getattr(manifest, "behavior_confidence", "BC2"),
                    evidence_packet=evidence_packet_dict,
                    evidence_manifest_hash=evidence_packet_dict.get("manifest_hash"),
                    required_gate_type=required_gate,
                    actual_gate_type=actual_gate,
                    review_sub_state=review_sub_state_value,
                    workflow_state=workflow_state_for_merge,
                )

                governance_blocks_merge = _persisted_governance_blocks_merge(
                    evidence_packet_dict,
                    merge_allowed=merge_decision.allowed,
                )
                if merge_decision.allowed and not governance_blocks_merge:
                    # Transition approved -> merged
                    merged_state = await engine.approve_merge(actor=actor, actor_type=ActorType.HUMAN)
                    manifest = _with_workflow_state(manifest, merged_state)
                    await manager.save_manifest(manifest)
            else:
                rejected_state = await engine.reject(
                    actor=actor,
                    actor_type=ActorType.HUMAN,
                    rationale=rationale,
                )
                manifest = _with_workflow_state(manifest, rejected_state)
                await manager.save_manifest(manifest)

            # JSON mode output
            if _output_mod._json_mode:
                data = {
                    "evidence_packet_id": resolved_evidence_packet_id,
                    "manifest_id": manifest_id,
                    "decision": decision_str,
                    "triage_color": color_value,
                    "rationale": rationale,
                }
                if review_data is not None:
                    data["review_findings"] = review_data["findings"]
                    data["critical_count"] = review_data["critical_count"]
                    data["high_count"] = review_data["high_count"]
                    data["unanimous_zero_findings"] = unanimous_zero_findings
                if merge_decision is not None:
                    data["merge_allowed"] = merge_decision.allowed and not governance_blocks_merge
                    data["merge_reason"] = "governance_blocked" if governance_blocks_merge else merge_decision.reason
                if builder_run is not None:
                    data["builder_run"] = serialize_builder_run_report(builder_run)
                typer.echo(json.dumps(data, indent=2))
                return

            # Rich mode display
            if approved:
                console.print(
                    Panel(
                        f"Evidence {resolved_evidence_packet_id} approved.\n"
                        f"Manifest: {manifest_id}\n"
                        f"Recorded in audit ledger.",
                        title="[green]Evidence Approved[/green]",
                        border_style="green",
                    )
                )
                # Show merge validation result
                if merge_decision is not None:
                    if merge_decision.allowed and not governance_blocks_merge:
                        console.print(
                            Panel(
                                "All merge precondition checks passed.",
                                title="[green]Merge Validation Passed[/green]",
                                border_style="green",
                            )
                        )
                    elif merge_decision.allowed and governance_blocks_merge:
                        console.print(
                            Panel(
                                "Approval was recorded, but persisted evidence contains blocking governance findings.",
                                title="[red]Governance Blocked[/red]",
                                border_style="red",
                            )
                        )
                    else:
                        console.print(
                            Panel(
                                f"Merge blocked: {merge_decision.reason}",
                                title="[red]Merge Blocked[/red]",
                                border_style="red",
                            )
                        )
            else:
                reject_msg = f"Evidence {resolved_evidence_packet_id} rejected."
                if reason:
                    reject_msg += f"\nReason: {reason}"
                reject_msg += f"\nManifest: {manifest_id}\nRecorded in audit ledger."
                console.print(
                    Panel(
                        reject_msg,
                        title="[yellow]Evidence Rejected[/yellow]",
                        border_style="yellow",
                    )
                )

    except (typer.BadParameter, ValueError) as exc:
        handle_error(exc)
    except (ConnectionError, RuntimeError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)
