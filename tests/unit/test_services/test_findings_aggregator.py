"""Tests for FindingsAggregator -- deterministic review findings aggregation.

Covers:
- Aggregation of single and triad review results
- Critical and high severity counting
- Unanimous zero-findings detection
- Severity-based ranking with confidence tiebreaks
- Disagreement detection between reviewers
- Immutability of AggregatedReview (frozen CESBaseModel)
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ces.harness.models.review_assignment import ReviewAssignment, ReviewerRole
from ces.harness.models.review_finding import (
    ReviewFinding,
    ReviewFindingSeverity,
    ReviewResult,
)
from ces.harness.services.findings_aggregator import (
    AggregatedReview,
    FindingsAggregator,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COUNTER = 0


def _make_finding(
    role: ReviewerRole = ReviewerRole.STRUCTURAL,
    severity: ReviewFindingSeverity = ReviewFindingSeverity.MEDIUM,
    file_path: str | None = "src/main.py",
    confidence: float = 0.8,
    **kwargs: object,
) -> ReviewFinding:
    """Create a ReviewFinding with sensible defaults for testing."""
    global _COUNTER  # noqa: PLW0603
    _COUNTER += 1
    defaults: dict[str, object] = {
        "finding_id": f"finding-{_COUNTER}",
        "reviewer_role": role,
        "severity": severity,
        "category": "test_category",
        "file_path": file_path,
        "line_number": 42,
        "title": f"Test finding {_COUNTER}",
        "description": "A test finding description.",
        "recommendation": "Fix it.",
        "confidence": confidence,
    }
    defaults.update(kwargs)
    return ReviewFinding(**defaults)  # type: ignore[arg-type]


def _make_result(
    role: ReviewerRole = ReviewerRole.STRUCTURAL,
    findings: tuple[ReviewFinding, ...] = (),
    **kwargs: object,
) -> ReviewResult:
    """Create a ReviewResult with sensible defaults for testing."""
    defaults: dict[str, object] = {
        "assignment": ReviewAssignment(
            role=role,
            model_id=f"model-{role.value}",
            agent_id=f"reviewer-{role.value}-model-{role.value}",
        ),
        "findings": findings,
        "summary": "Test review summary.",
        "review_duration_seconds": 1.5,
        "model_version": "test-v1",
        "tokens_used": 100,
        "timestamp": datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc),
    }
    defaults.update(kwargs)
    return ReviewResult(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# FindingsAggregator.aggregate
# ---------------------------------------------------------------------------


class TestAggregateSingleReviewer:
    """Tests for aggregating a single reviewer result."""

    def test_aggregate_single_reviewer(self) -> None:
        """One result -- findings are preserved in the aggregation."""
        f1 = _make_finding(severity=ReviewFindingSeverity.HIGH)
        f2 = _make_finding(severity=ReviewFindingSeverity.LOW)
        result = _make_result(findings=(f1, f2))

        aggregated = FindingsAggregator.aggregate([result])

        assert len(aggregated.review_results) == 1
        assert len(aggregated.all_findings) == 2
        assert aggregated.review_results[0] is result


class TestAggregateTriad:
    """Tests for aggregating triad (3 reviewer) results."""

    def test_aggregate_triad_combines_all_findings(self) -> None:
        """Three results -- all findings merged into all_findings."""
        f1 = _make_finding(role=ReviewerRole.STRUCTURAL)
        f2 = _make_finding(role=ReviewerRole.SEMANTIC)
        f3 = _make_finding(role=ReviewerRole.RED_TEAM)

        r1 = _make_result(role=ReviewerRole.STRUCTURAL, findings=(f1,))
        r2 = _make_result(role=ReviewerRole.SEMANTIC, findings=(f2,))
        r3 = _make_result(role=ReviewerRole.RED_TEAM, findings=(f3,))

        aggregated = FindingsAggregator.aggregate([r1, r2, r3])

        assert len(aggregated.review_results) == 3
        assert len(aggregated.all_findings) == 3


class TestAggregateEmptyResults:
    """Tests for aggregating an empty results list."""

    def test_aggregate_empty_results_list(self) -> None:
        """Empty results list produces empty AggregatedReview."""
        aggregated = FindingsAggregator.aggregate([])

        assert len(aggregated.review_results) == 0
        assert len(aggregated.all_findings) == 0
        assert aggregated.critical_count == 0
        assert aggregated.high_count == 0
        assert aggregated.disagreements == ()
        assert aggregated.unanimous_zero_findings is False


# ---------------------------------------------------------------------------
# Severity counts
# ---------------------------------------------------------------------------


class TestCriticalCount:
    """Tests for critical_count computation."""

    def test_critical_count_computed(self) -> None:
        """critical_count matches actual number of CRITICAL findings."""
        f_crit1 = _make_finding(severity=ReviewFindingSeverity.CRITICAL)
        f_crit2 = _make_finding(severity=ReviewFindingSeverity.CRITICAL)
        f_high = _make_finding(severity=ReviewFindingSeverity.HIGH)
        f_med = _make_finding(severity=ReviewFindingSeverity.MEDIUM)

        result = _make_result(findings=(f_crit1, f_crit2, f_high, f_med))
        aggregated = FindingsAggregator.aggregate([result])

        assert aggregated.critical_count == 2


class TestHighCount:
    """Tests for high_count computation."""

    def test_high_count_computed(self) -> None:
        """high_count matches actual number of HIGH findings."""
        f_high1 = _make_finding(severity=ReviewFindingSeverity.HIGH)
        f_high2 = _make_finding(severity=ReviewFindingSeverity.HIGH)
        f_high3 = _make_finding(severity=ReviewFindingSeverity.HIGH)
        f_crit = _make_finding(severity=ReviewFindingSeverity.CRITICAL)
        f_low = _make_finding(severity=ReviewFindingSeverity.LOW)

        result = _make_result(findings=(f_high1, f_high2, f_high3, f_crit, f_low))
        aggregated = FindingsAggregator.aggregate([result])

        assert aggregated.high_count == 3


# ---------------------------------------------------------------------------
# Unanimous zero-findings detection
# ---------------------------------------------------------------------------


class TestUnanimousZeroFindings:
    """Tests for unanimous_zero_findings detection."""

    def test_unanimous_zero_findings_detected(self) -> None:
        """All reviewers with zero findings -> True (suspicious)."""
        r1 = _make_result(role=ReviewerRole.STRUCTURAL, findings=())
        r2 = _make_result(role=ReviewerRole.SEMANTIC, findings=())
        r3 = _make_result(role=ReviewerRole.RED_TEAM, findings=())

        aggregated = FindingsAggregator.aggregate([r1, r2, r3])

        assert aggregated.unanimous_zero_findings is True

    def test_not_unanimous_when_one_has_findings(self) -> None:
        """One reviewer has findings -> False."""
        f1 = _make_finding(role=ReviewerRole.SEMANTIC)
        r1 = _make_result(role=ReviewerRole.STRUCTURAL, findings=())
        r2 = _make_result(role=ReviewerRole.SEMANTIC, findings=(f1,))
        r3 = _make_result(role=ReviewerRole.RED_TEAM, findings=())

        aggregated = FindingsAggregator.aggregate([r1, r2, r3])

        assert aggregated.unanimous_zero_findings is False

    def test_not_unanimous_when_empty_results(self) -> None:
        """No reviewers at all -> False (not suspicious, just empty)."""
        aggregated = FindingsAggregator.aggregate([])

        assert aggregated.unanimous_zero_findings is False


# ---------------------------------------------------------------------------
# FindingsAggregator.rank_findings
# ---------------------------------------------------------------------------


class TestRankFindings:
    """Tests for FindingsAggregator.rank_findings."""

    def test_rank_findings_severity_order(self) -> None:
        """Findings ranked CRITICAL > HIGH > MEDIUM > LOW > INFO."""
        f_info = _make_finding(severity=ReviewFindingSeverity.INFO)
        f_low = _make_finding(severity=ReviewFindingSeverity.LOW)
        f_med = _make_finding(severity=ReviewFindingSeverity.MEDIUM)
        f_high = _make_finding(severity=ReviewFindingSeverity.HIGH)
        f_crit = _make_finding(severity=ReviewFindingSeverity.CRITICAL)

        # Pass in reverse order
        ranked = FindingsAggregator.rank_findings([f_info, f_low, f_med, f_high, f_crit])

        assert ranked[0].severity == ReviewFindingSeverity.CRITICAL
        assert ranked[1].severity == ReviewFindingSeverity.HIGH
        assert ranked[2].severity == ReviewFindingSeverity.MEDIUM
        assert ranked[3].severity == ReviewFindingSeverity.LOW
        assert ranked[4].severity == ReviewFindingSeverity.INFO

    def test_rank_findings_confidence_tiebreak(self) -> None:
        """Same severity sorted by confidence descending."""
        f_low_conf = _make_finding(severity=ReviewFindingSeverity.HIGH, confidence=0.3)
        f_mid_conf = _make_finding(severity=ReviewFindingSeverity.HIGH, confidence=0.6)
        f_high_conf = _make_finding(severity=ReviewFindingSeverity.HIGH, confidence=0.9)

        ranked = FindingsAggregator.rank_findings([f_low_conf, f_mid_conf, f_high_conf])

        assert ranked[0].confidence == 0.9
        assert ranked[1].confidence == 0.6
        assert ranked[2].confidence == 0.3


# ---------------------------------------------------------------------------
# FindingsAggregator.detect_disagreements
# ---------------------------------------------------------------------------


class TestDetectDisagreements:
    """Tests for FindingsAggregator.detect_disagreements."""

    def test_detect_disagreement_critical_vs_none(self) -> None:
        """Reviewer A has critical on file X, B has nothing on X but findings elsewhere."""
        f_a = _make_finding(
            role=ReviewerRole.STRUCTURAL,
            severity=ReviewFindingSeverity.CRITICAL,
            file_path="src/danger.py",
        )
        f_b = _make_finding(
            role=ReviewerRole.SEMANTIC,
            severity=ReviewFindingSeverity.MEDIUM,
            file_path="src/other.py",
        )

        r_a = _make_result(role=ReviewerRole.STRUCTURAL, findings=(f_a,))
        r_b = _make_result(role=ReviewerRole.SEMANTIC, findings=(f_b,))

        disagreements = FindingsAggregator.detect_disagreements([r_a, r_b])

        assert len(disagreements) >= 1
        assert any("src/danger.py" in d for d in disagreements)
        assert any("structural" in d for d in disagreements)

    def test_no_disagreement_when_all_agree(self) -> None:
        """All reviewers find issues on the same file -- no disagreement."""
        f_a = _make_finding(
            role=ReviewerRole.STRUCTURAL,
            severity=ReviewFindingSeverity.HIGH,
            file_path="src/shared.py",
        )
        f_b = _make_finding(
            role=ReviewerRole.SEMANTIC,
            severity=ReviewFindingSeverity.MEDIUM,
            file_path="src/shared.py",
        )

        r_a = _make_result(role=ReviewerRole.STRUCTURAL, findings=(f_a,))
        r_b = _make_result(role=ReviewerRole.SEMANTIC, findings=(f_b,))

        disagreements = FindingsAggregator.detect_disagreements([r_a, r_b])

        assert disagreements == []

    def test_no_disagreement_when_reviewer_has_no_findings_at_all(self) -> None:
        """Reviewer B has zero findings total -- not a disagreement (B didn't skip selectively)."""
        f_a = _make_finding(
            role=ReviewerRole.STRUCTURAL,
            severity=ReviewFindingSeverity.CRITICAL,
            file_path="src/danger.py",
        )

        r_a = _make_result(role=ReviewerRole.STRUCTURAL, findings=(f_a,))
        r_b = _make_result(role=ReviewerRole.SEMANTIC, findings=())

        disagreements = FindingsAggregator.detect_disagreements([r_a, r_b])

        assert disagreements == []

    def test_no_disagreement_single_reviewer(self) -> None:
        """Single reviewer cannot disagree with itself."""
        f1 = _make_finding(severity=ReviewFindingSeverity.CRITICAL)
        r1 = _make_result(findings=(f1,))

        disagreements = FindingsAggregator.detect_disagreements([r1])

        assert disagreements == []

    def test_no_disagreement_empty_results(self) -> None:
        """Empty results list produces no disagreements."""
        disagreements = FindingsAggregator.detect_disagreements([])

        assert disagreements == []

    def test_detect_disagreement_reverse_direction(self) -> None:
        """The reviewer LATER in the pair (role_b) flags critical; earlier (role_a) is silent on that file but has other findings.

        Forces the reverse-direction check (lines 150-151), which the existing
        critical_vs_none test does not exercise because there role_a holds
        the critical finding.
        """
        # role_a (STRUCTURAL) -- only a medium on src/other.py (no critical/high)
        f_a = _make_finding(
            role=ReviewerRole.STRUCTURAL,
            severity=ReviewFindingSeverity.MEDIUM,
            file_path="src/other.py",
        )
        # role_b (SEMANTIC) -- critical on src/danger.py
        f_b = _make_finding(
            role=ReviewerRole.SEMANTIC,
            severity=ReviewFindingSeverity.CRITICAL,
            file_path="src/danger.py",
        )

        r_a = _make_result(role=ReviewerRole.STRUCTURAL, findings=(f_a,))
        r_b = _make_result(role=ReviewerRole.SEMANTIC, findings=(f_b,))

        disagreements = FindingsAggregator.detect_disagreements([r_a, r_b])

        assert any("semantic" in d and "src/danger.py" in d for d in disagreements)


# ---------------------------------------------------------------------------
# AggregatedReview immutability
# ---------------------------------------------------------------------------


class TestAggregatedReviewFrozen:
    """Tests that AggregatedReview is frozen (immutable CESBaseModel)."""

    def test_aggregated_review_frozen(self) -> None:
        """Cannot mutate AggregatedReview fields after creation."""
        aggregated = FindingsAggregator.aggregate([])

        with pytest.raises(ValidationError):
            aggregated.critical_count = 999  # type: ignore[misc]
