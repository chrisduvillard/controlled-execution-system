"""Tests for `ces verify`."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

runner = CliRunner()


def _get_app():
    from ces.cli import app

    return app


def test_verify_generates_contract_and_runs_commands(tmp_path: Path, monkeypatch) -> None:
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
