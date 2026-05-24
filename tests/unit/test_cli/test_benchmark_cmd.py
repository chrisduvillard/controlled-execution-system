"""CLI coverage for ``ces benchmark greenfield``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture(autouse=True)
def _reset_json_mode():
    from ces.cli._output import set_json_mode

    set_json_mode(False)
    yield
    set_json_mode(False)


def _get_app():
    from ces.cli import app

    return app


def test_benchmark_greenfield_json_writes_scorecard(tmp_path: Path) -> None:
    app = _get_app()

    result = runner.invoke(
        app,
        [
            "--json",
            "benchmark",
            "greenfield",
            "--scenario",
            "python-cli",
            "--project-root",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["scenario_id"] == "python-cli"
    assert payload["passed"] is True
    assert payload["metrics"]["intervention_count"] == 0
    assert payload["gauntlet_loop"] == ["ship", "build", "verify", "proof"]
    assert payload["independent_project_verification"]["passed"] is True
    assert Path(payload["scorecard_path"]).is_file()


def test_benchmark_greenfield_text_output_includes_score_and_next_step(tmp_path: Path) -> None:
    app = _get_app()

    result = runner.invoke(
        app,
        [
            "benchmark",
            "greenfield",
            "--scenario",
            "python-cli",
            "--project-root",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Greenfield Benchmark" in result.stdout
    assert "Score" in result.stdout
    assert "Scorecard" in result.stdout


def test_benchmark_greenfield_unknown_scenario_exits_nonzero(tmp_path: Path) -> None:
    app = _get_app()

    result = runner.invoke(
        app,
        ["benchmark", "greenfield", "--scenario", "missing", "--project-root", str(tmp_path)],
    )

    assert result.exit_code != 0
    assert "Unknown benchmark scenario" in result.stdout


def test_benchmark_compare_json_writes_side_by_side_report(tmp_path: Path) -> None:
    app = _get_app()
    spec_path = tmp_path / "ab-spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "benchmark_name": "CLI A/B compare",
                "runs": [
                    {
                        "scenario_id": "brownfield-fix",
                        "scenario_type": "brownfield",
                        "objective": "Fix a regression with tests.",
                        "vanilla": {
                            "workflow": "vanilla-codex",
                            "metrics": {
                                "completion": {"value": True, "evidence": "measured"},
                                "tests": {"value": 1, "evidence": "measured"},
                                "bugs": {"value": 1, "evidence": "measured"},
                                "auditability": {"value": 1, "evidence": "measured"},
                                "control": {"value": 1, "evidence": "measured"},
                            },
                        },
                        "ces": {
                            "workflow": "ces-codex",
                            "metrics": {
                                "completion": {"value": True, "evidence": "measured"},
                                "tests": {"value": 3, "evidence": "measured"},
                                "bugs": {"value": 0, "evidence": "measured"},
                                "auditability": {"value": 5, "evidence": "measured"},
                                "control": {"value": 5, "evidence": "measured"},
                            },
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    out_dir = tmp_path / "report"

    result = runner.invoke(
        app,
        [
            "--json",
            "benchmark",
            "compare",
            "--project-spec",
            str(spec_path),
            "--out",
            str(out_dir),
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["benchmark_name"] == "CLI A/B compare"
    assert payload["summary"]["recommendation"] == "ces-adds-measured-value"
    assert payload["summary"]["comparable_scenario_count"] == 1
    assert Path(payload["json_report_path"]).is_file()
    assert Path(payload["markdown_report_path"]).is_file()


def test_benchmark_compare_text_output_highlights_recommendation(tmp_path: Path) -> None:
    app = _get_app()
    spec_path = tmp_path / "ab-spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "benchmark_name": "Text A/B compare",
                "runs": [
                    {
                        "scenario_id": "greenfield-cli",
                        "scenario_type": "greenfield",
                        "objective": "Build a CLI app.",
                        "vanilla": {
                            "workflow": "vanilla-claude",
                            "metrics": {
                                "completion": {"value": True, "evidence": "measured"},
                                "friction": {"value": 2, "evidence": "measured"},
                                "bugs": {"value": 1, "evidence": "measured"},
                                "auditability": {"value": 1, "evidence": "measured"},
                                "control": {"value": 1, "evidence": "measured"},
                            },
                        },
                        "ces": {
                            "workflow": "ces-claude",
                            "metrics": {
                                "completion": {"value": True, "evidence": "measured"},
                                "friction": {"value": 3, "evidence": "measured"},
                                "bugs": {"value": 0, "evidence": "measured"},
                                "auditability": {"value": 5, "evidence": "measured"},
                                "control": {"value": 5, "evidence": "measured"},
                            },
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["benchmark", "compare", "--project-spec", str(spec_path), "--out", str(tmp_path / "out")],
    )

    assert result.exit_code == 0, result.stdout
    assert "A/B Benchmark Comparison" in result.stdout
    assert "ces-adds-measured-value" in result.stdout
    assert "Comparable completion scenarios" in result.stdout
    assert "Comparable" in result.stdout
    assert "comparison-report.md" in result.stdout
