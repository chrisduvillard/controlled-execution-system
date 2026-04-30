"""Implementation of the ``ces gate`` command.

Evaluates a phase gate and displays gate type (AGENT/HYBRID/HUMAN),
pass/fail result, confidence, and meta-review/hidden check indicators.

Supports --risk-tier, --bc, --trust-status options for specifying
classification context. Uses GateEvaluator.evaluate() from the
control plane (deterministic -- no LLM calls).

Exports:
    evaluate_gate: Typer command function for ``ces gate``.
"""

from __future__ import annotations

import json

import typer
from rich.panel import Panel

import ces.cli._output as _output_mod
from ces.cli._async import run_async
from ces.cli._context import find_project_root, get_project_id
from ces.cli._errors import handle_error
from ces.cli._factory import get_services
from ces.cli._output import console
from ces.shared.enums import (
    BehaviorConfidence,
    RiskTier,
    TrustStatus,
)


def _gate_type_style(gate_type: str) -> str:
    """Return a Rich-styled gate type string.

    Args:
        gate_type: Gate type value (agent/hybrid/human).

    Returns:
        Color-coded Rich markup string.
    """
    styles = {
        "agent": "[green]AGENT[/green]",
        "hybrid": "[yellow]HYBRID[/yellow]",
        "human": "[red]HUMAN[/red]",
    }
    return styles.get(gate_type, gate_type.upper())


@run_async
async def evaluate_gate(
    phase: int = typer.Argument(
        ...,
        help="Phase number (1-10)",
    ),
    scope: str = typer.Argument(
        ...,
        help="Scope identifier for the gate evaluation",
    ),
    risk_tier: str = typer.Option(
        "B",
        "--risk-tier",
        "-r",
        help="Risk tier (A/B/C)",
    ),
    bc: str = typer.Option(
        "BC1",
        "--bc",
        help="Behavior confidence (BC1/BC2/BC3)",
    ),
    trust_status: str = typer.Option(
        "candidate",
        "--trust-status",
        "-t",
        help="Trust status (candidate/trusted/watch/constrained)",
    ),
    confidence: float = typer.Option(
        0.95,
        "--confidence",
        help="Oracle confidence score (0.0-1.0)",
    ),
) -> None:
    """Evaluate a phase gate and display the gate type and result.

    Shows the gate type (AGENT/HYBRID/HUMAN), whether the gate is passed,
    confidence score used, and meta-review/hidden check indicators.
    """
    try:
        find_project_root()
        project_id = get_project_id()

        # Convert string options to enum values
        try:
            risk_tier_enum = RiskTier(risk_tier.upper())
        except ValueError:
            raise typer.BadParameter(f"Invalid risk tier: {risk_tier}. Must be A, B, or C.")

        try:
            bc_enum = BehaviorConfidence(bc.upper())
        except ValueError:
            raise typer.BadParameter(f"Invalid behavior confidence: {bc}. Must be BC1, BC2, or BC3.")

        try:
            trust_status_enum = TrustStatus(trust_status.lower())
        except ValueError:
            raise typer.BadParameter(
                f"Invalid trust status: {trust_status}. Must be candidate, trusted, watch, or constrained."
            )

        async with get_services() as services:
            evaluator = services["gate_evaluator"]

            # GateEvaluator.evaluate() is synchronous
            result = evaluator.evaluate(
                phase=phase,
                risk_tier=risk_tier_enum,
                bc=bc_enum,
                trust_status=trust_status_enum,
                oracle_confidence=confidence,
                profile_id=scope,
            )

            # Build result data
            data = {
                "gate_type": result.gate_type.value,
                "base_gate_type": result.base_gate_type.value,
                "phase": result.phase,
                "risk_tier": result.risk_tier.value,
                "behavior_confidence": result.behavior_confidence.value,
                "trust_status": result.trust_status.value,
                "confidence": result.confidence_used,
                "meta_review_selected": result.meta_review_selected,
                "hidden_check": result.hidden_check,
            }

            if _output_mod._json_mode:
                typer.echo(json.dumps(data, indent=2))
                return

            # Rich display
            gate_display = _gate_type_style(result.gate_type.value)
            base_display = _gate_type_style(result.base_gate_type.value)

            content_lines = [
                f"Gate Type: {gate_display}",
                f"Base Gate Type: {base_display}",
                f"Phase: {result.phase}",
                f"Risk Tier: {result.risk_tier.value}",
                f"Behavior Confidence: {result.behavior_confidence.value}",
                f"Trust Status: {result.trust_status.value}",
                f"Confidence: {result.confidence_used:.0%}",
            ]

            if result.meta_review_selected:
                content_lines.append("[bold yellow]Meta-review: SELECTED[/bold yellow]")
            else:
                content_lines.append("Meta-review: not selected")

            if result.hidden_check:
                content_lines.append("[bold red]Hidden Check: INJECTED[/bold red]")

            console.print(
                Panel(
                    "\n".join(content_lines),
                    title=f"Gate Evaluation: Phase {result.phase}",
                    border_style="blue",
                )
            )

    except (typer.BadParameter, ValueError) as exc:
        handle_error(exc)
    except (ConnectionError, RuntimeError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)
