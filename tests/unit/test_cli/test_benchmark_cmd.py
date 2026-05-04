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
