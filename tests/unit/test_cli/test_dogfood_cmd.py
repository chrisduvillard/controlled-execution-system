"""Tests for ces dogfood command: JSON output mode and zero-findings warning."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from ces.shared.enums import GateType

runner = CliRunner()


@pytest.fixture(autouse=True)
def _reset_json_mode():
    from ces.cli._output import set_json_mode

    set_json_mode(False)
    yield
    set_json_mode(False)


def _get_app():
    from ces.cli import app

    return app


def _fake_services(**overrides: Any) -> Any:
    """Return a patch() that yields a stub services dict from get_services()."""
    from ces.control.models.oracle_result import OracleClassificationResult
    from ces.control.services.classification import ClassificationRule
    from ces.shared.enums import BehaviorConfidence, ChangeClass, RiskTier

    rule = ClassificationRule(
        description="Change to evidence synthesizer",
        risk_tier=RiskTier.B,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_2,
    )
    oracle_result = OracleClassificationResult(
        matched_rule=rule,
        confidence=0.77,
        top_matches=[(rule, 0.77)],
        action="human_review",
    )
    mock_oracle = MagicMock()
    mock_oracle.classify.return_value = oracle_result

    mock_router = MagicMock()
    mock_router.assign_triad = MagicMock(return_value=[MagicMock(), MagicMock(), MagicMock()])
    mock_router.assign_single = MagicMock(return_value=MagicMock())
    mock_router.dispatch_review = AsyncMock(return_value=overrides.get("aggregated_review"))

    mock_synth = MagicMock()
    mock_synth.assemble_decision_views_from_review = MagicMock(return_value=[])

    mock_audit = AsyncMock()

    services = {
        "classification_oracle": mock_oracle,
        "review_router": mock_router,
        "evidence_synthesizer": mock_synth,
        "audit_ledger": mock_audit,
    }
    services.update({k: v for k, v in overrides.items() if k != "aggregated_review"})

    @asynccontextmanager
    async def _ctx():
        yield services

    return patch("ces.cli.dogfood_cmd.get_services", new=_ctx), services


def _fake_diff_extractor(*, empty: bool = False):
    """Patch DiffExtractor.extract_diff + truncate_diff to avoid hitting git."""
    from ces.harness.services.diff_extractor import DiffContext, DiffStats

    if empty:
        diff = DiffContext(
            files_changed=(),
            hunks=(),
            stats=DiffStats(insertions=0, deletions=0, files_changed=0),
            diff_text="",
            truncated=False,
        )
    else:
        diff = DiffContext(
            files_changed=("src/foo.py", "src/bar.py"),
            hunks=(),
            stats=DiffStats(insertions=42, deletions=7, files_changed=2),
            diff_text="--- diff body omitted for test ---",
            truncated=False,
        )
    return patch(
        "ces.harness.services.diff_extractor.DiffExtractor.extract_diff",
        new=AsyncMock(return_value=diff),
    ), patch(
        "ces.harness.services.diff_extractor.DiffExtractor.truncate_diff",
        new=MagicMock(return_value=diff),
    )


def _make_aggregated(*, findings: list[Any] | None = None, unanimous_zero: bool = False) -> Any:
    from ces.harness.models.review_assignment import ReviewAssignment, ReviewerRole
    from ces.harness.models.review_finding import ReviewResult
    from ces.harness.services.findings_aggregator import AggregatedReview

    findings_tup: tuple[Any, ...] = tuple(findings or [])
    assignment = ReviewAssignment(
        role=ReviewerRole.STRUCTURAL,
        model_id="claude-opus-4-7",
        agent_id="test-reviewer",
    )
    result = ReviewResult(assignment=assignment, findings=(), summary="", review_duration_seconds=0.0)
    return AggregatedReview(
        review_results=(result,),
        all_findings=findings_tup,
        critical_count=sum(1 for f in findings_tup if f.severity.value == "critical"),
        high_count=sum(1 for f in findings_tup if f.severity.value == "high"),
        unanimous_zero_findings=unanimous_zero,
    )


def _make_finding(*, severity: str = "high", title: str = "Coverage gate → 88%") -> Any:
    from ces.harness.models.review_assignment import ReviewerRole
    from ces.harness.models.review_finding import ReviewFinding, ReviewFindingSeverity

    return ReviewFinding(
        finding_id="F-001",
        reviewer_role=ReviewerRole.SEMANTIC,
        severity=ReviewFindingSeverity(severity),
        category="policy",
        file_path="pyproject.toml",
        line_number=233,
        title=title,
        description="Detail",
        recommendation="Revert",
        confidence=0.9,
    )


class TestDogfoodJsonOutput:
    """--json emits a parseable payload instead of crashing on Unicode in Rich."""

    def test_json_output_with_findings(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / ".ces").mkdir()
        monkeypatch.chdir(tmp_path)

        finding = _make_finding(severity="high", title="Coverage gate lowered 90\u2192 88")
        agg = _make_aggregated(findings=[finding])
        services_patch, _ = _fake_services(aggregated_review=agg)
        extract_patch, truncate_patch = _fake_diff_extractor()

        with services_patch, extract_patch, truncate_patch:
            app = _get_app()
            result = runner.invoke(app, ["--json", "dogfood", "--base", "HEAD~1"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        # stdout is a single JSON object (all Rich output is suppressed in --json mode)
        payload = json.loads(result.stdout)

        assert payload["base_ref"] == "HEAD~1"
        assert payload["diff"]["files_changed_count"] == 2
        assert payload["classification"]["risk_tier"] == "B"
        assert payload["reviewers"]["dispatched"] == 1
        assert payload["aggregated_review"]["total_findings"] == 1
        assert payload["aggregated_review"]["findings"][0]["title"].endswith("88")
        # Unicode preserved in JSON (didn't crash like Rich on Windows cp1252)
        assert "\u2192" in payload["aggregated_review"]["findings"][0]["title"]

    def test_json_output_with_no_diff(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / ".ces").mkdir()
        monkeypatch.chdir(tmp_path)

        services_patch, _ = _fake_services(aggregated_review=None)
        extract_patch, truncate_patch = _fake_diff_extractor(empty=True)

        with services_patch, extract_patch, truncate_patch:
            app = _get_app()
            result = runner.invoke(app, ["--json", "dogfood", "--base", "HEAD"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        payload = json.loads(result.stdout)
        assert payload["status"] == "no_changes"
        assert payload["diff"]["files_changed_count"] == 0


class TestDogfoodPersistsFindings:
    """Every dogfood run should persist findings to the local store — not only when --approve is set."""

    def test_persists_even_without_approve(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / ".ces").mkdir()
        monkeypatch.chdir(tmp_path)

        finding = _make_finding(severity="high", title="Coverage gate lowered")
        agg = _make_aggregated(findings=[finding])
        mock_store = MagicMock()
        mock_store.save_review_findings = MagicMock()
        services_patch, _ = _fake_services(aggregated_review=agg, local_store=mock_store)
        extract_patch, truncate_patch = _fake_diff_extractor()

        with services_patch, extract_patch, truncate_patch:
            app = _get_app()
            # Note: no --approve flag
            result = runner.invoke(app, ["dogfood", "--base", "HEAD~1"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        mock_store.save_review_findings.assert_called_once()
        called_manifest_id, called_agg = mock_store.save_review_findings.call_args[0]
        assert called_manifest_id == "dogfood-HEAD~1"
        assert called_agg is agg

    def test_missing_local_store_does_not_crash(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """If the services dict lacks `local_store` (non-local mode), the command still completes."""
        (tmp_path / ".ces").mkdir()
        monkeypatch.chdir(tmp_path)

        agg = _make_aggregated(findings=[_make_finding()])
        services_patch, _ = _fake_services(aggregated_review=agg)  # no local_store

        extract_patch, truncate_patch = _fake_diff_extractor()

        with services_patch, extract_patch, truncate_patch:
            app = _get_app()
            result = runner.invoke(app, ["dogfood", "--base", "HEAD~1"])

        assert result.exit_code == 0, f"stdout={result.stdout}"


class TestDogfoodJsonErrorPath:
    """--json must emit a structured error payload (not a Rich Panel) on failure."""

    def test_json_error_payload_on_exception(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / ".ces").mkdir()
        monkeypatch.chdir(tmp_path)

        boom = patch(
            "ces.harness.services.diff_extractor.DiffExtractor.extract_diff",
            new=AsyncMock(side_effect=RuntimeError("git diff failed (exit 128): bad ref")),
        )
        services_patch, _ = _fake_services(aggregated_review=None)

        with services_patch, boom:
            app = _get_app()
            result = runner.invoke(app, ["--json", "dogfood", "--base", "BOGUS"])

        assert result.exit_code != 0, f"expected non-zero exit; stdout={result.stdout}"
        payload = json.loads(result.stdout)
        # Stable schema: every top-level key is present even on failure
        assert payload["base_ref"] == "BOGUS"
        assert payload["status"] == "error"
        assert payload["diff"] is None
        assert payload["classification"] is None
        assert payload["aggregated_review"] is None
        assert payload["error"]["type"] == "RuntimeError"
        assert "bad ref" in payload["error"]["message"]


class TestDogfoodUnanimousZeroWarning:
    """Regression: the unanimous-zero-findings warning previously was unreachable."""

    def test_zero_findings_branch_prints_unanimous_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / ".ces").mkdir()
        monkeypatch.chdir(tmp_path)

        agg = _make_aggregated(findings=[], unanimous_zero=True)
        services_patch, _ = _fake_services(aggregated_review=agg)
        extract_patch, truncate_patch = _fake_diff_extractor()

        with services_patch, extract_patch, truncate_patch:
            app = _get_app()
            result = runner.invoke(app, ["dogfood", "--base", "HEAD~1"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        # Previously the warning was nested under `if all_findings:` and could never fire
        # with zero findings. The fix moves it into the zero-findings branch.
        assert "unanimous zero findings" in result.stdout.lower()
        assert "auto-escalated" in result.stdout.lower()


class TestDogfoodGateRouting:
    def test_dispatch_uses_risk_based_gate_type(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / ".ces").mkdir()
        monkeypatch.chdir(tmp_path)

        agg = _make_aggregated(findings=[_make_finding()])
        services_patch, services = _fake_services(aggregated_review=agg)
        extract_patch, truncate_patch = _fake_diff_extractor()

        with services_patch, extract_patch, truncate_patch:
            app = _get_app()
            result = runner.invoke(app, ["dogfood", "--base", "HEAD~1"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert services["review_router"].dispatch_review.await_args.kwargs["current_gate_type"] == GateType.HYBRID


class TestDogfoodApprovalGuards:
    def test_approve_rejects_unanimous_zero_findings(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / ".ces").mkdir()
        monkeypatch.chdir(tmp_path)

        agg = _make_aggregated(findings=[], unanimous_zero=True)
        services_patch, services = _fake_services(aggregated_review=agg)
        extract_patch, truncate_patch = _fake_diff_extractor()

        with services_patch, extract_patch, truncate_patch:
            app = _get_app()
            result = runner.invoke(app, ["dogfood", "--base", "HEAD~1", "--approve"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "auto-approval blocked" in result.stdout.lower()
        services["audit_ledger"].record_approval.assert_awaited_once()
        assert services["audit_ledger"].record_approval.await_args.kwargs["decision"] == "rejected"
        assert "unanimous zero findings" in services["audit_ledger"].record_approval.await_args.kwargs["rationale"]

    def test_json_approve_reports_rejected_for_unanimous_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / ".ces").mkdir()
        monkeypatch.chdir(tmp_path)

        agg = _make_aggregated(findings=[], unanimous_zero=True)
        services_patch, _ = _fake_services(aggregated_review=agg)
        extract_patch, truncate_patch = _fake_diff_extractor()

        with services_patch, extract_patch, truncate_patch:
            app = _get_app()
            result = runner.invoke(app, ["--json", "dogfood", "--base", "HEAD~1", "--approve"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        payload = json.loads(result.stdout)
        assert payload["approval"]["decision"] == "rejected"
        assert "unanimous zero findings" in payload["approval"]["rationale"]


# ---------------------------------------------------------------------------
# Completion Gate preflight (N3)
# ---------------------------------------------------------------------------


class _StubVerifier:
    """Returns a configured VerificationResult for dogfood preflight tests."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def verify(self, manifest, claim, project_root):
        self.calls.append((manifest, claim, project_root))
        return self.payload


