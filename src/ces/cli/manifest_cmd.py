"""Implementation of the ``ces manifest`` command.

Generates a task manifest from a natural language description by:
1. Using ClassificationOracle to classify the description (risk, confidence, change class)
2. Displaying proposed manifest fields for user confirmation
3. Persisting via ManifestManager on approval

The LLM provider is used by ClassificationOracle internally for NL parsing.
The manifest_cmd only calls oracle.classify() for classification and then
ManifestManager.create_manifest() to persist.

Exports:
    create_manifest: Typer command function for ``ces manifest``.
"""

from __future__ import annotations

import typer

from ces.cli._async import run_async
from ces.cli._context import find_project_root, get_project_config
from ces.cli._errors import handle_error
from ces.cli._factory import get_services
from ces.cli._output import console, output_dict
from ces.cli.ownership import resolve_actor
from ces.shared.enums import BehaviorConfidence, ChangeClass, RiskTier

# Default values for manifest fields not yet specified by the user
_DEFAULT_TOKEN_BUDGET = 100_000


@run_async
async def create_manifest(
    description: str = typer.Argument(
        ...,
        help="Natural language task description",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt",
    ),
    auto: bool = typer.Option(
        False,
        "--auto",
        help="Auto-generate manifest from truth artifacts via LLM",
    ),
    runtime: str = typer.Option(
        "auto",
        "--runtime",
        help="Runtime for local auto-generation: auto, codex, or claude",
    ),
    acceptance_criterion: list[str] = typer.Option(
        [],
        "--acceptance-criterion",
        help=(
            "Repeatable. Concrete done-when statement the agent must address "
            "with evidence in its ces:completion block. Each invocation adds one."
        ),
    ),
    verification_sensor: list[str] = typer.Option(
        [],
        "--verification-sensor",
        help=(
            "Repeatable. Sensor IDs the Completion Gate must pass: "
            "test_pass, lint, typecheck, coverage. Each invocation adds one. "
            "Empty list = no gate (legacy direct-to-review path)."
        ),
    ),
) -> None:
    """Generate a task manifest from a natural language description.

    Uses the classification oracle to determine risk tier, behavior
    confidence, and change class from the description.  Shows the
    proposed manifest for confirmation before saving.

    With ``--auto``, uses the configured local runtime to propose a
    manifest draft before human confirmation.
    """
    try:
        # Verify CES project root and get project context
        find_project_root()
        project_config = get_project_config()

        async with get_services() as services:
            manager = services["manifest_manager"]
            actor = resolve_actor()

            if auto:
                runtime_registry = services["runtime_registry"]
                settings = services["settings"]
                runtime_adapter = runtime_registry.resolve_runtime(
                    runtime_name=runtime,
                    preferred_runtime=project_config.get("preferred_runtime")
                    or getattr(settings, "default_runtime", "codex"),
                )
                proposal = runtime_adapter.generate_manifest_assist({}, description)
                risk_tier = RiskTier(proposal.get("risk_tier", RiskTier.B.value))
                behavior_confidence = BehaviorConfidence(
                    proposal.get("behavior_confidence", BehaviorConfidence.BC2.value)
                )
                change_class = ChangeClass(proposal.get("change_class", ChangeClass.CLASS_2.value))
                affected_files = proposal.get("affected_files", [])
                token_budget = proposal.get("token_budget", _DEFAULT_TOKEN_BUDGET)

                manifest_data = {
                    "description": proposal.get("description", description),
                    "risk_tier": risk_tier.value,
                    "behavior_confidence": behavior_confidence.value,
                    "change_class": change_class.value,
                    "affected_files": ", ".join(affected_files) or "(none)",
                    "token_budget": token_budget,
                    "reasoning": proposal.get("reasoning", ""),
                    "runtime": runtime_adapter.runtime_name,
                    "status": "LOCAL DRAFT (requires human review)",
                }
                output_dict(manifest_data, title="Auto-Generated Manifest Proposal")

                if not yes:
                    typer.confirm("Save this manifest?", abort=True)

                manifest = await manager.create_manifest(
                    description=proposal.get("description", description),
                    risk_tier=risk_tier,
                    behavior_confidence=behavior_confidence,
                    change_class=change_class,
                    affected_files=affected_files,
                    token_budget=token_budget,
                    owner=actor,
                    acceptance_criteria=acceptance_criterion or None,
                    verification_sensors=verification_sensor or None,
                )
            else:
                # Standard path: use ClassificationOracle
                oracle = services.get("classification_oracle")

                # Classify the description via oracle
                result = oracle.classify(description)
                matched = result.matched_rule

                # Determine classification values
                if matched is not None:
                    risk_tier = matched.risk_tier
                    behavior_confidence = matched.behavior_confidence
                    change_class = matched.change_class
                else:
                    # Fallback defaults when oracle has no confident match
                    risk_tier = RiskTier.A
                    behavior_confidence = BehaviorConfidence.BC3
                    change_class = ChangeClass.CLASS_5

                # Format confidence display
                confidence_pct = f"{result.confidence * 100:.0f}%"
                action_display = result.action.replace("_", " ").title()

                # Prepare manifest data for display
                manifest_data = {
                    "description": description,
                    "risk_tier": risk_tier.value,
                    "behavior_confidence": behavior_confidence.value,
                    "change_class": change_class.value,
                    "confidence": confidence_pct,
                    "action": action_display,
                    "reasoning": (
                        f"Best match: {matched.description}"
                        if matched
                        else "No confident match - using highest risk defaults"
                    ),
                    "token_budget": _DEFAULT_TOKEN_BUDGET,
                    "owner": actor,
                }

                # Display proposed manifest
                output_dict(manifest_data, title="Proposed Manifest")

                # Confirmation prompt (skipped with --yes)
                if not yes:
                    typer.confirm("Save this manifest?", abort=True)

                # Create and save the manifest
                manifest = await manager.create_manifest(
                    description=description,
                    risk_tier=risk_tier,
                    behavior_confidence=behavior_confidence,
                    change_class=change_class,
                    affected_files=[],
                    token_budget=_DEFAULT_TOKEN_BUDGET,
                    owner=actor,
                    acceptance_criteria=acceptance_criterion or None,
                    verification_sensors=verification_sensor or None,
                )

            # Display saved manifest info
            saved_data = {
                "manifest_id": manifest.manifest_id,
                "description": manifest.description,
                "risk_tier": manifest.risk_tier.value
                if hasattr(manifest.risk_tier, "value")
                else str(manifest.risk_tier),
                "behavior_confidence": manifest.behavior_confidence.value
                if hasattr(manifest.behavior_confidence, "value")
                else str(manifest.behavior_confidence),
                "change_class": manifest.change_class.value
                if hasattr(manifest.change_class, "value")
                else str(manifest.change_class),
                "token_budget": manifest.token_budget,
                "owner": manifest.owner,
                "acceptance_criteria": list(manifest.acceptance_criteria) if manifest.acceptance_criteria else "(none)",
                "verification_sensors": list(manifest.verification_sensors)
                if manifest.verification_sensors
                else "(none — legacy direct-to-review path)",
            }
            output_dict(saved_data, title="Manifest Saved")

    except typer.Abort:
        console.print("[yellow]Manifest discarded.[/yellow]")
        raise typer.Exit(code=0)
    except (typer.BadParameter, ValueError) as exc:
        handle_error(exc)
    except (ConnectionError, RuntimeError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)
