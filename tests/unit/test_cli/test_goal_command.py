"""Beginner-safe `ces goal` front-door command contracts."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

import typer
from typer.testing import CliRunner

runner = CliRunner()


def _get_app() -> typer.Typer:
    from ces.cli import app

    return app


def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_goal_json_routes_empty_project_to_from_scratch_without_side_effects(tmp_path: Path) -> None:
    result = runner.invoke(
        _get_app(),
        ["goal", "Build a tiny notes app", "--project-root", str(tmp_path), "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["command"] == "goal"
    assert payload["execution_mode"] == "read-only-goal-router"
    assert payload["objective"] == "Build a tiny notes app"
    assert payload["next_command"].startswith(f"cd {shlex.quote(str(tmp_path.resolve()))} && ces build --from-scratch")
    assert payload["recommended_command"].startswith("ces build --from-scratch")
    assert "Build a tiny notes app" in payload["next_command"]
    assert payload["decision"]["project_mode"] == "greenfield"
    assert payload["copy_paste_sequence"][0] == f"cd {shlex.quote(str(tmp_path.resolve()))}"
    assert payload["copy_paste_sequence"][1] == "ces doctor"
    assert payload["copy_paste_sequence"][-1] == "ces proof"
    assert any("read-only" in note for note in payload["safety_notes"])
    assert not (tmp_path / ".ces").exists()


def test_goal_json_routes_existing_project_to_diagnostics_not_greenfield(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", '[project]\nname = "existing-app"\nversion = "0.1.0"\n')
    _write(tmp_path / "README.md", "# Existing App\n")

    result = runner.invoke(
        _get_app(),
        ["goal", "Add CSV export", "--project-root", str(tmp_path), "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["decision"]["project_mode"] == "brownfield"
    assert "--from-scratch" not in payload["next_command"]
    assert payload["copy_paste_sequence"][0] == f"cd {shlex.quote(str(tmp_path.resolve()))}"
    assert "ces mri" in payload["copy_paste_sequence"]
    assert "ces next" in payload["copy_paste_sequence"]
    assert not (tmp_path / ".ces").exists()


def test_goal_treats_source_only_existing_project_as_brownfield(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "app.py", "print('hello')\n")

    result = runner.invoke(
        _get_app(),
        ["goal", "Improve the CLI", "--project-root", str(tmp_path), "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["decision"]["project_mode"] == "brownfield"
    assert "--from-scratch" not in payload["next_command"]
    assert payload["copy_paste_sequence"][0] == f"cd {shlex.quote(str(tmp_path.resolve()))}"
    assert "ces mri" in payload["copy_paste_sequence"]
    assert not (tmp_path / ".ces").exists()


def test_goal_quotes_shell_metacharacters_and_option_like_objectives(tmp_path: Path) -> None:
    pwned_path = tmp_path / "ces-goal-pwned"
    objective = f"--help $(touch {pwned_path}) `whoami`"

    result = runner.invoke(
        _get_app(),
        ["goal", objective, "--project-root", str(tmp_path), "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    command = payload["next_command"]
    assert command.startswith(f"cd {shlex.quote(str(tmp_path.resolve()))} && ces build --from-scratch=")
    assert payload["recommended_command"].startswith("ces build --from-scratch=")
    assert shlex.quote(objective) in command
    assert payload["objective"] == objective
    assert not pwned_path.exists()


def test_goal_accepts_option_like_objective_after_goal_options(tmp_path: Path) -> None:
    objective = "--dash-prefixed literal goal"

    result = runner.invoke(
        _get_app(),
        ["goal", "--project-root", str(tmp_path), "--format", "json", objective],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["objective"] == objective
    assert payload["recommended_command"].startswith("ces build --from-scratch=")
    assert shlex.quote(objective) in payload["next_command"]


def test_goal_accepts_equals_form_options_before_option_like_objective(tmp_path: Path) -> None:
    objective = "--dash-prefixed literal goal"

    result = runner.invoke(
        _get_app(),
        ["goal", f"--project-root={tmp_path}", "--format=json", objective],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["project_root"] == str(tmp_path.resolve())
    assert payload["objective"] == objective
    assert payload["recommended_command"].startswith("ces build --from-scratch=")


def test_goal_honors_root_json_and_missing_goal_is_clean_usage_error(tmp_path: Path) -> None:
    result = runner.invoke(_get_app(), ["--json", "goal", "--project-root", str(tmp_path)])

    assert result.exit_code == 2
    assert result.stdout == ""
    payload = json.loads(result.stderr)
    assert payload["error"]["type"] == "usage_error"
    assert "goal is required" in payload["error"]["message"]


def test_goal_markdown_is_plain_next_step_and_read_only(tmp_path: Path) -> None:
    result = runner.invoke(_get_app(), ["goal", "Ship a habit tracker", "--project-root", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("# CES Goal")
    assert "Next command:" in result.stdout
    assert "read-only" in result.stdout
    assert "does not create `.ces/`" in result.stdout
    assert "ces build --from-scratch" in result.stdout
    assert not (tmp_path / ".ces").exists()