class TestDogfoodCompletionGatePreflight:
    """`ces dogfood` runs the gate's sensors on the current repo state."""

    def test_preflight_payload_in_json_when_verifier_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from datetime import datetime, timezone

        from ces.harness.models.completion_claim import VerificationResult

        (tmp_path / ".ces").mkdir()
        monkeypatch.chdir(tmp_path)

        verifier = _StubVerifier(
            VerificationResult(
                passed=True,
                findings=(),
                sensor_results=(),
                timestamp=datetime.now(timezone.utc),
            )
        )
        agg = _make_aggregated(findings=[])
        services_patch, _ = _fake_services(aggregated_review=agg, completion_verifier=verifier)
        extract_patch, truncate_patch = _fake_diff_extractor()

        with services_patch, extract_patch, truncate_patch:
            result = runner.invoke(_get_app(), ["--json", "dogfood", "--base", "HEAD~1"])

        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        preflight = payload["completion_gate_preflight"]
        assert preflight is not None
        assert preflight["passed"] is True
        assert preflight["findings"] == []
        assert len(verifier.calls) == 1
        # Synthetic manifest must scope affected_files to the diff
        synthetic_manifest = verifier.calls[0][0]
        assert synthetic_manifest.manifest_id == "DOGFOOD-PREFLIGHT"
        assert "test_pass" in synthetic_manifest.verification_sensors

    def test_preflight_failure_is_non_blocking(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A red preflight must NOT abort the rest of the pipeline."""
        from datetime import datetime, timezone

        from ces.harness.models.completion_claim import (
            VerificationFinding,
            VerificationFindingKind,
            VerificationResult,
        )

        (tmp_path / ".ces").mkdir()
        monkeypatch.chdir(tmp_path)

        finding = VerificationFinding(
            kind=VerificationFindingKind.SENSOR_FAILURE,
            severity="high",
            message="lint reports 3 violations",
            hint="run ruff --fix",
            related_sensor="lint",
        )
        verifier = _StubVerifier(
            VerificationResult(
                passed=False,
                findings=(finding,),
                sensor_results=(),
                timestamp=datetime.now(timezone.utc),
            )
        )
        agg = _make_aggregated(findings=[])
        services_patch, _ = _fake_services(aggregated_review=agg, completion_verifier=verifier)
        extract_patch, truncate_patch = _fake_diff_extractor()

        with services_patch, extract_patch, truncate_patch:
            result = runner.invoke(_get_app(), ["--json", "dogfood", "--base", "HEAD~1"])

        # Exit code is 0 even though preflight failed — non-blocking by design.
        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        assert payload["completion_gate_preflight"]["passed"] is False
        assert payload["completion_gate_preflight"]["findings"][0]["related_sensor"] == "lint"
        # Review pipeline still ran (classification populated, reviewers dispatched)
        assert payload["classification"] is not None
        assert payload["reviewers"] is not None

    def test_preflight_skipped_when_verifier_not_in_services(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Backward-compat: factories without the verifier still work."""
        (tmp_path / ".ces").mkdir()
        monkeypatch.chdir(tmp_path)

        agg = _make_aggregated(findings=[])
        services_patch, _ = _fake_services(aggregated_review=agg)  # no completion_verifier
        extract_patch, truncate_patch = _fake_diff_extractor()

        with services_patch, extract_patch, truncate_patch:
            result = runner.invoke(_get_app(), ["--json", "dogfood", "--base", "HEAD~1"])

        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        assert payload["completion_gate_preflight"] is None
