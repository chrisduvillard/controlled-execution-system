"""Tests for ces approve command (approve_cmd module)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from ces.control.models.manifest import TaskManifest
from ces.control.models.merge_decision import MergeDecision
from ces.harness.models.triage_result import TriageColor, TriageDecision
from ces.shared.enums import (
    ArtifactStatus,
    BehaviorConfidence,
    ChangeClass,
    GateType,
    RiskTier,
    TrustStatus,
    WorkflowState,
)

runner = CliRunner()


def _get_app():
    """Import app lazily to avoid import errors during collection."""
    from ces.cli import app

    return app


def _patch_services(mock_services: dict[str, Any]):
    """Return a patch that replaces get_services with a fake async context manager."""

    @asynccontextmanager
    async def _fake_get_services():
        yield mock_services

    return patch("ces.cli.approve_cmd.get_services", new=_fake_get_services)


def _make_triage_decision(
    color: TriageColor = TriageColor.GREEN,
) -> TriageDecision:
    """Create a TriageDecision for testing."""
    return TriageDecision(
        color=color,
        risk_tier=RiskTier.C,
        trust_status=TrustStatus.TRUSTED,
        sensor_pass_rate=1.0,
        reason="Tier=C, Trust=trusted, SensorsGreen=True, PassRate=1.00",
        auto_approve_eligible=True,
    )


def _make_mock_manifest(
    manifest_id: str = "M-approve123",
    workflow_state: WorkflowState = WorkflowState.UNDER_REVIEW,
) -> MagicMock:
    """Create a mock manifest."""
    manifest = MagicMock()
    manifest.manifest_id = manifest_id
    manifest.description = "Add payment processing"
    manifest.risk_tier = RiskTier.C
    manifest.trust_status = TrustStatus.TRUSTED
    manifest.workflow_state = workflow_state
    return manifest


def _make_mock_services(
    triage_color: TriageColor = TriageColor.GREEN,
) -> dict[str, Any]:
    """Create a complete mock services dict for approve tests."""
    mock_manifest = _make_mock_manifest()
    mock_manager = AsyncMock()
    mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)

    mock_synth = MagicMock()
    mock_synth.triage = AsyncMock(return_value=_make_triage_decision(triage_color))
    mock_synth.format_summary_slots = AsyncMock(
        return_value=MagicMock(
            summary="Line 1: Payment module\nLine 2: Stripe\nLine 3: Error handling\nLine 4: Validation\nLine 5: Done",
            challenge="Challenge: No rate limiting",
        )
    )

    mock_audit = AsyncMock()
    mock_audit.record_approval = AsyncMock(return_value=MagicMock())

    mock_workflow = AsyncMock()
    mock_workflow.complete_review = AsyncMock(return_value=WorkflowState.APPROVED)
    mock_workflow.approve_merge = AsyncMock(return_value=WorkflowState.MERGED)

    mock_merge_ctrl = AsyncMock()
    mock_merge_ctrl.validate_merge = AsyncMock(return_value=MergeDecision(allowed=True, checks=[], reason=""))

    mock_sensor_orch = AsyncMock()
    mock_sensor_orch.run_all = AsyncMock(return_value=[])

    mock_provider_reg = MagicMock()
    mock_provider_reg.get_provider = MagicMock(side_effect=KeyError("no provider"))

    return {
        "manifest_manager": mock_manager,
        "evidence_synthesizer": mock_synth,
        "audit_ledger": mock_audit,
        "merge_controller": mock_merge_ctrl,
        "sensor_orchestrator": mock_sensor_orch,
        "provider_registry": mock_provider_reg,
        "settings": MagicMock(default_model_id="claude-sonnet-4-6"),
    }


def _make_review_data(*, unanimous_zero_findings: bool = False) -> dict[str, Any]:
    return {
        "findings": [],
        "critical_count": 0,
        "high_count": 0,
        "disagreements": [],
        "unanimous_zero_findings": unanimous_zero_findings,
    }


class TestApproveWithYesFlag:
    """Tests for ces approve --yes (skip confirmation)."""

    def test_approve_with_yes_records_approval(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces approve --yes records approval in audit ledger."""
        monkeypatch.chdir(ces_project)

        mock_services = _make_mock_services()

        with _patch_services(mock_services), patch("ces.cli.approve_cmd.WorkflowEngine", return_value=AsyncMock()):
            app = _get_app()
            result = runner.invoke(app, ["approve", "EP-test123", "--yes"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        mock_services["audit_ledger"].record_approval.assert_called_once()

    def test_approve_shows_triage_color(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces approve shows triage color in the display."""
        monkeypatch.chdir(ces_project)

        mock_services = _make_mock_services(TriageColor.YELLOW)

        with _patch_services(mock_services), patch("ces.cli.approve_cmd.WorkflowEngine", return_value=AsyncMock()):
            app = _get_app()
            result = runner.invoke(app, ["approve", "EP-yellow", "--yes"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        # Should show some indication of yellow triage
        assert "yellow" in result.stdout.lower() or "YELLOW" in result.stdout

    def test_yes_flag_blocks_unanimous_zero_escalation(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ces approve --yes fails closed when review escalation requires explicit human review."""
        monkeypatch.chdir(ces_project)

        mock_services = _make_mock_services()
        mock_store = MagicMock()
        mock_store.get_review_findings.return_value = _make_review_data(unanimous_zero_findings=True)
        mock_services["local_store"] = mock_store

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["approve", "EP-unanimous-zero", "--yes"])

        assert result.exit_code == 3, f"stdout={result.stdout}"
        assert "Cannot use --yes" in result.stdout
        mock_services["audit_ledger"].record_approval.assert_not_called()


class TestApproveRejection:
    """Tests for rejection flow."""

    def test_reject_with_reason(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces approve --reason 'bad code' with rejection records reason."""
        monkeypatch.chdir(ces_project)

        mock_services = _make_mock_services()

        with _patch_services(mock_services):
            app = _get_app()
            # Simulate saying 'n' to confirmation prompt
            result = runner.invoke(
                app,
                ["approve", "EP-reject", "--reason", "Insufficient tests"],
                input="n\n",
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        # Should have recorded rejection
        mock_services["audit_ledger"].record_approval.assert_called_once()
        call_kwargs = mock_services["audit_ledger"].record_approval.call_args
        # Verify rejection reason is passed
        assert "reject" in str(call_kwargs).lower() or "Insufficient" in str(call_kwargs)


class TestApproveInteractiveConfirmation:
    """Tests for interactive confirmation prompt."""

    def test_interactive_yes_approves(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Interactive 'y' response triggers approval."""
        monkeypatch.chdir(ces_project)

        mock_services = _make_mock_services()

        with _patch_services(mock_services), patch("ces.cli.approve_cmd.WorkflowEngine", return_value=AsyncMock()):
            app = _get_app()
            result = runner.invoke(
                app,
                ["approve", "EP-interactive"],
                input="y\n",
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        mock_services["audit_ledger"].record_approval.assert_called_once()
        # Should show approval message
        assert "approved" in result.stdout.lower() or "approve" in result.stdout.lower()

    def test_interactive_no_rejects(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Interactive 'n' response triggers rejection."""
        monkeypatch.chdir(ces_project)

        mock_services = _make_mock_services()

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                ["approve", "EP-interactive-no"],
                input="n\n",
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        # Should record rejection
        mock_services["audit_ledger"].record_approval.assert_called_once()

    def test_interactive_warning_for_unanimous_zero_findings(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Interactive approve surfaces the unanimous-zero escalation before approval."""
        monkeypatch.chdir(ces_project)

        mock_services = _make_mock_services()
        mock_store = MagicMock()
        mock_store.get_review_findings.return_value = _make_review_data(unanimous_zero_findings=True)
        mock_services["local_store"] = mock_store

        with _patch_services(mock_services), patch("ces.cli.approve_cmd.WorkflowEngine", return_value=AsyncMock()):
            app = _get_app()
            result = runner.invoke(app, ["approve", "EP-unanimous-zero"], input="y\n")

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "all reviewers reported zero findings" in result.stdout
        assert "explicit human review" in result.stdout
        mock_services["audit_ledger"].record_approval.assert_called_once()


class TestApproveJsonMode:
    """Tests for ces approve --json output mode."""

    def test_json_output_mode(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces --json approve --yes outputs decision as JSON."""
        monkeypatch.chdir(ces_project)

        mock_services = _make_mock_services()

        with _patch_services(mock_services), patch("ces.cli.approve_cmd.WorkflowEngine", return_value=AsyncMock()):
            app = _get_app()
            result = runner.invoke(app, ["--json", "approve", "EP-json", "--yes"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        output = result.stdout.strip()
        parsed = json.loads(output)
        assert isinstance(parsed, dict)
        assert parsed["decision"] == "approved"

    def test_json_output_includes_unanimous_zero_findings(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Persisted unanimous-zero review metadata is preserved in approve JSON output."""
        monkeypatch.chdir(ces_project)

        mock_services = _make_mock_services()
        mock_store = MagicMock()
        mock_store.get_review_findings.return_value = _make_review_data(unanimous_zero_findings=True)
        mock_services["local_store"] = mock_store

        with (
            _patch_services(mock_services),
            patch("ces.cli.approve_cmd.WorkflowEngine", return_value=AsyncMock()),
            patch("ces.cli.approve_cmd.typer.confirm", return_value=True),
        ):
            app = _get_app()
            result = runner.invoke(app, ["--json", "approve", "EP-json-unanimous-zero"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        parsed = json.loads(result.stdout.strip())
        assert parsed["decision"] == "approved"
        assert parsed["unanimous_zero_findings"] is True


class TestApproveMergeControllerIntegration:
    """Tests for MergeController integration in approve flow (MERGE-01/02/03)."""

    def test_approve_calls_merge_controller_validate_merge(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """approve_cmd calls merge_controller.validate_merge() after recording approval."""
        monkeypatch.chdir(ces_project)

        from ces.control.models.merge_decision import MergeDecision

        mock_services = _make_mock_services()
        mock_merge_ctrl = AsyncMock()
        mock_merge_ctrl.validate_merge = AsyncMock(return_value=MergeDecision(allowed=True, checks=[], reason=""))
        mock_services["merge_controller"] = mock_merge_ctrl
        saved_states: list[object] = []

        async def _capture_saved_manifest(manifest: Any) -> Any:
            saved_states.append(manifest.workflow_state)
            return manifest

        mock_services["manifest_manager"].save_manifest.side_effect = _capture_saved_manifest

        mock_engine = AsyncMock()
        mock_engine.complete_review = AsyncMock(return_value=WorkflowState.APPROVED)
        mock_engine.approve_merge = AsyncMock(return_value=WorkflowState.MERGED)

        with _patch_services(mock_services), patch("ces.cli.approve_cmd.WorkflowEngine", return_value=mock_engine):
            app = _get_app()
            result = runner.invoke(app, ["approve", "EP-merge-test", "--yes"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        mock_merge_ctrl.validate_merge.assert_called_once()

    def test_approve_shows_merge_passed_when_allowed(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """approve_cmd shows 'Merge validation passed' when MergeDecision.allowed is True."""
        monkeypatch.chdir(ces_project)

        from ces.control.models.merge_decision import MergeDecision

        mock_services = _make_mock_services()
        mock_merge_ctrl = AsyncMock()
        mock_merge_ctrl.validate_merge = AsyncMock(return_value=MergeDecision(allowed=True, checks=[], reason=""))
        mock_services["merge_controller"] = mock_merge_ctrl

        mock_engine = AsyncMock()
        mock_engine.complete_review = AsyncMock(return_value=WorkflowState.APPROVED)
        mock_engine.approve_merge = AsyncMock(return_value=WorkflowState.MERGED)

        with _patch_services(mock_services), patch("ces.cli.approve_cmd.WorkflowEngine", return_value=mock_engine):
            app = _get_app()
            result = runner.invoke(app, ["approve", "EP-merge-pass", "--yes"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        # Rich mode: "Merge Validation Passed"; JSON mode: "merge_allowed": true
        assert "merge validation passed" in result.stdout.lower() or '"merge_allowed": true' in result.stdout

    def test_approve_shows_merge_blocked_when_not_allowed(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """approve_cmd shows 'Merge blocked' when MergeDecision.allowed is False."""
        monkeypatch.chdir(ces_project)

        from ces.control.models.merge_decision import MergeDecision

        mock_services = _make_mock_services()
        mock_merge_ctrl = AsyncMock()
        mock_merge_ctrl.validate_merge = AsyncMock(
            return_value=MergeDecision(
                allowed=False,
                checks=[],
                reason="evidence_exists, manifest_fresh",
            )
        )
        mock_services["merge_controller"] = mock_merge_ctrl

        mock_engine = AsyncMock()
        mock_engine.complete_review = AsyncMock()

        with _patch_services(mock_services), patch("ces.cli.approve_cmd.WorkflowEngine", return_value=mock_engine):
            app = _get_app()
            result = runner.invoke(app, ["approve", "EP-merge-block", "--yes"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        # Rich mode: "Merge Blocked"; JSON mode: "merge_allowed": false
        assert "merge blocked" in result.stdout.lower() or '"merge_allowed": false' in result.stdout

    def test_approve_creates_workflow_engine_and_transitions(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """approve_cmd creates WorkflowEngine with manifest_id and calls complete_review + approve_merge."""
        monkeypatch.chdir(ces_project)

        from ces.control.models.merge_decision import MergeDecision

        mock_services = _make_mock_services()
        mock_merge_ctrl = AsyncMock()
        mock_merge_ctrl.validate_merge = AsyncMock(return_value=MergeDecision(allowed=True, checks=[], reason=""))
        mock_services["merge_controller"] = mock_merge_ctrl
        saved_states: list[object] = []

        async def _capture_saved_manifest(manifest: Any) -> Any:
            saved_states.append(manifest.workflow_state)
            return manifest

        mock_services["manifest_manager"].save_manifest.side_effect = _capture_saved_manifest

        mock_engine = AsyncMock()
        mock_engine.complete_review = AsyncMock(return_value=WorkflowState.APPROVED)
        mock_engine.approve_merge = AsyncMock(return_value=WorkflowState.MERGED)

        with (
            _patch_services(mock_services),
            patch("ces.cli.approve_cmd.WorkflowEngine", return_value=mock_engine) as mock_we_cls,
        ):
            app = _get_app()
            result = runner.invoke(app, ["approve", "EP-workflow", "--yes"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        # WorkflowEngine created with manifest_id and audit_ledger
        mock_we_cls.assert_called_once()
        call_kwargs = mock_we_cls.call_args
        assert call_kwargs.kwargs.get("manifest_id") == "M-approve123"
        assert call_kwargs.kwargs.get("audit_ledger") is not None
        # complete_review and approve_merge called
        mock_engine.complete_review.assert_called_once()
        mock_engine.approve_merge.assert_called_once()
        assert saved_states == [WorkflowState.APPROVED, WorkflowState.MERGED]

    def test_unanimous_zero_escalates_required_gate_and_uses_human_actual_gate(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """approve_cmd preserves the stricter review gate in merge validation."""
        monkeypatch.chdir(ces_project)

        mock_services = _make_mock_services()
        mock_store = MagicMock()
        mock_store.get_review_findings.return_value = _make_review_data(unanimous_zero_findings=True)
        mock_services["local_store"] = mock_store

        mock_merge_ctrl = AsyncMock()
        mock_merge_ctrl.validate_merge = AsyncMock(return_value=MergeDecision(allowed=True, checks=[], reason=""))
        mock_services["merge_controller"] = mock_merge_ctrl

        mock_engine = AsyncMock()
        mock_engine.complete_review = AsyncMock()
        mock_engine.approve_merge = AsyncMock()

        with _patch_services(mock_services), patch("ces.cli.approve_cmd.WorkflowEngine", return_value=mock_engine):
            app = _get_app()
            result = runner.invoke(app, ["approve", "EP-merge-unanimous-zero"], input="y\n")

        assert result.exit_code == 0, f"stdout={result.stdout}"
        call_kwargs = mock_merge_ctrl.validate_merge.call_args.kwargs
        assert call_kwargs["required_gate_type"] == GateType.HYBRID
        assert call_kwargs["actual_gate_type"] == GateType.HUMAN

    def test_approve_signs_unsigned_manifest_before_merge_validation(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """approve_cmd signs legacy unsigned manifests before relying on merge hash checks."""
        monkeypatch.chdir(ces_project)

        manifest = TaskManifest(
            manifest_id="M-unsigned-approve",
            description="Add payment processing",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=(),
            token_budget=50_000,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            workflow_state=WorkflowState.UNDER_REVIEW,
            version=1,
            status=ArtifactStatus.DRAFT,
            owner="cli-user",
            created_at=datetime.now(timezone.utc),
            last_confirmed=datetime.now(timezone.utc),
        )
        signed_manifest = manifest.model_copy(
            update={
                "status": ArtifactStatus.APPROVED,
                "signature": "sig-approve-123",
                "content_hash": "sha256:approve-123",
            }
        )

        mock_services = _make_mock_services()
        mock_services["manifest_manager"].get_manifest = AsyncMock(return_value=manifest)
        mock_services["manifest_manager"].sign_manifest = AsyncMock(return_value=signed_manifest)
        mock_merge_ctrl = AsyncMock()
        mock_merge_ctrl.validate_merge = AsyncMock(return_value=MergeDecision(allowed=True, checks=[], reason=""))
        mock_services["merge_controller"] = mock_merge_ctrl

        mock_engine = AsyncMock()
        mock_engine.complete_review = AsyncMock(return_value=WorkflowState.APPROVED)
        mock_engine.approve_merge = AsyncMock(return_value=WorkflowState.MERGED)

        with _patch_services(mock_services), patch("ces.cli.approve_cmd.WorkflowEngine", return_value=mock_engine):
            app = _get_app()
            result = runner.invoke(app, ["approve", "EP-unsigned-approve", "--yes"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        mock_services["manifest_manager"].sign_manifest.assert_awaited_once_with(manifest)
        merge_kwargs = mock_merge_ctrl.validate_merge.call_args.kwargs
        assert merge_kwargs["manifest_content_hash"] == "sha256:approve-123"
        assert merge_kwargs["evidence_manifest_hash"] == "sha256:approve-123"

    def test_rejection_skips_merge_validation_but_transitions_workflow(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Approval rejection avoids merge validation and records a rejected workflow state."""
        monkeypatch.chdir(ces_project)

        mock_services = _make_mock_services()
        mock_merge_ctrl = AsyncMock()
        mock_services["merge_controller"] = mock_merge_ctrl

        mock_engine = AsyncMock()
        mock_engine.reject = AsyncMock(return_value=WorkflowState.REJECTED)

        with _patch_services(mock_services), patch("ces.cli.approve_cmd.WorkflowEngine", return_value=mock_engine):
            app = _get_app()
            result = runner.invoke(
                app,
                ["approve", "EP-reject-no-merge"],
                input="n\n",
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        mock_merge_ctrl.validate_merge.assert_not_called()
        mock_engine.reject.assert_awaited_once()
        mock_engine.complete_review.assert_not_called()
        mock_engine.approve_merge.assert_not_called()
        saved_manifest = mock_services["manifest_manager"].save_manifest.await_args.args[0]
        assert saved_manifest.workflow_state == WorkflowState.REJECTED

    def test_approve_reuses_already_approved_manifest_without_second_complete_review(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """approve_cmd can retry merge validation from an already-approved manifest."""
        monkeypatch.chdir(ces_project)

        mock_services = _make_mock_services()
        approved_manifest = _make_mock_manifest(workflow_state=WorkflowState.APPROVED)
        mock_services["manifest_manager"].get_manifest = AsyncMock(return_value=approved_manifest)

        mock_engine = AsyncMock()
        mock_engine.approve_merge = AsyncMock(return_value=WorkflowState.MERGED)

        with (
            _patch_services(mock_services),
            patch("ces.cli.approve_cmd.WorkflowEngine", return_value=mock_engine) as mock_we_cls,
        ):
            app = _get_app()
            result = runner.invoke(app, ["approve", "EP-approved-rerun", "--yes"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert mock_we_cls.call_args.kwargs.get("initial_state") == WorkflowState.APPROVED.value
        mock_engine.complete_review.assert_not_called()
        mock_engine.approve_merge.assert_awaited_once()

    def test_approve_rejects_invalid_manifest_workflow_state(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """approve_cmd fails closed when invoked before review has started."""
        monkeypatch.chdir(ces_project)

        mock_services = _make_mock_services()
        queued_manifest = _make_mock_manifest(workflow_state=WorkflowState.QUEUED)
        mock_services["manifest_manager"].get_manifest = AsyncMock(return_value=queued_manifest)

        with _patch_services(mock_services), patch("ces.cli.approve_cmd.WorkflowEngine", return_value=AsyncMock()):
            app = _get_app()
            result = runner.invoke(app, ["approve", "EP-invalid-state", "--yes"])

        assert result.exit_code != 0, f"stdout={result.stdout}"
        assert "must be under_review or approved" in result.stdout
        mock_services["merge_controller"].validate_merge.assert_not_called()
        mock_services["audit_ledger"].record_approval.assert_not_called()

    def test_approve_merged_manifest_points_to_builder_report(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """approve_cmd keeps merged manifests closed but points to historical reports."""
        monkeypatch.chdir(ces_project)

        mock_services = _make_mock_services()
        merged_manifest = _make_mock_manifest(workflow_state=WorkflowState.MERGED)
        mock_services["manifest_manager"].get_manifest = AsyncMock(return_value=merged_manifest)

        with _patch_services(mock_services), patch("ces.cli.approve_cmd.WorkflowEngine", return_value=AsyncMock()):
            app = _get_app()
            result = runner.invoke(app, ["approve", "EP-merged", "--yes"])

        assert result.exit_code != 0, f"stdout={result.stdout}"
        assert "already merged" in result.stdout
        assert "ces report builder" in result.stdout
        assert "ces status" in result.stdout
        assert "ces audit" in result.stdout
        mock_services["merge_controller"].validate_merge.assert_not_called()
        mock_services["audit_ledger"].record_approval.assert_not_called()

    def test_approve_reject_path_blocks_already_approved_manifest(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """approve_cmd does not allow rejecting a manifest that is already approved."""
        monkeypatch.chdir(ces_project)

        mock_services = _make_mock_services()
        approved_manifest = _make_mock_manifest(workflow_state=WorkflowState.APPROVED)
        mock_services["manifest_manager"].get_manifest = AsyncMock(return_value=approved_manifest)

        with _patch_services(mock_services), patch("ces.cli.approve_cmd.WorkflowEngine", return_value=AsyncMock()):
            app = _get_app()
            result = runner.invoke(app, ["approve", "EP-approved-no"], input="n\n")

        assert result.exit_code != 0, f"stdout={result.stdout}"
        assert "must be under_review to reject" in result.stdout
        mock_services["audit_ledger"].record_approval.assert_not_called()
