"""Shared helpers for completion contract generation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from ces.verification.command_inference import infer_verification_commands
from ces.verification.completion_contract import (
    BehaviorDelta,
    CompletionContract,
    RiskTrack,
    criteria_from_texts,
    infer_risk_track,
)
from ces.verification.project_detector import detect_project_type
from ces.verification.proof_binding import proof_binding_hash

GREENFIELD_REQUIRED_ARTIFACTS = ("README.md", "run command", "test command", "verification evidence")
GREENFIELD_PROOF_REQUIREMENTS = (
    "README documents how to run the project locally",
    "README documents how to test or verify the project",
    "Completion evidence lists commands run and their outcomes",
    "Document unproven areas or remaining risks",
)


def build_completion_contract(
    *,
    project_root: Path,
    request: str,
    acceptance_criteria: list[str] | tuple[str, ...],
    runtime_name: str,
    runtime_metadata: dict[str, Any] | None = None,
    behavior_delta: BehaviorDelta | None = None,
    risk_track: RiskTrack | None = None,
) -> CompletionContract:
    project_type = detect_project_type(project_root)
    runtime = {"name": runtime_name}
    if runtime_metadata:
        runtime.update(runtime_metadata)
    delta = behavior_delta or BehaviorDelta()
    contract = CompletionContract(
        request=request,
        project_type=project_type,
        acceptance_criteria=criteria_from_texts(acceptance_criteria),
        inferred_commands=infer_verification_commands(
            project_root, project_type, acceptance_criteria=acceptance_criteria
        ),
        runtime=runtime,
        required_artifacts=GREENFIELD_REQUIRED_ARTIFACTS,
        proof_requirements=GREENFIELD_PROOF_REQUIREMENTS,
        behavior_delta=delta,
        risk_track=risk_track or infer_risk_track(delta),
        next_ces_command="ces verify --json",
    )
    return replace(contract, proof_binding_hash=proof_binding_hash(contract))


def write_completion_contract(
    *,
    project_root: Path,
    request: str,
    acceptance_criteria: list[str] | tuple[str, ...],
    runtime_name: str,
    runtime_metadata: dict[str, Any] | None = None,
    behavior_delta: BehaviorDelta | None = None,
    risk_track: RiskTrack | None = None,
) -> Path:
    contract = build_completion_contract(
        project_root=project_root,
        request=request,
        acceptance_criteria=acceptance_criteria,
        runtime_name=runtime_name,
        runtime_metadata=runtime_metadata,
        behavior_delta=behavior_delta,
        risk_track=risk_track,
    )
    path = project_root / ".ces" / "completion-contract.json"
    contract.write(path)
    return path
