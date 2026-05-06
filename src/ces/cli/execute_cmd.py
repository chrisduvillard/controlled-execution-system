"""Implementation of the ``ces execute`` command.

CES executes manifests locally through the configured runtime registry. The
published CLI no longer dispatches remote worker jobs or streams server-side
events.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import typer
from rich.panel import Panel
from rich.text import Text

import ces.cli._output as _output_mod
from ces.cli._async import run_async
from ces.cli._context import find_project_root, get_project_config
from ces.cli._errors import EXIT_SERVICE_ERROR, handle_error
from ces.cli._factory import get_services
from ces.cli._legacy_config import reject_server_mode
from ces.cli._output import console
from ces.cli.ownership import resolve_actor
from ces.control.services.workflow_engine import WorkflowEngine
from ces.execution.runtime_safety import runtime_side_effects_require_pre_execution_consent, safety_profile_for_runtime
from ces.harness.models.completion_claim import VerificationResult
from ces.harness.models.tool_call_signature import ToolCallSignature
from ces.harness.prompts.engineering_charter import attach_engineering_charter
from ces.harness.services.change_impact import build_observability_acceptance_template
from ces.shared.base import CESBaseModel
from ces.shared.enums import ActorType, WorkflowState

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
- Surface uncertainty in `open_questions` rather than hide it.
- Disclose scope deviations in `scope_deviations`.
"""


def _build_prompt_pack(manifest: object) -> str:
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

    sensors = getattr(manifest, "verification_sensors", ())
    gate_active = isinstance(sensors, tuple) and len(sensors) > 0
    if not gate_active:
        return attach_engineering_charter(base)

    criteria = getattr(manifest, "acceptance_criteria", ())
    if isinstance(criteria, tuple) and criteria:
        criteria_block = "\nAcceptance criteria you must address:\n" + "\n".join(f"- {c}" for c in criteria)
    else:
        criteria_block = "\nAcceptance criteria: (none declared; emit an empty criteria_satisfied list)"

    sensor_block = "\nConfigured verification sensors (artifacts you must produce):\n" + "\n".join(
        f"- {s}" for s in sensors
    )

    return attach_engineering_charter(base + criteria_block + sensor_block + COMPLETION_CLAIM_INSTRUCTIONS)


def _normalize_runtime_execution(result: Any) -> dict[str, Any]:
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


def _coerce_workflow_state_value(value: Any) -> str:
    candidate = getattr(value, "value", value)
    if isinstance(candidate, str) and candidate in {state.value for state in WorkflowState}:
        return candidate
    return WorkflowState.QUEUED.value


def _with_workflow_state(manifest: object, state: WorkflowState) -> object:
    if isinstance(manifest, CESBaseModel) and callable(getattr(manifest, "model_copy", None)):
        return manifest.model_copy(update={"workflow_state": state})
    setattr(manifest, "workflow_state", state)
    return manifest


async def _mark_execution_failed(
    *,
    manager: Any,
    engine: WorkflowEngine,
    manifest: object,
    actor: str,
) -> object:
    failed_state = await engine.fail(actor=actor, actor_type=ActorType.HUMAN)
    manifest = _with_workflow_state(manifest, failed_state)
    await manager.save_manifest(manifest)
    return manifest


def _completion_gate_enabled(manifest: object) -> bool:
    """A manifest opts into the gate by listing real sensor IDs in a tuple.

    The isinstance(tuple) check protects against MagicMock-based tests where
    attribute access yields a truthy MagicMock object.
    """
    sensors = getattr(manifest, "verification_sensors", ())
    return isinstance(sensors, tuple) and len(sensors) > 0


def _render_findings(result: VerificationResult) -> str:
    """One-line-per-finding text for human display + non-JSON output."""
    if result.passed:
        return "Verification passed"
    parts = ["Verification failed:"]
    for f in result.findings:
        prefix = f"[{f.severity}] {f.kind.value}"
        parts.append(f"  - {prefix}: {f.message}")
        parts.append(f"      hint: {f.hint}")
    return "\n".join(parts)


