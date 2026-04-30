"""Implementation of the ``ces brownfield`` subcommand group.

Provides five subcommands for managing the Observed Legacy Behavior Register:
- ``ces brownfield register``: Register a newly observed legacy behavior (BROWN-01).
- ``ces brownfield list``: List pending behaviors (optionally filtered by system).
- ``ces brownfield review``: Set disposition on a pending behavior (BROWN-03).
- ``ces brownfield promote``: Promote a reviewed behavior to PRL (BROWN-03).
- ``ces brownfield discard``: Discard a reviewed behavior (BROWN-03).

BROWN-02 enforcement: register goes to the register, NOT the PRL.
The service layer (LegacyBehaviorService) enforces this invariant.

Exports:
    brownfield_app: Typer sub-application for brownfield commands.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.panel import Panel
from rich.table import Table

import ces.cli._output as _output_mod
from ces.cli._async import run_async
from ces.cli._context import find_project_root, get_project_id
from ces.cli._errors import handle_error
from ces.cli._factory import get_services
from ces.cli._output import console
from ces.shared.enums import LegacyDisposition

# Valid disposition values for the review command
_VALID_DISPOSITIONS = {d.value for d in LegacyDisposition}

brownfield_app = typer.Typer(
    name="brownfield",
    help="Capture and review existing-system behavior before CES changes it.",
)


@brownfield_app.command(name="register")
@run_async
async def register_behavior(
    system: str = typer.Option(
        "",
        "--system",
        "-s",
        help="Legacy system name (required unless --from-scan is used).",
    ),
    description: str = typer.Option(
        "",
        "--description",
        "-d",
        help="Observed behavior description (required unless --from-scan is used).",
    ),
    inferred_by: str = typer.Option(
        "cli-user",
        "--inferred-by",
        help="Agent/user who inferred the behavior",
    ),
    confidence: float = typer.Option(
        0.5,
        "--confidence",
        "-c",
        help="Confidence score (0.0 to 1.0)",
    ),
    manifest_id: str = typer.Option(
        "",
        "--manifest-id",
        help="Source manifest ID (optional)",
    ),
    from_scan: str = typer.Option(
        "",
        "--from-scan",
        help=(
            "Bulk-register candidate behaviors from a scan.json. "
            "Empty value uses .ces/brownfield/scan.json; pass an explicit path "
            "to override, or combine with the bool flag '--from-scan' used alone."
        ),
    ),
    from_scan_default: bool = typer.Option(
        False,
        "--from-default-scan",
        help="Bulk-register from the default .ces/brownfield/scan.json (no path needed).",
    ),
) -> None:
    """Register a newly observed legacy behavior (BROWN-01).

    Creates an entry in the Observed Legacy Behavior Register.
    BROWN-02: This goes to the register, NOT the PRL.

    With ``--from-scan`` this bulk-registers one candidate behavior per
    module detected by ``ces scan``. The user reviews/dispositions each
    entry separately with ``ces brownfield review``.
    """
    try:
        project_root = find_project_root()
        project_id = get_project_id()

        if from_scan or from_scan_default:
            if system or description:
                raise typer.BadParameter("--from-scan cannot be combined with --system or --description.")
            scan_path = Path(from_scan) if from_scan else project_root / ".ces" / "brownfield" / "scan.json"
            if not scan_path.is_file():
                raise typer.BadParameter(f"Scan file not found: {scan_path}. Run 'ces scan' first.")
            await _register_from_scan(scan_path, inferred_by=inferred_by)
            return

        if not system or not description:
            raise typer.BadParameter("Both --system and --description are required unless --from-scan is used.")

        async with get_services() as services:
            legacy_service = services.get("legacy_behavior_service")

            entry = await legacy_service.register_behavior(
                system=system,
                behavior_description=description,
                inferred_by=inferred_by,
                confidence=confidence,
                source_manifest_id=manifest_id if manifest_id else None,
            )

            if _output_mod._json_mode:
                typer.echo(json.dumps(entry.model_dump(mode="json"), indent=2, default=str))
                return

            console.print(
                Panel(
                    f"[bold]Entry ID:[/bold] {entry.entry_id}\n"
                    f"[bold]System:[/bold] {entry.system}\n"
                    f"[bold]Description:[/bold] {entry.behavior_description}\n"
                    f"[bold]Confidence:[/bold] {entry.confidence}\n"
                    f"[bold]Disposition:[/bold] pending",
                    title="[green]Captured Existing Behavior[/green]",
                    border_style="green",
                )
            )

    except (typer.BadParameter, ValueError) as exc:
        handle_error(exc)
    except (ConnectionError, RuntimeError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)


async def _register_from_scan(scan_path: Path, *, inferred_by: str) -> None:
    """Read ``scan.json`` and draft one register entry per detected module."""
    payload = json.loads(scan_path.read_text(encoding="utf-8"))
    modules = payload.get("modules", [])
    if not modules:
        console.print("[yellow]No modules in scan — nothing to register.[/yellow]")
        return

    async with get_services() as services:
        legacy_service = services.get("legacy_behavior_service")
        created: list[tuple[str, str]] = []
        for module in modules:
            module_name = str(module.get("name") or module.get("path") or "unknown")
            module_path = str(module.get("path", ""))
            module_type = str(module.get("type", "unknown"))
            description = (
                f"Detected {module_type} module at {module_path}. "
                "Confirm the critical workflows CES must preserve before any agent change."
            )
            entry = await legacy_service.register_behavior(
                system=module_name,
                behavior_description=description,
                inferred_by=inferred_by,
                confidence=0.5,
                source_manifest_id=None,
            )
            created.append((module_name, entry.entry_id))

        if _output_mod._json_mode:
            typer.echo(
                json.dumps(
                    [{"system": name, "entry_id": eid} for name, eid in created],
                    indent=2,
                )
            )
            return

        table = Table(title=f"Drafted {len(created)} register entries from scan")
        table.add_column("System", style="bold")
        table.add_column("Entry ID")
        for name, eid in created:
            table.add_row(name, eid)
        console.print(table)


@brownfield_app.command(name="list")
@run_async
async def list_behaviors(
    system: str = typer.Option(
        "",
        "--system",
        "-s",
        help="Filter by system name",
    ),
) -> None:
    """List pending legacy behaviors.

    Without --system, lists all pending behaviors.
    With --system, lists behaviors for that specific system.
    """
    try:
        find_project_root()
        project_id = get_project_id()

        async with get_services() as services:
            legacy_service = services.get("legacy_behavior_service")

            if system:
                behaviors = await legacy_service.get_behaviors_by_system(system)
            else:
                behaviors = await legacy_service.get_pending_behaviors()

            if _output_mod._json_mode:
                data = [b.model_dump(mode="json") for b in behaviors]
                typer.echo(json.dumps(data, indent=2, default=str))
                return

            if not behaviors:
                console.print("[dim]No pending behaviors found.[/dim]")
                return

            table = Table(title="Existing System Behaviors")
            table.add_column("Entry ID", style="bold")
            table.add_column("System")
            table.add_column("Description")
            table.add_column("Confidence", justify="right")
            table.add_column("Disposition")
            table.add_column("Inferred At")

            for b in behaviors:
                disp = b.disposition if b.disposition else "pending"
                inferred = (
                    b.inferred_at.strftime("%Y-%m-%d %H:%M")
                    if hasattr(b.inferred_at, "strftime")
                    else str(b.inferred_at)
                )
                table.add_row(
                    b.entry_id,
                    b.system,
                    b.behavior_description[:60] + ("..." if len(b.behavior_description) > 60 else ""),
                    f"{b.confidence:.1%}",
                    disp,
                    inferred,
                )

            console.print(table)

    except (typer.BadParameter, ValueError) as exc:
        handle_error(exc)
    except (ConnectionError, RuntimeError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)


@brownfield_app.command(name="review")
@run_async
async def review_behavior(
    entry_id: str = typer.Argument(
        ...,
        help="Legacy behavior entry ID",
    ),
    reviewer: str = typer.Option(
        "cli-user",
        "--reviewer",
        help="Reviewer identifier",
    ),
    disposition: str = typer.Option(
        ...,
        "--disposition",
        "-d",
        help=f"Disposition: {', '.join(sorted(_VALID_DISPOSITIONS))}",
    ),
    notes: str = typer.Option(
        "",
        "--notes",
        "-n",
        help="Review notes",
    ),
) -> None:
    """Review a pending behavior and set its disposition (BROWN-03).

    Validates the disposition value and calls the service.
    """
    try:
        find_project_root()

        # Validate disposition
        if disposition not in _VALID_DISPOSITIONS:
            raise typer.BadParameter(
                f"Invalid disposition: {disposition}. Must be one of: {', '.join(sorted(_VALID_DISPOSITIONS))}"
            )

        disposition_enum = LegacyDisposition(disposition)

        async with get_services() as services:
            legacy_service = services.get("legacy_behavior_service")

            entry = await legacy_service.review_behavior(
                entry_id=entry_id,
                disposition=disposition_enum,
                reviewed_by=reviewer,
            )

            if _output_mod._json_mode:
                typer.echo(json.dumps(entry.model_dump(mode="json"), indent=2, default=str))
                return

            console.print(
                Panel(
                    f"[bold]Entry ID:[/bold] {entry.entry_id}\n"
                    f"[bold]System:[/bold] {entry.system}\n"
                    f"[bold]Disposition:[/bold] {entry.disposition}\n"
                    f"[bold]Reviewed by:[/bold] {entry.reviewed_by}",
                    title="[blue]Behavior Decision Saved[/blue]",
                    border_style="blue",
                )
            )

    except (typer.BadParameter, ValueError) as exc:
        handle_error(exc)
    except (ConnectionError, RuntimeError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)


@brownfield_app.command(name="promote")
@run_async
async def promote_behavior(
    entry_id: str = typer.Argument(
        ...,
        help="Legacy behavior entry ID to promote",
    ),
    approver: str = typer.Option(
        "cli-user",
        "--approver",
        help="Approver identifier",
    ),
) -> None:
    """Promote a reviewed behavior to the PRL (BROWN-03).

    Creates a new PRL item via copy-on-promote. The original
    register entry is preserved with a back-reference.
    """
    try:
        find_project_root()
        project_id = get_project_id()

        async with get_services() as services:
            legacy_service = services.get("legacy_behavior_service")

            updated_entry, prl_item = await legacy_service.promote_to_prl(
                entry_id=entry_id,
                approver=approver,
            )

            if _output_mod._json_mode:
                typer.echo(json.dumps(prl_item.model_dump(mode="json"), indent=2, default=str))
                return

            console.print(
                Panel(
                    f"[bold]PRL ID:[/bold] {prl_item.prl_id}\n"
                    f"[bold]Statement:[/bold] {prl_item.statement}\n"
                    f"[bold]Source Entry:[/bold] {updated_entry.entry_id}\n"
                    f"[bold]Approved by:[/bold] {approver}",
                    title="[green]Added To Product Truth[/green]",
                    border_style="green",
                )
            )

    except (typer.BadParameter, ValueError) as exc:
        handle_error(exc)
    except (ConnectionError, RuntimeError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)


@brownfield_app.command(name="discard")
@run_async
async def discard_behavior(
    entry_id: str = typer.Argument(
        ...,
        help="Legacy behavior entry ID to discard",
    ),
    reason: str = typer.Option(
        "",
        "--reason",
        "-r",
        help="Reason for discarding",
    ),
) -> None:
    """Discard a legacy behavior entry (BROWN-03).

    Marks the entry as discarded. Cannot discard an already-promoted entry.
    """
    try:
        find_project_root()
        project_id = get_project_id()

        async with get_services() as services:
            legacy_service = services.get("legacy_behavior_service")

            entry = await legacy_service.discard_behavior(
                entry_id=entry_id,
                reviewed_by="cli-user",
                reason=reason,
            )

            if _output_mod._json_mode:
                typer.echo(json.dumps(entry.model_dump(mode="json"), indent=2, default=str))
                return

            console.print(
                Panel(
                    f"[bold]Entry ID:[/bold] {entry.entry_id}\n"
                    f"[bold]System:[/bold] {entry.system}\n"
                    f"[bold]Disposition:[/bold] {entry.disposition}\n"
                    f"[bold]Discarded:[/bold] Yes",
                    title="[yellow]Behavior Retired[/yellow]",
                    border_style="yellow",
                )
            )

    except (typer.BadParameter, ValueError) as exc:
        handle_error(exc)
    except (ConnectionError, RuntimeError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)
