"""Tests for completion contract JSON model."""

from __future__ import annotations

from pathlib import Path


def test_completion_contract_roundtrips_json(tmp_path: Path) -> None:
    from ces.verification.completion_contract import (
        AcceptanceCriterion,
        CompletionContract,
        VerificationCommand,
    )

    contract = CompletionContract(
        request="Build PromptVault",
        project_type="python-cli",
        acceptance_criteria=(AcceptanceCriterion(id="AC-001", text="CLI lists prompts"),),
        inferred_commands=(VerificationCommand(id="VC-001", kind="test", command="python -m pytest -q"),),
        runtime={"name": "codex", "sandbox": "danger-full-access"},
    )
    path = tmp_path / ".ces" / "completion-contract.json"

    contract.write(path)
    loaded = CompletionContract.read(path)

    assert loaded.version == 1
    assert loaded.request == "Build PromptVault"
    assert loaded.acceptance_criteria[0].id == "AC-001"
    assert loaded.inferred_commands[0].command == "python -m pytest -q"
    assert loaded.runtime["name"] == "codex"