@run_async
async def execute_task(
    manifest_id: str = typer.Argument(
        ...,
        help="Manifest ID to execute",
    ),
    runtime: str = typer.Option(
        "auto",
        "--runtime",
        help="Runtime for local mode: auto, codex, or claude",
    ),
    accept_runtime_side_effects: bool = typer.Option(
        False,
        "--accept-runtime-side-effects",
        help=(
            "Explicitly consent before launching a runtime that cannot enforce manifest tool allowlists "
            "or workspace scoping. Required for Codex full-access execution."
        ),
    ),
    auto_repair: int = typer.Option(
        0,
        "--auto-repair",
        help=(
            "Maximum number of automatic repair retries when the Completion "
            "Gate fails. 0 disables auto-repair (single shot)."
        ),
        min=0,
    ),
) -> None:
    """Execute an agent task locally through the configured runtime."""
    try:
        project_root = find_project_root()
        project_config = get_project_config()

        reject_server_mode(project_config)

        async with get_services() as services:
            actor = resolve_actor()
            settings = services["settings"]
            manager = services["manifest_manager"]
            manifest = await manager.get_manifest(manifest_id)
            if manifest is None:
                raise ValueError(f"Manifest not found: {manifest_id}")

            initial_state = _coerce_workflow_state_value(
                getattr(manifest, "workflow_state", WorkflowState.QUEUED.value)
            )
            if initial_state not in {WorkflowState.QUEUED.value, WorkflowState.IN_FLIGHT.value}:
                raise ValueError(
                    f"Manifest must be queued or in_flight before local execution can start; got {initial_state}"
                )

            preferred_runtime = project_config.get("preferred_runtime") or getattr(settings, "default_runtime", "codex")
            runtime_adapter = services["runtime_registry"].resolve_runtime(
                runtime_name=runtime,
                preferred_runtime=preferred_runtime,
            )
            runtime_name = getattr(runtime_adapter, "runtime_name", runtime)
            pre_execution_safety = safety_profile_for_runtime(runtime_name)
            if runtime_side_effects_require_pre_execution_consent(
                pre_execution_safety,
                accepted=accept_runtime_side_effects,
            ):
                console.print(
                    Panel(
                        f"Runtime `{pre_execution_safety.runtime_name}` requires explicit runtime side-effect consent before "
                        "CES can launch it. "
                        f"{pre_execution_safety.notes} Re-run with `--accept-runtime-side-effects` only if you accept "
                        "this runtime boundary.",
                        title="[yellow]Runtime Side-Effect Consent Required[/yellow]",
                        border_style="yellow",
                    )
                )
                raise typer.Exit(code=1)

            audit_ledger = services.get("audit_ledger")
            engine = WorkflowEngine(
                manifest_id=manifest_id,
                audit_ledger=audit_ledger,
                initial_state=initial_state,
            )
            if initial_state == WorkflowState.QUEUED.value:
                await engine.start(actor=actor, actor_type=ActorType.HUMAN)
                manifest = _with_workflow_state(manifest, WorkflowState.IN_FLIGHT)
                await manager.save_manifest(manifest)
            # Completion Gate loop (P-CLI + Gap #2). Runs the agent, verifies,
            # and on failure either marks the manifest failed (auto_repair=0) or
            # rebuilds the prompt with the findings and retries within budget.
            verification: VerificationResult | None = None
            execution: dict[str, Any] = {}
            run_result: Any = None
            attempt = 0
            repair_context: str | None = None
            claim_signatures: list[ToolCallSignature] = []
            no_progress_detected = False
            while True:
                try:
                    run_result = await services["agent_runner"].execute_runtime(
                        manifest=manifest,
                        runtime=runtime_adapter,
                        prompt_pack=_build_prompt_pack(manifest),
                        working_dir=project_root,
                        repair_context=repair_context,
                    )
                except Exception:
                    await _mark_execution_failed(
                        manager=manager,
                        engine=engine,
                        manifest=manifest,
                        actor=actor,
                    )
                    raise
                execution = _normalize_runtime_execution(run_result)
                services["local_store"].save_runtime_execution(manifest_id, execution)

                if execution["exit_code"] != 0 or not _completion_gate_enabled(manifest):
                    break

                verifier = services.get("completion_verifier")
                if verifier is None:
                    break

                runtime_obj = getattr(run_result, "runtime_result", None)
                claim = getattr(runtime_obj, "completion_claim", None)
                if claim is None:
                    await _mark_execution_failed(
                        manager=manager,
                        engine=engine,
                        manifest=manifest,
                        actor=actor,
                    )
                    if _output_mod._json_mode:
                        typer.echo(
                            json.dumps(
                                {
                                    **execution,
                                    "verification": {
                                        "passed": False,
                                        "reason": "agent did not emit a ces:completion block",
                                    },
                                },
                                indent=2,
                            )
                        )
                        sys.exit(EXIT_SERVICE_ERROR)
                    console.print(
                        Panel(
                            "Agent did not emit a `ces:completion` block. "
                            "Verification gate cannot proceed; marking failed.",
                            title="[red]Completion Gate[/red]",
                            border_style="red",
                        )
                    )
                    sys.exit(EXIT_SERVICE_ERROR)

                # No-progress loop detection (N4). Each attempt's claim is
                # hashed; if the same (summary, files_changed) signature
                # repeats > 3 times, the agent is spinning — break out.
                claim_signatures.append(
                    ToolCallSignature.from_call(
                        "completion_claim",
                        {"summary": claim.summary, "files_changed": list(claim.files_changed)},
                    )
                )
                correction_for_progress = services.get("self_correction_manager")
                if correction_for_progress is not None and correction_for_progress.detect_no_progress(
                    tuple(claim_signatures)
                ):
                    no_progress_detected = True
                    await _mark_execution_failed(
                        manager=manager,
                        engine=engine,
                        manifest=manifest,
                        actor=actor,
                    )
                    break

                await engine.submit_for_verification(actor=actor, actor_type=ActorType.HUMAN)
                manifest = _with_workflow_state(manifest, WorkflowState.VERIFYING)
                verification = await verifier.verify(manifest, claim, project_root)

                if verification.passed:
                    await engine.verification_passed(actor=actor, actor_type=ActorType.CONTROL_PLANE)
                    manifest = _with_workflow_state(manifest, WorkflowState.UNDER_REVIEW)
                    await manager.save_manifest(manifest)
                    break

                rationale = f"{len(verification.findings)} verification finding(s); see ces audit ledger"
                await engine.verification_failed(
                    actor=actor,
                    actor_type=ActorType.CONTROL_PLANE,
                    rationale=rationale,
                )
                manifest = _with_workflow_state(manifest, WorkflowState.FAILED)
                await manager.save_manifest(manifest)

                if attempt >= auto_repair:
                    break  # gate failed terminally

                # Auto-repair: feed findings back to the agent and retry.
                correction = services.get("self_correction_manager")
                if correction is None:
                    break
                repair_context = correction.build_repair_prompt(verification.findings)
                try:
                    await engine.retry(actor=actor, actor_type=ActorType.CONTROL_PLANE)
                except Exception:
                    # Workflow refused (max_retries reached); honor it as terminal.
                    break
                manifest = _with_workflow_state(manifest, WorkflowState.IN_FLIGHT)
                await manager.save_manifest(manifest)
                attempt += 1
                console.print(
                    f"[yellow]Completion Gate: attempt {attempt} failed; retrying with repair prompt[/yellow]"
                )

            if _output_mod._json_mode:
                if execution["exit_code"] != 0:
                    await _mark_execution_failed(
                        manager=manager,
                        engine=engine,
                        manifest=manifest,
                        actor=actor,
                    )
                payload: dict[str, Any] = dict(execution)
                if verification is not None:
                    payload["verification"] = {
                        "passed": verification.passed,
                        "findings": [
                            {
                                "kind": f.kind.value,
                                "severity": f.severity,
                                "message": f.message,
                                "hint": f.hint,
                                "related_sensor": f.related_sensor,
                                "related_criterion": f.related_criterion,
                            }
                            for f in verification.findings
                        ],
                    }
                if no_progress_detected:
                    payload["no_progress_detected"] = True
                typer.echo(json.dumps(payload, indent=2))
                if (
                    execution["exit_code"] != 0
                    or no_progress_detected
                    or (verification is not None and not verification.passed)
                ):
                    sys.exit(EXIT_SERVICE_ERROR)
                return

            console.print(f"[bold]Runtime:[/bold] {execution['runtime_name']}")
            if execution.get("stdout"):
                console.print(Text(execution["stdout"]))
            if execution.get("stderr"):
                console.print(
                    Panel(
                        execution["stderr"],
                        title="[yellow]Runtime stderr[/yellow]",
                        border_style="yellow",
                    )
                )
            if execution["exit_code"] != 0:
                await _mark_execution_failed(
                    manager=manager,
                    engine=engine,
                    manifest=manifest,
                    actor=actor,
                )
                console.print(
                    Panel(
                        f"Runtime exited with code {execution['exit_code']}",
                        title="[red]Execution Error[/red]",
                        border_style="red",
                    )
                )
                sys.exit(EXIT_SERVICE_ERROR)
            if no_progress_detected:
                console.print(
                    Panel(
                        "Agent emitted the same completion claim more than 3 times "
                        "without progress. Aborting auto-repair to prevent runaway "
                        "cost. Inspect the agent's output and refine the manifest.",
                        title="[red]No Progress Detected[/red]",
                        border_style="red",
                    )
                )
                sys.exit(EXIT_SERVICE_ERROR)
            if verification is not None and not verification.passed:
                console.print(
                    Panel(
                        _render_findings(verification),
                        title="[red]Completion Gate Failed[/red]",
                        border_style="red",
                    )
                )
                sys.exit(EXIT_SERVICE_ERROR)
            success_msg = f"Task {manifest_id} completed via {execution['runtime_name']}."
            if verification is not None:
                success_msg += " Completion gate passed; manifest advanced to under_review."
            console.print(
                Panel(
                    success_msg,
                    title="[green]Execution Complete[/green]",
                    border_style="green",
                )
            )

    except SystemExit:
        raise
    except (typer.BadParameter, ValueError) as exc:
        handle_error(exc)
    except (RuntimeError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)
