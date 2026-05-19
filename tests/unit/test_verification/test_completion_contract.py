"""Tests for completion contract JSON model."""

from __future__ import annotations

from pathlib import Path


def test_completion_contract_roundtrips_json(tmp_path: Path) -> None:
    from ces.verification.completion_contract import (
        AcceptanceCriterion,
        BehaviorDelta,
        CompletionContract,
        RiskTrack,
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
        behavior_delta=BehaviorDelta(
            added=("CSV export includes invoice notes.",),
            modified=("Invoice export appends notes after existing columns.",),
            removed=("Legacy blank notes suppression is removed.",),
            preserved=("Existing CSV column order remains stable.",),
            unknown=("Downstream importer tolerance is unverified.",),
        ),
        risk_track=RiskTrack(
            tier="A",
            required_artifacts=("rollback-plan.md", "reviewer-signoff.md"),
            proof_requirements=("Document high-risk behavior evidence.",),
            evidence_requirements=("Fresh verification passed.", "Rollback path documented."),
        ),
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
    assert loaded.behavior_delta.preserved == ("Existing CSV column order remains stable.",)
    assert loaded.risk_track.tier == "A"
    assert loaded.risk_track.required_artifacts == ("rollback-plan.md", "reviewer-signoff.md")
    assert loaded.to_dict()["behavior_delta"]["unknown"] == ["Downstream importer tolerance is unverified."]
    assert loaded.to_dict()["risk_track"]["evidence_requirements"] == [
        "Fresh verification passed.",
        "Rollback path documented.",
    ]


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
    assert loaded.behavior_delta.has_signal() is False
    assert loaded.risk_track.tier == "C"
    assert loaded.risk_track.required_artifacts == ()
    assert loaded.proof_binding_hash is None
    assert loaded.to_dict()["proof_binding_hash"] is None
    assert loaded.next_ces_command == "ces verify --json"


def test_build_completion_contract_records_greenfield_acceptance_profile(tmp_path: Path) -> None:
    from ces.verification.build_contract import build_completion_contract
    from ces.verification.completion_contract import BehaviorDelta

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
        behavior_delta=BehaviorDelta(preserved=("Existing meal CLI keeps working.",)),
    )
    payload = contract.to_dict()

    assert payload["required_artifacts"] == ["README.md", "run command", "test command", "verification evidence"]
    assert payload["behavior_delta"]["preserved"] == ["Existing meal CLI keeps working."]
    assert payload["risk_track"]["tier"] == "B"
    assert payload["risk_track"]["required_artifacts"] == ["regression-evidence.md"]
    assert "Document unproven areas or remaining risks" in payload["proof_requirements"]
    assert payload["next_ces_command"] == "ces verify --json"
    assert payload["proof_binding_hash"]


def test_completion_contract_roundtrip_preserves_proof_binding_hash(tmp_path: Path) -> None:
    from ces.verification.completion_contract import CompletionContract

    contract = CompletionContract(
        request="Create a recipe app",
        project_type="unknown",
        proof_binding_hash="abc123",
    )
    path = tmp_path / "contract.json"
    contract.write(path)

    loaded = CompletionContract.read(path)

    assert loaded.proof_binding_hash == "abc123"
    assert loaded.to_dict()["proof_binding_hash"] == "abc123"
