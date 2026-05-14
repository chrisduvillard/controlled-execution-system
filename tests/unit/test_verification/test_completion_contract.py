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
        inferred_commands=(
            VerificationCommand(
                id="VC-001",
                kind="test",
                command="python -m pytest -q",
                expected_exit_codes=(0,),
            ),
            VerificationCommand(
                id="VC-002",
                kind="negative-smoke",
                command="releasepulse check missing.md",
                expected_exit_codes=(1,),
            ),
        ),
        runtime={"name": "codex", "sandbox": "danger-full-access"},
    )
    path = tmp_path / ".ces" / "completion-contract.json"

    contract.write(path)
    loaded = CompletionContract.read(path)

    assert loaded.version == 1
    assert loaded.request == "Build PromptVault"
    assert loaded.acceptance_criteria[0].id == "AC-001"
    assert loaded.inferred_commands[0].command == "python -m pytest -q"
    assert loaded.inferred_commands[0].expected_exit_codes == (0,)
    assert loaded.inferred_commands[1].command == "releasepulse check missing.md"
    assert loaded.inferred_commands[1].expected_exit_codes == (1,)
    assert loaded.runtime["name"] == "codex"


def test_completion_contract_roundtrip_preserves_acceptance_profile(tmp_path: Path) -> None:
    from ces.verification.completion_contract import CompletionContract

    contract = CompletionContract(
        request="Create a recipe app",
        project_type="unknown",
        required_artifacts=("README.md", "run command"),
        proof_requirements=("Document unproven areas or remaining risks",),
        next_ces_command="ces verify --json",
    )
    path = tmp_path / "contract.json"
    contract.write(path)

    loaded = CompletionContract.read(path)

    assert loaded.required_artifacts == ("README.md", "run command")
    assert loaded.proof_requirements == ("Document unproven areas or remaining risks",)
    assert loaded.next_ces_command == "ces verify --json"


def test_completion_contract_read_accepts_legacy_payload_without_acceptance_profile(tmp_path: Path) -> None:
    from ces.verification.completion_contract import CompletionContract

    path = tmp_path / "legacy-contract.json"
    path.write_text(
        "{\n"
        '  "version": 1,\n'
        '  "request": "Build PromptVault",\n'
        '  "project_type": "python-cli",\n'
        '  "acceptance_criteria": [],\n'
        '  "inferred_commands": [],\n'
        '  "runtime": {"name": "codex"}\n'
        "}\n",
        encoding="utf-8",
    )

    loaded = CompletionContract.read(path)

    assert loaded.required_artifacts == ()
    assert loaded.proof_requirements == ()
    assert loaded.next_ces_command == "ces verify --json"


def test_build_completion_contract_records_greenfield_acceptance_profile(tmp_path: Path) -> None:
    from ces.verification.build_contract import build_completion_contract

    (tmp_path / "README.md").write_text("# Meal Planner\n\nRun with `uv run meals`.\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'meals'\nversion = '0.1.0'\n[project.scripts]\nmeals = 'meals.cli:main'\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "meals").mkdir(parents=True)
    (tmp_path / "src" / "meals" / "cli.py").write_text("def main():\n    print('ok')\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_cli.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    contract = build_completion_contract(
        project_root=tmp_path,
        request="Create a meal planner app",
        acceptance_criteria=["User can add meals and view a weekly plan"],
        runtime_name="fake-runtime",
    )
    payload = contract.to_dict()

    assert payload["required_artifacts"] == ["README.md", "run command", "test command", "verification evidence"]
    assert "Document unproven areas or remaining risks" in payload["proof_requirements"]
    assert payload["next_ces_command"] == "ces verify --json"
