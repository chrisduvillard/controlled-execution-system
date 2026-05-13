"""Helpers backing ``ces explain`` (overview / decisioning / brownfield views).

Extracted from ``run_cmd.py`` so each view's rendering logic lives next to
the data-loading helpers it consumes. ``_should_run_brownfield_review``
also drives the build path in ``run_cmd._run_brief_flow``; it's exposed
here as the single source of truth for "does this session need brownfield
review?".

All public-by-prefix-but-private-by-naming-convention helpers in this
module are addressed via ``cli._explain_views.X``; nothing in here is
re-exported from ``ces.cli``.
"""

from __future__ import annotations

from typing import Any

import typer

from ces.harness.services.evidence_quality import compute_evidence_quality_state


def normalize_explain_view(view: str) -> str:
    normalized = view.strip().lower()
    if normalized not in {"overview", "decisioning", "brownfield"}:
        raise typer.BadParameter("Explain view must be one of: overview, decisioning, brownfield.")
    return normalized


def load_latest_builder_snapshot(local_store: Any) -> Any | None:
    get_snapshot = getattr(local_store, "get_latest_builder_session_snapshot", None)
    if callable(get_snapshot):
        candidate = get_snapshot()
        if isinstance(getattr(candidate, "request", None), str):
            return candidate
    return None


def load_explain_record(local_store: Any, session: Any | None) -> tuple[Any, bool]:
    import sqlite3

    record = None
    if session is not None and getattr(session, "brief_id", None) and hasattr(local_store, "get_builder_brief"):
        try:
            record = local_store.get_builder_brief(session.brief_id)
        except (sqlite3.Error, AttributeError, KeyError):
            # Best-effort lookup. SQLite errors / missing methods on test
            # mocks fall through to the get_latest_builder_brief() backstop
            # below.
            record = None
        if not isinstance(getattr(record, "request", None), str):
            record = None
    if record is None:
        record = local_store.get_latest_builder_brief()
    return record, session is None


def load_explain_manifest(local_store: Any, session: Any | None, record: Any) -> Any | None:
    manifest_id = getattr(session, "manifest_id", None) or getattr(record, "manifest_id", None)
    if not manifest_id or not hasattr(local_store, "get_manifest_row"):
        return None
    return local_store.get_manifest_row(manifest_id)


def load_explain_evidence(local_store: Any, session: Any | None, record: Any) -> dict[str, Any] | None:
    manifest_id = getattr(session, "manifest_id", None) or getattr(record, "manifest_id", None)
    if not manifest_id or not hasattr(local_store, "get_evidence"):
        return None
    return local_store.get_evidence(manifest_id)


def format_stage_label(stage: str | None) -> str:
    labels = {
        "collecting": "collecting context",
        "ready_to_run": "ready to run",
        "running": "running",
        "awaiting_review": "awaiting review",
        "completed": "completed",
        "blocked": "blocked",
    }
    return labels.get(stage or "", stage or "unknown")


def describe_follow_up_reasons(record: Any) -> list[str]:
    reasons: list[str] = []
    open_questions = dict(getattr(record, "open_questions", {}) or {})
    project_mode = getattr(record, "project_mode", "")
    if "constraints" in open_questions or getattr(record, "constraints", None):
        reasons.append("to keep the work inside your technical boundaries")
    if "acceptance" in open_questions or getattr(record, "acceptance_criteria", None):
        reasons.append("to understand what done should look like before CES runs anything")
    if "must_not_break" in open_questions or getattr(record, "must_not_break", None):
        reasons.append("to avoid breaking existing behavior that you explicitly care about")
    if project_mode == "brownfield" and ("source_of_truth" in open_questions or getattr(record, "source_of_truth", "")):
        reasons.append("to anchor brownfield decisions to the best available source of truth")
    if project_mode == "brownfield" and ("critical_flows" in open_questions or getattr(record, "critical_flows", None)):
        reasons.append("to protect the highest-value legacy flows during implementation")
    deduped: list[str] = []
    for reason in reasons:
        if reason not in deduped:
            deduped.append(reason)
    return deduped


def describe_latest_activity(session: Any | None, evidence: dict[str, Any] | None) -> str:
    if session is None:
        return "CES has a saved builder brief but no newer session activity yet."
    mapping = {
        "brief_captured": "CES captured the builder brief and is ready to continue.",
        "execution_started": "CES started the local runtime execution.",
        "brownfield_review_in_progress": "CES paused during grouped brownfield review.",
        "brownfield_review_completed": "CES finished grouped brownfield review and returned to the main flow.",
        "evidence_ready": "CES gathered runtime evidence and synthesized a review summary.",
        "runtime_missing": "CES could not find a supported local runtime.",
        "runtime_failed": "The last runtime execution failed before CES could finish the flow.",
        "approval_recorded": "CES recorded the latest review decision.",
        "approval_rejected": "CES recorded that the last review did not pass.",
        "legacy_brief_backfill": "CES reconstructed a builder session from an older saved brief.",
    }
    activity = mapping.get(getattr(session, "last_action", None))
    if activity:
        return activity
    if evidence is not None and evidence.get("summary"):
        return f"CES has evidence from the last run: {evidence['summary']}"
    return "CES has saved builder progress for this request."


