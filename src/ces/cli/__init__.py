"""CES CLI entry point using Typer for the local builder-first workflow."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from typing import Any

import click
import typer

from ces import __version__
from ces.cli import (
    approve_cmd,
    audit_cmd,
    autopilot_cmd,
    baseline_cmd,
    benchmark_cmd,
    brownfield_cmd,
    classify_cmd,
    complete_cmd,
    diff_cmd,
    doctor_cmd,
    dogfood_cmd,
    emergency_cmd,
    evidence_cmd,
    execute_cmd,
    gate_cmd,
    harness_cmd,
    init_cmd,
    intake_cmd,
    manifest_cmd,
    mri_cmd,
    profile_cmd,
    recover_cmd,
    report_cmd,
    review_cmd,
    run_cmd,
    scan_cmd,
    setup_ci_cmd,
    spec_cmd,
    status_cmd,
    triage_cmd,
    vault_cmd,
    verify_cmd,
    why_cmd,
)
from ces.cli._output import set_json_mode


def _root_json_requested(argv: Sequence[str]) -> bool:
    """Return True when the root --json flag appears before the command token."""
    for arg in argv:
        if arg == "--json":
            return True
        if arg == "--":
            return False
        if not arg.startswith("-"):
            return False
    return False


class JsonAwareTyperGroup(typer.core.TyperGroup):
    """Typer group that preserves machine-readable usage errors under root --json."""

    def main(  # type: ignore[override]
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        windows_expand_args: bool = True,
        **extra: Any,
    ) -> Any:
        argv = list(sys.argv[1:] if args is None else args)
        json_requested = _root_json_requested(argv)
        try:
            result = super().main(
                args=argv,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=False,
                windows_expand_args=windows_expand_args,
                **extra,
            )
        except click.ClickException as exc:
            if not standalone_mode:
                raise
            if json_requested:
                set_json_mode(True)
                payload = {
                    "error": {
                        "type": "usage_error",
                        "title": "Usage Error",
                        "message": exc.format_message(),
                        "exit_code": exc.exit_code,
                    }
                }
                click.echo(json.dumps(payload), err=True)
            else:
                exc.show()
            if standalone_mode:
                sys.exit(exc.exit_code)
            raise click.exceptions.Exit(exc.exit_code) from exc
        except click.exceptions.Exit:
            raise
        if standalone_mode and isinstance(result, int):
            sys.exit(result)
        if standalone_mode:
            sys.exit(0)
        return result


_ROOT_HELP = """Production Autopilot for local AI-built projects.

Start Here:
  `ces create`    Interactive project creation wizard for new apps
  `ces start`     Guided read-only path: plan → build → verify → prove
  `ces ship`      Read-only plan from idea/current repo to proof-backed delivery
  `ces build --from-scratch "Create a task tracker app"`
                  Create a new project from an empty folder
  `ces build`     Change an existing local project with governed runtime execution
  `ces mri`       Read-only diagnosis of readiness gaps and risks
  `ces proof`     Compact shareable proof card: evidence, gaps, ship/no-ship
  `ces next`      Show the next safest readiness step
  `ces status`    Show builder-first status; add `--expert` for the full expert view

Advanced Governance:
  `ces manifest`, `classify`, `review`, `triage`, `approve`, `audit`, `gate`
