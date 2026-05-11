"""Implementation of the ``ces dogfood`` command.

Automates the self-hosting protocol: uses CES-stable (the currently
installed version) to govern changes on the current branch.

The workflow:
1. Extract git diff for the current branch vs base
2. Classify the change using the classification oracle
3. Run the review pipeline (with LLM reviewers if available)
4. Display findings and decision views
5. Optionally approve and record in the audit ledger

This is the canonical "eating your own dogfood" entry point.

Exports:
    dogfood: Typer command function for ``ces dogfood``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.panel import Panel
from rich.table import Table

from ces.cli import _output as _output_mod
from ces.cli._async import run_async
from ces.cli._context import find_project_root, get_project_id
from ces.cli._errors import handle_error
from ces.cli._factory import get_services
from ces.cli._output import console
from ces.control.services.approval_pipeline import required_gate_type_for_risk

# Map filename keywords to governance component descriptions. The classification
# oracle scores incoming descriptions against its rule table; descriptions that
# name a known component match much more confidently than a generic "refactor".
_COMPONENT_KEYWORDS = {
    "classification": "classification engine",
    "audit_ledger": "audit ledger",
    "kill_switch": "kill switch",
    "review_executor": "review executor",
    "review_router": "review pipeline",
    "gate_evaluator": "gate evaluator",
    "merge_controller": "merge controller",
    "evidence_synthesizer": "evidence synthesizer",
    "sensor": "sensor framework",
    "manifest": "manifest",
    "workflow": "workflow engine",
    "api": "API endpoint",
    "test": "test",
}


def _describe_diff_for_classification(files_changed: tuple[str, ...]) -> str:
    """Build an oracle-friendly description from the list of changed files.

    Detects governance components by keyword in the file paths and names them
    in the description. Falls back to a generic refactor description when no
    component matches, so the oracle still has a known table entry to score.
    """
    detected: list[str] = []
    for file_path in files_changed:
        path_lower = file_path.lower()
        for keyword, component in _COMPONENT_KEYWORDS.items():
            if keyword in path_lower:
                detected.append(component)
                break

    if not detected:
        return "Refactor internal module boundaries"

    unique = list(dict.fromkeys(detected))  # preserve order, dedupe
    if len(unique) == 1:
        return f"Change to {unique[0]}"
    return f"Change to {', '.join(unique[:3])}"


def _classify_to_payload(classification: Any, description: str) -> dict[str, Any]:
    """Build the result['classification'] dict from an oracle result.

    Falls back to Tier A / BC3 / CLASS_4 when the oracle did not match a rule
    confidently enough — this is the safe default for a self-review pipeline.
    """
    matched = classification.matched_rule
    if matched is not None:
        risk_tier = matched.risk_tier.value
        bc = matched.behavior_confidence.value
        change_class = matched.change_class.value
        matched_desc = matched.description
    else:
        risk_tier = "A"
        bc = "BC3"
        change_class = "CLASS_4"
        matched_desc = "(no confident match — defaulting to Tier A)"

    return {
        "description": description,
        "risk_tier": risk_tier,
        "behavior_confidence": bc,
        "change_class": change_class,
        "oracle_confidence": round(classification.confidence, 4),
        "matched_rule": matched_desc,
    }


def _findings_to_payload(findings: tuple[Any, ...]) -> list[dict[str, Any]]:
    """Serialize ReviewFinding tuple to JSON-safe dicts (CLI output schema)."""
    return [
        {
            "severity": f.severity.value,
            "file_path": f.file_path,
            "line_number": f.line_number,
            "title": f.title,
            "reviewer_role": f.reviewer_role.value,
        }
        for f in findings
    ]


def _aggregated_to_payload(aggregated_review: Any) -> dict[str, Any]:
    """Serialize AggregatedReview to the result['aggregated_review'] shape."""
    return {
        "total_findings": len(aggregated_review.all_findings),
        "critical_count": aggregated_review.critical_count,
        "high_count": aggregated_review.high_count,
        "unanimous_zero_findings": aggregated_review.unanimous_zero_findings,
        "disagreements": list(aggregated_review.disagreements),
        "findings": _findings_to_payload(aggregated_review.all_findings),
    }


def _render_classification_panel(classification: dict[str, Any]) -> None:
    """Display classification as a Rich Panel. Caller must gate on json_mode."""
    console.print(
        Panel(
            f"Risk Tier: [bold]{classification['risk_tier']}[/bold]\n"
            f"Behavior Confidence: {classification['behavior_confidence']}\n"
            f"Change Class: {classification['change_class']}\n"
            f"Oracle Confidence: {classification['oracle_confidence']:.2f}\n"
            f"Matched Rule: {classification['matched_rule']}",
            title="Classification",
            border_style="blue",
        )
    )


_SEVERITY_STYLES = {
    "critical": "bold red",
    "high": "red",
    "medium": "yellow",
    "low": "cyan",
    "info": "dim",
}


def _render_findings_table(findings: tuple[Any, ...]) -> None:
    """Display findings as a Rich Table. Caller must gate on json_mode."""
    table = Table(title=f"Review Findings ({len(findings)})")
    table.add_column("Sev", width=8)
    table.add_column("File", width=30)
    table.add_column("Title", width=40)
    table.add_column("Role", width=12)
    for f in findings:
        location = f.file_path or ""
        if f.line_number is not None:
            location += f":{f.line_number}"
        table.add_row(
            f.severity.value.upper(),
            location,
            f.title,
            f.reviewer_role.value,
            style=_SEVERITY_STYLES.get(f.severity.value, ""),
        )
    console.print(table)


def _render_decision_views(views: list[Any]) -> None:
    """Display decision views as Rich Panels. Caller must gate on json_mode."""
    border_style_for = {"for": "green", "against": "red", "neutral": "blue"}
    for view in views:
        if view.content:
            console.print(
                Panel(
                    view.content,
                    title=f"Decision: {view.position.upper()}",
                    border_style=border_style_for.get(view.position, "white"),
                )
            )


_PREFLIGHT_SENSORS = ("test_pass", "lint", "typecheck", "coverage")


async def _run_completion_gate_preflight(
    *,
    services: dict[str, Any],
    files_changed: tuple[str, ...],
    project_root: Path,
    rich: Any,
    json_mode: bool,
) -> dict[str, Any] | None:
    """Run the Completion Gate's deterministic sensors against the current repo.

    Non-blocking: surfaces failures as a warning so dogfood still proceeds to
    the LLM review pipeline. Returns a serialisable payload for the JSON
    output schema, or ``None`` when the verifier service is not configured.

    The synthetic manifest scopes ``affected_files`` to the diff so the
    verifier's scope check accepts the synthetic claim. ``acceptance_criteria``
    is left empty — dogfood is preflighting deterministic checks, not
    semantic ones.
    """
    from datetime import datetime, timedelta, timezone

    from ces.control.models.manifest import TaskManifest
    from ces.harness.models.completion_claim import CompletionClaim
    from ces.shared.enums import (
        ArtifactStatus,
        BehaviorConfidence,
        ChangeClass,
        RiskTier,
    )

    verifier = services.get("completion_verifier")
    if verifier is None:
        return None

    now = datetime.now(timezone.utc)
    affected = tuple(files_changed) or ("**/*",)
    synthetic_manifest = TaskManifest(
        manifest_id="DOGFOOD-PREFLIGHT",
        description="Dogfood Completion Gate preflight",
        risk_tier=RiskTier.C,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_1,
        affected_files=affected,
        token_budget=1,
        expires_at=now + timedelta(hours=1),
        verification_sensors=_PREFLIGHT_SENSORS,
        version=1,
        status=ArtifactStatus.DRAFT,
        owner="ces-dogfood",
        created_at=now,
        last_confirmed=now,
    )
    synthetic_claim = CompletionClaim(
        task_id="DOGFOOD-PREFLIGHT",
        summary="Dogfood preflight against current repo state",
        files_changed=affected,
    )

    try:
        result = await verifier.verify(synthetic_manifest, synthetic_claim, project_root)
    except Exception as exc:
        if not json_mode:
            rich(f"[yellow]Completion Gate preflight error: {exc}[/yellow]")
        return {"passed": None, "error": str(exc)}

    payload = {
        "passed": result.passed,
        "sensors_run": [r.sensor_id for r in result.sensor_results],
        "findings": [
            {
                "kind": f.kind.value,
                "severity": f.severity,
                "message": f.message,
                "related_sensor": f.related_sensor,
            }
            for f in result.findings
        ],
    }

    if not json_mode:
        if result.passed:
            rich("[green]Completion Gate preflight: ✓ all configured sensors passed[/green]")
        else:
            rich(f"[yellow]Completion Gate preflight: {len(result.findings)} finding(s) (non-blocking)[/yellow]")

    return payload


@run_async
async def dogfood(
    base_ref: str = typer.Option(
        "HEAD~1",
        "--base",
        "-b",
        help="Git ref to diff against (e.g. main, HEAD~3, abc1234).",
    ),
    approve: bool = typer.Option(
        False,
        "--approve",
        "-y",
        help="Auto-approve after review (skip interactive prompt).",
    ),
    max_diff_chars: int = typer.Option(
        40_000,
        "--max-diff",
        help="Maximum diff size in chars before truncation.",
    ),
) -> None:
    """Use CES to review its own changes.

    Extracts the git diff, classifies the change, runs the review
    pipeline, and displays structured findings. The self-hosting
    bootstrap: CES-stable governs CES-dev.
    """
    json_mode = _output_mod.is_json_mode()
    # Stable top-level schema: every key is always present so JSON consumers
    # can assume a fixed shape regardless of which branch the command exits on.
    result: dict[str, Any] = {
        "base_ref": base_ref,
        "status": "ok",
        "diff": None,
        "completion_gate_preflight": None,
        "classification": None,
        "reviewers": None,
        "aggregated_review": None,
        "decision_views": [],
        "approval": None,
        "error": None,
    }

    def _rich(msg: Any) -> None:
        """Emit a Rich-formatted message only in non-JSON mode."""
        if not json_mode:
            console.print(msg)

    def _emit_json_and_exit(exc: Exception) -> None:
        """In JSON mode, emit a terminal error payload with the shape already built."""
        result["status"] = "error"
        result["error"] = {"type": exc.__class__.__name__, "message": str(exc)}
        typer.echo(json.dumps(result, indent=2, default=str))
        raise typer.Exit(1) from exc

    try:
        project_root = find_project_root()
        project_id = get_project_id()

        async with get_services() as services:
            classification_oracle = services.get("classification_oracle")
            review_router = services["review_router"]
            evidence_synthesizer = services["evidence_synthesizer"]
            audit_ledger = services.get("audit_ledger")
            local_store = services.get("local_store")

            # Step 1: Extract diff
            from ces.harness.services.diff_extractor import DiffExtractor

            _rich("[dim]Extracting diff...[/dim]")
            diff_context = await DiffExtractor.extract_diff(
                base_ref=base_ref,
                working_dir=project_root,
            )
            if not diff_context.files_changed:
                result["diff"] = {
                    "files_changed_count": 0,
                    "insertions": 0,
                    "deletions": 0,
                    "truncated": False,
                    "files_changed": [],
                }
                result["status"] = "no_changes"
                if json_mode:
                    typer.echo(json.dumps(result, indent=2, default=str))
                else:
                    console.print("[yellow]No changes found.[/yellow]")
                return

            diff_context = DiffExtractor.truncate_diff(diff_context, max_chars=max_diff_chars)

            result["diff"] = {
                "files_changed_count": len(diff_context.files_changed),
                "insertions": diff_context.stats.insertions,
                "deletions": diff_context.stats.deletions,
                "truncated": diff_context.truncated,
                "files_changed": list(diff_context.files_changed),
            }

            _rich(
                f"[dim]Diff: {len(diff_context.files_changed)} files, "
                f"+{diff_context.stats.insertions} -{diff_context.stats.deletions}"
                f"{' (truncated)' if diff_context.truncated else ''}[/dim]"
            )

            # Step 1.5: Completion Gate preflight (N3).
            # Runs the gate's deterministic sensors against the current repo
            # state before the expensive LLM review pipeline. Non-blocking:
            # surfaces failures as a warning so the operator can fix them
            # before merging, but doesn't short-circuit the review.
            preflight_payload = await _run_completion_gate_preflight(
                services=services,
                files_changed=diff_context.files_changed,
                project_root=project_root,
                rich=_rich,
                json_mode=json_mode,
            )
            result["completion_gate_preflight"] = preflight_payload

            # Step 2: Classify the change.
            description = _describe_diff_for_classification(diff_context.files_changed)
            classification = classification_oracle.classify(description)
            classification_payload = _classify_to_payload(classification, description)
            result["classification"] = classification_payload
            risk_tier = classification_payload["risk_tier"]
            bc = classification_payload["behavior_confidence"]

            if not json_mode:
                _render_classification_panel(classification_payload)

            # Step 3: Assign reviewers
            builder_agent_id = "dogfood-builder"
            builder_model_id = "ces-dogfood"

            if risk_tier == "A":
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

            # Step 4: Dispatch reviews
            manifest_context = {
                "description": description,
                "risk_tier": risk_tier,
                "behavior_confidence": bc,
            }

            aggregated_review = None
            dispatch_error: str | None = None
            try:
                _rich(f"[dim]Dispatching {len(assignments)} reviewer(s)...[/dim]")
                aggregated_review = await review_router.dispatch_review(
                    assignments=assignments,
                    diff_context=diff_context,
                    manifest_context=manifest_context,
                    current_gate_type=required_gate_type_for_risk(risk_tier),
                )
            except (RuntimeError, KeyError) as exc:
                dispatch_error = str(exc)
                _rich(f"[yellow]Review dispatch unavailable: {exc}[/yellow]")
                _rich("[dim]Hint: install/authenticate `claude` or `codex`, or use CES_DEMO_MODE=1[/dim]")

            result["reviewers"] = {
                "dispatched": len(assignments),
                "dispatch_error": dispatch_error,
            }

            # Persist findings so every dogfood run leaves an audit trail,
            # not just those terminated by --approve. Mirrors `ces review`,
            # which also calls save_review_findings before approval is decided.
            persisted_manifest_id = f"dogfood-{base_ref}"
            if aggregated_review is not None and local_store is not None:
                local_store.save_review_findings(persisted_manifest_id, aggregated_review)

            # Step 5: Display results.
            if aggregated_review is not None:
                result["aggregated_review"] = _aggregated_to_payload(aggregated_review)

            if aggregated_review is not None and aggregated_review.all_findings:
                # Decision views are computed in both modes (used in JSON output);
                # rendering is gated by json_mode below.
                review_data = {
                    "findings": [
                        {
                            "severity": f.severity.value,
                            "title": f.title,
                            "file_path": f.file_path,
                            "line_number": f.line_number,
                        }
                        for f in aggregated_review.all_findings
                    ],
                    "critical_count": aggregated_review.critical_count,
                    "high_count": aggregated_review.high_count,
                    "disagreements": list(aggregated_review.disagreements),
                }
                views = evidence_synthesizer.assemble_decision_views_from_review(review_data)
                result["decision_views"] = [
                    {"position": view.position, "content": view.content} for view in views if view.content
                ]

                if not json_mode:
                    _render_findings_table(aggregated_review.all_findings)
                    _render_decision_views(views)
                    console.print(
                        f"\n[bold]Summary:[/bold] {aggregated_review.critical_count} critical, "
                        f"{aggregated_review.high_count} high, "
                        f"{len(aggregated_review.all_findings)} total findings"
                    )
                    # `unanimous_zero_findings` is only true when *all* reviewers returned 0
                    # findings, which is logically incompatible with being inside the truthy-
                    # findings branch; the corresponding warning lives in the elif below.
            elif aggregated_review is not None:
                # Zero findings path: surface the auto-escalation warning here so it actually fires
                # when unanimous_zero_findings is True (previously trapped inside the truthy-findings branch).
                if not json_mode:
                    console.print("[green]No review findings — all clear.[/green]")
                    if aggregated_review.unanimous_zero_findings:
                        console.print(
                            "[yellow]Warning: unanimous zero findings — auto-escalated to HYBRID gate[/yellow]"
                        )

            # Step 6: Approval
            approval_payload: dict[str, Any] | None = None
            if approve and aggregated_review is not None:
                decision = "approved"
                rationale = f"Dogfood review of {len(diff_context.files_changed)} files vs {base_ref}"
                if aggregated_review.unanimous_zero_findings:
                    decision = "rejected"
                    rationale = (
                        f"{rationale}. Auto-approval blocked because unanimous zero findings "
                        "require stricter human review."
                    )
                    _rich("[yellow]Auto-approval blocked: unanimous zero findings require manual review.[/yellow]")
                elif aggregated_review.critical_count > 0:
                    decision = "rejected"
                    rationale = f"{rationale}. Critical findings present."
                    _rich("[red]Auto-rejected: critical findings present.[/red]")
                else:
                    _rich("[green]Auto-approved: no critical findings.[/green]")

                await audit_ledger.record_approval(
                    manifest_id=persisted_manifest_id,
                    actor="ces-dogfood",
                    decision=decision,
                    rationale=rationale,
                    project_id=project_id,
                )
                approval_payload = {
                    "decision": decision,
                    "rationale": rationale,
                    "manifest_id": persisted_manifest_id,
                }
            result["approval"] = approval_payload

            if json_mode:
                typer.echo(json.dumps(result, indent=2, default=str))

    except Exception as exc:
        # handle_error() classifies the exception internally and chooses the
        # right exit code; no need to split by type here. In JSON mode we
        # surface a terminal JSON payload instead of a Rich Panel.
        if json_mode:
            _emit_json_and_exit(exc)
        handle_error(exc)
