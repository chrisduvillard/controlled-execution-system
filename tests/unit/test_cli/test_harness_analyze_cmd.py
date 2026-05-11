"""Tests for `ces harness analyze`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

runner = CliRunner()


def _get_app() -> Any:
    from ces.cli import app

    return app


def test_harness_analyze_writes_json_and_markdown_without_raw_secret(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    transcript = tmp_path / "dogfood.log"
    secret_value = "OPENAI_API_KEY=" + "sk-" + "A" * 40
    transcript.write_text(
        f"""run_id: dogfood-cli-1
Command: uv run pytest tests/unit -q
FAILED tests/unit/test_example.py::test_case
{secret_value}
I only inspected the code and assumed this was enough.""",
        encoding="utf-8",
    )
    json_output = tmp_path / "report.json"
    markdown_output = tmp_path / "report.md"

    result = runner.invoke(
        _get_app(),
        [
            "harness",
            "analyze",
            "--from-transcript",
            str(transcript),
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(markdown_output),
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(json_output.read_text(encoding="utf-8"))
    markdown = markdown_output.read_text(encoding="utf-8")
    assert payload["task_run_id"] == "dogfood-cli-1"
    assert payload["outcome"] == "fail"
    assert payload["validation_commands_observed"] == ["uv run pytest tests/unit -q"]
    assert "raw_transcript" not in payload
    leaked_prefix = "sk-" + "A" * 8
    assert leaked_prefix not in json_output.read_text(encoding="utf-8")
    assert leaked_prefix not in markdown
    assert "Harness trajectory report" in markdown
    assert "wrote JSON" in result.stdout
    assert "wrote markdown" in result.stdout


def test_harness_analyze_missing_transcript_fails_closed(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(_get_app(), ["harness", "analyze", "--from-transcript", "missing.log"])

    assert result.exit_code == 1
    assert "could not analyze transcript" in result.stdout.lower()
