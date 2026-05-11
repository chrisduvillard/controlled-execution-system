"""Tests for harness change attribution and regression-aware verdicts."""

from __future__ import annotations

from ces.harness_evolution.attribution import compute_change_verdict
from ces.harness_evolution.models import HarnessChangeManifest
from ces.harness_evolution.trajectory import TrajectoryReport


def _manifest() -> HarnessChangeManifest:
    return HarnessChangeManifest(
        change_id="hchg-attribution-1",
        title="Detect proxy validation",
        component_type="tool_policy",
        files_changed=["src/ces/harness_evolution/patterns.py"],
        evidence_refs=["runs/dogfood-42.log"],
        failure_pattern="proxy validation accepted after failed tests",
        root_cause_hypothesis="agents treat inspection as validation",
        predicted_fixes=["proxy validation phrase detected", "validation commands observed"],
        predicted_regressions=["false positive proxy warning", "missed validation commands"],
        validation_plan=["run transcript distillation fixtures"],
        rollback_condition="operator sees regression blindness",
    )


def test_compute_change_verdict_scores_fixes_and_regressions_explicitly() -> None:
    report = TrajectoryReport(
        task_run_id="dogfood-42",
        outcome="fail",
        failure_class="validation_failure",
        suspected_root_cause="validation command failed",
        validation_commands_observed=["uv run pytest tests/unit -q"],
        proxy_validation_warnings=["line 5: proxy validation phrase detected"],
        evidence_pointers=["source: runs/dogfood-42.log", "unexpected regression: false positive proxy warning"],
    )

    verdict = compute_change_verdict(_manifest(), report)

    assert verdict.change_id == "hchg-attribution-1"
    assert verdict.observed_fixes == ["proxy validation phrase detected", "validation commands observed"]
    assert verdict.missed_fixes == []
    assert verdict.observed_predicted_regressions == ["false positive proxy warning"]
    assert verdict.unexpected_regressions == ["validation command failed"]
    assert verdict.verdict == "rollback"
    assert "regression" in verdict.rationale


def test_compute_change_verdict_can_keep_when_fixes_observed_without_regressions() -> None:
    report = TrajectoryReport(
        task_run_id="dogfood-43",
        outcome="pass",
        failure_class="none",
        suspected_root_cause="no failure detected",
        validation_commands_observed=["uv run pytest tests/unit -q"],
        proxy_validation_warnings=["line 2: proxy validation phrase detected"],
        evidence_pointers=["validation commands observed"],
    )

    verdict = compute_change_verdict(_manifest(), report)

    assert verdict.observed_fixes == ["proxy validation phrase detected", "validation commands observed"]
    assert verdict.missed_fixes == []
    assert verdict.observed_predicted_regressions == []
    assert verdict.unexpected_regressions == []
    assert verdict.verdict == "keep"


def test_compute_change_verdict_is_inconclusive_without_observations() -> None:
    report = TrajectoryReport(
        task_run_id=None,
        outcome="unknown",
        failure_class="unknown",
        suspected_root_cause="insufficient evidence",
        validation_commands_observed=[],
        proxy_validation_warnings=[],
        evidence_pointers=[],
    )

    verdict = compute_change_verdict(_manifest(), report)

    assert verdict.observed_fixes == []
    assert verdict.missed_fixes == _manifest().predicted_fixes
    assert verdict.verdict == "inconclusive"
