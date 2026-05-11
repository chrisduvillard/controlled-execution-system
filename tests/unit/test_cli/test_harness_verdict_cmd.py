"""Tests for `ces harness verdict`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

runner = CliRunner()


def _get_app() -> Any:
    from ces.cli import app

    return app


def _write_manifest(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "change_id": "hchg-cli-verdict-1",
                "title": "Detect proxy validation",
                "component_type": "tool_policy",
                "files_changed": ["src/ces/harness_evolution/patterns.py"],
                "evidence_refs": ["runs/dogfood-42.log"],
                "failure_pattern": "proxy validation accepted after failed tests",
                "root_cause_hypothesis": "agents treat inspection as validation",
                "predicted_fixes": ["proxy validation phrase detected", "validation commands observed"],
                "predicted_regressions": ["false positive proxy warning"],
                "validation_plan": ["run transcript distillation fixtures"],
                "rollback_condition": "operator sees regression blindness",
                "status": "active",
            }
        ),
        encoding="utf-8",
    )


def _write_analysis(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "task_run_id": "dogfood-cli-1",
                "outcome": "fail",
                "failure_class": "validation_failure",
                "suspected_root_cause": "validation command failed",
                "validation_commands_observed": ["uv run pytest tests/unit -q"],
                "proxy_validation_warnings": ["line 5: proxy validation phrase detected"],
                "evidence_pointers": [
                    "source: runs/dogfood-cli-1.log",
                    "unexpected regression: false positive proxy warning",
                ],
            }
        ),
        encoding="utf-8",
    )


def test_harness_verdict_persists_regression_aware_verdict(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    manifest = tmp_path / "manifest.json"
    analysis = tmp_path / "analysis.json"
    _write_manifest(manifest)
    _write_analysis(analysis)

    app = _get_app()
    add_result = runner.invoke(app, ["harness", "changes", "add", str(manifest)])
    assert add_result.exit_code == 0, add_result.stdout

    verdict_result = runner.invoke(app, ["harness", "verdict", "hchg-cli-verdict-1", "--from-analysis", str(analysis)])

    assert verdict_result.exit_code == 0, verdict_result.stdout
    assert "verdict: rollback" in verdict_result.stdout
    assert "predicted fixes observed: 2" in verdict_result.stdout
    assert "predicted regressions observed: 1" in verdict_result.stdout
    assert "unexpected regressions: 1" in verdict_result.stdout

    show_result = runner.invoke(app, ["harness", "changes", "show", "hchg-cli-verdict-1"])
    assert show_result.exit_code == 0, show_result.stdout
    assert "latest verdict: rollback" in show_result.stdout


def test_harness_verdict_fails_for_unknown_change(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    analysis = tmp_path / "analysis.json"
    _write_analysis(analysis)

    result = runner.invoke(
        _get_app(),
        ["harness", "verdict", "hchg-missing", "--from-analysis", str(analysis)],
    )

    assert result.exit_code == 1
    assert "Harness change not found" in result.stdout
