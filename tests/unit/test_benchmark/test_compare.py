"""A/B benchmark comparison model regressions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ces.benchmark.compare import (
    AB_GAUNTLET_METRICS,
    load_comparison_spec,
    render_markdown_report,
    run_comparison,
)


def _write_spec(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "benchmark_name": "CES value A/B pilot",
                "runs": [
                    {
                        "scenario_id": "greenfield-python-cli",
                        "scenario_type": "greenfield",
                        "objective": "Build a Python CLI with tests and README.",
                        "vanilla": {
                            "workflow": "vanilla-codex",
                            "metrics": {
                                "completion": {"value": True, "evidence": "measured"},
                                "time_minutes": {"value": 14, "evidence": "measured"},
                                "tokens": {"value": 12000, "evidence": "measured"},
                                "tool_calls": {"value": 22, "evidence": "measured"},
                                "corrections": {"value": 2, "evidence": "measured"},
                                "tests": {"value": 1, "evidence": "measured"},
                                "docs": {"value": 1, "evidence": "measured"},
                                "maintainability": {"value": 3, "evidence": "measured"},
                                "bugs": {"value": 1, "evidence": "measured"},
                                "friction": {"value": 2, "evidence": "measured"},
                                "auditability": {"value": 1, "evidence": "measured"},
                                "control": {"value": 1, "evidence": "measured"},
                            },
                        },
                        "ces": {
                            "workflow": "ces-codex",
                            "metrics": {
                                "completion": {"value": True, "evidence": "measured"},
                                "time_minutes": {"value": 18, "evidence": "measured"},
                                "tokens": {"value": 15000, "evidence": "measured"},
                                "tool_calls": {"value": 34, "evidence": "measured"},
                                "corrections": {"value": 0, "evidence": "measured"},
                                "tests": {"value": 3, "evidence": "measured"},
                                "docs": {"value": 1, "evidence": "measured"},
                                "maintainability": {"value": 4, "evidence": "measured"},
                                "bugs": {"value": 0, "evidence": "measured"},
                                "friction": {"value": 3, "evidence": "measured"},
                                "auditability": {"value": 5, "evidence": "measured"},
                                "control": {"value": 5, "evidence": "measured"},
                            },
                        },
                    },
                    {
                        "scenario_id": "brownfield-regression-fix",
                        "scenario_type": "brownfield",
                        "objective": "Fix a bug while preserving public CLI behavior.",
                        "vanilla": {
                            "workflow": "vanilla-claude",
                            "metrics": {
                                "completion": {"value": True, "evidence": "measured"},
                                "tests": {"value": 1, "evidence": "measured"},
                                "bugs": {"value": 1, "evidence": "measured"},
                                "auditability": {"value": 1, "evidence": "measured"},
                                "control": {"value": 1, "evidence": "measured"},
                            },
                        },
                        "ces": {
                            "workflow": "ces-claude",
                            "metrics": {
                                "completion": {"value": True, "evidence": "measured"},
                                "tests": {"value": 4, "evidence": "measured"},
                                "bugs": {"value": 0, "evidence": "measured"},
                                "auditability": {"value": 5, "evidence": "measured"},
                                "control": {"value": 5, "evidence": "measured"},
                            },
                        },
                    },
                    {
                        "scenario_id": "unmeasured-hypothesis",
                        "scenario_type": "greenfield",
                        "objective": "A hypothesis row must not be counted as measured evidence.",
                        "vanilla": {
                            "workflow": "vanilla-codex",
                            "metrics": {
                                "completion": {"value": True, "evidence": "inferred"},
                                "control": {"value": 1, "evidence": "inferred"},
                            },
                        },
                        "ces": {
                            "workflow": "ces-codex",
                            "metrics": {
                                "completion": {"value": True, "evidence": "inferred"},
                                "control": {"value": 5, "evidence": "inferred"},
                            },
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def test_comparison_report_separates_measured_findings_from_inferred_expectations(tmp_path: Path) -> None:
    spec_path = tmp_path / "ab-spec.json"
    _write_spec(spec_path)

    spec = load_comparison_spec(spec_path)
    report = run_comparison(spec)

    assert AB_GAUNTLET_METRICS == (
        "completion",
        "time_minutes",
        "tokens",
        "tool_calls",
        "corrections",
        "tests",
        "docs",
        "maintainability",
        "bugs",
        "friction",
        "auditability",
        "control",
    )
    assert report.summary["scenario_count"] == 3
    assert report.summary["measured_scenario_count"] == 2
    assert report.summary["inferred_scenario_count"] == 1
    assert report.summary["missing_scenario_count"] == 2
    assert report.summary["ces_completed_scenarios"] == 2
    assert report.summary["vanilla_completed_scenarios"] == 2
    assert report.summary["ces_metric_wins"] > report.summary["vanilla_metric_wins"]
    assert report.summary["recommendation"] == "ces-adds-measured-value"

    unmeasured = next(row for row in report.rows if row.scenario_id == "unmeasured-hypothesis")
    assert all(delta.advantage == "unmeasured" for delta in unmeasured.deltas.values())


def test_comparison_report_persists_json_and_markdown_scorecards(tmp_path: Path) -> None:
    spec_path = tmp_path / "ab-spec.json"
    out_dir = tmp_path / "out"
    _write_spec(spec_path)

    report = run_comparison(load_comparison_spec(spec_path), output_dir=out_dir)
    json_path = out_dir / "comparison-report.json"
    markdown_path = out_dir / "comparison-report.md"

    assert json_path.is_file()
    assert markdown_path.is_file()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["benchmark_name"] == "CES value A/B pilot"
    assert payload["summary"]["recommendation"] == "ces-adds-measured-value"
    assert payload["rows"][0]["recommendation_comparable"] is True
    assert payload["rows"][2]["recommendation_comparable"] is False
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "# CES value A/B pilot" in markdown
    assert "Measured scenarios: 2 / 3" in markdown
    assert "unmeasured-hypothesis" in markdown


def test_markdown_report_contains_side_by_side_fields(tmp_path: Path) -> None:
    spec_path = tmp_path / "ab-spec.json"
    _write_spec(spec_path)

    report = run_comparison(load_comparison_spec(spec_path))
    markdown = render_markdown_report(report)

    assert "| Metric | Vanilla | CES | Evidence | Advantage |" in markdown
    for metric in AB_GAUNTLET_METRICS:
        assert f"| {metric} |" in markdown
    assert "Inferred rows are hypothesis only" in markdown
    assert "Recommendation-comparable: true" in markdown
    assert "Recommendation-comparable: false" in markdown


def test_completion_failure_blocks_ces_value_recommendation(tmp_path: Path) -> None:
    spec_path = tmp_path / "completion-gate.json"
    spec_path.write_text(
        json.dumps(
            {
                "benchmark_name": "Completion gate",
                "runs": [
                    {
                        "scenario_id": "failed-ces",
                        "scenario_type": "brownfield",
                        "objective": "Fix the regression.",
                        "vanilla": {
                            "workflow": "vanilla-codex",
                            "metrics": {
                                "completion": {"value": True, "evidence": "measured"},
                                "time_minutes": {"value": 30, "evidence": "measured"},
                                "tokens": {"value": 20000, "evidence": "measured"},
                                "tool_calls": {"value": 40, "evidence": "measured"},
                                "corrections": {"value": 4, "evidence": "measured"},
                                "tests": {"value": 1, "evidence": "measured"},
                                "docs": {"value": 0, "evidence": "measured"},
                                "maintainability": {"value": 1, "evidence": "measured"},
                                "bugs": {"value": 3, "evidence": "measured"},
                                "friction": {"value": 5, "evidence": "measured"},
                                "auditability": {"value": 1, "evidence": "measured"},
                                "control": {"value": 1, "evidence": "measured"},
                            },
                        },
                        "ces": {
                            "workflow": "ces-codex",
                            "metrics": {
                                "completion": {"value": False, "evidence": "measured"},
                                "time_minutes": {"value": 5, "evidence": "measured"},
                                "tokens": {"value": 1000, "evidence": "measured"},
                                "tool_calls": {"value": 4, "evidence": "measured"},
                                "corrections": {"value": 0, "evidence": "measured"},
                                "tests": {"value": 5, "evidence": "measured"},
                                "docs": {"value": 2, "evidence": "measured"},
                                "maintainability": {"value": 5, "evidence": "measured"},
                                "bugs": {"value": 0, "evidence": "measured"},
                                "friction": {"value": 0, "evidence": "measured"},
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

    report = run_comparison(load_comparison_spec(spec_path))

    assert report.summary["ces_metric_wins"] > report.summary["vanilla_metric_wins"]
    assert report.summary["vanilla_completed_scenarios"] == 1
    assert report.summary["ces_completed_scenarios"] == 0
    assert report.summary["recommendation"] == "vanilla-outperformed-ces"


def test_no_successful_completion_blocks_value_recommendation_even_when_ces_wins_secondary_metrics(
    tmp_path: Path,
) -> None:
    spec_path = tmp_path / "no-success.json"
    spec_path.write_text(
        json.dumps(
            {
                "benchmark_name": "No successful completion",
                "runs": [
                    {
                        "scenario_id": "both-failed",
                        "scenario_type": "greenfield",
                        "objective": "A failed build cannot prove value.",
                        "vanilla": {
                            "workflow": "vanilla-codex",
                            "metrics": {
                                "completion": {"value": False, "evidence": "measured"},
                                "time_minutes": {"value": 30, "evidence": "measured"},
                            },
                        },
                        "ces": {
                            "workflow": "ces-codex",
                            "metrics": {
                                "completion": {"value": False, "evidence": "measured"},
                                "time_minutes": {"value": 5, "evidence": "measured"},
                            },
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = run_comparison(load_comparison_spec(spec_path))

    assert report.summary["ces_metric_wins"] > report.summary["vanilla_metric_wins"]
    assert report.summary["ces_completed_scenarios"] == 0
    assert report.summary["vanilla_completed_scenarios"] == 0
    assert report.summary["recommendation"] == "no-successful-completion"


def test_missing_completion_blocks_value_recommendation_even_when_secondary_metrics_are_measured(
    tmp_path: Path,
) -> None:
    spec_path = tmp_path / "missing-completion.json"
    spec_path.write_text(
        json.dumps(
            {
                "benchmark_name": "Missing completion",
                "runs": [
                    {
                        "scenario_id": "missing-completion",
                        "scenario_type": "greenfield",
                        "objective": "Completion must be measured before value claims.",
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

    report = run_comparison(load_comparison_spec(spec_path))

    assert report.summary["measured_scenario_count"] == 1
    assert report.summary["missing_scenario_count"] == 1
    assert report.summary["recommendation"] == "insufficient-measured-evidence"


def test_one_sided_completion_evidence_blocks_value_recommendation(tmp_path: Path) -> None:
    spec_path = tmp_path / "one-sided-completion.json"
    spec_path.write_text(
        json.dumps(
            {
                "benchmark_name": "One-sided completion",
                "runs": [
                    {
                        "scenario_id": "one-sided-completion",
                        "scenario_type": "greenfield",
                        "objective": "Do not treat missing opponent completion as failure.",
                        "vanilla": {
                            "workflow": "vanilla-codex",
                            "metrics": {"time_minutes": {"value": 30, "evidence": "measured"}},
                        },
                        "ces": {
                            "workflow": "ces-codex",
                            "metrics": {
                                "completion": {"value": True, "evidence": "measured"},
                                "time_minutes": {"value": 5, "evidence": "measured"},
                            },
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = run_comparison(load_comparison_spec(spec_path))

    assert report.rows[0].deltas["completion"].advantage == "unmeasured"
    assert report.summary["comparable_scenario_count"] == 0
    assert report.summary["ces_completed_scenarios"] == 0
    assert report.summary["vanilla_completed_scenarios"] == 0
    assert report.summary["recommendation"] == "insufficient-measured-evidence"


def test_mixed_one_sided_completion_does_not_drive_recommendation(tmp_path: Path) -> None:
    spec_path = tmp_path / "mixed-one-sided-completion.json"
    spec_path.write_text(
        json.dumps(
            {
                "benchmark_name": "Mixed one-sided completion",
                "runs": [
                    {
                        "scenario_id": "both-failed",
                        "scenario_type": "greenfield",
                        "objective": "Comparable failed row.",
                        "vanilla": {
                            "workflow": "vanilla-codex",
                            "metrics": {"completion": {"value": False, "evidence": "measured"}},
                        },
                        "ces": {
                            "workflow": "ces-codex",
                            "metrics": {"completion": {"value": False, "evidence": "measured"}},
                        },
                    },
                    {
                        "scenario_id": "one-sided-ces-success",
                        "scenario_type": "greenfield",
                        "objective": "One-sided success cannot prove CES value.",
                        "vanilla": {
                            "workflow": "vanilla-codex",
                            "metrics": {"time_minutes": {"value": 30, "evidence": "measured"}},
                        },
                        "ces": {
                            "workflow": "ces-codex",
                            "metrics": {
                                "completion": {"value": True, "evidence": "measured"},
                                "time_minutes": {"value": 5, "evidence": "measured"},
                            },
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    report = run_comparison(load_comparison_spec(spec_path))

    one_sided = next(row for row in report.rows if row.scenario_id == "one-sided-ces-success")
    assert one_sided.deltas["completion"].advantage == "unmeasured"
    assert report.summary["comparable_scenario_count"] == 1
    assert report.summary["ces_completed_scenarios"] == 0
    assert report.summary["vanilla_completed_scenarios"] == 0
    assert report.summary["recommendation"] == "no-successful-completion"


def test_failed_completion_rows_do_not_swing_tied_successful_completion_recommendation(
    tmp_path: Path,
) -> None:
    spec_path = tmp_path / "mixed-failed-completion-secondary-wins.json"
    spec_path.write_text(
        json.dumps(
            {
                "benchmark_name": "Mixed failed completion secondary wins",
                "runs": [
                    {
                        "scenario_id": "successful-completion-tie",
                        "scenario_type": "brownfield",
                        "objective": "Both arms complete successfully with no secondary edge.",
                        "vanilla": {
                            "workflow": "vanilla-codex",
                            "metrics": {
                                "completion": {"value": True, "evidence": "measured"},
                                "time_minutes": {"value": 10, "evidence": "measured"},
                            },
                        },
                        "ces": {
                            "workflow": "ces-codex",
                            "metrics": {
                                "completion": {"value": True, "evidence": "measured"},
                                "time_minutes": {"value": 10, "evidence": "measured"},
                            },
                        },
                    },
                    {
                        "scenario_id": "both-failed-secondary-win",
                        "scenario_type": "greenfield",
                        "objective": "Failed artifacts can expose friction but cannot prove CES value.",
                        "vanilla": {
                            "workflow": "vanilla-codex",
                            "metrics": {
                                "completion": {"value": False, "evidence": "measured"},
                                "time_minutes": {"value": 30, "evidence": "measured"},
                                "tokens": {"value": 20000, "evidence": "measured"},
                            },
                        },
                        "ces": {
                            "workflow": "ces-codex",
                            "metrics": {
                                "completion": {"value": False, "evidence": "measured"},
                                "time_minutes": {"value": 5, "evidence": "measured"},
                                "tokens": {"value": 1000, "evidence": "measured"},
                            },
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    report = run_comparison(load_comparison_spec(spec_path))
    payload = report.to_dict()
    failed_row = next(row for row in payload["rows"] if row["scenario_id"] == "both-failed-secondary-win")

    assert report.summary["comparable_scenario_count"] == 2
    assert report.summary["secondary_metric_counted_scenario_count"] == 1
    assert report.summary["ces_metric_wins"] > report.summary["vanilla_metric_wins"]
    assert report.summary["decision_ces_metric_wins"] == 0
    assert report.summary["decision_vanilla_metric_wins"] == 0
    assert report.summary["recommendation"] == "inconclusive-measured-tie"
    assert failed_row["recommendation_comparable"] is True
    assert failed_row["secondary_metrics_counted"] is False
    assert "neither arm completed successfully" in failed_row["recommendation_exclusion_reason"]
    assert report.summary["recommendation_basis"]["secondary_metric_counted_scenarios"] == ["successful-completion-tie"]


def test_split_primary_completion_tie_excludes_failed_row_secondary_metrics(
    tmp_path: Path,
) -> None:
    spec_path = tmp_path / "split-primary-tie.json"
    spec_path.write_text(
        json.dumps(
            {
                "benchmark_name": "Split primary completion tie",
                "runs": [
                    {
                        "scenario_id": "ces-only-success",
                        "scenario_type": "brownfield",
                        "objective": "CES completes while vanilla fails.",
                        "vanilla": {
                            "workflow": "vanilla-codex",
                            "metrics": {
                                "completion": {"value": False, "evidence": "measured"},
                                "time_minutes": {"value": 5, "evidence": "measured"},
                            },
                        },
                        "ces": {
                            "workflow": "ces-codex",
                            "metrics": {
                                "completion": {"value": True, "evidence": "measured"},
                                "time_minutes": {"value": 30, "evidence": "measured"},
                            },
                        },
                    },
                    {
                        "scenario_id": "vanilla-only-success",
                        "scenario_type": "greenfield",
                        "objective": "Vanilla completes while CES fails.",
                        "vanilla": {
                            "workflow": "vanilla-claude",
                            "metrics": {
                                "completion": {"value": True, "evidence": "measured"},
                                "tokens": {"value": 20000, "evidence": "measured"},
                            },
                        },
                        "ces": {
                            "workflow": "ces-claude",
                            "metrics": {
                                "completion": {"value": False, "evidence": "measured"},
                                "tokens": {"value": 1000, "evidence": "measured"},
                            },
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    report = run_comparison(load_comparison_spec(spec_path))

    assert report.summary["ces_completed_scenarios"] == 1
    assert report.summary["vanilla_completed_scenarios"] == 1
    assert report.summary["secondary_metric_counted_scenario_count"] == 0
    assert report.summary["decision_ces_metric_wins"] == 0
    assert report.summary["decision_vanilla_metric_wins"] == 0
    assert report.summary["recommendation"] == "inconclusive-measured-tie"


def test_missing_completion_rows_do_not_swing_tied_completion_recommendation(tmp_path: Path) -> None:
    spec_path = tmp_path / "mixed-missing-completion-secondary-wins.json"
    spec_path.write_text(
        json.dumps(
            {
                "benchmark_name": "Mixed missing completion secondary wins",
                "runs": [
                    {
                        "scenario_id": "tied-completion",
                        "scenario_type": "brownfield",
                        "objective": "Comparable completion tie.",
                        "vanilla": {
                            "workflow": "vanilla-codex",
                            "metrics": {"completion": {"value": True, "evidence": "measured"}},
                        },
                        "ces": {
                            "workflow": "ces-codex",
                            "metrics": {"completion": {"value": True, "evidence": "measured"}},
                        },
                    },
                    {
                        "scenario_id": "missing-completion-secondary-win",
                        "scenario_type": "brownfield",
                        "objective": "Secondary metrics without completion cannot swing the verdict.",
                        "vanilla": {
                            "workflow": "vanilla-codex",
                            "metrics": {"time_minutes": {"value": 30, "evidence": "measured"}},
                        },
                        "ces": {
                            "workflow": "ces-codex",
                            "metrics": {"time_minutes": {"value": 5, "evidence": "measured"}},
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    report = run_comparison(load_comparison_spec(spec_path))

    secondary_only = next(row for row in report.rows if row.scenario_id == "missing-completion-secondary-win")
    assert secondary_only.deltas["time_minutes"].advantage == "ces"
    assert report.summary["comparable_scenario_count"] == 1
    assert report.summary["ces_metric_wins"] == 0
    assert report.summary["vanilla_metric_wins"] == 0
    assert report.summary["recommendation"] == "inconclusive-measured-tie"


@pytest.mark.parametrize(
    ("metric", "value", "message"),
    [
        ("completion", 3, "boolean"),
        ("maintainability", 100, "between 0 and 5"),
        ("friction", -1, "between 0 and 5"),
        ("bugs", -4, "non-negative"),
        ("tests", True, "not boolean"),
    ],
)
def test_metric_validation_rejects_invalid_values(tmp_path: Path, metric: str, value: bool | int, message: str) -> None:
    spec_path = tmp_path / "invalid.json"
    spec_path.write_text(
        json.dumps(
            {
                "benchmark_name": "Invalid metrics",
                "runs": [
                    {
                        "scenario_id": "invalid",
                        "scenario_type": "greenfield",
                        "objective": "Reject invalid metric values.",
                        "vanilla": {
                            "workflow": "vanilla-codex",
                            "metrics": {metric: {"value": value, "evidence": "measured"}},
                        },
                        "ces": {
                            "workflow": "ces-codex",
                            "metrics": {metric: {"value": value, "evidence": "measured"}},
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        load_comparison_spec(spec_path)


def test_unknown_metric_key_is_rejected(tmp_path: Path) -> None:
    spec_path = tmp_path / "unknown.json"
    spec_path.write_text(
        json.dumps(
            {
                "benchmark_name": "Unknown metric",
                "runs": [
                    {
                        "scenario_id": "unknown",
                        "scenario_type": "greenfield",
                        "objective": "Reject typo metrics.",
                        "vanilla": {
                            "workflow": "vanilla-codex",
                            "metrics": {"controll": {"value": 5, "evidence": "measured"}},
                        },
                        "ces": {"workflow": "ces-codex", "metrics": {}},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unknown benchmark metric"):
        load_comparison_spec(spec_path)


def test_missing_only_rows_are_not_counted_as_inferred(tmp_path: Path) -> None:
    spec_path = tmp_path / "missing.json"
    spec_path.write_text(
        json.dumps(
            {
                "benchmark_name": "Missing only",
                "runs": [
                    {
                        "scenario_id": "missing-row",
                        "scenario_type": "greenfield",
                        "objective": "Missing data is not inferred data.",
                        "vanilla": {"workflow": "vanilla-codex", "metrics": {}},
                        "ces": {"workflow": "ces-codex", "metrics": {}},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = run_comparison(load_comparison_spec(spec_path))

    assert report.summary["measured_scenario_count"] == 0
    assert report.summary["inferred_scenario_count"] == 0
    assert report.summary["missing_scenario_count"] == 1
    assert report.summary["recommendation"] == "insufficient-measured-evidence"
