"""Tests for review output parsing hardening."""

from __future__ import annotations

from ces.harness.models.review_assignment import ReviewerRole
from ces.harness.models.review_finding import ReviewFindingSeverity
from ces.harness.services.review_executor import _parse_findings


def test_unparsed_review_output_is_blocking() -> None:
    findings = _parse_findings("not json at all", ReviewerRole.RED_TEAM)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.category == "unparsed_review"
    assert finding.severity == ReviewFindingSeverity.HIGH
