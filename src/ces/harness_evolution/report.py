"""Operator report generation for local harness evolution state."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Literal

from ces.execution.secrets import scrub_secrets_from_text
from ces.harness_evolution.repository import HarnessEvolutionRepository
from ces.local_store.records import (
    LocalHarnessChangeRecord,
    LocalHarnessChangeVerdictRecord,
    LocalHarnessMemoryLessonRecord,
)

ReportFormat = Literal["markdown", "json"]


@dataclass(frozen=True)
class HarnessOperatorReport:
    """Concise operator-facing snapshot of harness evolution state."""

    active_components: list[dict[str, str]]
    change_history: list[dict[str, str]]
    prediction_outcomes: list[dict[str, object]]
    regressions: list[dict[str, str]]
    current_recommendations: list[str]
    rollback_candidates: list[dict[str, str]]
    memory_lessons: list[dict[str, str]]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "active_components": self.active_components,
            "change_history": self.change_history,
            "prediction_outcomes": self.prediction_outcomes,
            "regressions": self.regressions,
            "current_recommendations": self.current_recommendations,
            "rollback_candidates": self.rollback_candidates,
            "memory_lessons": self.memory_lessons,
        }

    def to_markdown(self) -> str:
        lines = ["# CES Harness Operator Report", ""]
        lines.extend(_section("Active harness components", _format_component_rows(self.active_components)))
        lines.extend(_section("Change history", _format_change_rows(self.change_history)))
        lines.extend(_section("Predictions vs observed outcomes", _format_prediction_rows(self.prediction_outcomes)))
        lines.extend(_section("Regressions", _format_regression_rows(self.regressions)))
        lines.extend(_section("Current recommendations", self.current_recommendations))
        lines.extend(_section("Rollback candidates", _format_rollback_rows(self.rollback_candidates)))
        lines.extend(_section("Active memory lessons", _format_memory_rows(self.memory_lessons)))
        return "\n".join(lines).rstrip() + "\n"


def build_harness_operator_report(repository: HarnessEvolutionRepository) -> HarnessOperatorReport:
    """Build a concise report from persisted local harness evolution records."""

    changes = repository.list_changes()
    verdicts_by_change = {change.change_id: repository.list_verdicts(change.change_id) for change in changes}
    memory_lessons = repository.list_memory_lessons(status="active")
    return HarnessOperatorReport(
        active_components=_active_components(changes),
        change_history=_change_history(changes, verdicts_by_change),
        prediction_outcomes=_prediction_outcomes(changes, verdicts_by_change),
        regressions=_regressions(verdicts_by_change),
        current_recommendations=_recommendations(changes, verdicts_by_change, memory_lessons),
        rollback_candidates=_rollback_candidates(changes, verdicts_by_change),
        memory_lessons=_memory_lessons(memory_lessons),
    )


def _safe(value: object) -> str:
    return scrub_secrets_from_text(str(value))


def _latest_verdict(verdicts: list[LocalHarnessChangeVerdictRecord]) -> LocalHarnessChangeVerdictRecord | None:
    return verdicts[-1] if verdicts else None


def _active_components(changes: list[LocalHarnessChangeRecord]) -> list[dict[str, str]]:
    counts: Counter[str] = Counter()
    for change in changes:
        if change.status in {"active", "proposed"}:
            counts[change.component_type] += 1
    return [
        {"component_type": component, "active_or_proposed_changes": str(count)}
        for component, count in sorted(counts.items())
    ]


def _change_history(
    changes: list[LocalHarnessChangeRecord],
    verdicts_by_change: dict[str, list[LocalHarnessChangeVerdictRecord]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for change in changes:
        latest = _latest_verdict(verdicts_by_change.get(change.change_id, []))
        rows.append(
            {
                "change_id": _safe(change.change_id),
                "title": _safe(change.title),
                "component_type": _safe(change.component_type),
                "status": _safe(change.status),
                "latest_verdict": _safe(latest.verdict if latest else "none"),
                "updated_at": _safe(change.updated_at),
            }
        )
    return rows


def _prediction_outcomes(
    changes: list[LocalHarnessChangeRecord],
    verdicts_by_change: dict[str, list[LocalHarnessChangeVerdictRecord]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for change in changes:
        latest = _latest_verdict(verdicts_by_change.get(change.change_id, []))
        rows.append(
            {
                "change_id": _safe(change.change_id),
                "predicted_fixes": len(change.manifest.predicted_fixes),
                "predicted_fix_items": [_safe(item) for item in change.manifest.predicted_fixes],
                "predicted_regressions": len(change.manifest.predicted_regressions),
                "predicted_regression_items": [_safe(item) for item in change.manifest.predicted_regressions],
                "observed_fixes": len(latest.verdict_payload.observed_fixes) if latest else 0,
                "observed_fix_items": [_safe(item) for item in latest.verdict_payload.observed_fixes] if latest else [],
                "missed_fixes": len(latest.verdict_payload.missed_fixes) if latest else 0,
                "missed_fix_items": [_safe(item) for item in latest.verdict_payload.missed_fixes] if latest else [],
                "observed_predicted_regressions": len(latest.verdict_payload.observed_predicted_regressions)
                if latest
                else 0,
                "observed_predicted_regression_items": [
                    _safe(item) for item in latest.verdict_payload.observed_predicted_regressions
                ]
                if latest
                else [],
                "unexpected_regressions": len(latest.verdict_payload.unexpected_regressions) if latest else 0,
                "unexpected_regression_items": [_safe(item) for item in latest.verdict_payload.unexpected_regressions]
                if latest
                else [],
            }
        )
    return rows


def _regressions(verdicts_by_change: dict[str, list[LocalHarnessChangeVerdictRecord]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for change_id, verdicts in sorted(verdicts_by_change.items()):
        latest = _latest_verdict(verdicts)
        if latest is None:
            continue
        for item in latest.verdict_payload.observed_predicted_regressions:
            rows.append({"change_id": _safe(change_id), "kind": "predicted", "regression": _safe(item)})
        for item in latest.verdict_payload.unexpected_regressions:
            rows.append({"change_id": _safe(change_id), "kind": "unexpected", "regression": _safe(item)})
    return rows


def _recommendations(
    changes: list[LocalHarnessChangeRecord],
    verdicts_by_change: dict[str, list[LocalHarnessChangeVerdictRecord]],
    memory_lessons: list[LocalHarnessMemoryLessonRecord],
) -> list[str]:
    recommendations: list[str] = []
    changes_without_verdict = [change.change_id for change in changes if not verdicts_by_change.get(change.change_id)]
    if changes_without_verdict:
        recommendations.append(
            "Compute verdicts for changes without observed outcomes: "
            + ", ".join(_safe(item) for item in changes_without_verdict[:5])
        )
    latest_by_status: defaultdict[str, list[str]] = defaultdict(list)
    for change in changes:
        latest = _latest_verdict(verdicts_by_change.get(change.change_id, []))
        if latest is not None:
            latest_by_status[latest.verdict].append(change.change_id)
    if latest_by_status.get("rollback"):
        recommendations.append("Review rollback candidates before further harness changes.")
    if latest_by_status.get("revise"):
        recommendations.append(
            "Revise inconclusive or partially regressive changes: "
            + ", ".join(_safe(item) for item in latest_by_status["revise"][:5])
        )
    if not memory_lessons:
        recommendations.append("No active harness memory lessons; activate reviewed lessons only when evidence-backed.")
    if not recommendations:
        recommendations.append("No immediate harness action recommended; continue evidence-backed monitoring.")
    return recommendations


def _rollback_candidates(
    changes: list[LocalHarnessChangeRecord],
    verdicts_by_change: dict[str, list[LocalHarnessChangeVerdictRecord]],
) -> list[dict[str, str]]:
    change_lookup = {change.change_id: change for change in changes}
    candidates: list[dict[str, str]] = []
    for change_id, verdicts in sorted(verdicts_by_change.items()):
        latest = _latest_verdict(verdicts)
        if latest is None:
            continue
        verdict = latest.verdict_payload
        if verdict.verdict == "rollback" or verdict.unexpected_regressions or verdict.observed_predicted_regressions:
            change = change_lookup.get(change_id)
            candidates.append(
                {
                    "change_id": _safe(change_id),
                    "title": _safe(change.title if change else "unknown"),
                    "reason": _safe(verdict.rationale),
                    "rollback_condition": _safe(change.manifest.rollback_condition if change else "unknown"),
                }
            )
    return candidates


def _memory_lessons(memory_lessons: list[LocalHarnessMemoryLessonRecord]) -> list[dict[str, str]]:
    return [
        {
            "lesson_id": _safe(record.lesson_id),
            "kind": _safe(record.kind),
            "title": _safe(record.title),
            "content_hash": _safe(record.content_hash),
        }
        for record in memory_lessons
    ]


def _section(title: str, rows: list[str]) -> list[str]:
    section = [f"## {title}", ""]
    section.extend(rows or ["- None"])
    section.append("")
    return section


def _format_component_rows(rows: list[dict[str, str]]) -> list[str]:
    return [f"- {row['component_type']}: {row['active_or_proposed_changes']} active/proposed change(s)" for row in rows]


def _format_change_rows(rows: list[dict[str, str]]) -> list[str]:
    return [
        f"- {row['change_id']} [{row['status']}] {row['component_type']} — {row['title']} (latest verdict: {row['latest_verdict']})"
        for row in rows
    ]


def _format_prediction_rows(rows: list[dict[str, object]]) -> list[str]:
    return [
        "- {change_id}: fixes {observed_fixes}/{predicted_fixes} observed, missed {missed_fixes}; "
        "regressions predicted-observed {observed_predicted_regressions}/{predicted_regressions}, unexpected {unexpected_regressions}".format(
            **row
        )
        for row in rows
    ]


def _format_regression_rows(rows: list[dict[str, str]]) -> list[str]:
    return [f"- {row['change_id']} [{row['kind']}]: {row['regression']}" for row in rows]


def _format_rollback_rows(rows: list[dict[str, str]]) -> list[str]:
    return [
        f"- {row['change_id']} — {row['title']}: {row['reason']} (condition: {row['rollback_condition']})"
        for row in rows
    ]


def _format_memory_rows(rows: list[dict[str, str]]) -> list[str]:
    return [f"- {row['lesson_id']} [{row['kind']}] {row['title']} (hash: {row['content_hash']})" for row in rows]
