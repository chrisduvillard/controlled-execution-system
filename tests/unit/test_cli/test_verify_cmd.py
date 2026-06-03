"""Tests for `ces verify`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

runner = CliRunner()


def _get_app():
    from ces.cli import app

    return app


def test_verify_infers_contract_without_writing_by_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ces").mkdir()
    (tmp_path / ".ces" / "config.yaml").write_text("project_id: demo\npreferred_runtime: codex\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")

    result = runner.invoke(_get_app(), ["verify", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["project_type"] == "python-package"
    assert payload["verification"]["passed"] is True
    assert payload["contract_persisted"] is False
    latest = json.loads((tmp_path / ".ces" / "latest-verification.json").read_text(encoding="utf-8"))
    assert latest["verification"]["passed"] is True
    assert latest["proof_binding_hash"]
    assert latest["objective"] == "Independent verification"
    assert latest["reality_boundary"]["predicate_hash"]
    assert latest["reality_boundary"]["official_evaluators"][0]["id"]
    assert "command" not in latest["reality_boundary"]["official_evaluators"][0]
    assert "success_predicates" not in latest["reality_boundary"]
    assert latest["reality_boundary"]["protected_surfaces"]
    assert not (tmp_path / ".ces" / "completion-contract.json").exists()


def test_verify_inferred_python_commands_work_without_bare_python(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    (tmp_path / ".ces").mkdir()
    (tmp_path / ".ces" / "config.yaml").write_text("project_id: demo\npreferred_runtime: codex\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")

    result = runner.invoke(_get_app(), ["verify", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["verification"]["passed"] is True
    assert all(command["exit_code"] == 0 for command in payload["verification"]["commands"])
    assert all(
        command["effective_command"].startswith(sys.executable) for command in payload["verification"]["commands"]
    )


def test_verify_writes_inferred_contract_when_requested(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ces").mkdir()
    (tmp_path / ".ces" / "config.yaml").write_text("project_id: demo\npreferred_runtime: codex\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")

    result = runner.invoke(_get_app(), ["verify", "--json", "--write-contract"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["verification"]["passed"] is True
    assert payload["contract_persisted"] is True
    assert (tmp_path / ".ces" / "completion-contract.json").is_file()
    contract = json.loads((tmp_path / ".ces" / "completion-contract.json").read_text(encoding="utf-8"))
    assert contract["proof_binding_hash"] == payload["proof_binding_hash"]


def test_verify_write_contract_preserves_binding_hash_after_reload_for_secret_like_boundary(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ces").mkdir()
    (tmp_path / ".ces" / "config.yaml").write_text("project_id: demo\npreferred_runtime: codex\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")

    result = runner.invoke(_get_app(), ["verify", "--json", "--write-contract"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    from ces.verification.completion_contract import CompletionContract
    from ces.verification.proof_binding import proof_binding_hash

    reloaded = CompletionContract.read(tmp_path / ".ces" / "completion-contract.json")
    assert proof_binding_hash(reloaded) == payload["proof_binding_hash"]


def test_verify_write_contract_uses_storage_contract_not_evidence_export(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ces").mkdir()
    (tmp_path / ".ces" / "config.yaml").write_text("project_id: demo\npreferred_runtime: codex\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")

    result = runner.invoke(_get_app(), ["verify", "--json", "--write-contract"])

    assert result.exit_code == 0, result.stdout
    stored = json.loads((tmp_path / ".ces" / "completion-contract.json").read_text(encoding="utf-8"))
    evaluator = stored["reality_boundary"]["official_evaluators"][0]
    assert evaluator["command"]
    assert evaluator["command_sha256"]


def test_verify_accepts_project_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project"
    (project / ".ces").mkdir(parents=True)
    (project / ".ces" / "config.yaml").write_text("project_id: demo\npreferred_runtime: codex\n")
    (project / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (project / "tests").mkdir()
    (project / "tests" / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")

    result = runner.invoke(_get_app(), ["verify", "--project-root", str(project), "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["project_root"] == str(project.resolve())


def test_verify_json_exits_nonzero_when_no_commands_are_inferred(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ces").mkdir()
    (tmp_path / ".ces" / "config.yaml").write_text("project_id: demo\npreferred_runtime: codex\n")
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")

    result = runner.invoke(_get_app(), ["verify", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["verification"]["passed"] is False
    assert payload["verification"]["commands"] == []


def test_verify_runs_reality_boundary_official_evaluators_instead_of_weakened_inferred_commands(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ces").mkdir()
    (tmp_path / ".ces" / "completion-contract.json").write_text(
        json.dumps(
            {
                "version": 1,
                "request": "Do not let inferred commands bypass the official evaluator",
                "project_type": "unknown",
                "acceptance_criteria": [],
                "inferred_commands": [
                    {
                        "id": "smoke",
                        "kind": "smoke",
                        "command": "true",
                        "expected_exit_codes": [0],
                    }
                ],
                "runtime": {"name": "manual"},
                "reality_boundary": {
                    "official_evaluators": [
                        {
                            "id": "official-smoke",
                            "command_id": "official-smoke",
                            "kind": "smoke",
                            "command": f'{sys.executable} -c "import sys; sys.exit(99)"',
                            "expected_exit_codes": [0],
                        }
                    ]
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = runner.invoke(_get_app(), ["verify", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["verification"]["passed"] is False
    assert payload["verification"]["commands"][0]["id"] == "official-smoke"
    assert payload["verification"]["commands"][0]["exit_code"] == 99


def test_verify_json_scrubs_secret_like_objective_in_latest_evidence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ces").mkdir()
    (tmp_path / ".ces" / "completion-contract.json").write_text(
        json.dumps(
            {
                "version": 1,
                "request": "Verify OPENAI_API_KEY=sk-test-secret-value stays hidden",
                "project_type": "unknown",
                "acceptance_criteria": [],
                "inferred_commands": [
                    {
                        "id": "smoke",
                        "kind": "smoke",
                        "command": "true",
                        "expected_exit_codes": [0],
                    }
                ],
                "runtime": {"name": "manual"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = runner.invoke(_get_app(), ["verify", "--json"])

    assert result.exit_code == 0, result.stdout
    assert "sk-test-secret-value" not in result.stdout
    payload = json.loads(result.stdout)
    assert payload["objective"] == "Verify OPENAI_API_KEY=<REDACTED> stays hidden"
    latest = json.loads((tmp_path / ".ces" / "latest-verification.json").read_text(encoding="utf-8"))
    assert latest["objective"] == "Verify OPENAI_API_KEY=<REDACTED> stays hidden"


def test_verify_latest_reality_boundary_metadata_omits_raw_private_boundary_material(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ces").mkdir()
    private_root = tmp_path / "private" / "project"
    (tmp_path / ".ces" / "completion-contract.json").write_text(
        json.dumps(
            {
                "version": 1,
                "request": "Verify private boundary material stays hidden",
                "project_type": "unknown",
                "acceptance_criteria": [],
                "inferred_commands": [
                    {
                        "id": "smoke",
                        "kind": "smoke",
                        "command": "true",
                        "expected_exit_codes": [0],
                    }
                ],
                "runtime": {"name": "manual"},
                "reality_boundary": {
                    "contract_version": 1,
                    "success_predicates": [{"id": "AC-001", "text": "private acceptance detail"}],
                    "official_evaluators": [
                        {
                            "id": "VC-001",
                            "command_id": "smoke",
                            "kind": "smoke",
                            "command": "true",
                            "cwd": ".",
                            "expected_exit_codes": [0],
                        }
                    ],
                    "protected_surfaces": [
                        {"path": str(private_root / "tests" / "private_flow.py"), "reason": "private reason"}
                    ],
                    "mutable_test_policy": "warn",
                    "allowed_test_paths": [str(private_root / "tests")],
                    "denied_test_paths": [str(private_root / "tests" / "private_flow.py")],
                    "predicate_hash": "abc123",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = runner.invoke(_get_app(), ["verify", "--json"])

    assert result.exit_code == 0, result.stdout
    latest = json.loads((tmp_path / ".ces" / "latest-verification.json").read_text(encoding="utf-8"))
    exported = json.dumps(latest["reality_boundary"])
    assert "private acceptance detail" not in exported
    assert "uv run pytest tests/private_flow.py -q" not in exported
    assert str(private_root) not in exported
    assert "private reason" not in exported
    assert latest["reality_boundary"]["official_evaluators"][0]["command_sha256"]


def test_verify_refuses_to_write_latest_evidence_through_symlinked_ces_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    outside = tmp_path.parent / "outside-ces-state"
    outside.mkdir(exist_ok=True)
    (tmp_path / ".ces").symlink_to(outside, target_is_directory=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")

    result = runner.invoke(_get_app(), ["verify", "--json"])

    assert result.exit_code != 0
    assert not (outside / "latest-verification.json").exists()
    assert "symlinked .ces" in result.stdout or "symlinked .ces" in result.stderr


def test_verify_refuses_to_overwrite_symlinked_latest_evidence_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    outside = tmp_path.parent / "outside-latest-verification.json"
    outside.write_text("outside\n", encoding="utf-8")
    (tmp_path / ".ces").mkdir()
    (tmp_path / ".ces" / "latest-verification.json").symlink_to(outside)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")

    result = runner.invoke(_get_app(), ["verify", "--json"])

    assert result.exit_code != 0
    assert outside.read_text(encoding="utf-8") == "outside\n"
    assert "symlinked file" in result.stdout or "symlinked file" in result.stderr


def test_verify_write_contract_refuses_symlinked_ces_dir_before_contract_write(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    outside = tmp_path.parent / "outside-contract-state"
    outside.mkdir(exist_ok=True)
    (tmp_path / ".ces").symlink_to(outside, target_is_directory=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")

    result = runner.invoke(_get_app(), ["verify", "--json", "--write-contract"])

    assert result.exit_code != 0
    assert not (outside / "completion-contract.json").exists()
    combined_output = f"{result.stdout}\n{result.stderr}"
    assert "project root" in combined_output or "symlinked" in combined_output


def test_verify_rich_output_suggests_semantic_review_next_step(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ces").mkdir()
    (tmp_path / ".ces" / "config.yaml").write_text("project_id: demo\npreferred_runtime: codex\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")

    result = runner.invoke(_get_app(), ["verify"])

    assert result.exit_code == 0, result.stdout
    assert "ces review generate" in result.stdout
    assert "ces review show" in result.stdout
