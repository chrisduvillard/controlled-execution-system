"""Tests for CompletionClaim, VerificationFinding, VerificationResult frozen models.

Models live in src/ces/harness/models/completion_claim.py and form the contract
between the agent (which emits a CompletionClaim) and the CompletionVerifier
(which produces a VerificationResult).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ces.harness.models.completion_claim import (
    CompletionClaim,
    CriterionEvidence,
    EvidenceKind,
    VerificationFinding,
    VerificationFindingKind,
    VerificationResult,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TestCriterionEvidence:
    """CriterionEvidence — one row of the agent's claim."""

    def test_create_with_valid_data(self) -> None:
        ev = CriterionEvidence(
            criterion="all tests pass",
            evidence="ran `uv run pytest`; 412 passed, 0 failed",
            evidence_kind=EvidenceKind.COMMAND_OUTPUT,
        )
        assert ev.criterion == "all tests pass"
        assert ev.evidence_kind == EvidenceKind.COMMAND_OUTPUT

    def test_frozen(self) -> None:
        ev = CriterionEvidence(
            criterion="x",
            evidence="y",
            evidence_kind=EvidenceKind.MANUAL_INSPECTION,
        )
        with pytest.raises(ValidationError):
            ev.criterion = "changed"  # type: ignore[misc]

    def test_empty_criterion_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CriterionEvidence(
                criterion="",
                evidence="some evidence",
                evidence_kind=EvidenceKind.FILE_ARTIFACT,
            )

    def test_empty_evidence_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CriterionEvidence(
                criterion="some criterion",
                evidence="",
                evidence_kind=EvidenceKind.FILE_ARTIFACT,
            )


class TestCompletionClaim:
    """CompletionClaim — the structured 'I'm done' payload from the agent."""

    def test_create_with_minimal_fields(self) -> None:
        claim = CompletionClaim(
            task_id="MANIF-001",
            summary="Implemented login endpoint",
            files_changed=("src/auth/login.py",),
        )
        assert claim.task_id == "MANIF-001"
        assert claim.criteria_satisfied == ()
        assert claim.open_questions == ()
        assert claim.scope_deviations == ()

    def test_create_with_full_fields(self) -> None:
        ev = CriterionEvidence(
            criterion="tests pass",
            evidence="412 passed",
            evidence_kind=EvidenceKind.COMMAND_OUTPUT,
        )
        claim = CompletionClaim(
            task_id="MANIF-001",
            summary="Done",
            files_changed=("src/a.py", "src/b.py"),
            criteria_satisfied=(ev,),
            open_questions=("Should we cache the response?",),
            scope_deviations=("Refactored b.py for readability",),
        )
        assert len(claim.criteria_satisfied) == 1
        assert claim.criteria_satisfied[0].criterion == "tests pass"
        assert claim.scope_deviations == ("Refactored b.py for readability",)

    def test_frozen(self) -> None:
        claim = CompletionClaim(task_id="x", summary="y", files_changed=())
        with pytest.raises(ValidationError):
            claim.summary = "z"  # type: ignore[misc]

    def test_files_changed_is_tuple(self) -> None:
        claim = CompletionClaim(
            task_id="x",
            summary="y",
            files_changed=("src/a.py", "src/b.py"),
        )
        assert isinstance(claim.files_changed, tuple)


class TestVerificationFinding:
    """VerificationFinding — one failure surfaced by the verifier."""

    def test_create_with_required_fields(self) -> None:
        f = VerificationFinding(
            kind=VerificationFindingKind.SENSOR_FAILURE,
            severity="high",
            message="Coverage 72% below 88% floor",
            hint="Add tests for src/auth/login.py",
        )
        assert f.kind == VerificationFindingKind.SENSOR_FAILURE
        assert f.related_criterion is None
        assert f.related_sensor is None

    def test_create_with_optional_relations(self) -> None:
        f = VerificationFinding(
            kind=VerificationFindingKind.CRITERION_UNADDRESSED,
            severity="critical",
            message="Acceptance criterion 'user can log out' has no evidence",
            hint="Run the logout integration test and include its output",
            related_criterion="user can log out",
        )
        assert f.related_criterion == "user can log out"
        assert f.related_sensor is None

    def test_frozen(self) -> None:
        f = VerificationFinding(
            kind=VerificationFindingKind.SCOPE_VIOLATION,
            severity="high",
            message="m",
            hint="h",
        )
        with pytest.raises(ValidationError):
            f.message = "changed"  # type: ignore[misc]


class TestVerificationResult:
    """VerificationResult — the output of CompletionVerifier.verify()."""

    def test_passed_result_has_no_findings(self) -> None:
        result = VerificationResult(
            passed=True,
            findings=(),
            sensor_results=(),
            timestamp=_now(),
        )
        assert result.passed is True
        assert result.findings == ()

    def test_failed_result_has_findings(self) -> None:
        f = VerificationFinding(
            kind=VerificationFindingKind.EVIDENCE_MISMATCH,
            severity="critical",
            message="Claim says 412 tests passed; pytest reports 408 passed, 4 failed",
            hint="Fix the failing tests then re-run",
        )
        result = VerificationResult(
            passed=False,
            findings=(f,),
            sensor_results=(),
            timestamp=_now(),
        )
        assert result.passed is False
        assert len(result.findings) == 1

    def test_passed_with_findings_rejected(self) -> None:
        """A passed result must have zero findings — invariant."""
        f = VerificationFinding(
            kind=VerificationFindingKind.SCHEMA_VIOLATION,
            severity="high",
            message="m",
            hint="h",
        )
        with pytest.raises(ValidationError):
            VerificationResult(
                passed=True,
                findings=(f,),
                sensor_results=(),
                timestamp=_now(),
            )

    def test_frozen(self) -> None:
        result = VerificationResult(
            passed=True,
            findings=(),
            sensor_results=(),
            timestamp=_now(),
        )
        with pytest.raises(ValidationError):
            result.passed = False  # type: ignore[misc]
