"""Shared helpers for completion contract generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ces.verification.command_inference import infer_verification_commands
from ces.verification.completion_contract import CompletionContract, criteria_from_texts
from ces.verification.project_detector import detect_project_type


def build_completion_contract(
    *,
    project_root: Path,
    request: str,
    acceptance_criteria: list[str] | tuple[str, ...],
    runtime_name: str,
    runtime_metadata: dict[str, Any] | None = None,
) -> CompletionContract:
    project_type = detect_project_type(project_root)
    runtime = {"name": runtime_name}
    if runtime_metadata:
        runtime.update(runtime_metadata)
    return CompletionContract(
        request=request,
        project_type=project_type,
        acceptance_criteria=criteria_from_texts(acceptance_criteria),
        inferred_commands=infer_verification_commands(
            project_root, project_type, acceptance_criteria=acceptance_criteria
        ),
        runtime=runtime,
    )


def write_completion_contract(
    *,
    project_root: Path,
    request: str,
    acceptance_criteria: list[str] | tuple[str, ...],
    runtime_name: str,
    runtime_metadata: dict[str, Any] | None = None,
) -> Path:
    contract = build_completion_contract(
        project_root=project_root,
        request=request,
        acceptance_criteria=acceptance_criteria,
        runtime_name=runtime_name,
        runtime_metadata=runtime_metadata,
    )
    path = project_root / ".ces" / "completion-contract.json"
    contract.write(path)
    return path
