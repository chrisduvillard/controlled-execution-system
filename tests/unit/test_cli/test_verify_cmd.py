"""Tests for `ces verify`."""

from __future__ import annotations

import json
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
    assert not (tmp_path / ".ces" / "completion-contract.json").exists()


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
    assert "project root" in result.stdout or "project root" in result.stderr or "symlinked" in result.stdout
