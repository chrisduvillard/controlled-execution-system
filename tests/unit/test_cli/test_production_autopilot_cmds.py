"""CLI tests for Production Autopilot commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

runner = CliRunner()


def _get_app() -> Any:
    from ces.cli import app

    return app


def _write_minimal_project(root: Path) -> None:
    (root / "README.md").write_text("# Demo\nSafety invariant: never print secret values.\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        """
[project]
name = "demo"
dependencies = ["pytest", "ruff"]

[tool.pytest.ini_options]
addopts = "-q"

[tool.ruff]
line-length = 100
""".strip(),
        encoding="utf-8",
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")


def test_next_json_reports_next_safe_action(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)

    result = runner.invoke(_get_app(), ["next", "--project-root", str(tmp_path), "--format", "json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["current_maturity"] == "shareable-app"
    assert payload["target_maturity"] == "production-candidate"
    assert payload["recommended_command"]
    assert "feature_work_guidance" in payload


def test_next_prompt_markdown_contains_agent_guardrails(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)

    result = runner.invoke(_get_app(), ["next-prompt", "--project-root", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert "# Next Production-Readiness Prompt" in result.stdout
    assert "Secret-handling rule" in result.stdout
    assert "Completion evidence" in result.stdout


def test_passport_json_contains_evidence_backed_summary(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)

    result = runner.invoke(_get_app(), ["passport", "--project-root", str(tmp_path), "--format", "json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["detected_archetype"] == "python-package"
    assert payload["maturity_level"] == "shareable-app"
    assert payload["recommended_next_promotion"] == "production-candidate"
    assert payload["evidence_sources"]


def test_promote_json_is_read_only_sequential_plan(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    result = runner.invoke(
        _get_app(), ["promote", "production-candidate", "--project-root", str(tmp_path), "--format", "json"]
    )

    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert result.exit_code == 0, result.stdout
    assert before == after
    payload = json.loads(result.stdout)
    assert payload["target_level"] == "production-candidate"
    assert payload["execution_mode"] == "plan-only"
    assert payload["steps"][0]["target_maturity"] == "production-candidate"


def test_invariants_json_and_slop_scan_json(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)
    (tmp_path / "worker.py").write_text("try:\n    run()\nexcept Exception:\n    pass\n", encoding="utf-8")

    invariants = runner.invoke(_get_app(), ["invariants", "--project-root", str(tmp_path), "--format", "json"])
    slop = runner.invoke(_get_app(), ["slop-scan", "--project-root", str(tmp_path), "--format", "json"])

    assert invariants.exit_code == 0, invariants.stdout
    assert slop.exit_code == 0, slop.stdout
    assert json.loads(invariants.stdout)["invariants"]
    assert any(finding["category"] == "ai-slop" for finding in json.loads(slop.stdout)["findings"])


def test_launch_rehearsal_json_uses_nested_command_shape(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)

    result = runner.invoke(_get_app(), ["launch", "rehearsal", "--project-root", str(tmp_path), "--format", "json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["mode"] == "read-only-plan"
    assert "uv run pytest tests/ -q" in payload["recommended_commands"]
