"""Implementation of the ``ces audit`` command.

Queries audit ledger entries with filters: --event-type, --actor,
--after, --before. Supports pagination via --limit and --offset.

Shows entries in a Rich table with timestamp, event type, actor,
and details (truncated metadata).

T-06-19: Audit entries are designed for transparency. Showing audit
data to CLI user is the intended behavior per AUDIT-05.

Exports:
    query_audit: Typer command function for ``ces audit``.
"""

from __future__ import annotations

import json

import typer
from rich.table import Table

import ces.cli._output as _output_mod
from ces.cli._async import run_async
from ces.cli._context import find_project_root, get_project_id
from ces.cli._errors import handle_error
from ces.cli._factory import get_services
from ces.cli._output import console


@run_async
async def query_audit(
    event_type: str = typer.Option(
        "",
        "--event-type",
        "-e",
        help="Filter by event type",
    ),
    actor: str = typer.Option(
        "",
        "--actor",
        "-a",
        help="Filter by actor",
    ),
    after: str = typer.Option(
        "",
        "--after",
        help="Start time (ISO format)",
    ),
    before: str = typer.Option(
        "",
        "--before",
        help="End time (ISO format)",
    ),
    limit: int = typer.Option(
        20,
        "--limit",
        "-l",
        help="Page size",
    ),
    offset: int = typer.Option(
        0,
        "--offset",
        "-o",
        help="Skip entries",
    ),
) -> None:
    """Query audit ledger entries with optional filters and pagination.

    Shows entries in a Rich table with timestamp, event type, actor,
    and action summary. Supports --event-type, --actor, --after,
    --before filters, and --limit/--offset pagination.
    """
    try:
        find_project_root()
        project_id = get_project_id()

        async with get_services() as services:
            audit_ledger = services.get("audit_ledger")

            # Query entries using AuditLedgerService methods
            from datetime import datetime, timedelta, timezone

            raw_entries: list = []

            if event_type:
                # T-07-08: Validate event_type against EventType enum
                from ces.shared.enums import EventType as ET

                try:
                    et = ET(event_type.lower())
                except ValueError:
                    raise typer.BadParameter(f"Invalid event type: {event_type}")
                raw_entries = await audit_ledger.query_by_event_type(et, limit=limit + offset, project_id=project_id)
            elif actor:
                raw_entries = await audit_ledger.query_by_actor(actor, limit=limit + offset, project_id=project_id)
            elif after or before:
                start = datetime.fromisoformat(after) if after else datetime.min.replace(tzinfo=timezone.utc)
                end = datetime.fromisoformat(before) if before else datetime.now(timezone.utc)
                raw_entries = await audit_ledger.query_by_time_range(start, end, project_id=project_id)
            else:
                # Default: query last 24 hours
                now = datetime.now(timezone.utc)
                day_ago = now - timedelta(hours=24)
                raw_entries = await audit_ledger.query_by_time_range(day_ago, now, project_id=project_id)

            total = len(raw_entries)

            # Apply pagination (service methods don't support offset natively)
            raw_entries = raw_entries[offset : offset + limit]

            # Convert AuditEntry objects to dicts for display
            entry_dicts = []
            for e in raw_entries:
                entry_dicts.append(
                    {
                        "entry_id": e.entry_id,
                        "timestamp": str(e.timestamp),
                        "event_type": (e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type)),
                        "actor": e.actor,
                        "action_summary": e.action_summary,
                    }
                )

            if _output_mod._json_mode:
                typer.echo(json.dumps(entry_dicts, indent=2, default=str))
                return

            # Rich table
            table = Table(title="Audit Log")
            table.add_column("Entry ID", style="bold")
            table.add_column("Timestamp")
            table.add_column("Event Type")
            table.add_column("Actor")
            table.add_column("Summary")

            for entry in entry_dicts:
                summary = entry.get("action_summary", "")
                summary = summary[:60] + "..." if len(summary) > 60 else summary
                table.add_row(
                    entry["entry_id"],
                    entry["timestamp"],
                    entry["event_type"],
                    entry["actor"],
                    summary,
                )

            console.print(table)
            console.print(f"\n[dim]Showing {offset + 1}-{offset + len(entry_dicts)} of {total}[/dim]")

    except (typer.BadParameter, ValueError) as exc:
        handle_error(exc)
    except (ConnectionError, RuntimeError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)
