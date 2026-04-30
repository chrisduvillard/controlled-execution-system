"""Implementation of the ``ces classify`` command.

Classifies an existing task manifest by ID using the ClassificationOracle.
Displays the classification result with color-coded confidence scores:
- Green (>90%): auto-accept
- Yellow (70-90%): human review needed
- Red (<70%): escalate to full human classification

Exports:
    classify_task: Typer command function for ``ces classify``.
"""

from __future__ import annotations

import typer

import ces.cli._output as _output_mod
from ces.cli._async import run_async
from ces.cli._context import find_project_root, get_project_id
from ces.cli._errors import handle_error
from ces.cli._factory import get_services
from ces.cli._output import output_dict, output_table


def _confidence_display(confidence: float) -> str:
    """Format confidence as a color-coded percentage string for Rich output.

    Args:
        confidence: Confidence score between 0.0 and 1.0.

    Returns:
        Rich markup string with color-coded percentage.
    """
    pct = f"{confidence * 100:.0f}%"
    if confidence >= 0.90:
        return f"[green]{pct}[/green]"
    elif confidence >= 0.70:
        return f"[yellow]{pct}[/yellow]"
    else:
        return f"[red]{pct}[/red]"


@run_async
async def classify_task(
    manifest_id: str = typer.Argument(
        ...,
        help="Manifest ID to classify",
    ),
) -> None:
    """Classify a task manifest and display the classification result.

    Shows risk tier, behavior confidence, change class, confidence score
    (color-coded), recommended action, and reasoning.
    """
    try:
        # Verify CES project root
        find_project_root()
        project_id = get_project_id()

        async with get_services() as services:
            oracle = services.get("classification_oracle")
            manager = services["manifest_manager"]

            # Look up the manifest
            manifest = await manager.get_manifest(manifest_id)
            if manifest is None:
                raise typer.BadParameter(f"Manifest not found: {manifest_id}")

            # Classify via oracle
            result = oracle.classify(manifest.description)
            matched = result.matched_rule

            # Build classification data
            if matched is not None:
                risk_tier = matched.risk_tier.value
                behavior_confidence = matched.behavior_confidence.value
                change_class = matched.change_class.value
            else:
                risk_tier = "Unknown"
                behavior_confidence = "Unknown"
                change_class = "Unknown"

            confidence_pct = f"{result.confidence * 100:.0f}%"
            action_display = result.action.replace("_", " ").title()
            reasoning = f"Best match: {matched.description}" if matched else "No confident match found"

            # Build classification data dict for JSON mode
            classification_data = {
                "manifest_id": manifest_id,
                "risk_tier": risk_tier,
                "behavior_confidence": behavior_confidence,
                "change_class": change_class,
                "confidence": confidence_pct,
                "action": action_display,
                "reasoning": reasoning,
            }

            # Use output_dict for JSON mode (flat dict), output_table for Rich
            if _output_mod._json_mode:
                output_dict(classification_data, title="Classification Result")
            else:
                output_table(
                    title="Classification Result",
                    columns=["Field", "Value"],
                    rows=[
                        ["Manifest ID", manifest_id],
                        ["Risk Tier", risk_tier],
                        ["Behavior Confidence", behavior_confidence],
                        ["Change Class", change_class],
                        ["Confidence", _confidence_display(result.confidence)],
                        ["Action", action_display],
                        ["Reasoning", reasoning],
                    ],
                )

    except (typer.BadParameter, ValueError) as exc:
        handle_error(exc)
    except (ConnectionError, RuntimeError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)
