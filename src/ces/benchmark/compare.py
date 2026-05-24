"""Side-by-side A/B benchmark comparison reports for CES value gauntlets."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

EvidenceKind = Literal["measured", "inferred", "missing"]
Advantage = Literal["ces", "vanilla", "tie", "unmeasured"]
ScenarioType = Literal["greenfield", "brownfield"]

AB_GAUNTLET_METRICS = (
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

_LOWER_IS_BETTER = {"time_minutes", "tokens", "tool_calls", "corrections", "bugs", "friction"}
_HIGHER_IS_BETTER = set(AB_GAUNTLET_METRICS) - _LOWER_IS_BETTER
_SCORE_METRICS = {"maintainability", "friction", "auditability", "control"}
_NON_NEGATIVE_NUMBER_METRICS = {
    "time_minutes",
    "tokens",
    "tool_calls",
    "corrections",
    "tests",
    "docs",
    "bugs",
}


@dataclass(frozen=True)
class MetricMeasurement:
    """One metric value plus its evidence status."""

    value: bool | int | float | str | None
    evidence: EvidenceKind = "missing"
    note: str | None = None

    @property
    def is_measured(self) -> bool:
        return self.evidence == "measured"


@dataclass(frozen=True)
class WorkflowMetrics:
    """Metrics captured for one workflow arm."""

    workflow: str
    metrics: dict[str, MetricMeasurement]


@dataclass(frozen=True)
class BenchmarkRunSpec:
    """One side-by-side scenario in the A/B gauntlet."""

    scenario_id: str
    scenario_type: ScenarioType
    objective: str
    acceptance_criteria: tuple[str, ...]
    vanilla: WorkflowMetrics
    ces: WorkflowMetrics


@dataclass(frozen=True)
class ComparisonSpec:
    """A complete A/B benchmark comparison input."""

    benchmark_name: str
    runs: tuple[BenchmarkRunSpec, ...]


@dataclass(frozen=True)
class MetricDelta:
    """Side-by-side comparison for one metric."""

    metric: str
    vanilla: MetricMeasurement
    ces: MetricMeasurement
    advantage: Advantage
    delta: float | None = None


@dataclass(frozen=True)
class ComparisonRow:
    """Comparison output for one scenario."""

    scenario_id: str
    scenario_type: ScenarioType
    objective: str
    acceptance_criteria: tuple[str, ...]
    vanilla_workflow: str
    ces_workflow: str
    deltas: dict[str, MetricDelta]

    @property
    def has_measured_comparison(self) -> bool:
        return any(delta.advantage != "unmeasured" for delta in self.deltas.values())

    @property
    def has_inferred_metric(self) -> bool:
        return any(
            delta.vanilla.evidence == "inferred" or delta.ces.evidence == "inferred" for delta in self.deltas.values()
        )

    @property
    def has_missing_metric(self) -> bool:
        return any(
            delta.vanilla.evidence == "missing" or delta.ces.evidence == "missing" for delta in self.deltas.values()
        )

    @property
    def has_inferred_or_missing_only(self) -> bool:
        return not self.has_measured_comparison


@dataclass(frozen=True)
class ComparisonReport:
    """Side-by-side CES vs vanilla benchmark comparison report."""

    benchmark_name: str
    rows: tuple[ComparisonRow, ...]
    summary: dict[str, Any]
    json_report_path: Path | None = None
    markdown_report_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "benchmark_name": self.benchmark_name,
            "summary": self.summary,
            "rows": [_row_to_dict(row) for row in self.rows],
        }
        if self.json_report_path is not None:
            payload["json_report_path"] = str(self.json_report_path)
        if self.markdown_report_path is not None:
            payload["markdown_report_path"] = str(self.markdown_report_path)
        return payload


def load_comparison_spec(path: Path) -> ComparisonSpec:
    """Load a structured A/B comparison spec from JSON."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    benchmark_name = str(payload.get("benchmark_name") or path.stem)
    runs = tuple(_parse_run(run) for run in payload.get("runs", ()))
    if not runs:
        raise ValueError("Benchmark comparison spec must contain at least one run.")
    return ComparisonSpec(benchmark_name=benchmark_name, runs=runs)


def run_comparison(spec: ComparisonSpec, *, output_dir: Path | None = None) -> ComparisonReport:
    """Compare CES and vanilla workflow arms and optionally persist report artifacts."""

    rows = tuple(_compare_run(run) for run in spec.runs)
    report = ComparisonReport(benchmark_name=spec.benchmark_name, rows=rows, summary=_summary(rows))
    if output_dir is None:
        return report

    output_dir.mkdir(parents=True, exist_ok=True)
    json_report_path = output_dir / "comparison-report.json"
    markdown_report_path = output_dir / "comparison-report.md"
    persisted = ComparisonReport(
        benchmark_name=report.benchmark_name,
        rows=report.rows,
        summary=report.summary,
        json_report_path=json_report_path,
        markdown_report_path=markdown_report_path,
    )
    json_report_path.write_text(json.dumps(persisted.to_dict(), indent=2, default=str), encoding="utf-8")
    markdown_report_path.write_text(render_markdown_report(persisted), encoding="utf-8")
    return persisted


