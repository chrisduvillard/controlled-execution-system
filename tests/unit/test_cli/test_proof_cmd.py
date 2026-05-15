"""CLI tests for proof card front door."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

runner = CliRunner()


def _get_app() -> Any:
    from ces.cli import app

    return app


def _write_completion_contract(root: Path) -> None:
    ces_dir = root / ".ces"
    ces_dir.mkdir()
    (ces_dir / "completion-contract.json").write_text(
        json.dumps(
            {
                "version": 1,
                "request": "Create a tiny CLI calculator",
                "project_type": "python-cli",
                "acceptance_criteria": [],
                "inferred_commands": [
                    {
                        "id": "tests",
                        "kind": "test",
                        "command": "pytest",
                        "reason": "test suite",
                        "expected_exit_codes": [0],
                    }
                ],
                "runtime": {"name": "codex"},
                "required_artifacts": ["README.md", "run command", "test command", "verification evidence"],
                "proof_requirements": ["README includes beginner run and test instructions"],
                "next_ces_command": "ces verify --json",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _write_latest_verification(root: Path) -> None:
    (root / ".ces" / "latest-verification.json").write_text(
        json.dumps(
            {
                "verification": {
                    "passed": True,
                    "commands": [
                        {
                            "id": "tests",
                            "kind": "test",
                            "command": "pytest",
                            "required": True,
                            "exit_code": 0,
                            "stdout": "",
                            "stderr": "",
                            "cwd": ".",
                            "timeout_seconds": 120,
                            "expected_exit_codes": [0],
                            "passed": True,
                        }
                    ],
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_proof_json_command_outputs_shareable_payload(tmp_path: Path) -> None:
    _write_completion_contract(tmp_path)
    _write_latest_verification(tmp_path)
    (tmp_path / "README.md").write_text(
        "Run: `python app.py`\n\nTest: `pytest`\n\nVerification evidence: smoke passed.\n",
        encoding="utf-8",
    )

    result = runner.invoke(_get_app(), ["proof", "--project-root", str(tmp_path), "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["objective"] == "Create a tiny CLI calculator"
    assert payload["ship_recommendation"] == "candidate"
    assert payload["next_command"] == "ces verify --json"


def test_proof_honors_root_json_mode(tmp_path: Path) -> None:
    _write_completion_contract(tmp_path)

    result = runner.invoke(_get_app(), ["--json", "proof", "--project-root", str(tmp_path)])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ship_recommendation"] == "no-ship"


def test_proof_markdown_reports_no_ship_without_persisted_verification(tmp_path: Path) -> None:
    _write_completion_contract(tmp_path)
    (tmp_path / "README.md").write_text("Run: `python app.py`\n\nTest: `pytest`\n", encoding="utf-8")

    result = runner.invoke(_get_app(), ["proof", "--project-root", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "Ship recommendation: **no-ship**" in result.output
    assert "No persisted verification run" in result.output


def test_root_help_surfaces_proof_card_command() -> None:
    result = runner.invoke(_get_app(), ["--help"], env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "160"})

    assert result.exit_code == 0, result.output
    assert "ces proof" in result.output
    assert "ship/no-ship" in result.output
