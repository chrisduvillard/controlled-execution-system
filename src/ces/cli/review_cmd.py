"""Implementation of the ``ces review`` command.

Runs the review pipeline for a task manifest and displays evidence summary
with 10-line summary and 3-line challenge per EVID-04.

Supports --verbose/--full for complete evidence packet and --json for
machine-readable output.

Exports:
    review_task: Typer command function for ``ces review``.
"""

from __future__ import annotations

import json

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
from ces.cli._errors import handle_error
from ces.cli._factory import get_services
from ces.cli._output import console
from ces.control.services.workflow_engine import WorkflowEngine
from ces.execution.providers.bootstrap import resolve_primary_provider
from ces.shared.base import CESBaseModel
from ces.shared.enums import ActorType, GateType, WorkflowState


def _required_gate_type_for_risk(risk_tier_value: str) -> GateType:
    if risk_tier_value == "A":
        return GateType.HUMAN
    if risk_tier_value == "B":
        return GateType.HYBRID
    return GateType.AGENT


def _coerce_workflow_state_value(value: object) -> str:
    candidate = getattr(value, "value", value)
    if isinstance(candidate, str) and candidate in {state.value for state in WorkflowState}:
        return candidate
    return WorkflowState.QUEUED.value


def _with_workflow_state(manifest: object, state: WorkflowState) -> object:
    if isinstance(manifest, CESBaseModel) and callable(getattr(manifest, "model_copy", None)):
        return manifest.model_copy(update={"workflow_state": state})
    setattr(manifest, "workflow_state", state)
    return manifest


async def _advance_builder_handoff_to_review(
    *,
    manifest: object,
    manager: object,
    workflow_engine: WorkflowEngine,
    manifest_state: str,
) -> tuple[object, str]:
    """Advance builder-handoff manifests from queued/in_flight into review.

    The builder-first flow can hand off a manifest before the workflow state has
    been persisted beyond the default queued value. Expert review commands
    should recover that state only when the manifest target came from the
    current builder snapshot rather than an explicit user-supplied manifest ID.
    """
    current_manifest = manifest
    current_state = manifest_state

    if current_state == WorkflowState.QUEUED.value:
        started_state = await workflow_engine.start(actor="cli-user", actor_type=ActorType.HUMAN)
        if _coerce_workflow_state_value(started_state) == WorkflowState.QUEUED.value:
            started_state = WorkflowState.IN_FLIGHT
        current_manifest = _with_workflow_state(current_manifest, started_state)
        await manager.save_manifest(current_manifest)
        current_state = _coerce_workflow_state_value(started_state)

    if current_state == WorkflowState.IN_FLIGHT.value:
        review_state = await workflow_engine.submit_for_review(actor="cli-user", actor_type=ActorType.HUMAN)
        if _coerce_workflow_state_value(review_state) != WorkflowState.UNDER_REVIEW.value:
            review_state = WorkflowState.UNDER_REVIEW
        current_manifest = _with_workflow_state(current_manifest, review_state)
        await manager.save_manifest(current_manifest)
        current_state = _coerce_workflow_state_value(review_state)

    return current_manifest, current_state


