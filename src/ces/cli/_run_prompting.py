"""Prompt-building helpers for the guided local-first build flow."""

from __future__ import annotations

from typing import Any

from ces.cli._builder_flow import BuilderBriefDraft
from ces.execution.pipeline import build_completion_gate_prompt_fragment_from_values
from ces.harness.prompts.engineering_charter import attach_engineering_charter
from ces.harness.services.change_impact import build_observability_acceptance_template
from ces.harness.services.framework_reminders import FrameworkReminder, render_framework_reminders
from ces.harness_evolution.memory import HarnessMemoryLesson, render_active_memory_lessons
from ces.verification.build_contract import GREENFIELD_PROOF_REQUIREMENTS, GREENFIELD_REQUIRED_ARTIFACTS

BUILDER_COMPLETION_SENSORS = ("test_pass", "lint", "typecheck", "coverage")


def build_prompt_pack(
    brief: BuilderBriefDraft,
    *,
    promoted_prl_statements: list[str] | None = None,
    manifest: Any | None = None,
    framework_reminders: list[FrameworkReminder] | None = None,
    harness_memory_lessons: list[HarnessMemoryLesson] | None = None,
) -> str:
    """Build the runtime prompt sent to the local execution provider."""

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
    rendered_reminders = render_framework_reminders(framework_reminders or [])
    if rendered_reminders:
        lines.extend(["", rendered_reminders])
    rendered_memory = render_active_memory_lessons(harness_memory_lessons or [])
    if rendered_memory:
        lines.extend(["", rendered_memory])
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
    if brief.project_mode == "greenfield":
        lines.extend(greenfield_acceptance_prompt_lines())
    if brief.project_mode == "brownfield":
        lines.extend(["", "Project Mode: brownfield"])
        if brief.source_of_truth:
            lines.append(f"Source Of Truth: {brief.source_of_truth}")
        if brief.critical_flows:
            lines.extend(["Critical Flows:", *[f"- {item}" for item in brief.critical_flows]])
        if manifest is not None and getattr(manifest, "manifest_id", None):
            lines.extend(
                [
                    "",
                    f"Completion claim identity: task_id must be the active manifest ID: {manifest.manifest_id}",
                    "Do not use OLB-* legacy behavior IDs as task_id; list those only as related legacy context.",
                ]
            )
        if promoted_prl_statements:
            lines.extend(["", "Promoted Legacy Requirements:", *[f"- {item}" for item in promoted_prl_statements]])
    elif looks_like_subproject_build(brief, manifest):
        lines.extend(
            [
                "",
                "Subproject Hygiene:",
                "- If you create an app/package in a subdirectory, run the subproject's own validation commands from that subdirectory.",
                "- Include install, test, typecheck, build, and lint evidence when those scripts exist.",
                "- For Node/Vite apps, remove generated artifacts such as node_modules, dist, and coverage before final parent-repo verification.",
                "- Document clean-checkout validation evidence and any provider/browser caveats in the subproject README or report.",
                "",
                "Standalone Product Boundary:",
                "- Do not put standalone product prototypes under packageable examples/ unless the acceptance criteria explicitly require examples/.",
                "- If the product is intended to live independently, document that it should be extracted to a sibling workspace/repository before release packaging.",
                "- If it must stay inside the current repo, make package inclusion/exclusion intent explicit in docs and validation evidence.",
            ]
        )
    completion_fragment = build_completion_gate_prompt_fragment_from_values(
        acceptance_criteria=brief.acceptance_criteria,
        verification_sensors=list(BUILDER_COMPLETION_SENSORS),
    )
    if completion_fragment:
        lines.append(completion_fragment)
    return attach_engineering_charter("\n".join(lines))


def greenfield_acceptance_prompt_lines() -> list[str]:
    """Return greenfield-specific acceptance instructions for runtime prompts."""

    return [
        "",
        "Greenfield Acceptance Contract:",
        "- Create a project a beginner can run from a fresh checkout.",
        "- Required artifacts: " + ", ".join(GREENFIELD_REQUIRED_ARTIFACTS) + ".",
        "- README.md must include how to run the app and how to test or verify it.",
        "- Run the strongest available local verification before claiming completion.",
        "- Keep the implementation boring and minimal: no new framework, service, dependency, background job, or abstraction unless required by the request.",
        "- In the final ces:completion block, include commands run, evidence for each acceptance criterion, complexity_notes, and unproven / remaining risks.",
        "- Proof requirements: " + "; ".join(GREENFIELD_PROOF_REQUIREMENTS) + ".",
        "- If you cannot verify something, say so clearly and leave it in open_questions or scope_deviations.",
        "- Next CES command after runtime exits: ces verify --json.",
    ]


def looks_like_subproject_build(brief: BuilderBriefDraft, manifest: Any | None) -> bool:
    """Return whether the prompt should warn about subproject hygiene."""

    haystack = "\n".join(
        [
            brief.request,
            *brief.constraints,
            *brief.acceptance_criteria,
            *[str(path) for path in (getattr(manifest, "affected_files", ()) or ())],
        ]
    ).casefold()
    return "/" in haystack and any(
        marker in haystack for marker in ("package.json", "vite", "node", "npm", "app", "examples/")
    )
