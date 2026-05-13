"""First-class evidence attachment commands."""

from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer
from rich.panel import Panel

from ces.cli._async import run_async
from ces.cli._context import find_project_root
from ces.cli._errors import handle_error
from ces.cli._factory import get_services
from ces.cli._output import console
from ces.execution.secrets import scrub_secrets_from_text

MAX_ATTACHED_EVIDENCE_BYTES = 1_048_576
TRUNCATED_ATTACHED_EVIDENCE_MARKER = "\n...[truncated attached evidence]"

evidence_app = typer.Typer(help="Attach and inspect CES evidence packets.")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve_evidence_file(path: Path, project_root: Path, *, allow_external: bool) -> Path:
    resolved = path.resolve()
    if not resolved.exists():
        raise typer.BadParameter(f"Evidence file does not exist: {resolved}")
    if not resolved.is_file():
        raise typer.BadParameter(f"Evidence path must be a file: {resolved}")
    resolved_project_root = project_root.resolve()
    if not allow_external and not _is_relative_to(resolved, resolved_project_root):
        raise typer.BadParameter(
            "Evidence file is outside the CES project root; re-run with --allow-external-evidence "
            "only if you intentionally want to attach that file."
        )
    return resolved


def _read_attached_file(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    truncated = len(raw) > MAX_ATTACHED_EVIDENCE_BYTES
    text = raw[:MAX_ATTACHED_EVIDENCE_BYTES].decode("utf-8", errors="replace")
    text = scrub_secrets_from_text(text)
    if truncated:
        text += TRUNCATED_ATTACHED_EVIDENCE_MARKER
    return {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "bytes_read": min(len(raw), MAX_ATTACHED_EVIDENCE_BYTES),
        "truncated": truncated,
        "text": text,
    }


def _git_value(project_root: Path, *args: str) -> str | None:
    try:
        # Arguments are fixed git subcommands used for read-only provenance; shell=False.
        result = subprocess.run(  # noqa: S603
            ["git", *args],  # noqa: S607
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _git_provenance(project_root: Path) -> dict[str, Any]:
    status = _git_value(project_root, "status", "--short")
    return {
        "head": _git_value(project_root, "rev-parse", "HEAD"),
        "branch": _git_value(project_root, "branch", "--show-current"),
        "dirty": bool(status),
        "status_short": status or "",
    }


def _command_provenance(commands: list[str], project_root: Path) -> list[dict[str, Any]]:
    return [
        {
            "command": command,
            "cwd": str(project_root),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "exit_code": None,
            "note": "Command provenance was operator-attached; CES did not execute this command.",
        }
        for command in commands
    ]


@evidence_app.command(name="attach", help="Attach scrubbed manual evidence to a manifest with command provenance.")
@run_async
async def attach_evidence(
    manifest_id: str = typer.Option(
        ...,
        "--manifest-id",
        "-m",
        help="Manifest id to attach evidence to.",
    ),
    evidence_file: list[Path] = typer.Option(
        [],
        "--file",
        "-f",
        help="Evidence file to attach. Repeatable. Files are scrubbed and capped before persistence.",
    ),
    command: list[str] = typer.Option(
        [],
        "--command",
        "-c",
        help="Verification command to record as provenance. Repeatable; CES records but does not execute it.",
    ),
    summary: str = typer.Option(
        "Manual evidence attached by operator.",
        "--summary",
        help="Human-readable evidence summary.",
    ),
    challenge: str = typer.Option(
        "Manual evidence attachment; rerun recorded commands or inspect attached files for verification.",
        "--challenge",
        help="Skeptical reviewer challenge / verification prompt.",
    ),
    triage_color: str = typer.Option(
        "green",
        "--triage-color",
        help="Evidence triage color to persist: green, yellow, or red.",
    ),
    allow_external_evidence: bool = typer.Option(
        False,
        "--allow-external-evidence",
        help="Allow --file paths outside the CES project root after explicit operator review.",
    ),
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Repo/CES project root to operate on; defaults to cwd/.ces discovery.",
    ),
) -> None:
    """Attach manual evidence without using the lower-level completion flow."""
    try:
        if not evidence_file and not command:
            raise typer.BadParameter("Provide at least one --file or --command.")
        if triage_color not in {"green", "yellow", "red"}:
            raise typer.BadParameter("--triage-color must be one of: green, yellow, red.")
        resolved_project_root = find_project_root(project_root)
        files = [
            _read_attached_file(
                _resolve_evidence_file(path, resolved_project_root, allow_external=allow_external_evidence)
            )
            for path in evidence_file
        ]
        packet_id = f"EP-manual-{uuid.uuid4().hex[:12]}"
        content = {
            "manual_attachment": True,
            "attached_at": datetime.now(timezone.utc).isoformat(),
            "manifest_id": manifest_id,
            "packet_id": packet_id,
            "summary": summary,
            "challenge": challenge,
            "triage_color": triage_color,
            "evidence_files": files,
            "command_provenance": _command_provenance(command, resolved_project_root),
            "git": _git_provenance(resolved_project_root),
        }
        async with get_services(project_root=resolved_project_root) as services:
            services["local_store"].save_evidence(
                manifest_id,
                packet_id=packet_id,
                summary=summary,
                challenge=challenge,
                triage_color=triage_color,
                content=json.loads(json.dumps(content)),
            )
        console.print(
            Panel(
                f"Evidence packet: {packet_id}\n"
                f"Manifest: {manifest_id}\n"
                f"Files: {len(files)}\n"
                f"Commands recorded: {len(command)}",
                title="[green]Evidence Attached[/green]",
                border_style="green",
            )
        )
    except (typer.BadParameter, ValueError, RuntimeError, OSError) as exc:
        handle_error(exc)
