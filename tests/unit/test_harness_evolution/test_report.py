"""Tests for harness operator report generation."""

from __future__ import annotations

from datetime import UTC, datetime

from ces.harness_evolution.memory import HarnessMemoryLesson
from ces.harness_evolution.models import HarnessChangeManifest, HarnessChangeVerdict, HarnessComponentType
from ces.harness_evolution.report import build_harness_operator_report
from ces.harness_evolution.repository import HarnessEvolutionRepository
from ces.local_store import LocalProjectStore


def _repo(tmp_path):
    return HarnessEvolutionRepository(LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="default"))


def test_operator_report_summarizes_outcomes_and_rollback_candidates(tmp_path) -> None:
    repo = _repo(tmp_path)
    manifest = HarnessChangeManifest(
        change_id="hchg-report",
        title="Improve completion gate",
        component_type=HarnessComponentType.MIDDLEWARE,
        files_changed=["src/ces/execution/pipeline.py"],
        evidence_refs=["analysis:run-1"],
        failure_pattern="Completion claims were shallow",
        root_cause_hypothesis="Prompt fragment was duplicated",
        predicted_fixes=["Completion evidence improves"],
        predicted_regressions=["Prompt length increases"],
        validation_plan=["Run prompt-pack tests"],
        rollback_condition="Unexpected prompt injection risk",
        created_at=datetime(2026, 5, 11, tzinfo=UTC),
        status="active",
    )
    repo.save_change(manifest)
    repo.save_verdict(
        HarnessChangeVerdict(
            change_id="hchg-report",
            observed_fixes=["Completion evidence improves"],
            missed_fixes=[],
            observed_predicted_regressions=[],
            unexpected_regressions=["Builder prompt grew too much"],
            verdict="rollback",
            rationale="Unexpected regression observed",
            created_at=datetime(2026, 5, 11, tzinfo=UTC),
        )
    )
    repo.save_memory_lesson(
        HarnessMemoryLesson(
            lesson_id="hmem-report",
            kind="memory",
            title="Prefer shared gate fragments",
            body="Use shared gate fragments when prompt text repeats.",
            evidence_refs=["analysis:run-1"],
            status="active",
            created_at=datetime(2026, 5, 11, tzinfo=UTC),
        )
    )

    report = build_harness_operator_report(repo)

    assert report.active_components == [{"component_type": "middleware", "active_or_proposed_changes": "1"}]
    assert report.change_history[0]["latest_verdict"] == "rollback"
    assert report.prediction_outcomes[0]["unexpected_regressions"] == 1
    assert report.prediction_outcomes[0]["unexpected_regression_items"] == ["Builder prompt grew too much"]
    assert report.regressions == [
        {"change_id": "hchg-report", "kind": "unexpected", "regression": "Builder prompt grew too much"}
    ]
    assert report.rollback_candidates[0]["change_id"] == "hchg-report"
    markdown = report.to_markdown()
    assert "# CES Harness Operator Report" in markdown
    assert "## Rollback candidates" in markdown
    assert "hmem-report" in markdown


def test_operator_report_recommends_verdicts_for_unobserved_changes(tmp_path) -> None:
    repo = _repo(tmp_path)
    repo.save_change(
        HarnessChangeManifest(
            change_id="hchg-unobserved",
            title="Add sensor",
            component_type=HarnessComponentType.MIDDLEWARE,
            files_changed=["src/ces/harness/sensors/example.py"],
            evidence_refs=["analysis:run-2"],
            failure_pattern="No sensor evidence",
            root_cause_hypothesis="Missing guard",
            predicted_fixes=["Evidence appears"],
            predicted_regressions=["False positives"],
            validation_plan=["Run sensor tests"],
            rollback_condition="False positive blocks run",
            status="proposed",
        )
    )

    report = build_harness_operator_report(repo)

    assert any("Compute verdicts" in item for item in report.current_recommendations)
    assert report.rollback_candidates == []