def describe_blocker(session: Any | None, pending_count: int) -> str:
    if session is None:
        return "Waiting to continue from the saved builder brief."
    recovery_reason = getattr(session, "recovery_reason", None)
    next_action = getattr(session, "next_action", "")
    stage = getattr(session, "stage", "")
    if recovery_reason == "retry_execution":
        return "Waiting for a runtime retry."
    if recovery_reason == "install_runtime":
        return "Waiting for a supported local runtime on PATH."
    if recovery_reason == "needs_review":
        return "Waiting for another review pass."
    if recovery_reason == "needs_input":
        return "Waiting for more input."
    if next_action == "review_brownfield":
        return "Waiting for grouped brownfield review."
    if stage == "awaiting_review" or next_action == "review_evidence":
        return "Review evidence before shipping."
    if stage == "running":
        return "CES is running the task now."
    if stage == "ready_to_run":
        return "Ready to run."
    if stage == "completed":
        return "This builder session is complete."
    if pending_count:
        return "Pending brownfield decisions remain."
    return "Waiting for the next builder action."


def describe_next_step(session: Any | None, pending_count: int) -> str:
    if session is None:
        return "Run `ces continue` to resume from the saved builder brief."
    next_action = getattr(session, "next_action", "")
    mapping = {
        "run_continue": "Run `ces continue` to start the next execution pass.",
        "install_runtime": "Install and authenticate `codex` or `claude`, then run `ces continue`.",
        "retry_runtime": "Retry the last runtime execution with `ces continue`.",
        "review_evidence": "Review the evidence and decide whether to ship the change.",
        "review_brownfield": "Run `ces continue` to resume grouped brownfield review.",
        "answer_builder_questions": "Answer the remaining builder questions so CES can continue.",
        "start_new_session": "Start a new task with `ces build` when you're ready for the next request.",
    }
    if next_action in mapping:
        return mapping[next_action]
    if pending_count:
        return "Resolve the pending brownfield decisions, then run `ces continue`."
    return "Run `ces continue` to move this builder session forward."


def serialize_brownfield_checkpoint(session: Any | None) -> dict[str, Any] | None:
    if session is None:
        return None
    checkpoint = getattr(session, "brownfield_review_state", None)
    return checkpoint if isinstance(checkpoint, dict) else None


def should_run_brownfield_review(session: Any | None) -> bool:
    if session is None:
        return True
    if serialize_brownfield_checkpoint(session) is not None:
        return True
    if getattr(session, "next_action", None) == "review_brownfield":
        return True
    return getattr(session, "last_action", None) in {
        None,
        "",
        "brief_captured",
        "legacy_brief_backfill",
    }


def build_overview_explanation_lines(
    *,
    record: Any,
    session: Any | None,
    evidence: dict[str, Any] | None,
    pending_count: int,
    brief_only_fallback: bool,
    latest_activity: str | None = None,
    next_step: str | None = None,
    intent_gate_preflight: Any | None = None,
) -> list[str]:
    lines = [
        f"CES thinks you're building: {record.request}",
        f"Project mode: {getattr(record, 'project_mode', 'unknown')}",
    ]
    if brief_only_fallback:
        lines.append("No builder session is recorded yet.")
        lines.append("CES is explaining from the saved builder brief.")
        lines.append("Newer detail appears after CES records a session.")
    reasons = describe_follow_up_reasons(record)
    if reasons:
        lines.append("Why CES asked follow-up questions:")
        lines.extend(f"- CES asked {reason}." for reason in reasons)
    lines.extend(_intent_gate_summary_lines(intent_gate_preflight))
    lines.append(f"Current stage: {format_stage_label(getattr(session, 'stage', None))}")
    lines.append(f"Blocking/pending: {describe_blocker(session, pending_count)}")
    lines.append(f"Latest activity: {latest_activity or describe_latest_activity(session, evidence)}")
    lines.append(f"Next step: {next_step or describe_next_step(session, pending_count)}")
    return lines


