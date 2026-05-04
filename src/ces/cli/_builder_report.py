"""Helpers for normalizing and exporting the current builder session truth."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ces.harness.services.evidence_quality import compute_evidence_quality_state


@dataclass(frozen=True)
class BuilderRunReport:
    session_id: str | None
    request: str
    project_mode: str
    stage: str
    review_state: str
    latest_outcome: str
    latest_activity: str
    next_step: str
    latest_artifact: str | None
    manifest_id: str | None
    evidence_packet_id: str | None
    approval_decision: str | None
    workflow_state: str | None
    triage_color: str | None
    evidence_quality_state: str
    verification_sensor_state: str
    runtime_tool_allowlist_enforced: bool | None
    runtime_side_effect_waived: bool
    mcp_grounding_supported: bool | None
    prl_draft_path: str | None
    reported_model: str | None
    verification_findings: tuple[str, ...]
    superseded_verification_findings: tuple[str, ...]
    independent_verification_passed: bool | None
    completion_contract_path: str | None
    manual_completion_supersedes_rejected_auto_review: bool
    brownfield_reviewed_count: int
    brownfield_remaining_count: int
    brownfield_entry_reviewed_count: int = 0
    brownfield_entry_remaining_count: int = 0
    brownfield_item_reviewed_count: int = 0
    brownfield_item_remaining_count: int = 0


@dataclass(frozen=True)
class BuilderRunReportArtifacts:
    markdown_path: Path
    json_path: Path
    report: BuilderRunReport


def build_builder_run_report(snapshot: Any) -> BuilderRunReport | None:
    request = _text(getattr(snapshot, "request", None))
    if not request:
        return None
    session = getattr(snapshot, "session", None)
    brief = getattr(snapshot, "brief", None)
    manifest = getattr(snapshot, "manifest", None)
    runtime_execution = getattr(snapshot, "runtime_execution", None)
    evidence = getattr(snapshot, "evidence", None)
    approval = getattr(snapshot, "approval", None)
    brownfield = getattr(snapshot, "brownfield", None)

    approval_decision = _normalize_approval_decision(getattr(approval, "decision", None))
    workflow_state = _effective_workflow_state(
        stored_workflow_state=_text(getattr(manifest, "workflow_state", None)),
        approval_decision=approval_decision,
        stage=_text(getattr(snapshot, "stage", None)) or _text(getattr(session, "stage", None)),
    )
    review_state = _derive_review_state(
        approval_decision=approval_decision,
        workflow_state=workflow_state,
        stage=_text(getattr(snapshot, "stage", None)) or _text(getattr(session, "stage", None)),
        next_action=_text(getattr(snapshot, "next_action", None)) or _text(getattr(session, "next_action", None)),
    )
    latest_outcome = _derive_latest_outcome(
        approval_decision=approval_decision,
        runtime_exit_code=getattr(runtime_execution, "exit_code", None),
        has_evidence=isinstance(evidence, dict) and bool(evidence.get("packet_id")),
        has_manifest=manifest is not None,
        latest_artifact=_text(getattr(snapshot, "latest_artifact", None)),
        brief_only_fallback=bool(getattr(snapshot, "brief_only_fallback", False)),
    )
    runtime_safety = _runtime_safety_content(evidence if isinstance(evidence, dict) else None)
    raw_verification_findings = _verification_findings(evidence if isinstance(evidence, dict) else None)
    raw_superseded_verification_findings = _superseded_verification_findings(
        evidence if isinstance(evidence, dict) else None
    )
    independent_verification_passed = _independent_verification_passed(evidence if isinstance(evidence, dict) else None)
    completion_contract_path = _completion_contract_path(evidence if isinstance(evidence, dict) else None)
    approved_by_independent_verification = approval_decision == "approved" and independent_verification_passed is True
    verification_findings = () if approved_by_independent_verification else raw_verification_findings
    superseded_verification_findings = (
        raw_superseded_verification_findings + raw_verification_findings
        if approved_by_independent_verification
        else raw_superseded_verification_findings
    )
    evidence_quality_state = (
        "passed"
        if approved_by_independent_verification
        else compute_evidence_quality_state(evidence if isinstance(evidence, dict) else None)
    )
    triage_color = (
        "green"
        if approved_by_independent_verification
        else evidence.get("triage_color")
        if isinstance(evidence, dict)
        else None
    )
    brownfield_counts = _brownfield_counts(brownfield)
    return BuilderRunReport(
        session_id=_text(getattr(session, "session_id", None)),
        request=request,
        project_mode=_text(getattr(snapshot, "project_mode", None)) or "unknown",
        stage=_text(getattr(snapshot, "stage", None)) or _text(getattr(session, "stage", None)) or "unknown",
        review_state=review_state,
        latest_outcome=latest_outcome,
        latest_activity=_text(getattr(snapshot, "latest_activity", None))
        or "CES has saved builder progress for this request.",
        next_step=_text(getattr(snapshot, "next_step", None))
        or "Run `ces continue` to move this builder session forward.",
        latest_artifact=_text(getattr(snapshot, "latest_artifact", None)),
        manifest_id=_text(getattr(manifest, "manifest_id", None)),
        evidence_packet_id=evidence.get("packet_id") if isinstance(evidence, dict) else None,
        approval_decision=approval_decision,
        workflow_state=workflow_state,
        triage_color=triage_color,
        evidence_quality_state=evidence_quality_state,
        verification_sensor_state=(
            "configured"
            if tuple(getattr(manifest, "verification_sensors", ()) or ())
            else "none_configured_expert_opt_out"
        ),
        runtime_tool_allowlist_enforced=_optional_bool(runtime_safety.get("tool_allowlist_enforced")),
        runtime_side_effect_waived=bool(runtime_safety.get("accepted_runtime_side_effect_risk")),
        mcp_grounding_supported=_optional_bool(runtime_safety.get("mcp_grounding_supported")),
        prl_draft_path=_text(getattr(brief, "prl_draft_path", None)),
        reported_model=_text(getattr(runtime_execution, "reported_model", None)),
        verification_findings=verification_findings,
        superseded_verification_findings=superseded_verification_findings,
        independent_verification_passed=independent_verification_passed,
        completion_contract_path=completion_contract_path,
        manual_completion_supersedes_rejected_auto_review=(
            approval_decision == "approved" and bool(verification_findings or superseded_verification_findings)
        ),
        brownfield_reviewed_count=brownfield_counts["entry_reviewed"],
        brownfield_remaining_count=brownfield_counts["entry_remaining"],
        brownfield_entry_reviewed_count=brownfield_counts["entry_reviewed"],
        brownfield_entry_remaining_count=brownfield_counts["entry_remaining"],
        brownfield_item_reviewed_count=brownfield_counts["item_reviewed"],
        brownfield_item_remaining_count=brownfield_counts["item_remaining"],
    )


def load_builder_run_report(local_store: Any) -> BuilderRunReport | None:
    get_snapshot = getattr(local_store, "get_latest_builder_session_snapshot", None)
    if not callable(get_snapshot):
        return None
    return build_builder_run_report(get_snapshot())


def load_matching_builder_run_report(
    local_store: Any,
    *,
    manifest_id: str | None = None,
) -> BuilderRunReport | None:
    report = load_builder_run_report(local_store)
    if report is None:
        return None
    if manifest_id is not None and report.manifest_id != manifest_id:
        return None
    return report


def serialize_builder_run_report(report: BuilderRunReport | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return asdict(report)


def summarize_builder_run(report: BuilderRunReport) -> list[str]:
    lines = [
        f"Builder request: {report.request}",
        f"Project mode: {report.project_mode}",
        f"Review state: {report.review_state}",
        f"Latest outcome: {report.latest_outcome}",
        f"Latest activity: {report.latest_activity}",
        f"Next step: {report.next_step}",
    ]
    if report.manifest_id:
        lines.append(f"Manifest: {report.manifest_id}")
    if report.evidence_packet_id:
        lines.append(f"Evidence packet: {report.evidence_packet_id}")
    lines.append(f"Evidence quality: {report.evidence_quality_state}")
    if report.completion_contract_path:
        lines.append(f"Completion contract: {report.completion_contract_path}")
    if report.independent_verification_passed is not None:
        lines.append(f"Independent verification passed: {report.independent_verification_passed}")
    lines.append(f"Verification sensors: {report.verification_sensor_state}")
    if report.runtime_tool_allowlist_enforced is not None:
        lines.append(f"Runtime tool allowlist enforced: {report.runtime_tool_allowlist_enforced}")
        lines.append(f"Runtime side-effect waiver accepted: {report.runtime_side_effect_waived}")
    if report.mcp_grounding_supported is not None:
        lines.append(f"MCP grounding supported: {report.mcp_grounding_supported}")
    if report.manual_completion_supersedes_rejected_auto_review:
        lines.append("Manual completion superseded failed auto-approval: True")
    if report.verification_findings:
        lines.append("Verification findings:")
        lines.extend(f"- {finding}" for finding in report.verification_findings[:5])
    if report.superseded_verification_findings:
        lines.append("Superseded verification findings:")
        lines.extend(f"- {finding}" for finding in report.superseded_verification_findings[:5])
    return lines


def export_builder_run_report(
    *,
    output_dir: Path,
    snapshot: Any,
) -> BuilderRunReportArtifacts:
    report = build_builder_run_report(snapshot)
    if report is None:
        raise ValueError("No builder run report could be derived from the current snapshot.")
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"builder-run-report-{_slugify(report.session_id or report.manifest_id or 'latest')}"
    markdown_path = output_dir / f"{stem}.md"
    json_path = output_dir / f"{stem}.json"
    json_path.write_text(
        json.dumps(serialize_builder_run_report(report), indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(render_builder_run_report_markdown(report), encoding="utf-8")
    return BuilderRunReportArtifacts(
        markdown_path=markdown_path,
        json_path=json_path,
        report=report,
    )


def render_builder_run_report_markdown(report: BuilderRunReport) -> str:
    lines = [
        f"# Builder Run Report - {report.request}",
        "",
        f"- Request: {report.request}",
        f"- Project mode: {report.project_mode}",
        f"- Stage: {report.stage}",
        f"- Review state: {report.review_state}",
        f"- Latest outcome: {report.latest_outcome}",
        f"- Latest activity: {report.latest_activity}",
        f"- Next step: {report.next_step}",
        f"- Latest artifact: {report.latest_artifact or 'unknown'}",
        f"- Manifest ID: {report.manifest_id or 'none'}",
        f"- Evidence packet ID: {report.evidence_packet_id or 'none'}",
        f"- Approval decision: {report.approval_decision or 'none'}",
        f"- Workflow state: {report.workflow_state or 'unknown'}",
        f"- Triage color: {report.triage_color or 'unknown'}",
        f"- Evidence quality: {report.evidence_quality_state}",
        f"- Completion contract: {report.completion_contract_path or 'none'}",
        f"- Independent verification passed: {_render_optional_bool(report.independent_verification_passed)}",
        f"- Verification sensors: {report.verification_sensor_state}",
        f"- Runtime tool allowlist enforced: {_render_optional_bool(report.runtime_tool_allowlist_enforced)}",
        f"- Runtime side-effect waiver accepted: {report.runtime_side_effect_waived}",
        f"- MCP grounding supported: {_render_optional_bool(report.mcp_grounding_supported)}",
        f"- Reported model: {report.reported_model or 'unknown'}",
        f"- Manual completion superseded failed auto-approval: {report.manual_completion_supersedes_rejected_auto_review}",
    ]
    if report.prl_draft_path:
        lines.append(f"- PRL draft: {report.prl_draft_path}")
    if report.verification_findings:
        lines.extend(["", "## Verification Findings", ""])
        lines.extend(f"- {finding}" for finding in report.verification_findings)
    if report.superseded_verification_findings:
        lines.extend(["", "## Superseded Verification Findings", ""])
        lines.extend(f"- {finding}" for finding in report.superseded_verification_findings)
    if report.project_mode == "brownfield":
        lines.append(f"- Brownfield progress: {format_brownfield_progress(report)}")
    return "\n".join(lines) + "\n"


def format_brownfield_progress(report_or_brownfield: Any) -> str:
    """Render entry-level brownfield progress without hiding item-level review work.

    ``reviewed_count`` historically counted lower-level checkpoint items in some
    builder sessions. Operators, however, see and act on OLB behavior entries.
    Prefer the explicit entry-id count when present and keep checkpoint item
    counts as parenthetical diagnostics.
    """

    if isinstance(report_or_brownfield, BuilderRunReport):
        entry_reviewed = report_or_brownfield.brownfield_entry_reviewed_count
        entry_remaining = report_or_brownfield.brownfield_entry_remaining_count
        item_reviewed = report_or_brownfield.brownfield_item_reviewed_count
        item_remaining = report_or_brownfield.brownfield_item_remaining_count
        if (
            entry_reviewed == 0
            and entry_remaining == 0
            and item_reviewed == 0
            and item_remaining == 0
            and (report_or_brownfield.brownfield_reviewed_count or report_or_brownfield.brownfield_remaining_count)
        ):
            entry_reviewed = report_or_brownfield.brownfield_reviewed_count
            entry_remaining = report_or_brownfield.brownfield_remaining_count
            item_reviewed = report_or_brownfield.brownfield_reviewed_count
            item_remaining = report_or_brownfield.brownfield_remaining_count
    else:
        counts = _brownfield_counts(report_or_brownfield)
        entry_reviewed = counts["entry_reviewed"]
        entry_remaining = counts["entry_remaining"]
        item_reviewed = counts["item_reviewed"]
        item_remaining = counts["item_remaining"]

    behavior = "behavior" if entry_reviewed == 1 else "behaviors"
    remaining_behavior = "behavior" if entry_remaining == 1 else "behaviors"
    text = f"{entry_reviewed} {behavior} reviewed, {entry_remaining} {remaining_behavior} remaining"
    if item_reviewed != entry_reviewed or item_remaining != entry_remaining:
        reviewed_item = "review item" if item_reviewed == 1 else "review items"
        remaining_item = "review item" if item_remaining == 1 else "review items"
        text += f" ({item_reviewed} {reviewed_item} checked, {item_remaining} {remaining_item} remaining)"
    return text


def _brownfield_counts(brownfield: Any) -> dict[str, int]:
    raw_reviewed = int(getattr(brownfield, "reviewed_count", 0) or 0)
    raw_remaining = int(getattr(brownfield, "remaining_count", 0) or 0)
    checkpoint = getattr(brownfield, "checkpoint", None)
    entry_ids = tuple(getattr(brownfield, "entry_ids", ()) or ())
    if not entry_ids:
        entry_ids = _checkpoint_reviewed_entry_ids(checkpoint)
    checkpoint_reviewed = _checkpoint_reviewed_item_count(checkpoint)
    item_reviewed = checkpoint_reviewed if checkpoint_reviewed is not None else raw_reviewed
    item_remaining = raw_remaining
    has_entry_level_truth = bool(entry_ids)
    entry_reviewed = len(entry_ids) if has_entry_level_truth else raw_reviewed
    entry_remaining = (
        int(getattr(brownfield, "entry_remaining_count", 0) or 0) if has_entry_level_truth else raw_remaining
    )
    return {
        "entry_reviewed": entry_reviewed,
        "entry_remaining": entry_remaining,
        "item_reviewed": item_reviewed,
        "item_remaining": item_remaining,
    }


def _checkpoint_reviewed_entry_ids(checkpoint: Any) -> tuple[str, ...]:
    if not isinstance(checkpoint, dict):
        return ()
    reviewed = checkpoint.get("reviewed_entry_ids")
    if not isinstance(reviewed, list):
        return ()
    return tuple(entry_id for entry_id in reviewed if isinstance(entry_id, str) and entry_id.strip())


def _checkpoint_reviewed_item_count(checkpoint: Any) -> int | None:
    if not isinstance(checkpoint, dict):
        return None
    reviewed = checkpoint.get("reviewed_candidates")
    if isinstance(reviewed, list):
        return len(reviewed)
    return None


def _effective_workflow_state(
    *,
    stored_workflow_state: str | None,
    approval_decision: str | None,
    stage: str | None,
) -> str | None:
    """Resolve stale manual-completion states for operator-facing status."""
    if approval_decision == "approved" and stage == "completed" and stored_workflow_state == "rejected":
        return "approved"
    return stored_workflow_state


def _derive_review_state(
    *,
    approval_decision: str | None,
    workflow_state: str | None,
    stage: str | None,
    next_action: str | None,
) -> str:
    if approval_decision == "approved":
        return "approved"
    if approval_decision == "rejected":
        return "rejected"
    if workflow_state:
        return workflow_state
    if stage == "awaiting_review" or next_action == "review_evidence":
        return "under_review"
    if stage:
        return stage
    return "unknown"


def _derive_latest_outcome(
    *,
    approval_decision: str | None,
    runtime_exit_code: Any,
    has_evidence: bool,
    has_manifest: bool,
    latest_artifact: str | None,
    brief_only_fallback: bool,
) -> str:
    if approval_decision == "approved":
        return "approved"
    if approval_decision == "rejected":
        return "rejected"
    if isinstance(runtime_exit_code, int) and runtime_exit_code != 0:
        return "runtime_failed"
    if has_evidence:
        return "evidence_ready"
    if has_manifest:
        return "manifest_ready"
    if brief_only_fallback:
        return "brief_captured"
    if latest_artifact:
        return latest_artifact
    return "unknown"


def _normalize_approval_decision(value: Any) -> str | None:
    text = _text(value)
    if text in {"approve", "approved"}:
        return "approved"
    if text in {"reject", "rejected"}:
        return "rejected"
    return text


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "latest"


def _text(value: Any) -> str | None:
    primitive = getattr(value, "value", value)
    if primitive is None:
        return None
    if isinstance(primitive, str):
        stripped = primitive.strip()
        return stripped or None
    return str(primitive)


def _runtime_safety_content(evidence: dict[str, Any] | None) -> dict[str, Any]:
    content = _evidence_content(evidence)
    runtime_safety = content.get("runtime_safety")
    if isinstance(runtime_safety, dict):
        return runtime_safety
    superseded = _superseded_evidence_content(content)
    runtime_safety = superseded.get("runtime_safety")
    return runtime_safety if isinstance(runtime_safety, dict) else {}


def _verification_findings(evidence: dict[str, Any] | None) -> tuple[str, ...]:
    content = _evidence_content(evidence)
    verification = content.get("verification_result")
    return _verification_finding_messages(verification)


def _superseded_verification_findings(evidence: dict[str, Any] | None) -> tuple[str, ...]:
    content = _evidence_content(evidence)
    verification = _superseded_evidence_content(content).get("verification_result")
    return _verification_finding_messages(verification)


def _verification_finding_messages(verification: Any) -> tuple[str, ...]:
    if not isinstance(verification, dict) or verification.get("passed") is not False:
        return ()
    findings = verification.get("findings", ())
    messages: list[str] = []
    if isinstance(findings, list):
        for finding in findings:
            if isinstance(finding, dict):
                message = finding.get("message")
            else:
                message = getattr(finding, "message", None)
            if isinstance(message, str) and message.strip():
                messages.append(message.strip())
    return tuple(messages)


def _superseded_evidence_content(content: dict[str, Any]) -> dict[str, Any]:
    superseded = content.get("superseded_evidence")
    return _evidence_content(superseded) if isinstance(superseded, dict) else {}


def _independent_verification_passed(evidence: dict[str, Any] | None) -> bool | None:
    content = _evidence_content(evidence)
    verification = content.get("independent_verification")
    if not isinstance(verification, dict):
        verification = _superseded_evidence_content(content).get("independent_verification")
    passed = verification.get("passed") if isinstance(verification, dict) else None
    return passed if isinstance(passed, bool) else None


def _completion_contract_path(evidence: dict[str, Any] | None) -> str | None:
    content = _evidence_content(evidence)
    value = content.get("completion_contract_path")
    if not isinstance(value, str):
        value = _superseded_evidence_content(content).get("completion_contract_path")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _evidence_content(evidence: Any) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        return {}
    content = evidence.get("content")
    return content if isinstance(content, dict) else evidence


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _render_optional_bool(value: bool | None) -> str:
    return "unknown" if value is None else str(value)