@run_async
async def review_task(
    manifest_id: str | None = typer.Argument(
        None,
        help="Manifest ID to review. Defaults to the current builder session manifest when omitted.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose/--brief",
        help="Show full evidence packet",
    ),
    full: bool = typer.Option(
        False,
        "--full",
        help="Show complete evidence packet contents",
    ),
) -> None:
    """Run the review pipeline and display evidence summary.

    Shows 10-line summary and 3-line challenge per EVID-04.
    Use --verbose or --full for complete evidence details.
    """
    try:
        find_project_root()
        project_id = get_project_id()

        async with get_services() as services:
            manager = services["manifest_manager"]
            review_router = services["review_router"]
            evidence_synthesizer = services["evidence_synthesizer"]
            local_store = services.get("local_store")
            resolved_manifest_id, _builder_context = resolve_manifest_id(
                provided_ref=manifest_id,
                local_store=local_store,
                missing_message=("Manifest ID is required when CES cannot resolve a current builder session."),
            )
            builder_handoff = manifest_id is None
            builder_run = load_matching_builder_run_report(
                local_store,
                manifest_id=resolved_manifest_id,
            )

            # Look up the manifest
            manifest = await manager.get_manifest(resolved_manifest_id)
            if manifest is None:
                raise typer.BadParameter(f"Manifest not found: {resolved_manifest_id}")

            manifest_state = _coerce_workflow_state_value(getattr(manifest, "workflow_state", None))

            # WorkflowEngine: honor the persisted workflow state instead of
            # force-starting review from in_flight.
            audit_ledger = services.get("audit_ledger")
            wf_engine = WorkflowEngine(
                manifest_id=resolved_manifest_id,
                audit_ledger=audit_ledger,
                initial_state=manifest_state,
            )
            if builder_handoff and manifest_state in {
                WorkflowState.QUEUED.value,
                WorkflowState.IN_FLIGHT.value,
            }:
                manifest, manifest_state = await _advance_builder_handoff_to_review(
                    manifest=manifest,
                    manager=manager,
                    workflow_engine=wf_engine,
                    manifest_state=manifest_state,
                )
            elif manifest_state == WorkflowState.IN_FLIGHT.value:
                review_state = await wf_engine.submit_for_review(actor="cli-user", actor_type=ActorType.HUMAN)
                manifest = _with_workflow_state(manifest, review_state)
                await manager.save_manifest(manifest)
                manifest_state = review_state.value
            elif manifest_state == WorkflowState.MERGED.value:
                raise ValueError(
                    "Manifest is already merged; review has already completed for this builder run. "
                    "Use ces report builder for historical evidence; use ces status for current state; "
                    "use ces audit for the governance ledger."
                )
            elif manifest_state != WorkflowState.UNDER_REVIEW.value:
                raise ValueError(
                    f"Manifest must be in_flight or under_review before review can run; got {manifest_state}"
                )

            # Determine review type from risk tier
            risk_tier_value = (
                manifest.risk_tier.value if hasattr(manifest.risk_tier, "value") else str(manifest.risk_tier)
            )

            # Get builder info (with defaults for testing)
            builder_agent_id = getattr(manifest, "builder_agent_id", "agent-builder-default")
            builder_model_id = getattr(manifest, "builder_model_id", "claude-sonnet-4-6")

            # Route review based on risk tier
            if risk_tier_value == "A":
                assignments = review_router.assign_triad(
                    builder_agent_id=builder_agent_id,
                    builder_model_id=builder_model_id,
                )
            else:
                single = review_router.assign_single(
                    builder_agent_id=builder_agent_id,
                    builder_model_id=builder_model_id,
                )
                assignments = [single]

            # Extract git diff for code review
            from ces.harness.services.diff_extractor import DiffExtractor

            diff_context = await DiffExtractor.extract_diff(
                base_ref="HEAD~1",
                working_dir=find_project_root(),
            )

            # Dispatch review to LLM reviewers (if executor is wired)
            aggregated_review = None
            manifest_context = {
                "description": manifest.description,
                "risk_tier": risk_tier_value,
                "behavior_confidence": (
                    manifest.behavior_confidence.value
                    if hasattr(manifest.behavior_confidence, "value")
                    else str(manifest.behavior_confidence)
                ),
            }
            try:
                aggregated_review = await review_router.dispatch_review(
                    assignments=assignments,
                    diff_context=diff_context,
                    manifest_context=manifest_context,
                    current_gate_type=_required_gate_type_for_risk(risk_tier_value),
                )
            except RuntimeError:
                pass  # No review executor configured; fall through to summary-only

            # Persist findings so they survive between review and approve
            if aggregated_review is not None and local_store is not None:
                local_store.save_review_findings(resolved_manifest_id, aggregated_review)

            # Resolve LLM provider for summary generation (EVID-04 fix)
            provider_registry = services.get("provider_registry")
            settings = services["settings"]
            llm_provider = (
                resolve_primary_provider(provider_registry, settings.default_model_id)
                if provider_registry is not None
                else None
            )

            evidence_context: dict = {
                "manifest_id": resolved_manifest_id,
                "description": manifest.description,
                "risk_tier": risk_tier_value,
                "assignments": [{"role": a.role.value, "model_id": a.model_id} for a in assignments],
            }
            # Include review findings in evidence context for richer summaries
            if aggregated_review is not None:
                evidence_context["review_findings"] = [
                    {
                        "severity": f.severity.value,
                        "title": f.title,
                        "file_path": f.file_path,
                        "description": f.description,
                    }
                    for f in aggregated_review.all_findings
                ]
                evidence_context["critical_count"] = aggregated_review.critical_count
                evidence_context["high_count"] = aggregated_review.high_count

            # Get summary slots
            summary_slots = await evidence_synthesizer.format_summary_slots(
                provider=llm_provider,
                model_id=settings.default_model_id,
                evidence_context=evidence_context,
            )

            # Extract 10-line summary
            summary_lines = summary_slots.summary.strip().split("\n")
            summary_10 = "\n".join(summary_lines[:10])

            # Extract 3-line challenge
            challenge_lines = summary_slots.challenge.strip().split("\n")
            challenge_3 = "\n".join(challenge_lines[:3])

            # JSON mode
            if _output_mod._json_mode:
                data = {
                    "manifest_id": resolved_manifest_id,
                    "risk_tier": risk_tier_value,
                    "summary": summary_10,
                    "challenge": challenge_3,
                    "assignments": [
                        {
                            "role": a.role.value,
                            "model_id": a.model_id,
                            "agent_id": a.agent_id,
                        }
                        for a in assignments
                    ],
                }
                if aggregated_review is not None:
                    data["findings"] = [
                        {
                            "finding_id": f.finding_id,
                            "severity": f.severity.value,
                            "category": f.category,
                            "file_path": f.file_path,
                            "line_number": f.line_number,
                            "title": f.title,
                            "description": f.description,
                            "recommendation": f.recommendation,
                            "confidence": f.confidence,
                        }
                        for f in aggregated_review.all_findings
                    ]
                    data["critical_count"] = aggregated_review.critical_count
                    data["high_count"] = aggregated_review.high_count
                    data["disagreements"] = list(aggregated_review.disagreements)
                    data["unanimous_zero_findings"] = aggregated_review.unanimous_zero_findings
                if verbose or full:
                    data["full_summary"] = summary_slots.summary
                    data["full_challenge"] = summary_slots.challenge
                if builder_run is not None:
                    data["builder_run"] = serialize_builder_run_report(builder_run)
                typer.echo(json.dumps(data, indent=2))
                return

            # Rich mode: display review results
            if builder_run is not None:
                console.print(
                    Panel(
                        "\n".join(summarize_builder_run(builder_run)),
                        title="Builder Truth",
                        border_style="cyan",
                    )
                )

            # Reviewer assignments table
            assign_table = Table(title="Review Assignments")
            assign_table.add_column("Role")
            assign_table.add_column("Model")
            assign_table.add_column("Agent ID")
            for a in assignments:
                assign_table.add_row(a.role.value, a.model_id, a.agent_id)
            console.print(assign_table)

            # Review findings table (if dispatch produced findings)
            if aggregated_review is not None and aggregated_review.all_findings:
                severity_styles = {
                    "critical": "bold red",
                    "high": "red",
                    "medium": "yellow",
                    "low": "cyan",
                    "info": "dim",
                }
                findings_table = Table(title=f"Review Findings ({len(aggregated_review.all_findings)})")
                findings_table.add_column("Sev", width=8)
                findings_table.add_column("File", width=30)
                findings_table.add_column("Title", width=40)
                findings_table.add_column("Role", width=12)
                for f in aggregated_review.all_findings:
                    style = severity_styles.get(f.severity.value, "")
                    location = f.file_path or ""
                    if f.line_number is not None:
                        location += f":{f.line_number}"
                    findings_table.add_row(
                        f.severity.value.upper(),
                        location,
                        f.title,
                        f.reviewer_role.value,
                        style=style,
                    )
                console.print(findings_table)
            elif aggregated_review is not None:
                console.print("[green]No review findings.[/green]")
                if aggregated_review.unanimous_zero_findings:
                    console.print(
                        "[yellow]Warning: unanimous zero findings — stricter human review is still required.[/yellow]"
                    )

            # 10-line summary panel
            console.print(
                Panel(
                    summary_10,
                    title="Evidence Summary (10-line)",
                    border_style="blue",
                )
            )

            # 3-line challenge panel
            console.print(
                Panel(
                    challenge_3,
                    title="Challenge",
                    border_style="yellow",
                )
            )

            # Verbose: show full evidence
            if verbose or full:
                console.print(
                    Panel(
                        summary_slots.summary,
                        title="Full Evidence Summary",
                        border_style="cyan",
                    )
                )
                console.print(
                    Panel(
                        summary_slots.challenge,
                        title="Full Challenge Brief",
                        border_style="magenta",
                    )
                )

    except (typer.BadParameter, ValueError) as exc:
        handle_error(exc)
    except (ConnectionError, RuntimeError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)