def build_decisioning_explanation_lines(
    *,
    record: Any,
    session: Any | None,
    manifest: Any | None,
    evidence: dict[str, Any] | None,
    pending_count: int,
    governance: bool,
    intent_gate_preflight: Any | None = None,
) -> list[str]:
    planned_change = getattr(manifest, "description", None) or record.request
    lines = [
        f"CES planned this change as: {planned_change}",
        f"Current stage: {format_stage_label(getattr(session, 'stage', None))}",
        f"Review state: {describe_blocker(session, pending_count)}",
    ]
    if evidence is not None and evidence.get("summary"):
        lines.append(f"Evidence gathered: {evidence['summary']}")
    else:
        lines.append("Evidence gathered: CES has not recorded a detailed evidence packet yet.")
    lines.append(f"Evidence quality: {compute_evidence_quality_state(evidence)}")
    challenge = evidence.get("challenge") if evidence is not None else None
    if challenge:
        lines.append(f"Main challenge: {challenge}")
    lines.extend(_intent_gate_summary_lines(intent_gate_preflight))
    if governance:
        if manifest is not None:
            lines.append(f"Manifest ID: {manifest.manifest_id}")
            lines.append(f"Workflow state: {getattr(manifest, 'workflow_state', 'unknown')}")
            lines.append(f"Risk tier: {getattr(manifest, 'risk_tier', 'unknown')}")
            lines.append(f"Change class: {getattr(manifest, 'change_class', 'unknown')}")
            if not getattr(manifest, "verification_sensors", ()):
                lines.append("Verification sensors: none configured (expert opt-out)")
        if evidence is not None:
            if evidence.get("packet_id"):
                lines.append(f"Evidence packet: {evidence['packet_id']}")
            lines.append(f"Triage color: {evidence.get('triage_color', 'unknown')}")
            runtime_safety = _evidence_content(evidence).get("runtime_safety", {})
            if isinstance(runtime_safety, dict):
                if "tool_allowlist_enforced" in runtime_safety:
                    lines.append(f"Runtime tool allowlist enforced: {runtime_safety['tool_allowlist_enforced']}")
                if runtime_safety.get("accepted_runtime_side_effect_risk"):
                    lines.append("Runtime side-effect waiver: accepted by operator")
                if "mcp_grounding_supported" in runtime_safety:
                    lines.append(f"MCP grounding supported: {runtime_safety['mcp_grounding_supported']}")
        if session is not None:
            lines.append(f"Session next action: {getattr(session, 'next_action', 'unknown')}")
            if getattr(session, "recovery_reason", None):
                lines.append(f"Recovery reason: {session.recovery_reason}")
    return lines


def _intent_gate_summary_lines(value: Any | None) -> list[str]:
    if value is None:
        return []
    preflight = getattr(value, "preflight", value)
    decision = getattr(preflight, "decision", None)
    safe_next_step = getattr(preflight, "safe_next_step", None)
    preflight_id = getattr(preflight, "preflight_id", None)
    ledger = getattr(preflight, "ledger", None)
    if not decision:
        return []
    lines = [f"Intent Gate decision: {decision}"]
    if preflight_id:
        lines.append(f"Intent Gate preflight: {preflight_id}")
    if safe_next_step:
        lines.append(f"Intent Gate safe next step: {safe_next_step}")
    if ledger is not None:
        lines.append(
            "Intent Gate ledger: "
            f"{len(tuple(getattr(ledger, 'open_questions', ()) or ()))} open questions, "
            f"{len(tuple(getattr(ledger, 'assumptions', ()) or ()))} assumptions, "
            f"{len(tuple(getattr(ledger, 'acceptance_criteria', ()) or ()))} acceptance criteria"
        )
    return lines


def _evidence_content(evidence: dict[str, Any]) -> dict[str, Any]:
    content = evidence.get("content")
    return content if isinstance(content, dict) else evidence


def build_brownfield_explanation_lines(
    *,
    record: Any,
    session: Any | None,
    pending_count: int,
    governance: bool,
) -> list[str]:
    lines = [
        f"CES thinks you're building: {record.request}",
        "Brownfield review focuses on must-not-break behavior, critical flows, repo signals, and source-of-truth hints.",
    ]
    checkpoint = serialize_brownfield_checkpoint(session)
    if checkpoint is not None:
        groups = checkpoint.get("groups", [])
        reviewed_count = len(checkpoint.get("reviewed_candidates", []))
        total_count = sum(len(group.get("items", [])) for group in groups)
        remaining_count = max(total_count - reviewed_count, 0)
        group_index = int(checkpoint.get("group_index", 0))
        current_group = groups[group_index].get("label", "Unknown") if 0 <= group_index < len(groups) else "Complete"
        reviewed_label = "review item" if reviewed_count == 1 else "review items"
        remaining_label = "review item" if remaining_count == 1 else "review items"
        lines.append(
            f"Brownfield review progress: {reviewed_count} {reviewed_label} checked, "
            f"{remaining_count} {remaining_label} remaining"
        )
        lines.append(f"Current group: {current_group}")
        lines.append("CES will resume this checkpoint when you run `ces continue`.")
    else:
        lines.append("CES does not have an in-progress grouped brownfield checkpoint for this session.")
    if pending_count:
        suffix = "decision" if pending_count == 1 else "decisions"
        lines.append(f"Pending brownfield queue: {pending_count} {suffix}")
    blocker = describe_blocker(session, pending_count)
    lines.append(f"What CES is waiting on: {blocker}")
    if governance and checkpoint is not None:
        lines.append(f"Checkpoint group index: {checkpoint.get('group_index', 0)}")
        lines.append(f"Checkpoint item index: {checkpoint.get('item_index', 0)}")
    return lines