"""

app = typer.Typer(
    name="ces",
    cls=JsonAwareTyperGroup,
    help=_ROOT_HELP,
    rich_markup_mode="rich",
)


def _version_callback(show_version: bool) -> None:
    if show_version:
        typer.echo(f"controlled-execution-system {__version__}")
        raise typer.Exit


@app.callback()
def main(
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output results as JSON instead of Rich tables.",
    ),
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed CES version and exit.",
    ),
) -> None:
    """Controlled Execution System - Deterministic governance for AI agents."""
    _ = version
    set_json_mode(json_output)


# ---------------------------------------------------------------------------
# Core commands -- always available (no optional deps)
# ---------------------------------------------------------------------------

app.command(name="init", help="Optional manual setup before your first builder-first run.")(init_cmd.init_project)
app.command(name="manifest", help="Advanced governance: generate a task manifest from natural language.")(
    manifest_cmd.create_manifest
)
app.command(
    name="build",
    help=(
        "Describe what you want to build and let CES run the local workflow. "
        "Tip: CES_DEMO_MODE=1 only affects optional LLM-backed steps; "
        "`ces build` still needs Codex CLI or Claude Code."
    ),
)(run_cmd.run_task)
app.command(name="continue", help="Resume the latest saved builder brief without re-entering context.")(
    run_cmd.continue_task
)
app.command(name="complete", help="Reconcile externally completed builder work with the CES audit trail.")(
    complete_cmd.complete_builder_session
)
app.command(name="explain", help="Explain the latest builder brief and current CES state in plain language.")(
    run_cmd.explain_task
)
app.command(name="why", help="Explain why the latest builder run is blocked and show the next command.")(
    why_cmd.explain_blocker
)
app.command(name="recover", help="Recover from a blocked builder run with rerunnable verification evidence.")(
    recover_cmd.recover_builder_session
)
app.command(name="run", help="Legacy alias for the guided local-first build flow.")(run_cmd.run_task)

app.command(name="classify", help="Classify a task manifest.")(classify_cmd.classify_task)
app.command(name="execute", help="Execute an agent task locally with manifest evidence and delta checks.")(
    execute_cmd.execute_task
)
app.command(name="review", help="Run review pipeline and display evidence summary.")(review_cmd.review_task)
app.command(name="verify", help="Run independent local verification for the current project.")(
    verify_cmd.verify_project
)
app.command(name="triage", help="Pre-screen evidence with triage color.")(triage_cmd.triage_evidence)
app.command(name="approve", help="Approve or reject evidence.")(approve_cmd.approve_evidence)
app.command(name="gate", help="Evaluate a phase gate.")(gate_cmd.evaluate_gate)
app.command(name="intake", help="Run intake interview for a phase.")(intake_cmd.run_intake)
app.add_typer(vault_cmd.vault_app, name="vault")
app.add_typer(spec_cmd.spec_app, name="spec")
app.command(name="status", help="Show builder-first project status. Use --expert for the full expert view.")(
    status_cmd.show_status
)
app.command(name="dogfood", help="Use CES to review its own changes.")(dogfood_cmd.dogfood)
app.command(name="doctor", help="Run pre-flight checks (Python, providers, extras, project dir).")(
    doctor_cmd.run_doctor
)
app.command(name="setup-ci", help="Generate a CI gating workflow for the chosen provider (github|gitlab).")(
    setup_ci_cmd.setup_ci
)
app.command(name="scan", help="Inventory the repository: modules, generated code, CODEOWNERS.")(scan_cmd.scan)
app.command(name="mri", help="Read-only repository diagnostic with project-health risks and next CES actions.")(
    mri_cmd.mri
)
app.command(name="ship", help="Read-only plan from idea/current repo to proof-backed delivery.")(autopilot_cmd.ship)
app.command(name="create", help="Interactive project creation wizard for new apps.")(autopilot_cmd.create)
app.command(name="start", help="Interactive read-only guide from idea to proof-backed delivery.")(autopilot_cmd.start)
app.command(name="next", help="Show the next safest production-readiness action.")(autopilot_cmd.next_action)
app.command(name="next-prompt", help="Generate a guardrailed prompt for the next readiness step.")(
    autopilot_cmd.next_prompt
)
app.command(name="passport", help="Produce a local Production Passport report.")(autopilot_cmd.passport)
app.command(name="proof", help="Produce a compact proof card with ship/no-ship recommendation.")(autopilot_cmd.proof)
app.command(name="promote", help="Plan a safe maturity promotion, one checkpoint at a time.")(autopilot_cmd.promote)
app.command(name="invariants", help="Mine conservative evidence-backed project invariants.")(autopilot_cmd.invariants)
app.command(name="slop-scan", help="Report deterministic AI-native slop/failure findings.")(autopilot_cmd.slop_scan)
app.add_typer(autopilot_cmd.launch_app, name="launch")
app.command(name="baseline", help="Capture a day-0 sensor snapshot under .ces/baseline/.")(baseline_cmd.baseline)
app.add_typer(profile_cmd.profile_app, name="profile")
app.add_typer(harness_cmd.harness_app, name="harness")
app.add_typer(benchmark_cmd.benchmark_app, name="benchmark")
app.command(name="audit", help="Inspect the local audit ledger.")(audit_cmd.query_audit)
app.command(name="diff", help="Show changed files, optionally since the latest evidence baseline.")(diff_cmd.show_diff)
app.add_typer(evidence_cmd.evidence_app, name="evidence")
app.add_typer(report_cmd.report_app, name="report")
app.add_typer(brownfield_cmd.brownfield_app, name="brownfield")
app.add_typer(emergency_cmd.emergency_app, name="emergency")
