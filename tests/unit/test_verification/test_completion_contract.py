"""Tests for completion contract JSON model."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

requires_symlink = pytest.mark.skipif(sys.platform == "win32", reason="Windows symlink privileges vary by environment")


def _minimal_contract():
    from ces.verification.completion_contract import CompletionContract

    return CompletionContract(request="Create a recipe app", project_type="unknown")


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


def test_completion_contract_roundtrip_preserves_reality_boundary_contract(tmp_path: Path) -> None:
    from ces.verification.completion_contract import (
        CompletionContract,
        OfficialEvaluator,
        ProtectedSurface,
        RealityBoundaryContract,
        SuccessPredicate,
    )

    contract = CompletionContract(
        request="Build a safe migration helper",
        project_type="python-cli",
        reality_boundary=RealityBoundaryContract(
            success_predicates=(SuccessPredicate(id="AC-001", text="pytest must pass", source="acceptance_criterion"),),
            official_evaluators=(
                OfficialEvaluator(
                    id="VC-001",
                    command_id="VC-001",
                    kind="test",
                    command="uv run pytest -q",
                    required=True,
                    expected_exit_codes=(0,),
                ),
            ),
            protected_surfaces=(
                ProtectedSurface(path="tests/regression/test_migration.py", reason="official evaluator fixture"),
            ),
            mutable_test_policy="warn",
            allowed_test_paths=("tests/new/",),
            denied_test_paths=("tests/regression/",),
            contract_frozen_at="2026-06-03T09:00:00Z",
        ).with_predicate_hash(),
    )
    path = tmp_path / "contract.json"

    contract.write(path)
    loaded = CompletionContract.read(path)

    assert loaded.reality_boundary.success_predicates[0].text == "pytest must pass"
    assert loaded.reality_boundary.official_evaluators[0].command == "uv run pytest -q"
    assert loaded.reality_boundary.protected_surfaces[0].path == "tests/regression/test_migration.py"
    assert loaded.reality_boundary.denied_test_paths == ("tests/regression/",)
    assert loaded.reality_boundary.predicate_hash
    assert loaded.to_dict()["reality_boundary"]["predicate_hash"] == loaded.reality_boundary.predicate_hash


def test_reality_boundary_predicate_hash_uses_scrubbed_material() -> None:
    from ces.verification.completion_contract import OfficialEvaluator, RealityBoundaryContract, SuccessPredicate

    secret_key = "OPENAI_" + "API_KEY="
    secret_a = secret_key + "sk-tes...alue"
    secret_b = secret_key + "sk-oth...alue"
    first = RealityBoundaryContract(
        success_predicates=(SuccessPredicate(id="AC-001", text=f"Do not leak {secret_a}"),),
        official_evaluators=(
            OfficialEvaluator(
                id="VC-001",
                command_id="VC-001",
                kind="smoke",
                command=f"{secret_a} uv run pytest -q",
            ),
        ),
    ).with_predicate_hash()
    second = RealityBoundaryContract(
        success_predicates=(SuccessPredicate(id="AC-001", text=f"Do not leak {secret_b}"),),
        official_evaluators=(
            OfficialEvaluator(
                id="VC-001",
                command_id="VC-001",
                kind="smoke",
                command=f"{secret_b} uv run pytest -q",
            ),
        ),
    ).with_predicate_hash()

    assert first.predicate_hash == second.predicate_hash


def test_completion_contract_to_dict_scrubs_reality_boundary_secret_material() -> None:
    from ces.verification.completion_contract import (
        CompletionContract,
        OfficialEvaluator,
        RealityBoundaryContract,
        SuccessPredicate,
    )

    secret_key = "OPENAI_" + "API_KEY="
    secret = secret_key + "sk-tes...alue"
    contract = CompletionContract(
        request="Protect proof material",
        project_type="python-cli",
        reality_boundary=RealityBoundaryContract(
            success_predicates=(SuccessPredicate(id="AC-001", text=f"Do not leak {secret}"),),
            official_evaluators=(
                OfficialEvaluator(
                    id="VC-001",
                    command_id="VC-001",
                    kind="smoke",
                    command=f"{secret} uv run pytest -q",
                ),
            ),
        ).with_predicate_hash(),
    )

    exported_payload = contract.to_dict()
    exported = json.dumps(exported_payload)

    assert "Do not leak" not in exported
    assert "uv run pytest -q" not in exported
    assert "sk-tes...alue" not in exported
    assert exported_payload["reality_boundary"]["success_predicates"][0]["text_sha256"]
    assert exported_payload["reality_boundary"]["official_evaluators"][0]["command_sha256"]
    assert "text" not in exported_payload["reality_boundary"]["success_predicates"][0]
    assert "command" not in exported_payload["reality_boundary"]["official_evaluators"][0]


def test_completion_contract_read_accepts_legacy_payload_without_reality_boundary(tmp_path: Path) -> None:
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

    assert loaded.reality_boundary.success_predicates == ()
    assert loaded.reality_boundary.official_evaluators == ()
    assert loaded.reality_boundary.protected_surfaces == ()
    assert loaded.reality_boundary.mutable_test_policy == "warn"


def test_build_completion_contract_binds_reality_boundary_to_proof_hash(tmp_path: Path) -> None:
    from dataclasses import replace

    from ces.verification.build_contract import build_completion_contract
    from ces.verification.completion_contract import OfficialEvaluator, RealityBoundaryContract
    from ces.verification.proof_binding import proof_binding_hash

    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")

    contract = build_completion_contract(
        project_root=tmp_path,
        request="Build demo",
        acceptance_criteria=["The test suite passes."],
        runtime_name="codex",
    )
    mutated_boundary = replace(
        contract.reality_boundary,
        official_evaluators=(
            OfficialEvaluator(
                id="VC-999",
                command_id="VC-999",
                kind="test",
                command="echo forged self-report",
                required=True,
                expected_exit_codes=(0,),
            ),
        ),
    ).with_predicate_hash()
    mutated = replace(contract, reality_boundary=mutated_boundary, proof_binding_hash=None)

    assert contract.reality_boundary.success_predicates[0].text == "The test suite passes."
    assert contract.reality_boundary.official_evaluators
    assert contract.reality_boundary.protected_surfaces
    assert contract.reality_boundary.predicate_hash
    assert proof_binding_hash(mutated) != contract.proof_binding_hash
    assert RealityBoundaryContract.from_dict(contract.to_dict()["reality_boundary"]).predicate_hash


def test_completion_contract_write_preserves_reality_boundary_hashes_when_scrubbing_secret_material(
    tmp_path: Path,
) -> None:
    from ces.verification.completion_contract import (
        CompletionContract,
        OfficialEvaluator,
        RealityBoundaryContract,
        SuccessPredicate,
    )
    from ces.verification.proof_binding import proof_binding_hash

    secret_key = "OPENAI_" + "API_KEY="
    secret = secret_key + "sk-tes...alue"
    contract = CompletionContract(
        request="Protect proof material",
        project_type="python-cli",
        reality_boundary=RealityBoundaryContract(
            success_predicates=(SuccessPredicate(id="AC-001", text=f"Do not leak {secret}"),),
            official_evaluators=(
                OfficialEvaluator(
                    id="VC-001",
                    command_id="VC-001",
                    kind="smoke",
                    command=f"{secret} uv run pytest -q",
                ),
            ),
        ).with_predicate_hash(),
    )
    before = proof_binding_hash(contract)

    contract.write(tmp_path / ".ces" / "completion-contract.json")
    reloaded = CompletionContract.read(tmp_path / ".ces" / "completion-contract.json")

    assert proof_binding_hash(reloaded) == before
    stored = json.loads((tmp_path / ".ces" / "completion-contract.json").read_text(encoding="utf-8"))
    assert "sk-tes...alue" not in json.dumps(stored)
    assert stored["reality_boundary"]["success_predicates"][0]["text_sha256"]
    assert stored["reality_boundary"]["official_evaluators"][0]["command_sha256"]


def test_completion_contract_write_preserves_reality_boundary_path_hashes_when_scrubbing_secret_material(
    tmp_path: Path,
) -> None:
    from ces.verification.completion_contract import CompletionContract, RealityBoundaryContract
    from ces.verification.proof_binding import proof_binding_hash

    secret_key = "OPENAI_" + "API_KEY="
    secret_path = f"tests/{secret_key}sk-tes...alue/test_private.py"
    contract = CompletionContract(
        request="Protect path proof material",
        project_type="python-cli",
        reality_boundary=RealityBoundaryContract(
            allowed_test_paths=(secret_path,),
            denied_test_paths=(secret_path,),
        ).with_predicate_hash(),
    )
    before = proof_binding_hash(contract)

    contract.write(tmp_path / ".ces" / "completion-contract.json")
    reloaded = CompletionContract.read(tmp_path / ".ces" / "completion-contract.json")

    assert proof_binding_hash(reloaded) == before
    stored = json.loads((tmp_path / ".ces" / "completion-contract.json").read_text(encoding="utf-8"))
    assert "sk-tes...alue" not in json.dumps(stored)
    assert stored["reality_boundary"]["allowed_test_paths_sha256"]
    assert stored["reality_boundary"]["denied_test_paths_sha256"]


@requires_symlink
def test_completion_contract_rejects_symlinked_ces_directory(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".ces").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlinked|outside"):
        _minimal_contract().write(tmp_path / ".ces" / "completion-contract.json")

    assert not (outside / "completion-contract.json").exists()


@requires_symlink
def test_completion_contract_rejects_symlinked_destination(tmp_path: Path) -> None:
    ces_dir = tmp_path / ".ces"
    ces_dir.mkdir()
    outside = tmp_path / "outside-contract.json"
    (ces_dir / "completion-contract.json").symlink_to(outside)

    with pytest.raises(ValueError, match="symlinked|outside"):
        _minimal_contract().write(ces_dir / "completion-contract.json")

    assert not outside.exists()


def test_completion_contract_write_accepts_relative_ces_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ces.verification.completion_contract import CompletionContract

    monkeypatch.chdir(tmp_path)
    path = Path(".ces/completion-contract.json")

    _minimal_contract().write(path)
    loaded = CompletionContract.read(path)

    assert loaded.request == "Create a recipe app"
    assert (tmp_path / ".ces" / "completion-contract.json").is_file()


def test_completion_contract_write_with_relative_project_root_does_not_double_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ces.verification.completion_contract import CompletionContract

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(tmp_path)
    path = Path("project/.ces/completion-contract.json")

    _minimal_contract().write(path)
    loaded = CompletionContract.read(path)

    assert loaded.request == "Create a recipe app"
    assert path.is_file()
    assert not (project / "project" / ".ces" / "completion-contract.json").exists()


@requires_symlink
def test_completion_contract_read_rejects_symlinked_ces_directory(tmp_path: Path) -> None:
    from ces.verification.completion_contract import CompletionContract

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "completion-contract.json").write_text('{"version": 1, "request": "x", "project_type": "unknown"}\n')
    (tmp_path / ".ces").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlinked|outside"):
        CompletionContract.read(tmp_path / ".ces" / "completion-contract.json")


@requires_symlink
def test_completion_contract_read_rejects_symlinked_ces_file(tmp_path: Path) -> None:
    from ces.verification.completion_contract import CompletionContract

    ces_dir = tmp_path / ".ces"
    ces_dir.mkdir()
    outside = tmp_path / "outside-contract.json"
    outside.write_text('{"version": 1, "request": "x", "project_type": "unknown"}\n')
    (ces_dir / "completion-contract.json").symlink_to(outside)

    with pytest.raises(ValueError, match="symlinked|outside"):
        CompletionContract.read(ces_dir / "completion-contract.json")
