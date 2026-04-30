"""Implementation of the ``ces vault`` subcommand group.

Provides three subcommands:
- ``ces vault query <topic>``: Query vault and display matching notes.
- ``ces vault write <category>``: Write a new vault note.
- ``ces vault health``: Run trust decay check and index refresh.

Uses KnowledgeVaultService from the knowledge subsystem.
T-06-14 mitigation: Notes written via CLI use trust_level=AGENT_INFERRED
by default. Only verified content gets VERIFIED through separate review.

Exports:
    vault_app: Typer sub-application for vault commands.
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
from ces.shared.enums import VaultCategory, VaultTrustLevel

vault_app = typer.Typer(
    name="vault",
    help="Knowledge Vault operations (query, write, health).",
)


@vault_app.command(name="query")
@run_async
async def query_vault(
    topic: str = typer.Argument(
        ...,
        help="Topic or tag to search for",
    ),
    limit: int = typer.Option(
        10,
        "--limit",
        "-l",
        help="Maximum number of results",
    ),
) -> None:
    """Query the knowledge vault and display matching notes.

    Searches by tag and displays results in a Rich table with
    note ID, category, trust level, and content (truncated to 80 chars).
    """
    try:
        find_project_root()
        project_id = get_project_id()

        async with get_services() as services:
            vault = services["vault_service"]

            notes = await vault.query(tags=[topic], limit=limit)

            if _output_mod._json_mode:
                data = [
                    {
                        "note_id": n.note_id,
                        "category": n.category.value,
                        "trust_level": n.trust_level.value,
                        "content": n.content,
                        "source": n.source,
                        "tags": n.tags,
                    }
                    for n in notes
                ]
                typer.echo(json.dumps(data, indent=2, default=str))
                return

            if not notes:
                console.print(f"[dim]No notes found for topic: {topic}[/dim]")
                return

            table = Table(title=f"Vault Notes: {topic}")
            table.add_column("ID", style="bold")
            table.add_column("Category")
            table.add_column("Trust Level")
            table.add_column("Content")

            for note in notes:
                # Truncate content to 80 chars
                content = note.content[:80] + "..." if len(note.content) > 80 else note.content
                trust_style = {
                    "verified": "[green]verified[/green]",
                    "agent-inferred": "[yellow]agent-inferred[/yellow]",
                    "stale-risk": "[red]stale-risk[/red]",
                }.get(note.trust_level.value, note.trust_level.value)

                table.add_row(
                    note.note_id,
                    note.category.value,
                    trust_style,
                    content,
                )

            console.print(table)

    except (typer.BadParameter, ValueError) as exc:
        handle_error(exc)
    except (ConnectionError, RuntimeError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)


@vault_app.command(name="write")
@run_async
async def write_vault(
    category: str = typer.Argument(
        ...,
        help="Vault category (decisions/patterns/escapes/discovery/calibration/harness/domain/stakeholders/sessions)",
    ),
    content: str = typer.Option(
        "",
        "--content",
        "-c",
        help="Note content (prompts if not provided)",
    ),
) -> None:
    """Write a new note to the knowledge vault.

    T-06-14: Notes written via CLI use trust_level=AGENT_INFERRED by default.
    Only verified content gets VERIFIED through separate review.
    """
    try:
        find_project_root()
        project_id = get_project_id()

        # Validate category
        try:
            cat_enum = VaultCategory(category.lower())
        except ValueError:
            valid = ", ".join(c.value for c in VaultCategory)
            raise typer.BadParameter(f"Invalid category: {category}. Must be one of: {valid}")

        # Prompt for content if not provided
        if not content:
            content = typer.prompt("Note content")

        async with get_services() as services:
            vault = services["vault_service"]

            # T-06-14: Default trust_level=AGENT_INFERRED
            note = await vault.write_note(
                category=cat_enum,
                content=content,
                source="cli-user",
                trust_level=VaultTrustLevel.AGENT_INFERRED,
            )

            if _output_mod._json_mode:
                data = {
                    "note_id": note.note_id,
                    "category": note.category.value,
                    "trust_level": note.trust_level.value,
                    "content": note.content,
                    "created": True,
                }
                typer.echo(json.dumps(data, indent=2, default=str))
                return

            console.print(
                f"[green]Note created:[/green] {note.note_id} in {note.category.value} ({note.trust_level.value})"
            )

    except (typer.BadParameter, ValueError) as exc:
        handle_error(exc)
    except (ConnectionError, RuntimeError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)


@vault_app.command(name="health")
@run_async
async def vault_health() -> None:
    """Check vault health: refresh indexes and show health summary.

    Runs index refresh and reports index status, note counts by
    category, and stale notes count.
    """
    try:
        find_project_root()
        project_id = get_project_id()

        async with get_services() as services:
            vault = services["vault_service"]

            # Refresh indexes
            await vault.refresh_indexes()

            # Gather health data
            health_data = {
                "index_refreshed": True,
                "categories": {},
            }

            # Query each category for counts
            for cat in VaultCategory:
                try:
                    notes = await vault.query(category=cat, limit=1000)
                    health_data["categories"][cat.value] = len(notes)
                except Exception:
                    health_data["categories"][cat.value] = 0

            # Count stale notes
            try:
                stale = await vault.query(trust_level=VaultTrustLevel.STALE_RISK, limit=1000)
                health_data["stale_notes"] = len(stale)
            except Exception:
                health_data["stale_notes"] = 0

            if _output_mod._json_mode:
                typer.echo(json.dumps(health_data, indent=2))
                return

            # Rich display
            console.print("[bold green]Index refresh: OK[/bold green]")

            table = Table(title="Vault Health Summary")
            table.add_column("Category")
            table.add_column("Notes", justify="right")

            for cat_name, count in health_data["categories"].items():
                table.add_row(cat_name, str(count))

            console.print(table)

            stale_count = health_data["stale_notes"]
            if stale_count > 0:
                console.print(f"[yellow]Stale notes (stale-risk): {stale_count}[/yellow]")
            else:
                console.print("[green]No stale notes[/green]")

    except (typer.BadParameter, ValueError) as exc:
        handle_error(exc)
    except (ConnectionError, RuntimeError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)
