"""User-facing blocker diagnostics for builder-first CES runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from ces.cli._builder_report import BuilderRunReport

BlockerCategory = Literal[
    "none",
    "runtime_failed",
    "evidence_failed_verification",
    "evidence_missing_artifacts",
    "review_rejected",
    "blocked",
]


@dataclass(frozen=True)
class BlockerDiagnostic:
    """Actionable explanation for the latest builder-run state."""

    category: BlockerCategory
    reason: str
    source: str
    next_command: str
    product_may_be_complete: bool = False
    evidence: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def diagnose_builder_report(report: BuilderRunReport) -> BlockerDiagnostic:
    """Convert a builder report into an operator-facing blocker diagnosis."""
    if report.review_state == "blocked" or report.latest_outcome == "blocked":
        return BlockerDiagnostic(
            category="blocked",
            reason=report.next_step or "CES is blocked and needs operator review.",
            source="builder_report",
            next_command="ces why",
            product_may_be_complete=True,
        )

    if _is_approved(report):
        return BlockerDiagnostic(
            category="none",
            reason="No active blocker; the latest builder run is approved.",
            source="builder_report",
            next_command="ces report builder",
            product_may_be_complete=True,
        )

    if _looks_like_runtime_failure(report):
        runtime = _runtime_label(report)
        return BlockerDiagnostic(
            category="runtime_failed",
            reason=f"The runtime did not complete successfully at stage `{report.stage}`.",
            source="runtime_execution",
            next_command=f"ces doctor --deep --runtime {runtime}",
            product_may_be_complete=False,
        )

    if report.verification_findings:
        return BlockerDiagnostic(
            category="evidence_failed_verification",
            reason="completion evidence failed verification.",
            source="completion_verifier",
            next_command="ces recover --dry-run",
            product_may_be_complete=True,
            evidence=tuple(report.verification_findings),
        )

    if report.evidence_quality_state in {"missing_artifacts", "missing_packet", "missing_evidence"}:
        return BlockerDiagnostic(
            category="evidence_missing_artifacts",
            reason=f"Evidence quality is `{report.evidence_quality_state}`.",
            source="evidence_quality",
            next_command="ces recover --dry-run",
            product_may_be_complete=True,
        )

    if report.review_state == "rejected" or report.latest_outcome == "rejected":
        return BlockerDiagnostic(
            category="review_rejected",
            reason="The latest builder review rejected the run.",
            source="builder_review",
            next_command="ces review --full",
            product_may_be_complete=False,
        )

    return BlockerDiagnostic(
        category="blocked",
        reason=report.next_step or "CES is blocked and needs operator review.",
        source="builder_report",
        next_command="ces status",
        product_may_be_complete=False,
    )


def _is_approved(report: BuilderRunReport) -> bool:
    return (
        report.review_state == "approved"
        or report.latest_outcome == "approved"
        or report.approval_decision == "approved"
        or report.workflow_state == "approved"
    )


def _looks_like_runtime_failure(report: BuilderRunReport) -> bool:
    combined = f"{report.stage} {report.latest_outcome} {report.latest_activity}".lower()
    return "runtime" in combined and any(token in combined for token in ("fail", "error", "unavailable"))


def _runtime_label(report: BuilderRunReport) -> str:
    model = (report.reported_model or "").strip().lower()
    if "claude" in model:
        return "claude"
    if "codex" in model or model.startswith("gpt"):
        return "codex"
    return "codex"
