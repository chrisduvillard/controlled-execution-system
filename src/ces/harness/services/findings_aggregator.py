"""Findings aggregator -- combines triad review results deterministically.

Aggregates findings from multiple reviewers, detects disagreements,
ranks by severity, and produces an AggregatedReview for evidence synthesis.

No LLM calls -- pure deterministic aggregation.
"""

from __future__ import annotations

from ces.harness.models.review_finding import (
    ReviewFinding,
    ReviewFindingSeverity,
    ReviewResult,
)
from ces.shared.base import CESBaseModel

# ---------------------------------------------------------------------------
# AggregatedReview -- combined result from all reviewers
# ---------------------------------------------------------------------------


class AggregatedReview(CESBaseModel):
    """Combined result from all reviewers in a review cycle.

    Fields:
        review_results: Tuple of individual reviewer results.
        all_findings: All findings from all reviewers, ranked by severity.
        critical_count: Number of CRITICAL findings.
        high_count: Number of HIGH findings.
        disagreements: Human-readable descriptions of reviewer disagreements.
        unanimous_zero_findings: True if ALL reviewers reported zero findings (suspicious).
        degraded_model_diversity: True when the triad could not be staffed
            with the full number of distinct underlying models required by
            the risk tier (e.g. Tier A asked for 3 models but only 1 CLI
            provider was installed). Consumers (evidence synthesizer,
            approval gate) should surface this to the reviewer so the
            degraded triad is not silently trusted at the same level as a
            diverse one.
    """

    review_results: tuple[ReviewResult, ...]
    all_findings: tuple[ReviewFinding, ...]
    critical_count: int
    high_count: int
    disagreements: tuple[str, ...] = ()
    unanimous_zero_findings: bool = False
    degraded_model_diversity: bool = False


# ---------------------------------------------------------------------------
# FindingsAggregator -- deterministic, stateless aggregation
# ---------------------------------------------------------------------------


class FindingsAggregator:
    """Aggregates findings from multiple review executions.

    Deterministic, stateless -- all methods are static.
    """

    @staticmethod
    def aggregate(results: list[ReviewResult]) -> AggregatedReview:
        """Combine findings from multiple reviewers into a single aggregated result.

        Args:
            results: List of ReviewResult from individual reviewers.

        Returns:
            AggregatedReview with ranked findings, counts, and disagreement detection.
        """
        all_findings: list[ReviewFinding] = []
        for result in results:
            all_findings.extend(result.findings)

        ranked = FindingsAggregator.rank_findings(all_findings)
        disagreements = FindingsAggregator.detect_disagreements(results)

        critical_count = sum(1 for f in ranked if f.severity == ReviewFindingSeverity.CRITICAL)
        high_count = sum(1 for f in ranked if f.severity == ReviewFindingSeverity.HIGH)

        unanimous_zero = len(results) > 0 and all(len(r.findings) == 0 for r in results)

        return AggregatedReview(
            review_results=tuple(results),
            all_findings=tuple(ranked),
            critical_count=critical_count,
            high_count=high_count,
            disagreements=tuple(disagreements),
            unanimous_zero_findings=unanimous_zero,
        )

    @staticmethod
    def detect_disagreements(results: list[ReviewResult]) -> list[str]:
        """Detect disagreements between reviewers.

        A disagreement occurs when one reviewer flags CRITICAL or HIGH severity
        findings for a file but another reviewer has zero findings for the same
        file AND that other reviewer has findings on OTHER files (so they didn't
        just skip everything).

        Args:
            results: List of ReviewResult from individual reviewers.

        Returns:
            List of human-readable disagreement descriptions.
        """
        if len(results) < 2:
            return []

        # Build per-reviewer maps:
        # 1. files with CRITICAL or HIGH findings
        # 2. all files with ANY findings
        critical_high_files: dict[str, set[str]] = {}
        all_finding_files: dict[str, set[str]] = {}

        for result in results:
            role = result.assignment.role.value
            ch_files: set[str] = set()
            any_files: set[str] = set()

            for finding in result.findings:
                file_path = finding.file_path or "<no-file>"
                any_files.add(file_path)
                if finding.severity in (
                    ReviewFindingSeverity.CRITICAL,
                    ReviewFindingSeverity.HIGH,
                ):
                    ch_files.add(file_path)

            critical_high_files[role] = ch_files
            all_finding_files[role] = any_files

        disagreements: list[str] = []

        # For each pair of reviewers, check for disagreements
        roles = list(critical_high_files.keys())
        for i, role_a in enumerate(roles):
            for role_b in roles[i + 1 :]:
                # Check: A has critical/high on a file, B has nothing on that file
                # AND B has findings on OTHER files (B didn't just skip everything)
                for file_path in critical_high_files[role_a]:
                    if file_path not in all_finding_files[role_b] and len(all_finding_files[role_b]) > 0:
                        disagreements.append(
                            f"{role_a} flagged critical/high on {file_path} but {role_b} had no findings on that file"
                        )

                # Check the reverse: B has critical/high, A has nothing
                for file_path in critical_high_files[role_b]:
                    if file_path not in all_finding_files[role_a] and len(all_finding_files[role_a]) > 0:
                        disagreements.append(
                            f"{role_b} flagged critical/high on {file_path} but {role_a} had no findings on that file"
                        )

        return disagreements

    @staticmethod
    def rank_findings(findings: list[ReviewFinding]) -> list[ReviewFinding]:
        """Rank findings by severity (CRITICAL first) then confidence (highest first).

        Args:
            findings: Unordered list of findings.

        Returns:
            Findings sorted by severity (CRITICAL > HIGH > MEDIUM > LOW > INFO),
            then by confidence descending within same severity.
        """
        severity_order = {
            ReviewFindingSeverity.CRITICAL: 0,
            ReviewFindingSeverity.HIGH: 1,
            ReviewFindingSeverity.MEDIUM: 2,
            ReviewFindingSeverity.LOW: 3,
            ReviewFindingSeverity.INFO: 4,
        }
        return sorted(
            findings,
            key=lambda f: (severity_order[f.severity], -f.confidence),
        )
