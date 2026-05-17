"""Completion-summary helpers for the guided local-first build flow."""

from __future__ import annotations

from ces.cli._builder_flow import BuilderBriefDraft
from ces.harness.models.control_plane_status import ControlPlaneStatus
from ces.harness.services.control_plane_status import build_control_plane_status
from ces.verification.completion_contract import CompletionContract


def acceptance_verified_from_auto_blockers(auto_blockers: list[str]) -> bool:
    """Return whether automatic blockers include acceptance/evidence failures."""

    acceptance_keywords = ("verification", "evidence", "completion")
    return not any(keyword in item.lower() for item in auto_blockers for keyword in acceptance_keywords)


def build_completion_summary(
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
    merge_not_applied: bool = False,
    control_status: ControlPlaneStatus | None = None,
    completion_contract: CompletionContract | None = None,
) -> str:
    """Build the concise user-facing run completion summary."""

    blockers = list(auto_blockers or [])
    if control_status is None:
        control_status = build_control_plane_status(
            code_completed=True,
            governance_enabled=governance,
            triage_color=triage_color,
            sensor_policy_blocking=any("sensor policy" in item.lower() for item in blockers),
            approval_decision=decision,
            merge_allowed=merge_allowed,
            merge_not_applied=merge_not_applied,
            auto_blockers=blockers,
            acceptance_verified=acceptance_verified_from_auto_blockers(blockers),
        )
    outcome = control_status.summary_outcome
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
                f"Governance: {control_status.governance_state.value}",
                f"Ready to ship: {'yes' if control_status.ready_to_ship else 'no'}",
            ]
        )
    else:
        lines.append("Need deeper CES details? Re-run with `--governance` or use `ces review`.")
    if brief.project_mode == "greenfield":
        lines.extend(greenfield_handoff_lines(completion_contract))
    if auto_blockers:
        lines.append("Blocking reasons:")
        lines.extend(f"- {item}" for item in auto_blockers)
        lines.append("Next: ces why")
        if any("evidence" in item.lower() or "verification" in item.lower() for item in auto_blockers):
            lines.append("Next: ces recover --dry-run")
    elif decision != "approve":
        lines.append("Next: ces why")
    elif merge_allowed is False:
        lines.append("Next: ces report builder" if merge_not_applied else "Next: ces why")
    else:
        lines.append("Next: ces report builder")
    if prl_draft_path:
        lines.append(f"PRL draft: {prl_draft_path}")
    return "\n".join(lines)


def greenfield_handoff_lines(completion_contract: CompletionContract | None) -> list[str]:
    """Return greenfield handoff lines for the completion summary."""

    commands = list(completion_contract.inferred_commands if completion_contract is not None else ())
    test_commands = [
        command.command for command in commands if command.kind in {"test", "typecheck", "lint", "build", "compile"}
    ]
    run_commands = [command.command for command in commands if command.kind in {"smoke", "serve", "run"}]
    next_command = completion_contract.next_ces_command if completion_contract is not None else "ces verify --json"
    lines = [
        "How to run: see README.md and run the app's documented local command.",
        "How to test: " + ("; ".join(test_commands) if test_commands else "run the README's documented test command"),
    ]
    if run_commands:
        lines.append("Runnable smoke: " + "; ".join(run_commands))
    lines.extend(
        [
            "Unproven / remaining risks: review open_questions, scope_deviations, skipped verification, and any manual-only evidence before shipping.",
            f"Next CES command: {next_command}",
        ]
    )
    return lines
