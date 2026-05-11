"""Regression-aware attribution for harness change verdicts."""

from __future__ import annotations

from ces.harness_evolution.models import HarnessChangeManifest, HarnessChangeVerdict
from ces.harness_evolution.trajectory import TrajectoryReport


def compute_change_verdict(manifest: HarnessChangeManifest, report: TrajectoryReport) -> HarnessChangeVerdict:
    """Compare a change manifest's predictions with one distilled trajectory report."""

    observed_text = _observation_text(report)
    observed_fixes = [fix for fix in manifest.predicted_fixes if _matches_prediction(fix, observed_text)]
    missed_fixes = [fix for fix in manifest.predicted_fixes if fix not in observed_fixes]
    observed_predicted_regressions = [
        regression for regression in manifest.predicted_regressions if _matches_prediction(regression, observed_text)
    ]
    unexpected_regressions = _unexpected_regressions(report, manifest.predicted_regressions)
    verdict = _net_verdict(
        report=report,
        observed_fixes=observed_fixes,
        missed_fixes=missed_fixes,
        observed_predicted_regressions=observed_predicted_regressions,
        unexpected_regressions=unexpected_regressions,
    )
    return HarnessChangeVerdict(
        change_id=manifest.change_id,
        observed_fixes=observed_fixes,
        missed_fixes=missed_fixes,
        observed_predicted_regressions=observed_predicted_regressions,
        unexpected_regressions=unexpected_regressions,
        verdict=verdict,
        rationale=_rationale(
            verdict=verdict,
            observed_fixes=observed_fixes,
            missed_fixes=missed_fixes,
            observed_predicted_regressions=observed_predicted_regressions,
            unexpected_regressions=unexpected_regressions,
        ),
    )


def _observation_text(report: TrajectoryReport) -> str:
    parts: list[str] = [
        report.outcome,
        report.failure_class,
        report.suspected_root_cause,
        *report.validation_commands_observed,
        *report.proxy_validation_warnings,
        *report.evidence_pointers,
    ]
    if report.validation_commands_observed:
        parts.append("validation commands observed")
    if report.proxy_validation_warnings:
        parts.append("proxy validation phrase detected")
    return "\n".join(parts).casefold()


def _matches_prediction(prediction: str, observed_text: str) -> bool:
    normalized = prediction.casefold().strip()
    if not normalized:
        return False
    return normalized in observed_text


def _unexpected_regressions(report: TrajectoryReport, predicted_regressions: list[str]) -> list[str]:
    if report.outcome != "fail":
        return []
    candidate = report.suspected_root_cause.strip()
    if not candidate or candidate == "insufficient evidence":
        return []
    predicted_text = "\n".join(predicted_regressions).casefold()
    if candidate.casefold() in predicted_text:
        return []
    return [candidate]


def _net_verdict(
    *,
    report: TrajectoryReport,
    observed_fixes: list[str],
    missed_fixes: list[str],
    observed_predicted_regressions: list[str],
    unexpected_regressions: list[str],
) -> str:
    if observed_predicted_regressions or unexpected_regressions:
        return "rollback"
    if report.outcome == "unknown" and not observed_fixes:
        return "inconclusive"
    if missed_fixes:
        return "revise"
    return "keep"


def _rationale(
    *,
    verdict: str,
    observed_fixes: list[str],
    missed_fixes: list[str],
    observed_predicted_regressions: list[str],
    unexpected_regressions: list[str],
) -> str:
    return (
        f"{verdict}: {len(observed_fixes)} predicted fixes observed, "
        f"{len(missed_fixes)} missed, "
        f"{len(observed_predicted_regressions)} predicted regressions observed, "
        f"{len(unexpected_regressions)} unexpected regressions."
    )