def render_markdown_report(report: ComparisonReport) -> str:
    """Render a human-readable comparison report."""

    lines = [
        f"# {report.benchmark_name}",
        "",
        f"Recommendation: `{report.summary['recommendation']}`",
        f"Measured scenarios: {report.summary['measured_scenario_count']} / {report.summary['scenario_count']}",
        f"Comparable completion scenarios: {report.summary['comparable_scenario_count']}",
        f"Inferred scenarios: {report.summary['inferred_scenario_count']}",
        f"Missing-data scenarios: {report.summary['missing_scenario_count']}",
        f"CES completed scenarios: {report.summary['ces_completed_scenarios']}",
        f"Vanilla completed scenarios: {report.summary['vanilla_completed_scenarios']}",
        f"CES metric wins: {report.summary['ces_metric_wins']}",
        f"Vanilla metric wins: {report.summary['vanilla_metric_wins']}",
        f"Ties: {report.summary['metric_ties']}",
        f"Unmeasured comparisons: {report.summary['unmeasured_comparisons']}",
        "",
        "Only scenarios with completion measured for both arms count toward the recommendation.",
        "Inferred rows are hypothesis only; they do not count as measured CES value.",
    ]
    for row in report.rows:
        lines.extend(
            [
                "",
                f"## {row.scenario_id}",
                "",
                f"Type: `{row.scenario_type}`",
                f"Objective: {row.objective}",
                f"Recommendation-comparable: {_format_bool(_is_recommendation_comparable(row))}",
                f"Vanilla workflow: `{row.vanilla_workflow}`",
                f"CES workflow: `{row.ces_workflow}`",
                "",
                "| Metric | Vanilla | CES | Evidence | Advantage |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for metric in AB_GAUNTLET_METRICS:
            delta = row.deltas[metric]
            evidence = f"vanilla:{delta.vanilla.evidence} / ces:{delta.ces.evidence}"
            lines.append(
                f"| {metric} | {_format_value(delta.vanilla.value)} | {_format_value(delta.ces.value)} | "
                f"{evidence} | {delta.advantage} |"
            )
    lines.append("")
    return "\n".join(lines)


def _parse_run(payload: dict[str, Any]) -> BenchmarkRunSpec:
    return BenchmarkRunSpec(
        scenario_id=str(payload["scenario_id"]),
        scenario_type=_scenario_type(payload.get("scenario_type")),
        objective=str(payload["objective"]),
        acceptance_criteria=tuple(str(item) for item in payload.get("acceptance_criteria", ())),
        vanilla=_parse_workflow(payload["vanilla"]),
        ces=_parse_workflow(payload["ces"]),
    )


def _scenario_type(value: Any) -> ScenarioType:
    if value not in {"greenfield", "brownfield"}:
        raise ValueError("scenario_type must be 'greenfield' or 'brownfield'.")
    return value


def _parse_workflow(payload: dict[str, Any]) -> WorkflowMetrics:
    metrics_payload = payload.get("metrics", {})
    unknown_metrics = sorted(set(metrics_payload) - set(AB_GAUNTLET_METRICS))
    if unknown_metrics:
        raise ValueError(f"Unknown benchmark metric(s): {', '.join(unknown_metrics)}")
    metrics = {metric: _parse_measurement(metric, metrics_payload.get(metric)) for metric in AB_GAUNTLET_METRICS}
    return WorkflowMetrics(workflow=str(payload["workflow"]), metrics=metrics)


def _parse_measurement(metric: str, payload: Any) -> MetricMeasurement:
    if payload is None:
        return MetricMeasurement(value=None, evidence="missing")
    evidence = payload.get("evidence", "missing")
    if evidence not in {"measured", "inferred", "missing"}:
        raise ValueError("metric evidence must be measured, inferred, or missing.")
    value = payload.get("value")
    _validate_metric_value(metric, value=value, evidence=evidence)
    return MetricMeasurement(value=value, evidence=evidence, note=payload.get("note"))


def _validate_metric_value(metric: str, *, value: Any, evidence: EvidenceKind) -> None:
    if evidence == "missing":
        if value is not None:
            raise ValueError(f"Missing metric {metric!r} must use a null value.")
        return
    if metric == "completion":
        if not isinstance(value, bool):
            raise ValueError("Metric 'completion' must be a boolean.")
        return
    if isinstance(value, bool):
        raise ValueError(f"Metric {metric!r} must be numeric, not boolean.")
    numeric = _number(value)
    if numeric is None:
        raise ValueError(f"Metric {metric!r} must be numeric.")
    if not math.isfinite(numeric):
        raise ValueError(f"Metric {metric!r} must be finite.")
    if metric in _SCORE_METRICS and not 0 <= numeric <= 5:
        raise ValueError(f"Metric {metric!r} must be between 0 and 5.")
    if metric in _NON_NEGATIVE_NUMBER_METRICS and numeric < 0:
        raise ValueError(f"Metric {metric!r} must be non-negative.")


def _compare_run(run: BenchmarkRunSpec) -> ComparisonRow:
    deltas = {
        metric: _compare_metric(metric, vanilla=run.vanilla.metrics[metric], ces=run.ces.metrics[metric])
        for metric in AB_GAUNTLET_METRICS
    }
    return ComparisonRow(
        scenario_id=run.scenario_id,
        scenario_type=run.scenario_type,
        objective=run.objective,
        acceptance_criteria=run.acceptance_criteria,
        vanilla_workflow=run.vanilla.workflow,
        ces_workflow=run.ces.workflow,
        deltas=deltas,
    )


def _compare_metric(metric: str, *, vanilla: MetricMeasurement, ces: MetricMeasurement) -> MetricDelta:
    vanilla_number = _number(vanilla.value)
    ces_number = _number(ces.value)
    if not vanilla.is_measured or not ces.is_measured or vanilla_number is None or ces_number is None:
        return MetricDelta(metric=metric, vanilla=vanilla, ces=ces, advantage="unmeasured")

    delta = round(ces_number - vanilla_number, 4)
    if delta == 0:
        advantage: Advantage = "tie"
    elif metric in _HIGHER_IS_BETTER:
        advantage = "ces" if delta > 0 else "vanilla"
    else:
        advantage = "ces" if delta < 0 else "vanilla"
    return MetricDelta(metric=metric, vanilla=vanilla, ces=ces, advantage=advantage, delta=delta)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, int | float):
        return float(value)
    return None


def _summary(rows: tuple[ComparisonRow, ...]) -> dict[str, Any]:
    all_deltas = [delta for row in rows for delta in row.deltas.values()]
    measured_rows = [row for row in rows if row.has_measured_comparison]
    comparable_rows = [row for row in rows if _is_recommendation_comparable(row)]
    comparable_deltas = [delta for row in comparable_rows for delta in row.deltas.values()]
    ces_wins = sum(1 for delta in comparable_deltas if delta.advantage == "ces")
    vanilla_wins = sum(1 for delta in comparable_deltas if delta.advantage == "vanilla")
    ties = sum(1 for delta in comparable_deltas if delta.advantage == "tie")
    unmeasured = sum(1 for delta in all_deltas if delta.advantage == "unmeasured")
    ces_completed = sum(1 for row in comparable_rows if _measured_completion(row.deltas["completion"].ces) is True)
    vanilla_completed = sum(
        1 for row in comparable_rows if _measured_completion(row.deltas["completion"].vanilla) is True
    )
    if not measured_rows or not comparable_rows:
        recommendation = "insufficient-measured-evidence"
    elif ces_completed == 0 and vanilla_completed == 0:
        recommendation = "no-successful-completion"
    elif ces_completed > vanilla_completed:
        recommendation = "ces-adds-measured-value"
    elif vanilla_completed > ces_completed:
        recommendation = "vanilla-outperformed-ces"
    elif ces_wins > vanilla_wins:
        recommendation = "ces-adds-measured-value"
    elif vanilla_wins > ces_wins:
        recommendation = "vanilla-outperformed-ces"
    else:
        recommendation = "inconclusive-measured-tie"
    return {
        "scenario_count": len(rows),
        "measured_scenario_count": len(measured_rows),
        "comparable_scenario_count": len(comparable_rows),
        "inferred_scenario_count": sum(1 for row in rows if row.has_inferred_metric),
        "missing_scenario_count": sum(1 for row in rows if row.has_missing_metric),
        "ces_completed_scenarios": ces_completed,
        "vanilla_completed_scenarios": vanilla_completed,
        "ces_metric_wins": ces_wins,
        "vanilla_metric_wins": vanilla_wins,
        "metric_ties": ties,
        "unmeasured_comparisons": unmeasured,
        "recommendation": recommendation,
    }


def _measured_completion(measurement: MetricMeasurement) -> bool | None:
    if measurement.evidence != "measured" or not isinstance(measurement.value, bool):
        return None
    return measurement.value


def _measures_both_arms(delta: MetricDelta) -> bool:
    return _measured_completion(delta.vanilla) is not None and _measured_completion(delta.ces) is not None


def _is_recommendation_comparable(row: ComparisonRow) -> bool:
    return _measures_both_arms(row.deltas["completion"])


def _format_bool(value: bool) -> str:
    return "true" if value else "false"


def _row_to_dict(row: ComparisonRow) -> dict[str, Any]:
    return {
        "scenario_id": row.scenario_id,
        "scenario_type": row.scenario_type,
        "objective": row.objective,
        "acceptance_criteria": list(row.acceptance_criteria),
        "recommendation_comparable": _is_recommendation_comparable(row),
        "vanilla_workflow": row.vanilla_workflow,
        "ces_workflow": row.ces_workflow,
        "deltas": {metric: _delta_to_dict(delta) for metric, delta in row.deltas.items()},
    }


def _delta_to_dict(delta: MetricDelta) -> dict[str, Any]:
    return {
        "metric": delta.metric,
        "vanilla": asdict(delta.vanilla),
        "ces": asdict(delta.ces),
        "advantage": delta.advantage,
        "delta": delta.delta,
    }


def _format_value(value: bool | int | float | str | None) -> str:
    if value is None:
        return ""
    return str(value)
