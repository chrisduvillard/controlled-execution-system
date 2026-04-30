"""Rich and JSON output helpers for CES CLI.

Provides a global toggle between Rich (human-friendly) and JSON
(machine-friendly) output modes.  All CLI commands use these helpers
so the --json flag works consistently.

Exports:
    console: Rich Console instance for direct use.
    set_json_mode: Toggle between Rich and JSON output.
    output_table: Render a table (Rich Table or JSON array).
    output_dict: Render a dict (Rich Panel or JSON object).
"""

from __future__ import annotations

import json
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

_json_mode: bool = False


def set_json_mode(enabled: bool) -> None:
    """Toggle JSON output mode globally.

    When enabled, output_table and output_dict emit JSON to stdout.
    When disabled, they render Rich tables and panels to the console.

    Args:
        enabled: True for JSON output, False for Rich output.
    """
    global _json_mode  # noqa: PLW0603
    _json_mode = enabled


def is_json_mode() -> bool:
    """Return True when the CLI has been switched to JSON output mode."""
    return _json_mode


def output_table(
    title: str,
    columns: list[str],
    rows: list[list[str]],
) -> None:
    """Render a table as either a Rich Table or JSON array.

    In JSON mode, each row becomes a dict keyed by column names.

    Args:
        title: Table title (used in Rich mode).
        columns: Column header names.
        rows: List of row data (each row is a list of strings).
    """
    if _json_mode:
        data = [dict(zip(columns, row)) for row in rows]
        typer.echo(json.dumps(data, indent=2))
        return

    table = Table(title=title)
    for col in columns:
        table.add_column(col)
    for row in rows:
        table.add_row(*row)
    console.print(table)


def output_dict(data: dict[str, Any], title: str = "") -> None:
    """Render a dict as either a Rich Panel or JSON object.

    In JSON mode, the dict is printed as a JSON object.
    In Rich mode, key-value pairs are displayed in a Panel.

    Args:
        data: Dictionary to display.
        title: Panel title (used in Rich mode).
    """
    if _json_mode:
        typer.echo(json.dumps(data, indent=2, default=str))
        return

    lines = [f"[bold]{k}:[/bold] {v}" for k, v in data.items()]
    content = "\n".join(lines) if lines else "(empty)"
    console.print(Panel(content, title=title or "Details"))
