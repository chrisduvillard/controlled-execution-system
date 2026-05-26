"""Docs contract for A/B value gauntlet benchmarking."""

from __future__ import annotations

import json
from pathlib import Path

from ces.benchmark.compare import load_comparison_spec, run_comparison

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
    assert "ces benchmark compare" in docs
    assert "--project-spec" in docs
    assert "measured successful completions" in docs
    assert "secondary-metric-counted" in docs
    assert "Failed-row secondary metrics remain visible but do not prove CES value" in docs
    assert "ces benchmark preflight" in docs
    assert "--probe-runtime" in docs


def test_benchmark_docs_track_blocked_runtime_pilot_without_product_claims() -> None:
    readme = (_REPO_ROOT / "docs" / "benchmark" / "evidence" / "pilot-2026-05-26" / "README.md").read_text(
        encoding="utf-8"
    )
    plan = json.loads(
        (_REPO_ROOT / "docs" / "benchmark" / "evidence" / "pilot-2026-05-26" / "pilot-plan.json").read_text(
            encoding="utf-8"
        )
    )
    codex = json.loads(
        (_REPO_ROOT / "docs" / "benchmark" / "evidence" / "pilot-2026-05-26" / "preflight" / "codex.json").read_text(
            encoding="utf-8"
        )
    )
    claude = json.loads(
        (_REPO_ROOT / "docs" / "benchmark" / "evidence" / "pilot-2026-05-26" / "preflight" / "claude.json").read_text(
            encoding="utf-8"
        )
    )

    assert "not CES-vs-vanilla product evidence" in readme
    assert "runtime-blocked" in readme
    assert len(plan["scenarios"]) == 3
    assert codex["recommendation"] == "runtime-blocked"
    assert claude["recommendation"] == "runtime-blocked"


def test_benchmarking_docs_require_self_contained_evidence_packs() -> None:
    docs = (_REPO_ROOT / "docs" / "Benchmarking.md").read_text(encoding="utf-8")

    assert "For PR evidence packs" in docs
    assert "docs/benchmark/evidence/<run-id>/ab-gauntlet.json" in docs
    assert "comparison-report.json" in docs
    assert "comparison-report.md" in docs
    for required in (
        "exact prompts/commands per arm",
        "runtime/model versions",
        "CES version/commit",
        "scenario fixture/base commit",
        "verification outputs",
        "reviewer scoring notes",
        "known missing metrics",
    ):
        assert required in docs


def test_benchmarking_docs_distinguish_fake_runtime_from_ab_evidence() -> None:
    docs = (_REPO_ROOT / "docs" / "Benchmarking.md").read_text(encoding="utf-8")

    assert "Deterministic harness vs product evidence" in docs
    assert "ces benchmark greenfield" in docs
    assert "deterministic fake runtime" in docs
    assert "does not prove CES-vs-vanilla value" in docs


def test_sample_ab_gauntlet_spec_is_unmeasured_template_not_evidence() -> None:
    sample_path = _REPO_ROOT / "docs" / "benchmark" / "ab-gauntlet-sample.json"
    payload = json.loads(sample_path.read_text(encoding="utf-8"))
    docs = (_REPO_ROOT / "docs" / "Benchmarking.md").read_text(encoding="utf-8")

    assert payload["evidence_status"] == "template-unmeasured"
    assert payload["expected_recommendation_before_measurement"] == "insufficient-measured-evidence"
    assert "provenance_requirements" in payload
    assert "It is intentionally unmeasured" in docs
    assert "Treat it as a template, not as product evidence" in docs
    for run in payload["runs"]:
        for arm in ("vanilla", "ces"):
            for measurement in run[arm]["metrics"].values():
                assert measurement["value"] is None
                assert measurement["evidence"] == "missing"

    report = run_comparison(load_comparison_spec(sample_path))
    assert report.summary["scenario_count"] == 10
    assert report.summary["comparable_scenario_count"] == 0
    assert report.summary["recommendation"] == "insufficient-measured-evidence"


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
