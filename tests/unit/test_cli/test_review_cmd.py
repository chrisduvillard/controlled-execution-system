"""Tests for ces review command (review_cmd module)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from ces.harness.models.review_assignment import ReviewAssignment, ReviewerRole
from ces.harness.models.review_finding import ReviewResult
from ces.harness.services.diff_extractor import DiffContext, DiffStats
from ces.harness.services.findings_aggregator import AggregatedReview
from ces.shared.enums import GateType, WorkflowState

runner = CliRunner()

# Shared mock diff context for review command tests
_MOCK_DIFF_CONTEXT = DiffContext(
    diff_text="+ mock change",
    files_changed=("src/main.py",),
    hunks=(),
    stats=DiffStats(insertions=1, deletions=0, files_changed=1),
)


def _patch_diff_extractor():
    """Patch DiffExtractor.extract_diff to avoid real git calls in tests."""
    return patch(
        "ces.harness.services.diff_extractor.DiffExtractor.extract_diff",
        new=AsyncMock(return_value=_MOCK_DIFF_CONTEXT),
    )


def _get_app():
    """Import app lazily to avoid import errors during collection."""
    from ces.cli import app

    return app


def _patch_services(mock_services: dict[str, Any]):
    """Return a patch that replaces get_services with a fake async context manager."""

    @asynccontextmanager
    async def _fake_get_services(*args: Any, **kwargs: Any):
        del args, kwargs
        yield mock_services

    return patch("ces.cli.review_cmd.get_services", new=_fake_get_services)


def _make_mock_manifest(
    manifest_id: str = "M-review123",
    risk_tier_value: str = "A",
    workflow_state: WorkflowState = WorkflowState.IN_FLIGHT,
) -> MagicMock:
    """Create a mock manifest with classification."""
    manifest = MagicMock()
    manifest.manifest_id = manifest_id
    manifest.description = "Implement payment processing"
    manifest.risk_tier = MagicMock(value=risk_tier_value)
    manifest.workflow_state = workflow_state
    manifest.builder_agent_id = "agent-builder-1"
    manifest.builder_model_id = "claude-3-opus"
    return manifest


def _make_review_assignments() -> list[ReviewAssignment]:
    """Create a list of mock review assignments."""
    return [
        ReviewAssignment(role=ReviewerRole.STRUCTURAL, model_id="gpt-4o", agent_id="reviewer-structural-gpt-4o"),
        ReviewAssignment(
            role=ReviewerRole.SEMANTIC, model_id="claude-3-haiku", agent_id="reviewer-semantic-claude-3-haiku"
        ),
        ReviewAssignment(role=ReviewerRole.RED_TEAM, model_id="gemini-pro", agent_id="reviewer-red_team-gemini-pro"),
    ]


def _make_mock_review_router(assignments: list[ReviewAssignment] | None = None) -> MagicMock:
    """Create a mock ReviewRouter."""
    router = MagicMock()
    if assignments is None:
        assignments = _make_review_assignments()
    router.assign_triad.return_value = assignments
    router.assign_single.return_value = assignments[0]
    # dispatch_review raises RuntimeError when no executor is wired (graceful fallback)
    router.dispatch_review = AsyncMock(side_effect=RuntimeError("No review executor configured"))
    return router


def _make_zero_findings_aggregate(assignments: list[ReviewAssignment] | None = None) -> AggregatedReview:
    if assignments is None:
        assignments = _make_review_assignments()
    review_results = tuple(
        ReviewResult(assignment=assignment, findings=(), summary="", review_duration_seconds=0.01)
        for assignment in assignments
    )
    return AggregatedReview(
        review_results=review_results,
        all_findings=(),
        critical_count=0,
        high_count=0,
        disagreements=(),
        unanimous_zero_findings=True,
    )


def _make_mock_evidence_synthesizer() -> MagicMock:
    """Create a mock EvidenceSynthesizer."""
    synth = MagicMock()
    summary_slots = MagicMock()
    summary_slots.summary = (
        "Line 1: Payment module added\n"
        "Line 2: Stripe integration\n"
        "Line 3: Error handling implemented\n"
        "Line 4: Input validation added\n"
        "Line 5: Retry logic for failures\n"
        "Line 6: Webhook handler created\n"
        "Line 7: Idempotency keys used\n"
        "Line 8: Amount validation\n"
        "Line 9: Currency conversion\n"
        "Line 10: Audit logging added"
    )
    summary_slots.challenge = (
        "Challenge 1: Race condition in concurrent payments\n"
        "Challenge 2: No rate limiting on payment endpoint\n"
        "Challenge 3: Missing PCI compliance checks"
    )
    synth.format_summary_slots = AsyncMock(return_value=summary_slots)
    return synth


def _make_provider_and_settings() -> tuple[MagicMock, MagicMock]:
    """Create mock provider_registry and settings for EVID-04 wiring."""
    mock_reg = MagicMock()
    mock_reg.get_provider = MagicMock(side_effect=KeyError("no provider"))
    mock_settings = MagicMock(default_model_id="claude-3-opus")
    return mock_reg, mock_settings


class TestReviewDisplaySummary:
    """Tests for ces review summary display."""

    def test_review_shows_10_line_summary_and_3_line_challenge(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ces review <manifest-id> shows 10-line summary and 3-line challenge."""
        monkeypatch.chdir(ces_project)

        mock_manifest = _make_mock_manifest()
        mock_manager = AsyncMock()
        mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)

        mock_router = _make_mock_review_router()
        mock_synth = _make_mock_evidence_synthesizer()

        mock_reg, mock_settings = _make_provider_and_settings()
        mock_services = {
            "manifest_manager": mock_manager,
            "review_router": mock_router,
            "evidence_synthesizer": mock_synth,
            "audit_ledger": AsyncMock(),
            "provider_registry": mock_reg,
            "settings": mock_settings,
        }

        with (
            _patch_services(mock_services),
            patch("ces.cli.review_cmd.WorkflowEngine", return_value=AsyncMock()),
            _patch_diff_extractor(),
        ):
            app = _get_app()
            result = runner.invoke(app, ["review", "M-review123"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        # Should show summary content
        assert "Payment module" in result.stdout or "summary" in result.stdout.lower()

    def test_review_shows_reviewer_assignments(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces review displays reviewer model and role assignments."""
        monkeypatch.chdir(ces_project)

        mock_manifest = _make_mock_manifest()
        mock_manager = AsyncMock()
        mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)

        mock_router = _make_mock_review_router()
        mock_synth = _make_mock_evidence_synthesizer()

        mock_reg, mock_settings = _make_provider_and_settings()
        mock_services = {
            "manifest_manager": mock_manager,
            "review_router": mock_router,
            "evidence_synthesizer": mock_synth,
            "audit_ledger": AsyncMock(),
            "provider_registry": mock_reg,
            "settings": mock_settings,
        }

        with (
            _patch_services(mock_services),
            patch("ces.cli.review_cmd.WorkflowEngine", return_value=AsyncMock()),
            _patch_diff_extractor(),
        ):
            app = _get_app()
            result = runner.invoke(app, ["review", "M-review123"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        # Should show some reviewer info
        assert "structural" in result.stdout.lower() or "gpt-4o" in result.stdout.lower()


class TestReviewVerboseMode:
    """Tests for ces review --verbose and --full flags."""

    def test_verbose_shows_full_evidence(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces review --verbose shows complete evidence packet."""
        monkeypatch.chdir(ces_project)

        mock_manifest = _make_mock_manifest()
        mock_manager = AsyncMock()
        mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)

        mock_router = _make_mock_review_router()
        mock_synth = _make_mock_evidence_synthesizer()

        mock_reg, mock_settings = _make_provider_and_settings()
        mock_services = {
            "manifest_manager": mock_manager,
            "review_router": mock_router,
            "evidence_synthesizer": mock_synth,
            "audit_ledger": AsyncMock(),
            "provider_registry": mock_reg,
            "settings": mock_settings,
        }

        with (
            _patch_services(mock_services),
            patch("ces.cli.review_cmd.WorkflowEngine", return_value=AsyncMock()),
            _patch_diff_extractor(),
        ):
            app = _get_app()
            result = runner.invoke(app, ["review", "M-review123", "--verbose"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        # Verbose mode should show more content
        assert "challenge" in result.stdout.lower() or "Challenge" in result.stdout


class TestReviewJsonMode:
    """Tests for ces review --json output mode."""

    def test_json_output_mode(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces --json review outputs evidence as JSON."""
        monkeypatch.chdir(ces_project)

        mock_manifest = _make_mock_manifest()
        mock_manager = AsyncMock()
        mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)

        mock_router = _make_mock_review_router()
        mock_synth = _make_mock_evidence_synthesizer()

        mock_reg, mock_settings = _make_provider_and_settings()
        mock_services = {
            "manifest_manager": mock_manager,
            "review_router": mock_router,
            "evidence_synthesizer": mock_synth,
            "audit_ledger": AsyncMock(),
            "provider_registry": mock_reg,
            "settings": mock_settings,
        }

        with (
            _patch_services(mock_services),
            patch("ces.cli.review_cmd.WorkflowEngine", return_value=AsyncMock()),
            _patch_diff_extractor(),
        ):
            app = _get_app()
            result = runner.invoke(app, ["--json", "review", "M-review123"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        output = result.stdout.strip()
        parsed = json.loads(output)
        assert isinstance(parsed, dict)
        assert "summary" in parsed or "manifest_id" in parsed

    def test_json_output_includes_unanimous_zero_findings(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(ces_project)

        mock_manifest = _make_mock_manifest(manifest_id="M-zero", risk_tier_value="B")
        mock_manager = AsyncMock()
        mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)

        assignments = _make_review_assignments()
        mock_router = _make_mock_review_router(assignments)
        mock_router.dispatch_review = AsyncMock(return_value=_make_zero_findings_aggregate(assignments))
        mock_synth = _make_mock_evidence_synthesizer()

        mock_reg, mock_settings = _make_provider_and_settings()
        mock_services = {
            "manifest_manager": mock_manager,
            "review_router": mock_router,
            "evidence_synthesizer": mock_synth,
            "audit_ledger": AsyncMock(),
            "provider_registry": mock_reg,
            "settings": mock_settings,
        }

        with (
            _patch_services(mock_services),
            patch("ces.cli.review_cmd.WorkflowEngine", return_value=AsyncMock()),
            _patch_diff_extractor(),
        ):
            app = _get_app()
            result = runner.invoke(app, ["--json", "review", "M-zero"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        parsed = json.loads(result.stdout)
        assert parsed["unanimous_zero_findings"] is True


class TestReviewGateRouting:
    def test_review_passes_risk_based_gate_type_to_dispatch(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(ces_project)

        mock_manifest = _make_mock_manifest(manifest_id="M-gate", risk_tier_value="A")
        mock_manager = AsyncMock()
        mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)

        assignments = _make_review_assignments()
        mock_router = _make_mock_review_router(assignments)
        mock_router.dispatch_review = AsyncMock(return_value=_make_zero_findings_aggregate(assignments))
        mock_synth = _make_mock_evidence_synthesizer()

        mock_reg, mock_settings = _make_provider_and_settings()
        mock_services = {
            "manifest_manager": mock_manager,
            "review_router": mock_router,
            "evidence_synthesizer": mock_synth,
            "audit_ledger": AsyncMock(),
            "provider_registry": mock_reg,
            "settings": mock_settings,
        }

        with (
            _patch_services(mock_services),
            patch("ces.cli.review_cmd.WorkflowEngine", return_value=AsyncMock()),
            _patch_diff_extractor(),
        ):
            app = _get_app()
            result = runner.invoke(app, ["review", "M-gate"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert mock_router.dispatch_review.await_args.kwargs["current_gate_type"] == GateType.HUMAN


class TestReviewMissingManifest:
    """Tests for ces review when manifest is not found."""

    def test_missing_manifest_exits_with_error(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces review with invalid manifest ID exits with error."""
        monkeypatch.chdir(ces_project)

        mock_manager = AsyncMock()
        mock_manager.get_manifest = AsyncMock(return_value=None)

        mock_services = {
            "manifest_manager": mock_manager,
            "review_router": MagicMock(),
            "evidence_synthesizer": MagicMock(),
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["review", "M-nonexistent"])

        assert result.exit_code != 0, f"stdout={result.stdout}"


class TestReviewWorkflowEngineIntegration:
    """Tests for WorkflowEngine integration in review flow."""

    def test_review_creates_workflow_engine_and_calls_submit_for_review(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """review_cmd creates WorkflowEngine with manifest_id and audit_ledger, calls submit_for_review()."""
        monkeypatch.chdir(ces_project)

        mock_manifest = _make_mock_manifest()
        mock_manager = AsyncMock()
        mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)

        mock_router = _make_mock_review_router()
        mock_synth = _make_mock_evidence_synthesizer()
        mock_audit = AsyncMock()

        mock_reg, mock_settings = _make_provider_and_settings()
        mock_services = {
            "manifest_manager": mock_manager,
            "review_router": mock_router,
            "evidence_synthesizer": mock_synth,
            "audit_ledger": mock_audit,
            "provider_registry": mock_reg,
            "settings": mock_settings,
        }

        mock_engine = AsyncMock()
        mock_engine.submit_for_review = AsyncMock(return_value=WorkflowState.UNDER_REVIEW)

        with (
            _patch_services(mock_services),
            patch("ces.cli.review_cmd.WorkflowEngine", return_value=mock_engine) as mock_we_cls,
            _patch_diff_extractor(),
        ):
            app = _get_app()
            result = runner.invoke(app, ["review", "M-review-wf"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        # WorkflowEngine created with manifest_id and audit_ledger
        mock_we_cls.assert_called_once()
        call_kwargs = mock_we_cls.call_args
        assert call_kwargs.kwargs.get("manifest_id") == "M-review-wf"
        assert call_kwargs.kwargs.get("audit_ledger") is mock_audit
        assert call_kwargs.kwargs.get("initial_state") == WorkflowState.IN_FLIGHT.value
        # submit_for_review called
        mock_engine.submit_for_review.assert_called_once()
        mock_manager.save_manifest.assert_awaited_once()

    def test_review_reuses_under_review_manifest_without_second_transition(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """review_cmd does not forge a new transition when the manifest is already under review."""
        monkeypatch.chdir(ces_project)

        mock_manifest = _make_mock_manifest(workflow_state=WorkflowState.UNDER_REVIEW)
        mock_manager = AsyncMock()
        mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)

        mock_router = _make_mock_review_router()
        mock_synth = _make_mock_evidence_synthesizer()
        mock_audit = AsyncMock()

        mock_reg, mock_settings = _make_provider_and_settings()
        mock_services = {
            "manifest_manager": mock_manager,
            "review_router": mock_router,
            "evidence_synthesizer": mock_synth,
            "audit_ledger": mock_audit,
            "provider_registry": mock_reg,
            "settings": mock_settings,
        }

        mock_engine = AsyncMock()
        mock_engine.submit_for_review = AsyncMock(return_value=WorkflowState.UNDER_REVIEW)

        with (
            _patch_services(mock_services),
            patch("ces.cli.review_cmd.WorkflowEngine", return_value=mock_engine) as mock_we_cls,
            _patch_diff_extractor(),
        ):
            app = _get_app()
            result = runner.invoke(app, ["review", "M-review-wf"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert mock_we_cls.call_args.kwargs.get("initial_state") == WorkflowState.UNDER_REVIEW.value
        mock_engine.submit_for_review.assert_not_called()
        mock_manager.save_manifest.assert_not_awaited()

    def test_review_rejects_invalid_manifest_workflow_state(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """review_cmd fails closed when review is invoked before execution starts."""
        monkeypatch.chdir(ces_project)

        mock_manifest = _make_mock_manifest(workflow_state=WorkflowState.QUEUED)
        mock_manager = AsyncMock()
        mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)

        mock_router = _make_mock_review_router()
        mock_synth = _make_mock_evidence_synthesizer()
        mock_audit = AsyncMock()

        mock_reg, mock_settings = _make_provider_and_settings()
        mock_services = {
            "manifest_manager": mock_manager,
            "review_router": mock_router,
            "evidence_synthesizer": mock_synth,
            "audit_ledger": mock_audit,
            "provider_registry": mock_reg,
            "settings": mock_settings,
        }

        with (
            _patch_services(mock_services),
            patch("ces.cli.review_cmd.WorkflowEngine", return_value=AsyncMock()),
            _patch_diff_extractor(),
        ):
            app = _get_app()
            result = runner.invoke(app, ["review", "M-review-wf"])

        assert result.exit_code != 0, f"stdout={result.stdout}"
        assert "must be in_flight or under_review" in result.stdout
        mock_manager.save_manifest.assert_not_awaited()

    def test_review_merged_manifest_points_to_builder_report(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """review_cmd keeps merged manifests closed but points to historical reports."""
        monkeypatch.chdir(ces_project)

        mock_manifest = _make_mock_manifest(workflow_state=WorkflowState.MERGED)
        mock_manager = AsyncMock()
        mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)

        mock_services = {
            "manifest_manager": mock_manager,
            "review_router": _make_mock_review_router(),
            "evidence_synthesizer": _make_mock_evidence_synthesizer(),
            "audit_ledger": AsyncMock(),
            "provider_registry": MagicMock(get_provider=MagicMock(side_effect=KeyError("no provider"))),
            "settings": MagicMock(default_model_id="gpt-5.4"),
        }

        with (
            _patch_services(mock_services),
            patch("ces.cli.review_cmd.WorkflowEngine", return_value=AsyncMock()),
            _patch_diff_extractor(),
        ):
            app = _get_app()
            result = runner.invoke(app, ["review", "M-review-wf", "--full"])

        assert result.exit_code != 0, f"stdout={result.stdout}"
        assert "already merged" in result.stdout
        assert "ces report builder" in result.stdout
        assert "ces status" in result.stdout
        assert "ces audit" in result.stdout


def test_review_accepts_project_root_option(tmp_path: Path, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PromptVault dogfood: ces review should support the same --project-root affordance as status."""
    project = tmp_path / "target"
    project.mkdir()
    (project / ".ces").mkdir()
    (project / ".ces" / "config.yaml").write_text("project_id: proj-target\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    mock_manifest = _make_mock_manifest(workflow_state=WorkflowState.UNDER_REVIEW)
    mock_manager = AsyncMock()
    mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)
    mock_reg, mock_settings = _make_provider_and_settings()
    mock_services = {
        "manifest_manager": mock_manager,
        "review_router": _make_mock_review_router(),
        "evidence_synthesizer": _make_mock_evidence_synthesizer(),
        "audit_ledger": AsyncMock(),
        "provider_registry": mock_reg,
        "settings": mock_settings,
    }

    with (
        _patch_services(mock_services),
        patch("ces.cli.review_cmd.WorkflowEngine", return_value=AsyncMock()),
        _patch_diff_extractor(),
    ):
        result = runner.invoke(_get_app(), ["review", "M-review123", "--project-root", str(project)])

    assert result.exit_code == 0, f"stdout={result.stdout}"


def test_review_full_for_rejected_builder_run_shows_verification_findings(
    ces_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PromptVault dogfood: rejected builder runs should be inspectable without re-reviewing."""
    monkeypatch.chdir(ces_project)
    mock_manifest = _make_mock_manifest(workflow_state=WorkflowState.REJECTED)
    mock_manager = AsyncMock()
    mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)
    mock_store = MagicMock()
    mock_store.get_latest_builder_session_snapshot.return_value = SimpleNamespace(
        request="Build PromptVault",
        project_mode="greenfield",
        stage="blocked",
        next_action="review_evidence",
        next_step="Review the evidence",
        latest_activity="CES recorded rejection",
        latest_artifact="approval",
        brief_only_fallback=False,
        brief=SimpleNamespace(prl_draft_path=None),
        manifest=SimpleNamespace(manifest_id="M-review123", workflow_state="rejected"),
        runtime_execution=SimpleNamespace(exit_code=0, reported_model="gpt-5.5"),
        evidence={
            "packet_id": "EP-review",
            "triage_color": "red",
            "verification_result": {
                "passed": False,
                "findings": [{"message": "Acceptance criterion has no evidence: 'export works'"}],
            },
        },
        approval=SimpleNamespace(decision="reject"),
        session=SimpleNamespace(session_id="BS-review"),
        brownfield=None,
    )
    mock_services = {
        "manifest_manager": mock_manager,
        "review_router": _make_mock_review_router(),
        "evidence_synthesizer": _make_mock_evidence_synthesizer(),
        "audit_ledger": AsyncMock(),
        "provider_registry": MagicMock(get_provider=MagicMock(side_effect=KeyError("no provider"))),
        "settings": MagicMock(default_model_id="gpt-5.5"),
        "local_store": mock_store,
    }

    with _patch_services(mock_services):
        result = runner.invoke(_get_app(), ["review", "M-review123", "--full"])

    assert result.exit_code == 0, f"stdout={result.stdout}"
    assert "Builder Truth" in result.stdout
    assert "Acceptance criterion has no evidence" in result.stdout
