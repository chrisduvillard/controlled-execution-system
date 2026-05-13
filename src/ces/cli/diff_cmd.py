"""Diff helpers for reviewing drift since captured evidence baselines."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import typer
from rich.panel import Panel

from ces.cli._async import run_async
from ces.cli._context import find_project_root
from ces.cli._errors import handle_error
from ces.cli._factory import get_services
from ces.cli._output import console


def _latest_git_head_from_evidence(packet: dict[str, Any] | None) -> str | None:
    if not packet:
        return None
    git = packet.get("git")
    if isinstance(git, dict):
        head = git.get("head")
        if isinstance(head, str) and head.strip():
            return head.strip()
    return None


def _run_git_diff(project_root: Path, baseline: str | None) -> str:
    args = ["git", "diff", "--name-status"]
    if baseline:
        args.append(baseline)
    # Arguments are fixed git subcommands plus a stored commit hash; shell=False.
    result = subprocess.run(  # noqa: S603
        args,
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git diff failed")
    return result.stdout.strip() or "(no changes)"


@run_async
async def show_diff(
    since_approval: bool = typer.Option(
        False,
        "--since-approval",
        help="Diff against the git HEAD captured in the latest evidence/approval packet.",
    ),
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        help="Repo/CES project root to operate on; defaults to cwd/.ces discovery.",
    ),
) -> None:
    """Show changed files, optionally since the latest reviewed evidence baseline."""
    try:
        resolved_project_root = find_project_root(project_root)
        baseline: str | None = None
        packet_id = "(none)"
        manifest_id = "(none)"
        if since_approval:
            async with get_services(project_root=resolved_project_root) as services:
                packet = services["local_store"].get_latest_evidence_packet()
            baseline = _latest_git_head_from_evidence(packet)
            if not baseline:
                raise RuntimeError(
                    "No git baseline found in the latest evidence packet; attach evidence with CES v0.1.19+ "
                    "or run without --since-approval."
                )
            packet_id = str(packet.get("packet_id", "(unknown)")) if packet else "(unknown)"
            manifest_id = str(packet.get("manifest_id", "(unknown)")) if packet else "(unknown)"
        diff = _run_git_diff(resolved_project_root, baseline)
        title = "[cyan]Diff Since Approval[/cyan]" if since_approval else "[cyan]Working Tree Diff[/cyan]"
        prefix = ""
        if since_approval:
            prefix = f"Baseline packet: {packet_id}\nManifest: {manifest_id}\nBaseline HEAD: {baseline}\n\n"
        console.print(Panel(prefix + diff, title=title, border_style="cyan"))
    except (RuntimeError, OSError, ValueError) as exc:
        handle_error(exc)
