"""Implementation of the ``ces triage`` command.

Pre-screens evidence and displays triage color (green/yellow/red) with
reasoning and auto-approve eligibility.

Uses the EvidenceSynthesizer.triage() method which applies the exhaustive
triage matrix (D-02) to determine evidence quality.

Exports:
    triage_evidence: Typer command function for ``ces triage``.
"""

from __future__ import annotations

import json
from typing import Any

import typer
from rich.panel import Panel

import ces.cli._output as _output_mod
from ces.cli._async import run_async
from ces.cli._builder_handoff import resolve_manifest_id
from ces.cli._builder_report import (
    load_matching_builder_run_report,
    serialize_builder_run_report,
    summarize_builder_run,
)
from ces.cli._context import find_project_root, get_project_id
from ces.cli._errors import handle_error
from ces.cli._evidence_handoff import load_persisted_evidence_view
from ces.cli._factory import get_services
from ces.cli._output import console, set_json_mode

# Color mapping for triage display
_TRIAGE_COLOR_STYLES = {
    "green": "[green]GREEN[/green]",
    "yellow": "[yellow]YELLOW[/yellow]",
    "red": "[red]RED[/red]",
}


@run_async
async def triage_evidence(
    evidence_packet_id: str | None = typer.Argument(
        None,
        help="Evidence packet ID to triage. Defaults to the current builder session evidence when omitted.",
    ),
    refresh: bool = typer.Option(
        False,
        "--refresh",
        help="Rerun sensors instead of reading the persisted evidence packet.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output triage as JSON. Equivalent to `ces --json triage`.",
    ),
) -> None:
    """Pre-screen evidence and display triage color.

    Shows the triage color (green/yellow/red), reasoning, and
    whether the evidence is eligible for auto-approval.
    """
    if json_output:
        set_json_mode(True)
    try:
        find_project_root()
        project_id = get_project_id()

        async with get_services() as services:
            manager = services["manifest_manager"]
            evidence_synthesizer = services["evidence_synthesizer"]
            local_store = services.get("local_store")
            resolved_manifest_id, handoff_context = resolve_manifest_id(
                provided_ref=evidence_packet_id,
                local_store=local_store,
                missing_message=("Evidence packet ID is required when CES cannot resolve a current builder session."),
            )
            resolved_evidence_packet_id = (
                evidence_packet_id
                or (handoff_context.evidence_packet_id if handoff_context is not None else None)
                or resolved_manifest_id
            )
            builder_run = load_matching_builder_run_report(
                local_store,
                manifest_id=resolved_manifest_id,
            )

            persisted_evidence = None
            if not refresh:
                persisted_evidence = load_persisted_evidence_view(
                    local_store=local_store,
                    manifest_id=resolved_manifest_id,
                    evidence_packet_id=resolved_evidence_packet_id,
                )
            if persisted_evidence is not None:
                color_value = persisted_evidence.triage_color
                data = {
                    "evidence_packet_id": persisted_evidence.packet_id or resolved_evidence_packet_id,
                    "manifest_id": persisted_evidence.manifest_id,
                    "color": color_value,
                    "risk_tier": "unknown",
                    "trust_status": "unknown",
                    "sensor_pass_rate": None,
                    "reason": persisted_evidence.reason,
                    "auto_approve_eligible": False,
                    "source": "persisted",
                }
                if builder_run is not None:
                    data["builder_run"] = serialize_builder_run_report(builder_run)
                if _output_mod._json_mode:
                    typer.echo(json.dumps(data, indent=2))
                    return

                color_display = _TRIAGE_COLOR_STYLES.get(color_value, f"[bold]{color_value.upper()}[/bold]")
                content_lines = [
                    f"Triage Color: {color_display}",
                    f"Reasoning: {data['reason']}",
                    "Source: persisted evidence packet",
                ]
                if builder_run is not None:
                    content_lines.extend(["", *summarize_builder_run(builder_run)])
                console.print(
                    Panel(
                        "\n".join(content_lines),
                        title=f"Triage Result: {color_display}",
                        border_style=color_value if color_value in ("green", "yellow", "red") else "white",
                    )
                )
                return

            # Look up evidence packet and associated manifest
            manifest = await manager.get_manifest(resolved_manifest_id)
            if manifest is None:
                raise typer.BadParameter(f"Evidence packet not found: {resolved_evidence_packet_id}")

            # Get triage attributes from manifest
            risk_tier = manifest.risk_tier
            trust_status = getattr(manifest, "trust_status", None)
            if trust_status is None:
                from ces.shared.enums import TrustStatus

                trust_status = TrustStatus.CANDIDATE

            # Run sensors for triage input (EVID-05 fix)
            sensor_orchestrator = services["sensor_orchestrator"]
            project_root = find_project_root()
            sensor_context = {
                "manifest_id": resolved_manifest_id,
                "risk_tier": risk_tier.value if hasattr(risk_tier, "value") else str(risk_tier),
                "affected_files": getattr(manifest, "affected_files", []) or [],
                "project_root": str(project_root),
                "description": getattr(manifest, "description", ""),
                "change_class": str(getattr(manifest.change_class, "value", ""))
                if hasattr(manifest, "change_class")
                else "",
            }
            pack_results = await sensor_orchestrator.run_all(sensor_context)
            sensor_results: list = []
            for pack in pack_results:
                sensor_results.extend(pack.results)

            # Run triage
            triage_result = await evidence_synthesizer.triage(
                risk_tier=risk_tier,
                trust_status=trust_status,
                sensor_results=sensor_results,
            )

            # JSON mode
            if _output_mod._json_mode:
                live_data: dict[str, Any] = {
                    "evidence_packet_id": resolved_evidence_packet_id,
                    "color": triage_result.color.value,
                    "risk_tier": triage_result.risk_tier.value,
                    "trust_status": triage_result.trust_status.value,
                    "sensor_pass_rate": triage_result.sensor_pass_rate,
                    "reason": triage_result.reason,
                    "auto_approve_eligible": triage_result.auto_approve_eligible,
                }
                if builder_run is not None:
                    live_data["builder_run"] = serialize_builder_run_report(builder_run)
                typer.echo(json.dumps(live_data, indent=2))
                return

            # Rich mode: display triage result
            color_value = triage_result.color.value
            color_display = _TRIAGE_COLOR_STYLES.get(color_value, f"[bold]{color_value.upper()}[/bold]")

            content_lines = [
                f"Triage Color: {color_display}",
                f"Reasoning: {triage_result.reason}",
                f"Auto-approve eligible: {triage_result.auto_approve_eligible}",
            ]

            if triage_result.auto_approve_eligible:
                content_lines.append("\n[dim]This evidence is eligible for auto-approval (Tier C/BC1/Trusted)[/dim]")
            if builder_run is not None:
                content_lines.extend(["", *summarize_builder_run(builder_run)])

            console.print(
                Panel(
                    "\n".join(content_lines),
                    title=f"Triage Result: {color_display}",
                    border_style=color_value if color_value in ("green", "yellow", "red") else "white",
                )
            )

    except (typer.BadParameter, ValueError) as exc:
        handle_error(exc)
    except (ConnectionError, RuntimeError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)
