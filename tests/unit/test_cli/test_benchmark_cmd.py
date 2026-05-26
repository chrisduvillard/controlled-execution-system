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


def test_benchmark_preflight_json_reports_blocked_runtime_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _get_app()

    def fake_preflight(**kwargs):  # type: ignore[no-untyped-def]
        assert kwargs["runtime"] == "codex"
        assert kwargs["project_root"] == tmp_path
        assert kwargs["probe_runtime"] is True
        return {
            "runtime": "codex",
            "project_root": str(tmp_path),
            "probe_runtime": True,
            "installed": True,
            "recommendation": "runtime-blocked",
            "checks": [
                {"name": "runtime-installed", "ok": True, "detail": "codex found on PATH"},
                {
                    "name": "workspace-write-probe",
                    "ok": False,
                    "detail": "runtime exited without creating benchmark probe file",
                    "exit_code": 0,
                },
            ],
        }

    monkeypatch.setattr("ces.cli.benchmark_cmd.run_runtime_preflight", fake_preflight)

    result = runner.invoke(
        app,
        [
            "--json",
            "benchmark",
            "preflight",
            "--runtime",
            "codex",
            "--project-root",
            str(tmp_path),
            "--probe-runtime",
        ],
    )

    assert result.exit_code == 1, result.stdout
    payload = json.loads(result.stdout)
    assert payload["recommendation"] == "runtime-blocked"
    assert payload["checks"][1]["name"] == "workspace-write-probe"


def test_benchmark_preflight_text_reports_not_probed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app = _get_app()

    def fake_preflight(**kwargs):  # type: ignore[no-untyped-def]
        assert kwargs["runtime"] == "claude"
        assert kwargs["probe_runtime"] is False
        return {
            "runtime": "claude",
            "project_root": str(tmp_path),
            "probe_runtime": False,
            "installed": True,
            "recommendation": "runtime-not-verified",
            "checks": [
                {"name": "runtime-installed", "ok": True, "detail": "claude found on PATH"},
                {
                    "name": "workspace-write-probe",
                    "ok": None,
                    "detail": "not run; pass --probe-runtime to verify workspace writes",
                },
            ],
        }

    monkeypatch.setattr("ces.cli.benchmark_cmd.run_runtime_preflight", fake_preflight)

    result = runner.invoke(
        app,
        ["benchmark", "preflight", "--runtime", "claude", "--project-root", str(tmp_path)],
    )

    assert result.exit_code == 0, result.stdout
    assert "Benchmark Runtime Preflight" in result.stdout
    assert "runtime-not-verified" in result.stdout
    assert "workspace-write-probe" in result.stdout


def test_benchmark_compare_text_output_hides_uncounted_secondary_wins(tmp_path: Path) -> None:
    app = _get_app()
    spec_path = tmp_path / "ab-missing-completion.json"
    spec_path.write_text(
        json.dumps(
            {
                "benchmark_name": "Text missing-completion A/B compare",
                "runs": [
                    {
                        "scenario_id": "missing-completion-secondary-win",
                        "scenario_type": "greenfield",
                        "objective": "Completion missing, secondary metric measured.",
                        "vanilla": {
                            "workflow": "vanilla-codex",
                            "metrics": {"time_minutes": {"value": 30, "evidence": "measured"}},
                        },
                        "ces": {
                            "workflow": "ces-codex",
                            "metrics": {"time_minutes": {"value": 5, "evidence": "measured"}},
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
    assert "Secondary counted" in result.stdout
    assert "Counted CES wins" in result.stdout
    assert "completion not measured for one or both arms" in result.stdout
    assert "missing-completion-secondary-win" in result.stdout
    assert "│ False      │ 1        │" not in result.stdout
