"""Shared helpers for completion contract generation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from ces.verification.command_inference import infer_verification_commands
from ces.verification.completion_contract import (
    BehaviorDelta,
    CompletionContract,
    OfficialEvaluator,
    ProtectedSurface,
    RealityBoundaryContract,
    RiskTrack,
    SuccessPredicate,
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
    acceptance = criteria_from_texts(acceptance_criteria)
    inferred_commands = infer_verification_commands(project_root, project_type, acceptance_criteria=acceptance_criteria)
    reality_boundary = _build_reality_boundary_contract(
        acceptance_criteria=acceptance,
        inferred_commands=inferred_commands,
        required_artifacts=GREENFIELD_REQUIRED_ARTIFACTS,
    )
    contract = CompletionContract(
        request=request,
        project_type=project_type,
        acceptance_criteria=acceptance,
        inferred_commands=inferred_commands,
        runtime=runtime,
        required_artifacts=GREENFIELD_REQUIRED_ARTIFACTS,
        proof_requirements=GREENFIELD_PROOF_REQUIREMENTS,
        behavior_delta=delta,
        risk_track=risk_track or infer_risk_track(delta),
        reality_boundary=reality_boundary,
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


def _build_reality_boundary_contract(
    *,
    acceptance_criteria: tuple,
    inferred_commands: tuple,
    required_artifacts: tuple[str, ...],
) -> RealityBoundaryContract:
    success_predicates = tuple(
        SuccessPredicate(id=criterion.id, text=criterion.text, source="acceptance_criterion")
        for criterion in acceptance_criteria
    )
    official_evaluators = tuple(
        OfficialEvaluator(
            id=command.id,
            command_id=command.id,
            kind=command.kind,
            command=command.command,
            required=command.required,
            cwd=command.cwd,
            timeout_seconds=command.timeout_seconds,
            expected_exit_codes=command.expected_exit_codes,
        )
        for command in inferred_commands
    )
    protected_surfaces = tuple(
        ProtectedSurface(path=path, reason="required completion artifact") for path in required_artifacts
    ) + tuple(
        ProtectedSurface(path=command.cwd, reason=f"official evaluator cwd for {command.id}")
        for command in inferred_commands
        if command.cwd and command.cwd != "."
    )
    return RealityBoundaryContract(
        success_predicates=success_predicates,
        official_evaluators=official_evaluators,
        protected_surfaces=protected_surfaces,
        mutable_test_policy="warn",
        denied_test_paths=("tests/regression/", "benchmarks/", ".ces/contracts/"),
    ).with_predicate_hash()
