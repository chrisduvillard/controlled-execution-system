"""Shared local execution pipeline helpers.

This module holds prompt and result-normalization pieces used by both expert
`ces execute` and builder-first runtime paths so lifecycle policy does not drift
inside CLI command modules.
"""

from __future__ import annotations

from typing import Any

from ces.harness.prompts.engineering_charter import attach_engineering_charter
from ces.harness.services.change_impact import build_observability_acceptance_template

SIMPLICITY_GUARD_INSTRUCTIONS = """\

## Simplicity Guard

Prefer the smallest boring solution that satisfies the acceptance criteria.
Do not add frameworks, services, layers, abstractions, dependencies, background jobs,
configuration systems, or architectural rewrites unless the task clearly requires them.
Before editing, inspect existing patterns and reuse them. If you introduce complexity,
state why the simpler alternative was insufficient and include proof in
`complexity_notes`.
"""

COMPLETION_CLAIM_INSTRUCTIONS = """\

## Completion Gate

This task is governed by the CES Completion Gate. Before exiting, you MUST
emit a `ces:completion` fenced block containing a JSON object that addresses
every acceptance criterion below. The verifier rejects the run if the block
is missing, malformed, or leaves any criterion without explicit evidence.

Schema (emit one such block, no markdown wrapping the JSON):

```ces:completion
{
  "task_id": "<this manifest's id>",
  "summary": "<one sentence: what you did>",
  "files_changed": ["<path>", ...],
  "exploration_evidence": [
    {"path": "<file/test/doc inspected>", "reason": "<why it mattered>", "observation": "<convention or behavior learned>"}
  ],
  "verification_commands": [
    {"command": "<command run>", "exit_code": 0, "summary": "<key result>", "artifact_path": "<optional artifact path>"}
  ],
  "criteria_satisfied": [
    {"criterion": "<exact text from acceptance_criteria>", "evidence": "<command output, file path, or other concrete proof>", "evidence_kind": "command_output | file_artifact | manual_inspection"}
  ],
  "dependency_changes": [
    {"file_path": "<dependency file>", "package": "<dependency/package name>", "rationale": "<why it is needed>", "existing_alternative_considered": "<stdlib or existing dependency considered>", "lockfile_evidence": "<lockfile/check evidence>", "audit_evidence": "<audit/check evidence>"}
  ],
  "complexity_notes": {
    "new_abstractions": ["<new layer/helper/class introduced, or empty if none>"],
    "new_dependencies": ["<new package/tool/service introduced, or empty if none>"],
    "simpler_alternative_considered": "<simplest viable alternative considered>",
    "why_not_simpler": "<why added complexity was necessary, or 'No extra complexity added.'>"
  },
  "open_questions": ["<anything you are unsure about>"],
  "scope_deviations": ["<anything you changed beyond the stated scope>"]
}
```

Rules:
- The `task_id` must equal the manifest id printed below.
- `files_changed` must list every file you edited; out-of-scope files fail the gate.
- `exploration_evidence` must list the repo files, tests, docs, or conventions you inspected before editing when the manifest requires it.
- `verification_commands` must list the concrete verification commands you ran when the manifest requires it.
- Every entry in this manifest's `acceptance_criteria` MUST appear once in `criteria_satisfied` with concrete evidence (a command you ran and its output, or a file artifact you produced).
- If you changed dependency files, include one `dependency_changes` entry per dependency file.
- Use `complexity_notes` to justify any new abstraction, dependency, service, or layer. If you did not add complexity, say so.
- Treat unnecessary complexity as a task failure: prefer direct edits in existing files over new architecture unless clearly required.
- Surface uncertainty in `open_questions` rather than hide it.
- Disclose scope deviations in `scope_deviations`.
"""


def completion_gate_enabled(manifest: object) -> bool:
    """Return True when a manifest opts into completion-gate verification."""

    sensors = getattr(manifest, "verification_sensors", ())
    return isinstance(sensors, tuple) and len(sensors) > 0


def build_completion_gate_prompt_fragment(manifest: object) -> str:
    """Render the shared completion-gate fragment for a manifest."""

    if not completion_gate_enabled(manifest):
        return ""
    return build_completion_gate_prompt_fragment_from_values(
        acceptance_criteria=getattr(manifest, "acceptance_criteria", ()),
        verification_sensors=getattr(manifest, "verification_sensors", ()),
    )


def build_completion_gate_prompt_fragment_from_values(
    *, acceptance_criteria: tuple[str, ...] | list[str], verification_sensors: tuple[str, ...] | list[str]
) -> str:
    """Render the shared completion-gate fragment from explicit values."""

    if not verification_sensors:
        return ""
    if acceptance_criteria:
        criteria_block = "\nAcceptance criteria you must address:\n" + "\n".join(
            f"- {criterion}" for criterion in acceptance_criteria
        )
    else:
        criteria_block = "\nAcceptance criteria: (none declared; emit an empty criteria_satisfied list)"

    sensor_block = "\nConfigured verification sensors (artifacts you must produce):\n" + "\n".join(
        f"- {sensor}" for sensor in verification_sensors
    )
    return criteria_block + sensor_block + SIMPLICITY_GUARD_INSTRUCTIONS + COMPLETION_CLAIM_INSTRUCTIONS


def build_manifest_execution_prompt(manifest: object) -> str:
    """Build the shared expert execution prompt pack for a task manifest."""

    description = getattr(manifest, "description", "")
    base = (
        "You are executing a governed CES task.\n"
        "Complete the requested work inside the current workspace.\n"
        "Keep changes scoped to the described task.\n\n"
        f"Task:\n{description}\n"
        f"Manifest ID:\n{getattr(manifest, 'manifest_id', 'unknown')}"
    )
    mcp_servers = getattr(manifest, "mcp_servers", ())
    if isinstance(mcp_servers, tuple) and mcp_servers:
        base += (
            "\nMCP grounding requested:\n"
            + "\n".join(f"- {server}" for server in mcp_servers)
            + "\nUse these servers only when the runtime exposes them; disclose unsupported grounding."
        )
    observability_template = build_observability_acceptance_template(
        list(getattr(manifest, "affected_files", ()) or ())
    )
    if observability_template:
        base += f"\n{observability_template}"
    return attach_engineering_charter(base + build_completion_gate_prompt_fragment(manifest))


def normalize_runtime_execution(result: Any) -> dict[str, Any]:
    """Normalize provider runtime results to the persisted execution dict shape."""

    if isinstance(result, dict):
        return result
    runtime_result = getattr(result, "runtime_result", None)
    if runtime_result is not None:
        if hasattr(runtime_result, "model_dump"):
            return runtime_result.model_dump(mode="json")
        return dict(runtime_result)
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
