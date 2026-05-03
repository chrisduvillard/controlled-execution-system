"""Implementation of the ``ces status`` command.

Shows a Rich status view with up to 5 sections:
1. Trust Status: harness profile trust levels
2. Active Manifests: non-terminal workflow states
3. Pending Reviews: manifests in under_review state
4. Recent Audit: last 10 audit events
5. Telemetry summary: optional local metrics when available

Supports --watch mode for continuous refresh and --json for machine output.
Supports --verbose for detailed telemetry metrics when present.

T-06-18 mitigation: --watch uses configurable interval (min 0.5s) to prevent
tight-loop queries. Live display handles KeyboardInterrupt for clean exit.

Exports:
    show_status: Typer command function for ``ces status``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import typer
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

import ces.cli._output as _output_mod
from ces.cli._async import run_async
from ces.cli._builder_report import build_builder_run_report, serialize_builder_run_report
from ces.cli._context import find_project_root, get_project_config, get_project_id
from ces.cli._errors import handle_error
from ces.cli._factory import get_services
from ces.cli._output import console, set_json_mode


def _load_builder_snapshot(local_store: Any) -> Any | None:
    get_snapshot = getattr(local_store, "get_latest_builder_session_snapshot", None)
    if callable(get_snapshot):
        candidate = get_snapshot()
        if isinstance(getattr(candidate, "request", None), str):
            return candidate
    return None


def _describe_builder_next_step(session: Any | None) -> str | None:
    if session is None:
        return None
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
    return mapping.get(next_action)


def _build_trust_table(profiles: list[dict]) -> Table:
    """Build a Rich table for trust profiles.

    Args:
        profiles: List of profile dicts with profile_id, trust_status, etc.

    Returns:
        Rich Table with trust profile information.
    """
    table = Table(title="Trust Status")
    table.add_column("Profile ID", style="bold")
    table.add_column("Trust Status")
    table.add_column("Tasks", justify="right")
    table.add_column("Last Promotion")

    trust_styles = {
        "trusted": "[green]trusted[/green]",
        "candidate": "[yellow]candidate[/yellow]",
        "watch": "[red]watch[/red]",
        "constrained": "[bold red]constrained[/bold red]",
    }

    for p in profiles:
        status = p.get("trust_status", "unknown")
        styled = trust_styles.get(status, status)
        table.add_row(
            p.get("profile_id", ""),
            styled,
            str(p.get("task_count", 0)),
            str(p.get("last_promotion", "N/A")),
        )

    return table


def _build_manifests_table(manifests: list[dict]) -> Table:
    """Build a Rich table for active manifests.

    Args:
        manifests: List of manifest dicts with manifest_id, description, etc.

    Returns:
        Rich Table with active manifest information.
    """
    table = Table(title="Active Manifests")
    table.add_column("Manifest ID", style="bold")
    table.add_column("Description")
    table.add_column("Risk Tier")
    table.add_column("State")

    for m in manifests:
        desc = m.get("description", "")
        desc = desc[:50] + "..." if len(desc) > 50 else desc
        table.add_row(
            m.get("manifest_id", ""),
            desc,
            m.get("risk_tier", ""),
            m.get("workflow_state", ""),
        )

    return table


def _build_reviews_table(reviews: list[dict]) -> Table:
    """Build a Rich table for pending reviews.

    Args:
        reviews: List of review dicts.

    Returns:
        Rich Table with pending review information.
    """
    table = Table(title="Pending Reviews")
    table.add_column("Manifest ID", style="bold")
    table.add_column("Gate Type")
    table.add_column("Reviewers", justify="right")

    for r in reviews:
        table.add_row(
            r.get("manifest_id", ""),
            r.get("gate_type", ""),
            str(r.get("reviewer_count", 0)),
        )

    return table


def _build_metrics_table(summaries: dict[str, dict]) -> Table:
    """Build a Rich table showing key telemetry metrics per level.

    Args:
        summaries: Dict of level -> summary metrics collected locally.

    Returns:
        Rich Table with one key metric per telemetry level.
    """
    table = Table(title="Telemetry (Last Hour)")
    table.add_column("Level", style="bold")
    table.add_column("Key Metric")
    table.add_column("Value", justify="right")

    # Extract the single most important metric per level
    level_key_metrics = {
        "task": ("Tasks Executed", "record_count"),
        "agent": ("Avg Error Rate", "avg_error_rate"),
        "harness": ("Review Catch Rate", "avg_review_catch_rate"),
        "control_plane": ("Approval Queue", "max_approval_queue_depth"),
        "system": ("Active Agents", "max_active_agents"),
    }

    level_display_names = {
        "task": "Task",
        "agent": "Agent",
        "harness": "Harness",
        "control_plane": "Control Plane",
        "system": "System",
    }

    for level, (metric_label, metric_key) in level_key_metrics.items():
        level_data = summaries.get(level, {})
        value = level_data.get(metric_key, 0)
        # Format floats as rates (percentage or decimal)
        if isinstance(value, float):
            display_value = f"{value:.2f}"
        else:
            display_value = str(value)
        table.add_row(
            level_display_names.get(level, level),
            metric_label,
            display_value,
        )

    return table


def _build_verbose_metrics_table(summaries: dict[str, dict]) -> Table:
    """Build a detailed Rich table with all metrics per level.

    Args:
        summaries: Dict of level -> summary metrics collected locally.

    Returns:
        Rich Table with all available metrics per level.
    """
    table = Table(title="Telemetry Detail (Last Hour)")
    table.add_column("Level", style="bold")
    table.add_column("Metric")
    table.add_column("Value", justify="right")

    level_display_names = {
        "task": "Task",
        "agent": "Agent",
        "harness": "Harness",
        "control_plane": "Control Plane",
        "system": "System",
    }

    for level_name, metrics in summaries.items():
        display_name = level_display_names.get(level_name, level_name)
        for metric_key, value in metrics.items():
            if metric_key == "record_count":
                continue  # Skip internal count
            if isinstance(value, (list, dict)):
                continue  # Skip complex nested data
            if isinstance(value, float):
                display_value = f"{value:.4f}"
            else:
                display_value = str(value)
            table.add_row(display_name, metric_key, display_value)

    return table


def _build_events_table(events: list[dict]) -> Table:
    """Build a Rich table for recent audit events.

    Args:
        events: List of event dicts.

    Returns:
        Rich Table with recent audit event information.
    """
    table = Table(title="Recent Audit Events")
    table.add_column("Timestamp")
    table.add_column("Event Type")
    table.add_column("Actor")
    table.add_column("Summary")

    for e in events:
        summary = e.get("summary", e.get("action_summary", ""))
        summary = summary[:60] + "..." if len(summary) > 60 else summary
        table.add_row(
            str(e.get("timestamp", "")),
            e.get("event_type", ""),
            e.get("actor", ""),
            summary,
        )

    return table


def _build_overview_panel(project_id: str, data: dict, project_name: str | None = None) -> Panel:
    active_manifests = data["active_manifests"]
    pending_reviews = data["pending_reviews"]
    recent_events = data["recent_events"]
    builder_snapshot = data.get("builder_snapshot")
    builder_session = data.get("builder_session")
    builder_brief = data.get("builder_brief")
    pending_brownfield_count = data.get("pending_brownfield_count", 0)
    builder_run = build_builder_run_report(builder_snapshot)

    if builder_snapshot is not None and getattr(builder_snapshot, "next_step", None):
        next_step = str(builder_snapshot.next_step)
    elif builder_session is not None and getattr(builder_session, "next_action", None):
        next_step = _describe_builder_next_step(builder_session) or str(builder_session.next_action)
    elif pending_brownfield_count:
        next_step = "Resolve the pending brownfield decisions before shipping more changes."
    elif pending_reviews:
        next_step = f"Review the current change with `ces review {pending_reviews[0]['manifest_id']}`."
    elif active_manifests:
        next_step = "Work is in flight. Use `ces status --expert` for the full expert view."
    else:
        next_step = 'Start with `ces build "describe what you want to build"`.'

    current_request = (
        builder_snapshot.request
        if builder_snapshot is not None
        else builder_session.request
        if builder_session is not None
        else builder_brief.request
        if builder_brief is not None
        else active_manifests[0]["description"]
        if active_manifests
        else "No active build request."
    )
    latest_activity = (
        str(builder_snapshot.latest_activity)
        if builder_snapshot is not None and getattr(builder_snapshot, "latest_activity", None)
        else recent_events[0]["summary"]
        if recent_events
        else "No recent CES activity recorded yet."
    )
    project_mode = (
        getattr(builder_snapshot, "project_mode", "unknown")
        if builder_snapshot is not None
        else getattr(builder_session, "project_mode", "unknown")
        if builder_session is not None
        else getattr(builder_brief, "project_mode", "unknown")
        if builder_brief is not None
        else "unknown"
    )
    display_project = project_name or project_id
    lines = [
        f"Project: {display_project}",
    ]
    if project_name and project_name != project_id:
        lines.append(f"Project ID: {project_id}")
    lines.extend(
        [
            f"Current request: {current_request}",
            f"Project mode: {project_mode}",
            f"Needs review: {len(pending_reviews)}",
        ]
    )
    if builder_run is not None:
        lines.append(f"Review state: {builder_run.review_state}")
        lines.append(f"Latest outcome: {builder_run.latest_outcome}")
    if builder_snapshot is not None:
        lines.append(f"Current session stage: {builder_snapshot.stage}")
    elif builder_session is not None:
        lines.append(f"Current session stage: {builder_session.stage}")
        if getattr(builder_session, "recovery_reason", None):
            lines.append(f"Recovery path: {builder_session.recovery_reason}")
    if builder_snapshot is not None and getattr(builder_snapshot, "brownfield", None) is not None:
        lines.append(
            "Brownfield progress: "
            f"{builder_snapshot.brownfield.reviewed_count} reviewed, "
            f"{builder_snapshot.brownfield.remaining_count} remaining"
        )
    elif pending_brownfield_count:
        suffix = "decision" if pending_brownfield_count == 1 else "decisions"
        lines.append(f"Brownfield queue: {pending_brownfield_count} pending brownfield {suffix}")
    lines.extend(
        [
            f"Latest activity: {latest_activity}",
            f"Next step: {next_step}",
        ]
    )
    body = "\n".join(lines)
    return Panel(body, title="Builder Status", border_style="cyan")


def _serialize_status_payload(project_id: str, data: dict, project_name: str | None = None) -> dict:
    builder_run = serialize_builder_run_report(build_builder_run_report(data.get("builder_snapshot")))
    return {
        "project_id": project_id,
        "project_name": project_name,
        "trust_profiles": data["trust_profiles"],
        "active_manifests": data["active_manifests"],
        "pending_reviews": data["pending_reviews"],
        "recent_events": data["recent_events"],
        "pending_brownfield_count": data.get("pending_brownfield_count", 0),
        "telemetry_summary": data.get("telemetry_summary", {}),
        "builder_run": builder_run,
    }


async def _gather_status_data(
    services: dict,
    project_id: str | None = None,
    project_config: dict[str, Any] | None = None,
) -> dict:
    """Gather all local status data from CES services.

    Calls TrustManager, ManifestManager, and AuditLedgerService to gather
    the data shown by ``ces status``.

    Args:
        services: Service dict from get_services().
        project_config: Optional CES project config. When omitted, the helper
            best-effort loads it from the current project root.

    Returns:
        Dict with trust_profiles, active_manifests, pending_reviews, recent_events.
    """
    from datetime import datetime, timedelta, timezone

    trust_manager = services["trust_manager"]
    manifest_manager = services["manifest_manager"]
    audit_ledger = services.get("audit_ledger")

    # Trust profiles — TrustManager does not have a bulk query method yet,
    # so we return an empty list. Phase 9 will wire this.
    trust_profiles: list[dict] = []

    # Active manifests from ManifestManager
    active_manifests_raw = await manifest_manager.get_active_manifests()
    active_manifests = [
        {
            "manifest_id": m.manifest_id,
            "description": getattr(m, "description", ""),
            "risk_tier": m.risk_tier.value if hasattr(m.risk_tier, "value") else str(m.risk_tier),
            "workflow_state": m.workflow_state.value
            if hasattr(m.workflow_state, "value")
            else str(getattr(m, "workflow_state", "")),
        }
        for m in active_manifests_raw
    ]

    # Pending reviews — manifests in under_review state
    pending_reviews = [
        {
            "manifest_id": m["manifest_id"],
            "gate_type": "",
            "reviewer_count": 0,
        }
        for m in active_manifests
        if m.get("workflow_state") == "under_review"
    ]

    # Recent audit events (last 24 hours, max 10)
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)
    try:
        recent_entries = await audit_ledger.query_by_time_range(day_ago, now, project_id=project_id)
        recent_events = [
            {
                "timestamp": str(e.timestamp),
                "event_type": e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type),
                "actor": e.actor,
                "summary": e.action_summary,
            }
            for e in recent_entries[:10]
        ]
    except Exception:
        recent_events = []

    builder_session = None
    builder_brief = None
    builder_snapshot = None
    local_store = services.get("local_store")
    if local_store is not None:
        builder_snapshot = _load_builder_snapshot(local_store)
        if builder_snapshot is not None:
            builder_session = getattr(builder_snapshot, "session", None)
            builder_brief = getattr(builder_snapshot, "brief", None)
        ensure_session = getattr(local_store, "ensure_latest_builder_session", None)
        if builder_session is None and callable(ensure_session):
            try:
                candidate = ensure_session()
                if isinstance(getattr(candidate, "stage", None), str):
                    builder_session = candidate
            except Exception:
                builder_session = None
        if builder_session is None and hasattr(local_store, "get_latest_builder_session"):
            try:
                candidate = local_store.get_latest_builder_session()
                if isinstance(getattr(candidate, "stage", None), str):
                    builder_session = candidate
            except Exception:
                builder_session = None
    if builder_brief is None and local_store is not None and hasattr(local_store, "get_latest_builder_brief"):
        try:
            builder_brief = local_store.get_latest_builder_brief()
        except Exception:
            builder_brief = None

    pending_brownfield_count = 0
    if builder_snapshot is not None and getattr(builder_snapshot, "brownfield", None) is not None:
        pending_brownfield_count = builder_snapshot.brownfield.remaining_count
    else:
        legacy_behavior_service = services.get("legacy_behavior_service")
        if legacy_behavior_service is not None and hasattr(legacy_behavior_service, "get_pending_behaviors"):
            try:
                pending_brownfield_count = len(await legacy_behavior_service.get_pending_behaviors())
            except Exception:
                pending_brownfield_count = 0

    # CES is published as a local product. The builder status view therefore does
    # not query any external telemetry store.
    telemetry_summary: dict[str, dict] = {}

    return {
        "trust_profiles": trust_profiles,
        "active_manifests": active_manifests,
        "pending_reviews": pending_reviews,
        "recent_events": recent_events,
        "builder_snapshot": builder_snapshot,
        "builder_session": builder_session,
        "builder_brief": builder_brief,
        "pending_brownfield_count": pending_brownfield_count,
        "telemetry_summary": telemetry_summary,
    }


@run_async
async def show_status(
    watch: bool = typer.Option(
        False,
        "--watch",
        "-w",
        help="Continuous refresh mode",
    ),
    interval: float = typer.Option(
        2.0,
        "--interval",
        help="Refresh interval in seconds (min 0.5)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed telemetry metrics for all 5 levels",
    ),
    expert: bool = typer.Option(
        False,
        "--expert",
        help="Show the detailed expert view instead of the concise builder view.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output status as JSON. Equivalent to `ces --json status`.",
    ),
) -> None:
    """Show project status with trust, manifests, reviews, and audit context.

    T-06-18: --watch uses configurable interval (min 0.5s).
    """
    if json_output:
        set_json_mode(True)
    try:
        find_project_root()
        project_id = get_project_id()
        project_config = get_project_config()

        # T-06-18: Enforce minimum interval
        interval = max(0.5, interval)

        async with get_services() as services:
            data = await _gather_status_data(services, project_id=project_id, project_config=project_config)

            if _output_mod._json_mode:
                typer.echo(
                    json.dumps(
                        _serialize_status_payload(project_id, data, project_config.get("project_name")), indent=2
                    )
                )
                return

            if watch:
                # Continuous refresh with Rich Live
                try:
                    with Live(console=console, refresh_per_second=1) as live:
                        while True:
                            data = await _gather_status_data(
                                services,
                                project_id=project_id,
                                project_config=project_config,
                            )
                            tables = [_build_overview_panel(project_id, data, project_config.get("project_name"))]
                            if expert:
                                tables.extend(
                                    [
                                        _build_trust_table(data["trust_profiles"]),
                                        _build_manifests_table(data["active_manifests"]),
                                        _build_reviews_table(data["pending_reviews"]),
                                        _build_events_table(data["recent_events"]),
                                    ]
                                )
                            # Telemetry metrics panel (shown only when local telemetry exists)
                            if data.get("telemetry_summary"):
                                if verbose:
                                    tables.append(_build_verbose_metrics_table(data["telemetry_summary"]))
                                else:
                                    tables.append(_build_metrics_table(data["telemetry_summary"]))
                            # Use a group to display all tables
                            from rich.console import Group

                            live.update(Group(*tables))
                            await asyncio.sleep(interval)
                except KeyboardInterrupt:
                    console.print("\n[dim]Watch mode stopped.[/dim]")
                return

            # Single display
            console.print(_build_overview_panel(project_id, data, project_config.get("project_name")))

            # Telemetry metrics panel (shown only when local telemetry exists)
            if data.get("telemetry_summary"):
                console.print()
                if verbose:
                    console.print(_build_verbose_metrics_table(data["telemetry_summary"]))
                else:
                    console.print(_build_metrics_table(data["telemetry_summary"]))

            if expert:
                console.print()
                console.print(_build_trust_table(data["trust_profiles"]))
                console.print()
                console.print(_build_manifests_table(data["active_manifests"]))
                console.print()
                console.print(_build_reviews_table(data["pending_reviews"]))
                console.print()
                console.print(_build_events_table(data["recent_events"]))

    except (typer.BadParameter, ValueError) as exc:
        handle_error(exc)
    except (ConnectionError, RuntimeError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)
