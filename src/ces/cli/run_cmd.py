"""Implementation of the guided local-first `ces run` command."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer
from rich.panel import Panel
from rich.table import Table

from ces.cli import _explain_views, _wizard_helpers
from ces.cli._async import run_async
from ces.cli._builder_evidence import (
    missing_completion_result,
    serialize_model,
)
from ces.cli._builder_evidence import (
    workspace_scope_violations as collect_workspace_scope_violations,
)
from ces.cli._builder_flow import BuilderBriefDraft, BuilderFlowOrchestrator
from ces.cli._context import find_project_root, get_project_config
from ces.cli._errors import handle_error
from ces.cli._factory import get_services
from ces.cli._legacy_config import reject_server_mode
from ces.cli._output import console
from ces.cli._runtime_diagnostics import summarize_runtime_failure, write_runtime_diagnostics
from ces.cli._wizard_helpers import WIZARD_STEPS
from ces.cli.execute_cmd import COMPLETION_CLAIM_INSTRUCTIONS
from ces.cli.init_cmd import derive_project_name, initialize_local_project
from ces.cli.ownership import resolve_actor
from ces.control.models.manifest import TaskManifest
from ces.control.services.workflow_engine import WorkflowEngine
from ces.control.spec.parser import SpecParser
from ces.control.spec.template_loader import TemplateLoader
from ces.execution.completion_parser import parse_completion_claim
from ces.execution.providers.bootstrap import resolve_primary_provider
from ces.execution.runtime_safety import runtime_side_effects_block_auto_approval, safety_profile_for_runtime
from ces.execution.workspace_delta import WorkspaceDelta, WorkspaceSnapshot
from ces.harness.prompts.engineering_charter import attach_engineering_charter
from ces.harness.sensors.security import SecuritySensor
from ces.harness.services.change_impact import build_observability_acceptance_template
from ces.harness.services.risk_sensor_policy import evaluate_sensor_policy
from ces.shared.enums import (
    ActorType,
    BehaviorConfidence,
    ChangeClass,
    GateType,
    RiskTier,
    TrustStatus,
    WorkflowState,
)
from ces.verification.build_contract import write_completion_contract
from ces.verification.completion_contract import CompletionContract
from ces.verification.runner import run_verification_commands

BUILDER_COMPLETION_SENSORS = ("test_pass", "lint", "typecheck", "coverage")

#: Directories excluded from sensor file discovery.
SENSOR_EXCLUDED_DIRS = {".venv", "node_modules", "__pycache__", ".git", ".ces"}
#: Maximum files to pass to sensors when discovering from project root.
SENSOR_MAX_FILES = 500


def _default_prompt_fn(_prompt: str, default: str = "") -> str:
    """Stub for ``typer.prompt`` that returns the default in non-interactive runs."""
    return default


def _normalize_option_values(values: list[str] | None) -> list[str]:
    return [value.strip() for value in values or [] if value.strip()]


def _validate_noninteractive_brief(brief: BuilderBriefDraft) -> None:
    """Fail closed when unattended mode lacks the governance context it skips."""
    if not brief.acceptance_criteria:
        raise typer.BadParameter(
            "Non-interactive `--yes` builds with a description require at least one "
            "`--acceptance` value so CES can judge what done means."
        )
    if brief.project_mode == "brownfield" and (not brief.source_of_truth or not brief.critical_flows):
        raise typer.BadParameter(
            "Non-interactive brownfield `--yes` builds require `--source-of-truth` "
            "and at least one `--critical-flow` so CES does not silently preserve inferred behavior."
        )


def _required_gate_type_for_risk(risk_tier_value: str) -> GateType:
    if risk_tier_value == "A":
        return GateType.HUMAN
    if risk_tier_value == "B":
        return GateType.HYBRID
    return GateType.AGENT


def _with_workflow_state(manifest: object, workflow_state: object) -> object:
    if isinstance(manifest, TaskManifest):
        return manifest.model_copy(update={"workflow_state": workflow_state})
    try:
        setattr(manifest, "workflow_state", workflow_state)
    except (AttributeError, TypeError):
        pass
    return manifest


def _manifest_with_effective_greenfield_scope(
    manifest: object,
    brief: BuilderBriefDraft,
    delta: WorkspaceDelta,
) -> object:
    """For greenfield builds, treat actual runtime-created files as manifest scope.

    Greenfield `ces build` requests often start with an empty manifest scope because
    the product layout is not knowable until the runtime creates it. Brownfield
    builds remain fail-closed and must declare scope explicitly.
    """
    if getattr(brief, "project_mode", "") != "greenfield" or getattr(manifest, "affected_files", ()):
        return manifest
    changed_files = tuple(delta.changed_files)
    if not changed_files:
        return manifest
    if isinstance(manifest, TaskManifest):
        return manifest.model_copy(update={"affected_files": changed_files})
    try:
        setattr(manifest, "affected_files", changed_files)
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


def _normalize_runtime_execution(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    runtime_result = getattr(result, "runtime_result", None)
    if runtime_result is not None and hasattr(runtime_result, "model_dump"):
        return runtime_result.model_dump(mode="json")
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    return {
        "runtime_name": getattr(result, "runtime_name"),
        "runtime_version": getattr(result, "runtime_version"),
        "reported_model": getattr(result, "reported_model", None),
        "invocation_ref": getattr(result, "invocation_ref"),
        "exit_code": getattr(result, "exit_code"),
        "stdout": getattr(result, "stdout", ""),
        "stderr": getattr(result, "stderr", ""),
        "duration_seconds": getattr(result, "duration_seconds", 0.0),
        "transcript_path": getattr(result, "transcript_path", None),
    }


def _promoted_prl_context(local_store: Any) -> list[str]:
    get_items = getattr(local_store, "get_promoted_prl_items", None)
    if not callable(get_items):
        return []
    items = get_items()
    statements: list[str] = []
    for item in items:
        if isinstance(item, dict):
            statement = item.get("statement")
        else:
            statement = getattr(item, "statement", None)
        if statement:
            statements.append(str(statement))
    return statements


def _prompt_pack(
    brief: BuilderBriefDraft,
    *,
    promoted_prl_statements: list[str] | None = None,
    manifest: Any | None = None,
) -> str:
    lines = [
        "You are executing a governed CES task in local mode.",
        "Work directly in the current project and keep the change scoped.",
        "",
        "Builder Request:",
        brief.request,
    ]
    if brief.constraints:
        lines.extend(["", "Constraints:", *[f"- {item}" for item in brief.constraints]])
    if brief.acceptance_criteria:
        lines.extend(["", "Acceptance Criteria:", *[f"- {item}" for item in brief.acceptance_criteria]])
    if brief.must_not_break:
        lines.extend(["", "Must Not Break:", *[f"- {item}" for item in brief.must_not_break]])
    mcp_servers = tuple(getattr(manifest, "mcp_servers", ()) or ()) if manifest is not None else ()
    if mcp_servers:
        lines.extend(
            [
                "",
                "MCP Grounding Requested:",
                *[f"- {server}" for server in mcp_servers],
                "Use these only when the runtime adapter exposes them; otherwise disclose that limitation.",
            ]
        )
    if manifest is not None:
        observability_template = build_observability_acceptance_template(
            list(getattr(manifest, "affected_files", ()) or ())
        )
        if observability_template:
            lines.extend(["", observability_template])
    if brief.project_mode == "brownfield":
        lines.extend(["", "Project Mode: brownfield"])
        if brief.source_of_truth:
            lines.append(f"Source Of Truth: {brief.source_of_truth}")
        if brief.critical_flows:
            lines.extend(["Critical Flows:", *[f"- {item}" for item in brief.critical_flows]])
        if promoted_prl_statements:
            lines.extend(["", "Promoted Legacy Requirements:", *[f"- {item}" for item in promoted_prl_statements]])
    criteria = brief.acceptance_criteria
    if criteria:
        lines.extend(
            [
                "",
                "Acceptance criteria you must address in the ces:completion claim:",
                *[f"- {item}" for item in criteria],
            ]
        )
    else:
        lines.append("\nAcceptance criteria: (none declared; emit an empty criteria_satisfied list)")
    lines.append(COMPLETION_CLAIM_INSTRUCTIONS)
    return attach_engineering_charter("\n".join(lines))


def _ensure_builder_project(project_root: Path | None = None) -> tuple[Path, dict[str, Any], bool]:
    """Return project root/config, auto-bootstrapping local state when missing."""
    if project_root is not None:
        resolved_root = project_root.resolve()
        if (resolved_root / ".ces").is_dir():
            return resolved_root, get_project_config(resolved_root), False
        config = initialize_local_project(resolved_root, name=derive_project_name(resolved_root.name))
        return resolved_root, config, True
    try:
        project_root = find_project_root()
        return project_root, get_project_config(project_root), False
    except typer.BadParameter:
        project_root = Path.cwd().resolve()
        config = initialize_local_project(project_root, name=derive_project_name(project_root.name))
        return project_root, config, True


def _coerce_text(value: Any) -> str:
    primitive = getattr(value, "value", value)
    return primitive if isinstance(primitive, str) else str(primitive)


def _write_completion_contract_for_build(
    *,
    project_root: Path,
    brief: BuilderBriefDraft,
    manifest: Any,
    runtime_adapter: Any,
) -> Path:
    runtime_name = str(getattr(runtime_adapter, "runtime_name", "unknown"))
    runtime_metadata = {
        "manifest_id": str(getattr(manifest, "manifest_id", "")),
        "accepted_runtime_side_effect_risk": bool(getattr(manifest, "accepted_runtime_side_effect_risk", False)),
    }
    return write_completion_contract(
        project_root=project_root,
        request=brief.request,
        acceptance_criteria=tuple(brief.acceptance_criteria),
        runtime_name=runtime_name,
        runtime_metadata=runtime_metadata,
    )


def _completion_verification_blockers(completion_verification: Any) -> list[str]:
    """Render completion-verification failures as actionable auto-blockers."""
    if completion_verification is None or bool(getattr(completion_verification, "passed", False)):
        return []
    findings = getattr(completion_verification, "findings", ()) or ()
    messages: list[str] = []
    for finding in findings:
        message = getattr(finding, "message", "")
        if isinstance(message, str) and message.strip():
            messages.append(message.strip())
    if not messages:
        return ["completion evidence failed verification"]
    return [f"completion evidence failed verification: {message}" for message in messages]


def _build_request_preview(
    brief: BuilderBriefDraft,
    *,
    runtime_name: str,
    governance: bool,
    proposal: dict[str, Any],
    manifest: Any | None = None,
) -> str:
    lines = [
        f"Request: {brief.request}",
        f"Mode: {brief.project_mode}",
        f"Runtime: {runtime_name}",
        "CES will create a bounded work contract, run checks, and ask before shipping.",
    ]
    if brief.acceptance_criteria:
        lines.append(f"Acceptance: {', '.join(brief.acceptance_criteria)}")
    if brief.must_not_break:
        lines.append(f"Must not break: {', '.join(brief.must_not_break)}")
    if governance:
        lines.extend(
            [
                "",
                f"Risk: {proposal.get('risk_tier', '')}",
                f"Confidence: {proposal.get('behavior_confidence', '')}",
                f"Change Class: {proposal.get('change_class', '')}",
            ]
        )
        if manifest is not None:
            lines.insert(-3, f"Manifest: {manifest.manifest_id}")
    return "\n".join(lines)


def _build_completion_summary(
    brief: BuilderBriefDraft,
    *,
    runtime_name: str,
    decision: str,
    merge_allowed: bool | None,
    triage_color: str,
    governance: bool,
    manifest_id: str,
    auto_blockers: list[str] | None = None,
    prl_draft_path: str | None = None,
) -> str:
    if decision != "approve":
        outcome = "held for another pass"
    elif merge_allowed is False:
        outcome = "approved, but merge is still blocked"
    else:
        outcome = "ready to ship"
    lines = [
        f"Request: {brief.request}",
        f"Mode: {brief.project_mode}",
        f"Runtime: {runtime_name}",
        f"Outcome: {outcome}",
    ]
    if governance:
        lines.extend(
            [
                f"Manifest: {manifest_id}",
                f"Triage: {triage_color}",
            ]
        )
    else:
        lines.append("Need deeper CES details? Re-run with `--governance` or use `ces review`.")
    if auto_blockers:
        lines.append("Blocking reasons:")
        lines.extend(f"- {item}" for item in auto_blockers)
        lines.append("Next: ces why")
        if any("evidence" in item.lower() or "verification" in item.lower() for item in auto_blockers):
            lines.append("Next: ces recover --dry-run")
    elif decision != "approve":
        lines.append("Next: ces why")
    elif merge_allowed is False:
        lines.append("Next: ces review --full")
    else:
        lines.append("Next: ces report builder")
    if prl_draft_path:
        lines.append(f"PRL draft: {prl_draft_path}")
    return "\n".join(lines)


def _brief_from_record(record: Any) -> BuilderBriefDraft:
    return BuilderBriefDraft(
        request=record.request,
        project_mode=record.project_mode,
        constraints=list(getattr(record, "constraints", []) or []),
        acceptance_criteria=list(getattr(record, "acceptance_criteria", []) or []),
        must_not_break=list(getattr(record, "must_not_break", []) or []),
        open_questions=dict(getattr(record, "open_questions", {}) or {}),
        source_of_truth=getattr(record, "source_of_truth", "") or "",
        critical_flows=list(getattr(record, "critical_flows", []) or []),
    )


def _load_latest_builder_session(local_store: Any) -> Any | None:
    ensure_session = getattr(local_store, "ensure_latest_builder_session", None)
    if callable(ensure_session):
        candidate = ensure_session()
        if isinstance(getattr(candidate, "stage", None), str):
            return candidate
    get_latest = getattr(local_store, "get_latest_builder_session", None)
    if callable(get_latest):
        candidate = get_latest()
        if isinstance(getattr(candidate, "stage", None), str):
            return candidate
    return None


async def _wizard_flow(
    *,
    services: dict[str, Any],
    project_config: dict[str, Any],
    runtime: str,
    brief: bool,
    full: bool,
    governance: bool,
    export_prl_draft: bool,
    project_root: Path,
    description: str | None,
    greenfield: bool,
    brownfield_flag: bool,
    accept_runtime_side_effects: bool = False,
) -> None:
    """Guided interactive wizard: 5 steps with Rich panels, inline help, and confirmation."""
    # Step 1 - Project Scan
    defaults = _wizard_helpers.scan_project_defaults(project_root)
    _wizard_helpers.wizard_step_panel(1, WIZARD_STEPS, "Project Scan", _wizard_helpers.format_scan_results(defaults))

    # Step 2 - Brief Collection
    console.print("  [dim]CES will ask about your request, constraints, and acceptance criteria.[/dim]")
    builder_flow = BuilderFlowOrchestrator(project_root)
    brief_draft = builder_flow.collect_brief(
        description=description,
        prompt_fn=typer.prompt,
        force_greenfield=greenfield,
        force_brownfield=brownfield_flag,
    )
    _wizard_helpers.wizard_step_panel(
        2,
        WIZARD_STEPS,
        "Brief Collected",
        f"Request: {brief_draft.request}\nMode: {brief_draft.project_mode}",
        help_text="CES uses your brief to scope the work contract.",
    )

    # Step 3 - Brownfield Review
    if brief_draft.project_mode == "brownfield":
        _wizard_helpers.wizard_step_panel(
            3,
            WIZARD_STEPS,
            "Brownfield Review",
            f"Brownfield mode: {defaults.manifest_count} existing manifests",
            help_text="CES will review legacy behaviors that must not break.",
        )
    else:
        _wizard_helpers.wizard_step_panel(
            3,
            WIZARD_STEPS,
            "Brownfield Review",
            "Skipped (greenfield project)",
            help_text="No legacy behaviors to review in greenfield mode.",
        )

    # Step 4 - Governance
    _wizard_helpers.wizard_step_panel(
        4,
        WIZARD_STEPS,
        "Governance",
        f"Governance: {'enabled' if governance else 'standard'}",
        help_text="Governance mode shows manifest IDs, risk tiers, and audit details.",
    )

    # Step 5 - Confirmation
    table = _wizard_helpers.build_confirmation_table(
        risk_tier=defaults.suggested_risk_tier,
        affected_files_count=0,
        acceptance_criteria=brief_draft.acceptance_criteria,
        runtime=runtime,
        brownfield_count=defaults.manifest_count,
        governance=governance,
    )
    _wizard_helpers.wizard_step_panel(5, WIZARD_STEPS, "Confirmation", "Review your settings below:")
    console.print(table)

    if not typer.confirm("Proceed with execution?", default=True):
        raise typer.Abort

    # Execution with spinner -- Wizard already confirmed, pass yes=True
    with console.status("[bold green]Starting execution...", spinner="dots"):
        await _run_brief_flow(
            brief_draft=brief_draft,
            services=services,
            project_config=project_config,
            runtime=runtime,
            yes=True,  # Wizard already confirmed -- avoid double-prompting
            brief=brief,
            full=full,
            governance=governance,
            export_prl_draft=export_prl_draft,
            project_root=project_root,
            accept_runtime_side_effects=accept_runtime_side_effects,
        )


async def _run_brief_flow(
    *,
    brief_draft: BuilderBriefDraft,
    services: dict[str, Any],
    project_config: dict[str, Any],
    runtime: str,
    yes: bool,
    brief: bool,
    full: bool,
    governance: bool,
    export_prl_draft: bool,
    project_root: Path,
    accept_runtime_side_effects: bool = False,
    existing_brief_id: str | None = None,
    existing_session_id: str | None = None,
) -> None:
    settings = services["settings"]
    manager = services["manifest_manager"]
    local_store = services.get("local_store")
    runtime_registry = services["runtime_registry"]
    agent_runner = services["agent_runner"]
    synth = services["evidence_synthesizer"]
    sensor_orchestrator = services["sensor_orchestrator"]
    legacy_behavior_service = services.get("legacy_behavior_service")
    builder_flow = BuilderFlowOrchestrator(project_root)
    brief_id = existing_brief_id
    session_id = existing_session_id
    if brief_id is None:
        brief_id = local_store.save_builder_brief(
            request=brief_draft.request,
            project_mode=brief_draft.project_mode,
            constraints=brief_draft.constraints,
            acceptance_criteria=brief_draft.acceptance_criteria,
            must_not_break=brief_draft.must_not_break,
            open_questions=brief_draft.open_questions,
            source_of_truth=brief_draft.source_of_truth,
            critical_flows=brief_draft.critical_flows or [],
        )
    if session_id is None and hasattr(local_store, "save_builder_session"):
        session_id = local_store.save_builder_session(
            brief_id=brief_id,
            request=brief_draft.request,
            project_mode=brief_draft.project_mode,
            stage="ready_to_run",
            next_action="run_continue",
            last_action="brief_captured",
            source_of_truth=brief_draft.source_of_truth,
            critical_flows=brief_draft.critical_flows or [],
        )
    current_session = None
    if existing_session_id is not None and hasattr(local_store, "get_builder_session"):
        current_session = local_store.get_builder_session(existing_session_id)

    try:
        runtime_adapter = runtime_registry.resolve_runtime(
            runtime_name=runtime,
            preferred_runtime=project_config.get("preferred_runtime") or getattr(settings, "default_runtime", "codex"),
        )
    except RuntimeError:
        if session_id is not None and hasattr(local_store, "update_builder_session"):
            local_store.update_builder_session(
                session_id,
                stage="blocked",
                next_action="install_runtime",
                last_action="runtime_missing",
                recovery_reason="install_runtime",
                last_error="No supported local runtime detected.",
            )
        console.print(
            Panel(
                "[bold]No agent runtime found.[/bold]\n\n"
                "CES needs a local agent runtime to execute tasks.\n"
                "Install one of:\n"
                "  - [bold]Claude Code[/bold]: install and authenticate `claude` so it is on PATH\n"
                "  - [bold]Codex CLI[/bold]: install and authenticate `codex` so it is on PATH\n\n"
                "CES_DEMO_MODE does not replace the required runtime for `ces build`.\n"
                "Run [bold]ces doctor[/bold] after installing a supported runtime.",
                title="[yellow]Runtime Not Found[/yellow]",
                border_style="yellow",
            )
        )
        raise typer.Exit(code=1)

    runtime_name = getattr(runtime_adapter, "runtime_name", runtime)
    actor = resolve_actor()
    proposal = builder_flow.propose_manifest(
        brief=brief_draft,
        runtime_adapter=runtime_adapter,
    )

    # Override hardcoded adapter defaults with real TF-IDF classification
    # when the oracle has sufficient confidence (>= 0.70).
    oracle = services.get("classification_oracle")
    if oracle is not None:
        oracle_result = oracle.classify(brief_draft.request)
        if oracle_result.matched_rule and oracle_result.confidence >= 0.70:
            rule = oracle_result.matched_rule
            proposal["risk_tier"] = rule.risk_tier.value
            proposal["behavior_confidence"] = rule.behavior_confidence.value
            proposal["change_class"] = rule.change_class.value
    prl_draft_path: str | None = None
    if export_prl_draft:
        prl_draft = builder_flow.export_prl_draft(
            brief_id=brief_id,
            brief=brief_draft,
        )
        prl_draft_path = str(prl_draft)
        local_store.update_builder_brief_artifacts(
            brief_id,
            prl_draft_path=prl_draft_path,
        )

    console.print(
        Panel(
            _build_request_preview(
                brief_draft,
                runtime_name=runtime_name,
                governance=governance,
                proposal=proposal,
            ),
            title="[cyan]Plan For Your Request[/cyan]",
            border_style="cyan",
        )
    )

    manifest = None
    if (
        current_session is not None
        and getattr(current_session, "next_action", None) == "review_brownfield"
        and getattr(current_session, "manifest_id", None)
    ):
        manifest = local_store.get_manifest_row(current_session.manifest_id)

    if manifest is None:
        manifest = await manager.create_manifest(
            description=proposal.get("description", brief_draft.request),
            risk_tier=RiskTier(proposal.get("risk_tier", RiskTier.B.value)),
            behavior_confidence=BehaviorConfidence(proposal.get("behavior_confidence", BehaviorConfidence.BC2.value)),
            change_class=ChangeClass(proposal.get("change_class", ChangeClass.CLASS_2.value)),
            affected_files=proposal.get("affected_files", []),
            acceptance_criteria=brief_draft.acceptance_criteria,
            token_budget=proposal.get("token_budget", 100_000),
            owner=actor,
            verification_sensors=list(BUILDER_COMPLETION_SENSORS),
            requires_exploration_evidence=True,
            requires_verification_commands=True,
            requires_impacted_flow_evidence=brief_draft.project_mode == "brownfield",
            requires_docs_evidence_for_public_changes=True,
            accepted_runtime_side_effect_risk=accept_runtime_side_effects,
        )
        local_store.update_builder_brief_artifacts(
            brief_id,
            manifest_id=manifest.manifest_id,
        )
    manifest = await _ensure_signed_manifest(manager, manifest)
    contract_path = _write_completion_contract_for_build(
        project_root=project_root,
        brief=brief_draft,
        manifest=manifest,
        runtime_adapter=runtime_adapter,
    )
    if session_id is not None and hasattr(local_store, "update_builder_session"):
        current_attempts = getattr(current_session, "attempt_count", 0) or 0
        local_store.update_builder_session(
            session_id,
            stage="running",
            next_action="review_evidence",
            last_action="execution_started",
            recovery_reason=None,
            last_error=None,
            attempt_count=current_attempts + 1,
            manifest_id=manifest.manifest_id,
            runtime_manifest_id=manifest.manifest_id,
        )

    if brief_draft.project_mode == "brownfield" and _explain_views.should_run_brownfield_review(current_session):
        checkpoint = getattr(current_session, "brownfield_review_state", None) if current_session is not None else None

        def _save_review_checkpoint(state: dict[str, Any] | None) -> None:
            if session_id is None or not hasattr(local_store, "update_builder_session"):
                return
            if state is None:
                local_store.update_builder_session(
                    session_id,
                    stage="running",
                    next_action="review_evidence",
                    last_action="brownfield_review_completed",
                    brownfield_review_state=None,
                )
                return
            local_store.update_builder_session(
                session_id,
                stage="collecting",
                next_action="review_brownfield",
                last_action="brownfield_review_in_progress",
                manifest_id=manifest.manifest_id,
                runtime_manifest_id=manifest.manifest_id,
                brownfield_review_state=state,
                brownfield_entry_ids=list(state.get("reviewed_entry_ids", [])),
                brownfield_reviewed_count=int(state.get("reviewed_count", 0)),
                brownfield_remaining_count=int(state.get("remaining_count", 0)),
            )

        brownfield_prompt_fn = _default_prompt_fn if yes else typer.prompt
        await builder_flow.capture_brownfield_behaviors(
            brief=brief_draft,
            legacy_behavior_service=legacy_behavior_service,
            prompt_fn=brownfield_prompt_fn,
            source_manifest_id=manifest.manifest_id,
            review_state=checkpoint,
            checkpoint_fn=_save_review_checkpoint,
        )
        if session_id is not None and hasattr(local_store, "get_builder_session"):
            current_session = local_store.get_builder_session(session_id)

    manifest = _with_workflow_state(manifest, WorkflowState.IN_FLIGHT)
    await manager.save_manifest(manifest)

    pre_runtime_security = await SecuritySensor().run(
        {
            "project_root": str(project_root),
            "affected_files": list(getattr(manifest, "affected_files", ()) or ()),
            "context_files": [path for path in (getattr(brief_draft, "prl_draft_path", None),) if path],
        }
    )
    if not pre_runtime_security.passed:
        if session_id is not None and hasattr(local_store, "update_builder_session"):
            local_store.update_builder_session(
                session_id,
                stage="blocked",
                next_action="retry_runtime",
                last_action="runtime_failed",
                recovery_reason="security_context_blocked",
                last_error="Pre-runtime security scan found sensitive context",
                runtime_manifest_id=manifest.manifest_id,
            )
        raise RuntimeError(
            "Pre-runtime security scan found sensitive context; review security findings before running."
        )

    workspace_before = WorkspaceSnapshot.capture(project_root)
    run_result = await agent_runner.execute_runtime(
        manifest=manifest,
        runtime=runtime_adapter,
        prompt_pack=_prompt_pack(
            brief_draft,
            promoted_prl_statements=_promoted_prl_context(local_store),
            manifest=manifest,
        ),
        working_dir=project_root,
    )
    workspace_delta = workspace_before.diff(WorkspaceSnapshot.capture(project_root))
    manifest_for_verification = _manifest_with_effective_greenfield_scope(manifest, brief_draft, workspace_delta)
    execution = _normalize_runtime_execution(run_result)
    runtime_safety = safety_profile_for_runtime(
        execution.get("runtime_name", getattr(runtime_adapter, "runtime_name", "unknown")),
        allowed_tools=tuple(getattr(manifest, "allowed_tools", ()) or ()),
        mcp_servers=tuple(getattr(manifest, "mcp_servers", ()) or ()),
    ).model_copy(
        update={
            "accepted_runtime_side_effect_risk": accept_runtime_side_effects
            or bool(getattr(manifest, "accepted_runtime_side_effect_risk", False))
        }
    )
    runtime_result = getattr(run_result, "runtime_result", None)
    completion_claim = getattr(runtime_result, "completion_claim", None)
    if completion_claim is None:
        completion_claim = parse_completion_claim(str(execution.get("stdout", "")))
    completion_verification = None
    if execution["exit_code"] == 0:
        verifier = services.get("completion_verifier")
        if completion_claim is None:
            completion_verification = missing_completion_result()
        elif verifier is not None:
            completion_verification = await verifier.verify(manifest_for_verification, completion_claim, project_root)
    workspace_scope_violations = collect_workspace_scope_violations(manifest_for_verification, workspace_delta)
    contract_path = _write_completion_contract_for_build(
        project_root=project_root,
        brief=brief_draft,
        manifest=manifest,
        runtime_adapter=runtime_adapter,
    )
    independent_verification = None
    if execution["exit_code"] == 0 and contract_path.is_file():
        independent_contract = CompletionContract.read(contract_path)
        if independent_contract.inferred_commands:
            independent_verification = run_verification_commands(project_root, independent_contract.inferred_commands)
    local_store.save_runtime_execution(manifest.manifest_id, execution)

    # When manifest has no affected_files, discover Python files from project root
    # so sensors have real files to analyze instead of skipping silently.
    # Prioritise src/ files so sensors always see production code even when
    # the 500-file cap is reached before traversal finishes the tree.
    sensor_affected_files = list(manifest.affected_files or [])
    if not sensor_affected_files:
        _discovered = list(project_root.rglob("*.py"))
        _all_files = [
            p.relative_to(project_root).as_posix()
            for p in _discovered
            if not any(part in SENSOR_EXCLUDED_DIRS for part in p.parts)
        ]
        # Put src/ files first so sensors always analyse production code.
        _all_files.sort(key=lambda f: (0 if f.startswith("src/") else 1, f))
        sensor_affected_files = _all_files[:SENSOR_MAX_FILES]

    pack_results = await sensor_orchestrator.run_all(
        {
            "manifest_id": manifest.manifest_id,
            "description": brief_draft.request,
            "execution": execution,
            "affected_files": sensor_affected_files,
            "project_root": str(project_root),
        }
    )
    sensor_results = [result for pack in pack_results for result in getattr(pack, "results", ())]
    sensor_policy = evaluate_sensor_policy(manifest.risk_tier, sensor_results)

    summary_text = ""
    challenge_text = ""
    summarizer = getattr(runtime_adapter, "summarize_evidence", None)
    if callable(summarizer):
        candidate = summarizer(
            {
                "manifest_id": manifest.manifest_id,
                "description": brief_draft.request,
                "runtime_name": execution["runtime_name"],
                "exit_code": execution["exit_code"],
                "output_lines": len(execution.get("stdout", "").splitlines()),
            }
        )
        if isinstance(candidate, tuple) and len(candidate) == 2:
            summary_text, challenge_text = candidate
    if not summary_text and not challenge_text:
        # Try to use the LLM provider for real evidence synthesis
        llm_provider = None
        provider_registry = services.get("provider_registry")
        if provider_registry:
            llm_provider = resolve_primary_provider(provider_registry, settings.default_model_id)

        slots = await synth.format_summary_slots(
            provider=llm_provider,
            model_id=settings.default_model_id if llm_provider else "",
            evidence_context={"manifest": manifest.manifest_id, "execution": execution},
        )
        summary_text = slots.summary
        challenge_text = slots.challenge

    triage = await synth.triage(
        risk_tier=manifest.risk_tier,
        trust_status=TrustStatus.TRUSTED,
        sensor_results=sensor_results,
    )

    packet_id = f"EP-{uuid.uuid4().hex[:12]}"
    local_store.save_evidence(
        manifest.manifest_id,
        packet_id=packet_id,
        summary=summary_text,
        challenge=challenge_text,
        triage_color=triage.color.value,
        content={
            "execution": execution,
            "sensors": [getattr(sensor, "model_dump", lambda **_: sensor)() for sensor in sensor_results],
            "completion_claim": serialize_model(completion_claim),
            "verification_result": serialize_model(completion_verification),
            "workspace_delta": serialize_model(workspace_delta),
            "workspace_scope_violations": list(workspace_scope_violations),
            "runtime_safety": serialize_model(runtime_safety),
            "independent_verification": independent_verification.to_dict() if independent_verification else None,
            "completion_contract_path": str(contract_path),
            "sensor_policy": serialize_model(sensor_policy),
            "triage_reason": triage.reason,
        },
    )
    local_store.update_builder_brief_artifacts(
        brief_id,
        evidence_packet_id=packet_id,
        prl_draft_path=prl_draft_path,
    )
    if session_id is not None and hasattr(local_store, "update_builder_session"):
        local_store.update_builder_session(
            session_id,
            stage="awaiting_review",
            next_action="review_evidence",
            last_action="evidence_ready",
            runtime_manifest_id=manifest.manifest_id,
            evidence_packet_id=packet_id,
        )

    runtime_output = execution.get("stdout", "")
    if full:
        evidence_body = runtime_output or "(no runtime stdout)"
    elif brief:
        evidence_body = summary_text
    else:
        evidence_body = "\n\n".join(part for part in [summary_text, challenge_text] if part)
    console.print(
        Panel(
            evidence_body,
            title="[magenta]What CES Found[/magenta]",
            border_style=_coerce_text(triage.color),
        )
    )

    if execution["exit_code"] != 0:
        diagnostics_path = write_runtime_diagnostics(project_root, manifest.manifest_id, execution)
        failure_summary = summarize_runtime_failure(execution)
        console.print(
            Panel(
                f"{failure_summary}\n\nDiagnostics: {diagnostics_path}",
                title="[red]Runtime Failed[/red]",
                border_style="red",
            )
        )
        if session_id is not None and hasattr(local_store, "update_builder_session"):
            local_store.update_builder_session(
                session_id,
                stage="blocked",
                next_action="retry_runtime",
                last_action="runtime_failed",
                recovery_reason="retry_execution",
                last_error=(
                    f"{execution['runtime_name']} exited with code {execution['exit_code']}; "
                    f"diagnostics: {diagnostics_path}"
                ),
                runtime_manifest_id=manifest.manifest_id,
                evidence_packet_id=packet_id,
            )
        raise RuntimeError(
            f"{execution['runtime_name']} exited with code {execution['exit_code']}. Diagnostics: {diagnostics_path}"
        )

    workflow_engine = WorkflowEngine(
        manifest_id=manifest.manifest_id,
        audit_ledger=services["audit_ledger"],
        initial_state="in_flight",
    )
    review_state = await workflow_engine.submit_for_review(actor=actor, actor_type=ActorType.HUMAN)
    manifest = _with_workflow_state(manifest, review_state)
    await manager.save_manifest(manifest)

    auto_blockers: list[str] = []
    auto_blockers.extend(_completion_verification_blockers(completion_verification))
    if independent_verification is not None and not independent_verification.passed:
        auto_blockers.append("independent verification failed; run `ces verify --json` for command details")
    if workspace_scope_violations:
        auto_blockers.append("workspace changes exceeded manifest scope")
    if sensor_policy.blocking:
        auto_blockers.append("risk-aware sensor policy found blocking issues")
    if yes and brief_draft.project_mode == "brownfield" and not getattr(manifest, "affected_files", ()):
        auto_blockers.append("brownfield scope unknown: manifest affected_files is empty")
    if yes and runtime_side_effects_block_auto_approval(
        runtime_safety,
        accepted=accept_runtime_side_effects or bool(getattr(manifest, "accepted_runtime_side_effect_risk", False)),
    ):
        auto_blockers.append("runtime side-effect boundary requires explicit operator acceptance")

    approved = yes and not auto_blockers
    if not yes:
        if auto_blockers:
            console.print(
                Panel(
                    "\n".join(f"- {item}" for item in auto_blockers),
                    title="[yellow]Approval Requires Explicit Review[/yellow]",
                    border_style="yellow",
                )
            )
        approved = typer.confirm("Ship this change?", default=execution["exit_code"] == 0)
    decision = "approve" if approved else "reject"
    if yes and auto_blockers:
        rationale = "Auto-approval blocked: " + "; ".join(auto_blockers)
    elif yes:
        rationale = "Auto-approved by the builder flow"
    else:
        rationale = f"User selected {decision} after evidence review"
    local_store.save_approval(
        manifest.manifest_id,
        decision=decision,
        rationale=rationale,
    )

    await services["audit_ledger"].record_approval(
        manifest_id=manifest.manifest_id,
        actor=actor,
        decision=decision,
        rationale=rationale,
    )
    merge_decision = None
    if approved:
        from ces.shared.enums import ReviewSubState

        workflow_engine._review_sub_state = ReviewSubState.DECISION
        approved_state = await workflow_engine.complete_review(actor=actor, actor_type=ActorType.HUMAN)
        manifest = _with_workflow_state(manifest, approved_state)
        await manager.save_manifest(manifest)

        merge_controller = services.get("merge_controller")
        if merge_controller is not None:
            risk_value = manifest.risk_tier.value if hasattr(manifest.risk_tier, "value") else str(manifest.risk_tier)
            merge_decision = await merge_controller.validate_merge(
                manifest_id=manifest.manifest_id,
                manifest_expires_at=getattr(manifest, "expires_at", datetime.now(timezone.utc)),
                manifest_content_hash=getattr(manifest, "content_hash", ""),
                manifest_risk_tier=risk_value,
                manifest_bc=getattr(manifest, "behavior_confidence", "BC2"),
                evidence_packet={
                    "summary": summary_text,
                    "challenge": challenge_text,
                    "triage_color": triage.color.value,
                },
                evidence_manifest_hash=getattr(manifest, "content_hash", ""),
                required_gate_type=_required_gate_type_for_risk(risk_value),
                actual_gate_type=GateType.HUMAN,
                review_sub_state="decision",
                workflow_state=WorkflowState.APPROVED.value,
            )
            if merge_decision.allowed:
                merged_state = await workflow_engine.approve_merge(actor=actor, actor_type=ActorType.HUMAN)
                manifest = _with_workflow_state(manifest, merged_state)
                await manager.save_manifest(manifest)
    else:
        rejected_state = await workflow_engine.reject(
            actor=actor,
            actor_type=ActorType.HUMAN,
            rationale=rationale,
        )
        manifest = _with_workflow_state(manifest, rejected_state)
        await manager.save_manifest(manifest)

    merge_blocked = merge_decision is not None and not merge_decision.allowed
    if session_id is not None and hasattr(local_store, "update_builder_session"):
        if approved and not merge_blocked:
            local_store.update_builder_session(
                session_id,
                stage="completed",
                next_action="start_new_session",
                last_action="approval_recorded",
                recovery_reason=None,
                last_error=None,
                approval_manifest_id=manifest.manifest_id,
            )
        else:
            local_store.update_builder_session(
                session_id,
                stage="blocked",
                next_action="review_evidence",
                last_action="merge_blocked" if merge_blocked else "approval_rejected",
                recovery_reason="needs_review",
                approval_manifest_id=manifest.manifest_id,
            )

    console.print(
        Panel(
            _build_completion_summary(
                brief_draft,
                runtime_name=execution["runtime_name"],
                decision=decision,
                merge_allowed=(None if merge_decision is None else merge_decision.allowed),
                triage_color=_coerce_text(triage.color),
                governance=governance,
                manifest_id=manifest.manifest_id,
                auto_blockers=list(auto_blockers),
                prl_draft_path=prl_draft_path,
            ),
            title="[green]Build Review Complete[/green]",
            border_style="green",
        )
    )
    if merge_decision is not None:
        if merge_decision.allowed:
            console.print(
                Panel(
                    "All merge precondition checks passed.",
                    title="[green]Merge Validation Passed[/green]",
                    border_style="green",
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


@run_async
async def run_task(
    description: str | None = typer.Argument(
        None,
        help="Task description to execute",
    ),
    gsd: str | None = typer.Option(
        None,
        "--gsd",
        help="0-to-100 greenfield request. Alias for a greenfield builder run with actionable final UX.",
    ),
    runtime: str = typer.Option(
        "auto",
        "--runtime",
        help="Runtime for local mode: auto, codex, or claude",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Run non-interactively and approve only after explicit acceptance context is supplied.",
    ),
    brief: bool = typer.Option(
        False,
        "--brief",
        help="Show a concise evidence view",
    ),
    full: bool = typer.Option(
        False,
        "--full",
        help="Show the full runtime output in the evidence section",
    ),
    governance: bool = typer.Option(
        False,
        "--governance",
        help="Show CES internals like manifest IDs, risk tiers, and triage details.",
    ),
    greenfield: bool = typer.Option(
        False,
        "--greenfield",
        help="Force the build flow to treat this repo as a greenfield project.",
    ),
    brownfield: bool = typer.Option(
        False,
        "--brownfield",
        help="Force the build flow to treat this repo as a brownfield project.",
    ),
    constraints: list[str] | None = typer.Option(
        None,
        "--constraint",
        help="Constraint to include in a non-interactive builder brief. Repeatable.",
    ),
    acceptance: list[str] | None = typer.Option(
        None,
        "--acceptance",
        help="Acceptance criterion required for non-interactive `--yes` builds. Repeatable.",
    ),
    must_not_break: list[str] | None = typer.Option(
        None,
        "--must-not-break",
        help="Behavior that must keep working. Repeatable.",
    ),
    source_of_truth: str | None = typer.Option(
        None,
        "--source-of-truth",
        help="Brownfield source of truth required for non-interactive brownfield `--yes` builds.",
    ),
    critical_flows: list[str] | None = typer.Option(
        None,
        "--critical-flow",
        help="Brownfield workflow that must keep working. Repeatable.",
    ),
    export_prl_draft: bool = typer.Option(
        False,
        "--export-prl-draft",
        help="Write a lightweight PRL-style draft from the builder brief to `.ces/exports/`.",
    ),
    accept_runtime_side_effects: bool = typer.Option(
        False,
        "--accept-runtime-side-effects",
        help="Allow unattended approval when the selected runtime cannot enforce manifest tool allowlists.",
    ),
    from_spec: Path | None = typer.Option(
        None,
        "--from-spec",
        help="Preview the build order for a decomposed spec's manifests.",
    ),
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Repo/CES project root to operate on; defaults to cwd/.ces discovery.",
    ),
    story: str | None = typer.Option(
        None,
        "--story",
        help="Restrict --from-spec output to a single story id.",
    ),
) -> None:
    """Run the full local CES flow in one builder-first command."""
    try:
        if from_spec is not None:
            await _preview_from_spec(from_spec, story_id=story)
            return
        if gsd and description:
            raise typer.BadParameter("Choose either a positional task description or --gsd, not both.")
        if gsd:
            description = gsd
            greenfield = True
        requested_project_root = project_root
        project_root, project_config, bootstrapped = _ensure_builder_project(requested_project_root)
        reject_server_mode(project_config)
        if greenfield and brownfield:
            raise typer.BadParameter("Choose only one of --greenfield or --brownfield.")

        if bootstrapped:
            project_name = project_config.get("project_name", project_root.name)
            console.print(
                Panel(
                    "CES set up local project state for this repo so this build can start right away.\n"
                    f"Project: {project_name}\n"
                    f"Project root: {project_root}\n"
                    "Manual setup is still available later with `ces init`.",
                    title="[green]Builder-First Setup[/green]",
                    border_style="green",
                )
            )

        if not bootstrapped:
            console.print(f"[dim]Using project root: {project_root}[/dim]")

        services_context = (
            get_services(project_root=project_root) if requested_project_root is not None else get_services()
        )
        async with services_context as services:
            if yes:
                builder_flow = BuilderFlowOrchestrator(project_root)
                if description:
                    prompt_fn = _default_prompt_fn
                else:
                    prompt_fn = typer.prompt
                brief_draft = builder_flow.collect_brief(
                    description=description,
                    prompt_fn=prompt_fn,
                    force_greenfield=greenfield,
                    force_brownfield=brownfield,
                    provided_constraints=_normalize_option_values(constraints),
                    provided_acceptance_criteria=_normalize_option_values(acceptance),
                    provided_must_not_break=_normalize_option_values(must_not_break),
                    provided_source_of_truth=source_of_truth,
                    provided_critical_flows=_normalize_option_values(critical_flows),
                )
                if description:
                    _validate_noninteractive_brief(brief_draft)
                await _run_brief_flow(
                    brief_draft=brief_draft,
                    services=services,
                    project_config=project_config,
                    runtime=runtime,
                    yes=yes,
                    brief=brief,
                    full=full,
                    governance=governance,
                    export_prl_draft=export_prl_draft,
                    project_root=project_root,
                    accept_runtime_side_effects=accept_runtime_side_effects,
                )
            else:
                # Wizard path: guided step-by-step flow
                await _wizard_flow(
                    services=services,
                    project_config=project_config,
                    runtime=runtime,
                    brief=brief,
                    full=full,
                    governance=governance,
                    export_prl_draft=export_prl_draft,
                    project_root=project_root,
                    description=description,
                    greenfield=greenfield,
                    brownfield_flag=brownfield,
                    accept_runtime_side_effects=accept_runtime_side_effects,
                )
    except typer.Abort:
        raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as exc:
        handle_error(exc)


@run_async
async def continue_task(
    runtime: str = typer.Option(
        "auto",
        "--runtime",
        help="Runtime for local mode: auto, codex, or claude",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Run non-interactively and approve after the saved brief's review summary.",
    ),
    brief: bool = typer.Option(
        False,
        "--brief",
        help="Show a concise evidence view",
    ),
    full: bool = typer.Option(
        False,
        "--full",
        help="Show the full runtime output in the evidence section",
    ),
    governance: bool = typer.Option(
        False,
        "--governance",
        help="Show CES internals like manifest IDs, risk tiers, and triage details.",
    ),
    export_prl_draft: bool = typer.Option(
        False,
        "--export-prl-draft",
        help="Write a lightweight PRL-style draft from the builder brief to `.ces/exports/`.",
    ),
    accept_runtime_side_effects: bool = typer.Option(
        False,
        "--accept-runtime-side-effects",
        help="Allow unattended approval when the selected runtime cannot enforce manifest tool allowlists.",
    ),
) -> None:
    """Continue from the latest saved builder brief without re-answering prompts."""
    try:
        project_root = find_project_root()
        project_config = get_project_config()
        reject_server_mode(project_config)

        async with get_services() as services:
            local_store = services.get("local_store")
            session = _load_latest_builder_session(local_store)
            if session is not None and session.stage == "completed":
                console.print(
                    Panel(
                        "The latest builder session is already completed.\n"
                        "Start a new task with `ces build`, or run `ces explain` "
                        "or `ces status` to review the finished request.",
                        title="[cyan]Nothing To Resume[/cyan]",
                        border_style="cyan",
                    )
                )
                return
            record = None
            if session is not None and getattr(session, "brief_id", None) and hasattr(local_store, "get_builder_brief"):
                record = local_store.get_builder_brief(session.brief_id)
            if record is None:
                record = local_store.get_latest_builder_brief()
            if record is None:
                raise RuntimeError("No saved builder brief found. Start with `ces build`.")
            await _run_brief_flow(
                brief_draft=_brief_from_record(record),
                services=services,
                project_config=project_config,
                runtime=runtime,
                yes=yes,
                brief=brief,
                full=full,
                governance=governance,
                export_prl_draft=export_prl_draft,
                project_root=project_root,
                existing_brief_id=getattr(record, "brief_id", None),
                existing_session_id=getattr(session, "session_id", None),
                accept_runtime_side_effects=accept_runtime_side_effects,
            )
    except typer.Abort:
        raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as exc:
        handle_error(exc)


@run_async
async def explain_task(
    view: str = typer.Option(
        "overview",
        "--view",
        help="Explanation view: overview, decisioning, or brownfield.",
    ),
    governance: bool = typer.Option(
        False,
        "--governance",
        help="Include additional CES metadata for the selected explanation view.",
    ),
) -> None:
    """Explain the latest builder brief and its current CES state in plain language."""
    try:
        find_project_root()
        selected_view = _explain_views.normalize_explain_view(view)
        async with get_services() as services:
            local_store = services.get("local_store")
            snapshot = _explain_views.load_latest_builder_snapshot(local_store)
            session = (
                getattr(snapshot, "session", None)
                if snapshot is not None
                else _load_latest_builder_session(local_store)
            )
            if snapshot is not None:
                record = (
                    getattr(snapshot, "brief", None)
                    or (snapshot if getattr(snapshot, "request", None) else None)
                    or getattr(snapshot, "session", None)
                )
                brief_only_fallback = bool(getattr(snapshot, "brief_only_fallback", False))
            else:
                record, brief_only_fallback = _explain_views.load_explain_record(local_store, session)
            if record is None:
                raise RuntimeError("No saved builder brief found. Start with `ces build`.")

            manifest = (
                getattr(snapshot, "manifest", None)
                if snapshot is not None
                else _explain_views.load_explain_manifest(local_store, session, record)
            )
            evidence = (
                getattr(snapshot, "evidence", None)
                if snapshot is not None
                else _explain_views.load_explain_evidence(local_store, session, record)
            )
            approval = getattr(snapshot, "approval", None) if snapshot is not None else None
            pending_count = 0
            if snapshot is not None and getattr(snapshot, "brownfield", None) is not None:
                pending_count = getattr(snapshot.brownfield, "remaining_count", 0)
            else:
                legacy_behavior_service = services.get("legacy_behavior_service")
                if legacy_behavior_service is not None:
                    pending_count = len(await legacy_behavior_service.get_pending_behaviors())

            if selected_view == "overview":
                lines = _explain_views.build_overview_explanation_lines(
                    record=record,
                    session=session,
                    evidence=evidence,
                    pending_count=pending_count,
                    brief_only_fallback=brief_only_fallback,
                    latest_activity=getattr(snapshot, "latest_activity", None),
                    next_step=getattr(snapshot, "next_step", None),
                )
            elif selected_view == "decisioning":
                lines = _explain_views.build_decisioning_explanation_lines(
                    record=record,
                    session=session,
                    manifest=manifest,
                    evidence=evidence,
                    pending_count=pending_count,
                    governance=governance,
                )
                if approval is not None:
                    lines.append(f"Recorded decision: {approval.decision}")
            else:
                lines = _explain_views.build_brownfield_explanation_lines(
                    record=record,
                    session=session,
                    pending_count=pending_count,
                    governance=governance,
                )
                if (
                    snapshot is not None
                    and getattr(snapshot, "brownfield", None) is not None
                    and not any(line.startswith("Brownfield review progress:") for line in lines)
                ):
                    lines.append(
                        "Brownfield review progress: "
                        f"{snapshot.brownfield.reviewed_count} reviewed, "
                        f"{snapshot.brownfield.remaining_count} remaining"
                    )

            if governance and selected_view == "overview":
                if manifest is not None:
                    lines.append(f"Manifest ID: {manifest.manifest_id}")
                if evidence is not None and evidence.get("packet_id"):
                    lines.append(f"Evidence packet: {evidence['packet_id']}")
                if session is not None:
                    lines.append(f"Session next action: {getattr(session, 'next_action', 'unknown')}")
                    if getattr(session, "recovery_reason", None):
                        lines.append(f"Recovery reason: {session.recovery_reason}")
            if governance and getattr(record, "prl_draft_path", None):
                lines.append(f"PRL draft: {record.prl_draft_path}")
            if selected_view != "brownfield" and session is not None and getattr(session, "last_error", None):
                lines.append(f"Last error: {session.last_error}")

            console.print(
                Panel(
                    "\n".join(lines),
                    title="[cyan]Builder Explanation[/cyan]",
                    border_style="cyan",
                )
            )
    except typer.Exit:
        raise
    except Exception as exc:
        handle_error(exc)


async def _preview_from_spec(spec_path: Path, story_id: str | None) -> None:
    """Print the topologically-ordered manifests derived from a spec.

    Does NOT invoke the builder orchestrator -- actual per-manifest build
    dispatch lives in a future phase once the orchestrator grows a
    manifest-driven entry point. For now, the preview confirms the plumbing:
    spec -> persisted manifests -> topological order -> story filter.
    """
    if not spec_path.exists() or not spec_path.is_file():
        raise typer.BadParameter(f"Spec file not found: {spec_path}")

    root = Path.cwd()
    loader = TemplateLoader(root)
    doc = SpecParser(loader).parse(spec_path.read_text(encoding="utf-8"))

    async with get_services() as services:
        manager = services["manifest_manager"]
        manifests = list(await manager.list_by_spec(doc.frontmatter.spec_id))

    if not manifests:
        console.print(
            f"[yellow]No manifests found for spec {doc.frontmatter.spec_id}. Run `ces spec decompose` first.[/yellow]"
        )
        return

    ordered = _topological_sort_manifests(manifests)

    table = Table(title=f"Build order for {doc.frontmatter.spec_id}")
    table.add_column("Order")
    table.add_column("Story")
    table.add_column("Manifest")
    table.add_column("Description")

    order_index = 0
    for mf in ordered:
        if story_id and mf.parent_story_id != story_id:
            continue
        order_index += 1
        description = (mf.description or "").splitlines()[0] if mf.description else ""
        table.add_row(
            str(order_index),
            mf.parent_story_id or "",
            mf.manifest_id,
            description,
        )

    console.print(table)
    # TODO(phase-future): once BuilderFlowOrchestrator exposes a manifest-driven
    # entry point, iterate `ordered` (filtered) and dispatch each manifest.


def _topological_sort_manifests(manifests: list) -> list:
    """Kahn's algorithm keyed off TaskManifest.dependencies[].artifact_id.

    Manifests outside the input set are ignored (e.g., an inherited
    dependency on a manifest from a different spec does not block ordering).
    """
    by_id = {m.manifest_id: m for m in manifests}
    indegree: dict[str, int] = dict.fromkeys(by_id, 0)
    edges: dict[str, list[str]] = {mid: [] for mid in by_id}
    for m in manifests:
        for dep in m.dependencies:
            if dep.artifact_id in by_id:
                edges[dep.artifact_id].append(m.manifest_id)
                indegree[m.manifest_id] += 1
    queue = [mid for mid, n in indegree.items() if n == 0]
    out: list = []
    while queue:
        mid = queue.pop(0)
        out.append(by_id[mid])
        for nxt in edges[mid]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    return out
