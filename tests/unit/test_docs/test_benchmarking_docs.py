"""Docs contract for A/B value gauntlet benchmarking."""

from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_benchmarking_docs_define_value_question_and_metrics() -> None:
    docs = (_REPO_ROOT / "docs" / "Benchmarking.md").read_text(encoding="utf-8")

    assert "Is CES adding value over vanilla Codex CLI or Claude Code?" in docs
    assert "5 greenfield" in docs
    assert "5 brownfield" in docs
    for field in (
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
    ):
        assert field in docs
    assert "measured" in docs
    assert "inferred" in docs
    assert "missing" in docs
    assert "no-successful-completion" in docs
    assert "recommendation-comparable" in docs
    assert "recommendation-comparable flag" in docs
    assert "two-sided measured completion" in docs
    assert "measured successful completions" in docs


def test_sample_ab_gauntlet_spec_has_five_greenfield_and_five_brownfield_scenarios() -> None:
    payload = json.loads((_REPO_ROOT / "docs" / "benchmark" / "ab-gauntlet-sample.json").read_text(encoding="utf-8"))

    runs = payload["runs"]
    assert len(runs) == 10
    assert sum(1 for run in runs if run["scenario_type"] == "greenfield") == 5
    assert sum(1 for run in runs if run["scenario_type"] == "brownfield") == 5
    assert {run["scenario_id"] for run in runs} == {
        "greenfield-python-cli",
        "greenfield-crud-api",
        "greenfield-static-site",
        "greenfield-data-cleaner",
        "greenfield-chat-ui",
        "brownfield-bug-fix",
        "brownfield-feature-addition",
        "brownfield-refactor-no-behavior-change",
        "brownfield-docs-only",
        "brownfield-test-rescue",
    }
    for run in runs:
        assert set(run) >= {"scenario_id", "scenario_type", "objective", "acceptance_criteria", "vanilla", "ces"}
        assert set(run["vanilla"]["metrics"]) == {
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
        }
        assert set(run["ces"]["metrics"]) == set(run["vanilla"]["metrics"])
