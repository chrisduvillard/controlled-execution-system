"""Implementation of the ``ces emergency`` subcommand group.

Provides ``ces emergency declare`` for activating the emergency hotfix path.
Shows blast radius, prompts for confirmation, and displays SLA countdown.

T-06-15: Emergency declaration requires interactive confirmation unless
--yes explicitly provided. EmergencyService enforces single-emergency
constraint and 500-line cap.

T-06-16: Emergency declaration logged in audit ledger with timestamp
and declarer identity (handled by EmergencyService).

Exports:
    emergency_app: Typer sub-application for emergency commands.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import typer
from rich.panel import Panel

import ces.cli._output as _output_mod
from ces.cli._async import run_async
from ces.cli._context import find_project_root, get_project_id
from ces.cli._errors import handle_error
from ces.cli._factory import get_services
from ces.cli._output import console

emergency_app = typer.Typer(
    name="emergency",
    help="Emergency hotfix operations.",
)


@emergency_app.command(name="declare")
@run_async
async def declare_emergency(
    description: str = typer.Argument(
        ...,
        help="Emergency description",
    ),
    files: list[str] = typer.Option(
        [],
        "--file",
        "-f",
        help="Affected files (repeatable)",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt",
    ),
) -> None:
    """Declare an emergency and activate the hotfix path.

    Shows blast radius (affected files, 500-line cap, 15-minute SLA),
    prompts for confirmation unless --yes, then creates an emergency
    manifest and displays the SLA countdown.
    """
    try:
        find_project_root()
        project_id = get_project_id()

        # Show blast radius panel
        if not _output_mod._json_mode:
            blast_lines = [
                "[bold red]Emergency Hotfix Path[/bold red]",
                "",
                f"Description: {description}",
                "",
                "[bold]Blast Radius:[/bold]",
            ]
            for f in files:
                blast_lines.append(f"  - {f}")

            blast_lines.extend(
                [
                    "",
                    "[bold]Constraints:[/bold]",
                    "  - Maximum 500 lines changed",
                    "  - 15-minute SLA deadline",
                    "  - Compensating controls activated:",
                    "    - Kill switch freeze on non-emergency work",
                    "    - Mandatory 24h post-incident review",
                    "    - Retroactive evidence packet required",
                ]
            )

            console.print(
                Panel(
                    "\n".join(blast_lines),
                    title="[red]Emergency Declaration[/red]",
                    border_style="red",
                )
            )

        # Confirmation prompt (T-06-15)
        if not yes:
            typer.confirm(
                "Declare emergency? This activates the hotfix path.",
                abort=True,
            )

        async with get_services() as services:
            emergency_service = services["emergency_service"]

            manifest = await emergency_service.declare_emergency(
                description=description,
                affected_files=files,
                declared_by="cli-user",
            )

            if _output_mod._json_mode:
                data = {
                    "manifest_id": manifest.manifest_id,
                    "description": description,
                    "affected_files": files,
                    "sla_deadline": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
                    "status": "active",
                }
                typer.echo(json.dumps(data, indent=2, default=str))
                return

            # Show success with SLA countdown info
            sla_deadline = datetime.now(timezone.utc) + timedelta(minutes=15)

            console.print(
                Panel(
                    f"[bold green]Emergency declared successfully[/bold green]\n\n"
                    f"Manifest ID: [bold]{manifest.manifest_id}[/bold]\n"
                    f"SLA Deadline: [bold red]{sla_deadline.strftime('%H:%M:%S UTC')}[/bold red] "
                    f"(15 minutes from now)\n\n"
                    f"[dim]Emergency active. Complete hotfix within SLA.\n"
                    f"Coordinate recovery through the operator-owned service path when done.[/dim]",
                    title="[green]Emergency Active[/green]",
                    border_style="green",
                )
            )

    except typer.Abort:
        console.print("[dim]Emergency declaration cancelled.[/dim]")
    except (typer.BadParameter, ValueError) as exc:
        handle_error(exc)
    except (ConnectionError, RuntimeError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)
