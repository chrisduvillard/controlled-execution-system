"""Tests for the guided local-first `ces run` command."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from ces.control.models.manifest import TaskManifest
from ces.control.models.merge_decision import MergeDecision
from ces.shared.enums import ArtifactStatus, BehaviorConfidence, ChangeClass, RiskTier, WorkflowState

runner = CliRunner()


def _get_app():
    from ces.cli import app

    return app


def _patch_services(mock_services: dict[str, Any]):
    @asynccontextmanager
    async def _fake_get_services():
        yield mock_services

    return patch("ces.cli.run_cmd.get_services", new=_fake_get_services)


def _completion_stdout(task_id: str, criterion: str = "Portfolio site renders") -> str:
    return (
        "Done\n"
        "```ces:completion\n"
        "{"
        f'"task_id": "{task_id}", '
        '"summary": "did it", '
        '"files_changed": [], '
        f'"criteria_satisfied": [{{"criterion": "{criterion}", "evidence": "manual inspection", '
        '"evidence_kind": "manual_inspection"}], '
        '"open_questions": [], '
        '"scope_deviations": []'
        "}\n"
        "```"
    )


def test_brownfield_prompt_pack_includes_promoted_prl_statements() -> None:
    from ces.cli._builder_flow import BuilderBriefDraft
    from ces.cli.run_cmd import _prompt_pack

    prompt = _prompt_pack(
        BuilderBriefDraft(
            request="Add discounts",
            project_mode="brownfield",
            constraints=[],
            acceptance_criteria=[],
            must_not_break=[],
            open_questions={},
            source_of_truth="tests",
            critical_flows=[],
        ),
        promoted_prl_statements=["Preserve legacy tax rounding"],
    )

    assert "Promoted Legacy Requirements:" in prompt
    assert "- Preserve legacy tax rounding" in prompt


def test_builder_prompt_pack_attaches_engineering_charter() -> None:
    from ces.cli._builder_flow import BuilderBriefDraft
    from ces.cli.run_cmd import _prompt_pack

    prompt = _prompt_pack(
        BuilderBriefDraft(
            request="Add discounts",
            project_mode="greenfield",
            constraints=[],
            acceptance_criteria=["Discounts apply at checkout"],
            must_not_break=[],
            open_questions={},
            source_of_truth=None,
            critical_flows=[],
        ),
    )

    assert "Explore first" in prompt
    assert "clarify or block" in prompt
    assert "ces:completion" in prompt
    assert "Discounts apply at checkout" in prompt


class TestRunCommand:
    def test_build_yes_with_description_requires_acceptance_context(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "manifest_manager": AsyncMock(),
            "runtime_registry": MagicMock(resolve_runtime=MagicMock(side_effect=RuntimeError("should not run"))),
            "agent_runner": AsyncMock(),
            "local_store": MagicMock(),
            "evidence_synthesizer": MagicMock(),
            "audit_ledger": AsyncMock(),
            "sensor_orchestrator": MagicMock(run_all=AsyncMock(return_value=[])),
            "legacy_behavior_service": AsyncMock(),
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["build", "Build a habit tracker", "--yes"])

        assert result.exit_code != 0
        assert "--acceptance" in result.stdout
        mock_services["runtime_registry"].resolve_runtime.assert_not_called()

    def test_brownfield_yes_requires_explicit_preservation_context(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "app.py").write_text("print('existing')\n", encoding="utf-8")
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "manifest_manager": AsyncMock(),
            "runtime_registry": MagicMock(resolve_runtime=MagicMock(side_effect=RuntimeError("should not run"))),
            "agent_runner": AsyncMock(),
            "local_store": MagicMock(),
            "evidence_synthesizer": MagicMock(),
            "audit_ledger": AsyncMock(),
            "sensor_orchestrator": MagicMock(run_all=AsyncMock(return_value=[])),
            "legacy_behavior_service": AsyncMock(),
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "build",
                    "Change existing app",
                    "--brownfield",
                    "--yes",
                    "--acceptance",
                    "Existing app still starts",
                ],
            )

        assert result.exit_code != 0
        assert "--source-of-truth" in result.stdout
        assert "--critical-flow" in result.stdout
        mock_services["runtime_registry"].resolve_runtime.assert_not_called()

    def test_build_reports_demo_mode_does_not_replace_runtime(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        prompts = iter(
            [
                "Build a habit tracker",
                "Expose an HTTP endpoint",
                "User can create and complete habits",
                "Existing CLI commands",
            ]
        )
        monkeypatch.setattr("ces.cli.run_cmd.typer.prompt", lambda *args, **kwargs: next(prompts))

        mock_store = MagicMock()
        mock_store.save_builder_brief.return_value = "BB-runtime-missing"
        mock_store.save_builder_session.return_value = "BS-runtime-missing"
        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "manifest_manager": AsyncMock(),
            "runtime_registry": MagicMock(resolve_runtime=MagicMock(side_effect=RuntimeError("no runtime detected"))),
            "agent_runner": AsyncMock(),
            "local_store": mock_store,
            "evidence_synthesizer": MagicMock(),
            "audit_ledger": AsyncMock(),
            "sensor_orchestrator": MagicMock(run_all=AsyncMock(return_value=[])),
            "legacy_behavior_service": AsyncMock(),
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["build", "--yes"])

        assert result.exit_code == 1, f"stdout={result.stdout}"
        assert "No agent runtime found" in result.stdout
        assert "does not replace the required runtime" in result.stdout
        assert "ces doctor" in result.stdout
        mock_store.save_builder_brief.assert_called_once()
        mock_store.save_builder_session.assert_called_once()
        mock_store.update_builder_session.assert_called_once()
        assert mock_store.update_builder_session.call_args.args[0] == "BS-runtime-missing"
        assert mock_store.update_builder_session.call_args.kwargs["stage"] == "blocked"
        assert mock_store.update_builder_session.call_args.kwargs["next_action"] == "install_runtime"

    def test_build_auto_bootstraps_local_project_when_ces_dir_is_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        prompts = iter(
            [
                "Expose an HTTP endpoint",
                "User can create and complete habits",
                "Existing CLI commands",
            ]
        )
        monkeypatch.setattr("ces.cli.run_cmd.typer.prompt", lambda *args, **kwargs: next(prompts))

        manifest = MagicMock()
        manifest.manifest_id = "M-build123"
        manifest.description = "Build a habit tracker"
        manifest.risk_tier = RiskTier.C
        manifest.behavior_confidence = BehaviorConfidence.BC1
        manifest.change_class = ChangeClass.CLASS_1
        manifest.affected_files = []

        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = manifest
        saved_states: list[object] = []

        async def _capture_saved_manifest(saved_manifest: Any) -> Any:
            saved_states.append(saved_manifest.workflow_state)
            return saved_manifest

        mock_manager.save_manifest.side_effect = _capture_saved_manifest
        mock_runtime = MagicMock()
        mock_runtime.runtime_name = "codex"
        mock_runtime.generate_manifest_assist.return_value = {
            "description": "Build a habit tracker",
            "risk_tier": RiskTier.C.value,
            "behavior_confidence": BehaviorConfidence.BC1.value,
            "change_class": ChangeClass.CLASS_1.value,
            "affected_files": ["api.py"],
            "token_budget": 50000,
            "reasoning": "Low-risk greenfield request",
        }
        mock_runtime_registry = MagicMock()
        mock_runtime_registry.resolve_runtime.return_value = mock_runtime
        mock_runner = AsyncMock()
        mock_runner.execute_runtime.return_value = {
            "runtime_name": "codex",
            "runtime_version": "1.0.0",
            "reported_model": None,
            "invocation_ref": "run-123",
            "exit_code": 0,
            "stdout": _completion_stdout("M-run-merge"),
            "stderr": "",
            "duration_seconds": 0.5,
        }
        mock_store = MagicMock()
        mock_store.save_builder_brief.return_value = "BB-123"
        mock_synth = MagicMock()
        mock_synth.format_summary_slots = AsyncMock(return_value=MagicMock(summary="Line 1", challenge="Challenge 1"))
        mock_synth.triage = AsyncMock(
            return_value=MagicMock(
                color=MagicMock(value="green"),
                auto_approve_eligible=False,
                reason="Looks fine",
            )
        )

        mock_provider_registry = MagicMock()
        mock_provider_registry.get_provider.side_effect = KeyError("no provider")

        mock_services = {
            "settings": MagicMock(default_runtime="codex", default_model_id="claude-3-opus"),
            "manifest_manager": mock_manager,
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "local_store": mock_store,
            "evidence_synthesizer": mock_synth,
            "audit_ledger": AsyncMock(),
            "sensor_orchestrator": MagicMock(run_all=AsyncMock(return_value=[])),
            "legacy_behavior_service": AsyncMock(),
            "provider_registry": mock_provider_registry,
            "project_config": {"preferred_runtime": "codex"},
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                ["build", "Build a habit tracker", "--yes", "--acceptance", "User can create and complete habits"],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert (tmp_path / ".ces").is_dir()
        assert (tmp_path / ".ces" / "config.yaml").exists()
        assert "set up local project state" in result.stdout.lower()

    def test_build_without_description_prompts_and_persists_builder_brief(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        prompts = iter(
            [
                "Build a habit tracker",
                "Expose an HTTP endpoint",
                "User can create and complete habits",
                "Existing CLI commands",
            ]
        )
        monkeypatch.setattr("ces.cli.run_cmd.typer.prompt", lambda *args, **kwargs: next(prompts))

        manifest = MagicMock()
        manifest.manifest_id = "M-build123"
        manifest.description = "Build a habit tracker"
        manifest.risk_tier = RiskTier.C
        manifest.behavior_confidence = BehaviorConfidence.BC1
        manifest.change_class = ChangeClass.CLASS_1
        manifest.affected_files = []

        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = manifest
        mock_runtime = MagicMock()
        mock_runtime.runtime_name = "codex"
        mock_runtime.generate_manifest_assist.return_value = {
            "description": "Build a habit tracker",
            "risk_tier": RiskTier.C.value,
            "behavior_confidence": BehaviorConfidence.BC1.value,
            "change_class": ChangeClass.CLASS_1.value,
            "affected_files": ["api.py"],
            "token_budget": 50000,
            "reasoning": "Low-risk greenfield request",
        }
        mock_runtime_registry = MagicMock()
        mock_runtime_registry.resolve_runtime.return_value = mock_runtime
        mock_runner = AsyncMock()
        mock_runner.execute_runtime.return_value = {
            "runtime_name": "codex",
            "runtime_version": "1.0.0",
            "reported_model": None,
            "invocation_ref": "run-123",
            "exit_code": 0,
            "stdout": _completion_stdout("M-run-merge-blocked"),
            "stderr": "",
            "duration_seconds": 0.5,
        }
        mock_store = MagicMock()
        mock_store.save_builder_brief.return_value = "BB-123"
        mock_synth = MagicMock()
        mock_synth.format_summary_slots = AsyncMock(return_value=MagicMock(summary="Line 1", challenge="Challenge 1"))
        mock_synth.triage = AsyncMock(
            return_value=MagicMock(
                color=MagicMock(value="green"),
                auto_approve_eligible=False,
                reason="Looks fine",
            )
        )

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "manifest_manager": mock_manager,
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "local_store": mock_store,
            "evidence_synthesizer": mock_synth,
            "audit_ledger": AsyncMock(),
            "sensor_orchestrator": MagicMock(run_all=AsyncMock(return_value=[])),
            "legacy_behavior_service": AsyncMock(),
            "project_config": {"preferred_runtime": "codex"},
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["build", "--yes"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        mock_store.save_builder_brief.assert_called_once()
        brief_kwargs = mock_store.save_builder_brief.call_args.kwargs
        assert brief_kwargs["request"] == "Build a habit tracker"
        assert brief_kwargs["project_mode"] == "greenfield"
        assert brief_kwargs["constraints"] == ["Expose an HTTP endpoint"]
        assert brief_kwargs["acceptance_criteria"] == ["User can create and complete habits"]
        assert brief_kwargs["must_not_break"] == ["Existing CLI commands"]

    def test_build_alias_runs_guided_flow(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        manifest = MagicMock()
        manifest.manifest_id = "M-build123"
        manifest.description = "Build portfolio site"
        manifest.risk_tier = RiskTier.C
        manifest.behavior_confidence = BehaviorConfidence.BC1
        manifest.change_class = ChangeClass.CLASS_1
        manifest.affected_files = []

        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = manifest
        mock_runtime = MagicMock()
        mock_runtime.runtime_name = "codex"
        mock_runtime.generate_manifest_assist.return_value = {
            "description": "Build portfolio site",
            "risk_tier": RiskTier.C.value,
            "behavior_confidence": BehaviorConfidence.BC1.value,
            "change_class": ChangeClass.CLASS_1.value,
            "affected_files": [],
            "token_budget": 50000,
            "reasoning": "Guided local draft",
        }
        mock_runtime_registry = MagicMock()
        mock_runtime_registry.resolve_runtime.return_value = mock_runtime
        mock_runner = AsyncMock()
        mock_runner.execute_runtime.return_value = {
            "runtime_name": "codex",
            "runtime_version": "1.0.0",
            "reported_model": None,
            "invocation_ref": "run-123",
            "exit_code": 0,
            "stdout": _completion_stdout("M-run-merge"),
            "stderr": "",
            "duration_seconds": 0.5,
        }
        mock_store = MagicMock()
        mock_synth = MagicMock()
        mock_synth.format_summary_slots = AsyncMock(return_value=MagicMock(summary="Line 1", challenge="Challenge 1"))
        mock_synth.triage = AsyncMock(
            return_value=MagicMock(
                color=MagicMock(value="green"),
                auto_approve_eligible=False,
                reason="Looks fine",
            )
        )

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "manifest_manager": mock_manager,
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "local_store": mock_store,
            "evidence_synthesizer": mock_synth,
            "audit_ledger": AsyncMock(),
            "sensor_orchestrator": MagicMock(run_all=AsyncMock(return_value=[])),
            "legacy_behavior_service": AsyncMock(),
        }

        monkeypatch.setattr("ces.cli.run_cmd.typer.prompt", lambda *args, **kwargs: "")
        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "build",
                    "Build portfolio site",
                    "--yes",
                    "--accept-runtime-side-effects",
                    "--acceptance",
                    "Portfolio site renders",
                ],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        mock_manager.create_manifest.assert_awaited_once()
        mock_runtime_registry.resolve_runtime.assert_called_once()
        mock_runner.execute_runtime.assert_awaited_once()
        mock_store.save_runtime_execution.assert_called_once()

    def test_build_uses_project_root_as_runtime_working_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_root = tmp_path / "repo"
        nested_dir = project_root / "src" / "feature"
        nested_dir.mkdir(parents=True)
        monkeypatch.chdir(nested_dir)

        ces_dir = project_root / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        prompts = iter(
            [
                "Build a habit tracker",
                "Expose an HTTP endpoint",
                "User can create and complete habits",
                "Existing CLI commands",
            ]
        )
        monkeypatch.setattr("ces.cli.run_cmd.typer.prompt", lambda *args, **kwargs: next(prompts))

        manifest = MagicMock()
        manifest.manifest_id = "M-build-root"
        manifest.description = "Build a habit tracker"
        manifest.risk_tier = RiskTier.C
        manifest.behavior_confidence = BehaviorConfidence.BC1
        manifest.change_class = ChangeClass.CLASS_1
        manifest.affected_files = []

        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = manifest
        mock_runtime = MagicMock()
        mock_runtime.runtime_name = "codex"
        mock_runtime.generate_manifest_assist.return_value = {
            "description": "Build a habit tracker",
            "risk_tier": RiskTier.C.value,
            "behavior_confidence": BehaviorConfidence.BC1.value,
            "change_class": ChangeClass.CLASS_1.value,
            "affected_files": ["api.py"],
            "token_budget": 50000,
            "reasoning": "Low-risk greenfield request",
        }
        mock_runtime_registry = MagicMock()
        mock_runtime_registry.resolve_runtime.return_value = mock_runtime
        mock_runner = AsyncMock()
        mock_runner.execute_runtime.return_value = {
            "runtime_name": "codex",
            "runtime_version": "1.0.0",
            "reported_model": None,
            "invocation_ref": "run-root",
            "exit_code": 0,
            "stdout": _completion_stdout("M-run-merge"),
            "stderr": "",
            "duration_seconds": 0.5,
        }
        mock_store = MagicMock()
        mock_store.save_builder_brief.return_value = "BB-root"
        mock_synth = MagicMock()
        mock_synth.format_summary_slots = AsyncMock(return_value=MagicMock(summary="Line 1", challenge="Challenge 1"))
        mock_synth.triage = AsyncMock(
            return_value=MagicMock(
                color=MagicMock(value="green"),
                auto_approve_eligible=False,
                reason="Looks fine",
            )
        )

        mock_services = {
            "settings": MagicMock(default_runtime="codex", default_model_id="claude-3-opus"),
            "manifest_manager": mock_manager,
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "local_store": mock_store,
            "evidence_synthesizer": mock_synth,
            "audit_ledger": AsyncMock(),
            "sensor_orchestrator": MagicMock(run_all=AsyncMock(return_value=[])),
            "legacy_behavior_service": AsyncMock(),
            "provider_registry": MagicMock(get_provider=MagicMock(side_effect=KeyError("no provider"))),
            "project_config": {"preferred_runtime": "codex"},
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["build", "--yes"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert mock_runner.execute_runtime.await_args.kwargs["working_dir"] == project_root
        mock_store.save_evidence.assert_called_once()
        mock_store.save_approval.assert_called_once()

    def test_run_guides_manifest_execute_and_approval(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        manifest = MagicMock()
        manifest.manifest_id = "M-run123"
        manifest.description = "Build portfolio site"
        manifest.risk_tier = RiskTier.C
        manifest.behavior_confidence = BehaviorConfidence.BC1
        manifest.change_class = ChangeClass.CLASS_1
        manifest.affected_files = []

        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = manifest
        mock_runtime = MagicMock()
        mock_runtime.runtime_name = "codex"
        mock_runtime.generate_manifest_assist.return_value = {
            "description": "Build portfolio site",
            "risk_tier": RiskTier.C.value,
            "behavior_confidence": BehaviorConfidence.BC1.value,
            "change_class": ChangeClass.CLASS_1.value,
            "affected_files": [],
            "token_budget": 50000,
            "reasoning": "Guided local draft",
        }
        mock_runtime_registry = MagicMock()
        mock_runtime_registry.resolve_runtime.return_value = mock_runtime
        mock_runner = AsyncMock()
        mock_runner.execute_runtime.return_value = {
            "runtime_name": "codex",
            "runtime_version": "1.0.0",
            "reported_model": None,
            "invocation_ref": "run-123",
            "exit_code": 0,
            "stdout": _completion_stdout("M-run-merge-blocked"),
            "stderr": "",
            "duration_seconds": 0.5,
        }
        mock_store = MagicMock()
        mock_synth = MagicMock()
        mock_synth.format_summary_slots = AsyncMock(return_value=MagicMock(summary="Line 1", challenge="Challenge 1"))
        mock_synth.triage = AsyncMock(
            return_value=MagicMock(
                color=MagicMock(value="green"),
                auto_approve_eligible=False,
                reason="Looks fine",
            )
        )

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "manifest_manager": mock_manager,
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "local_store": mock_store,
            "evidence_synthesizer": mock_synth,
            "audit_ledger": AsyncMock(),
            "sensor_orchestrator": MagicMock(run_all=AsyncMock(return_value=[])),
            "legacy_behavior_service": AsyncMock(),
        }

        monkeypatch.setattr("ces.cli.run_cmd.typer.prompt", lambda *args, **kwargs: "")
        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                ["run", "Build portfolio site", "--yes", "--acceptance", "Portfolio site renders"],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        mock_manager.create_manifest.assert_awaited_once()
        mock_runtime_registry.resolve_runtime.assert_called_once()
        mock_runner.execute_runtime.assert_awaited_once()
        mock_store.save_runtime_execution.assert_called_once()
        mock_store.save_evidence.assert_called_once()
        mock_store.save_approval.assert_called_once()

    def test_build_approval_runs_workflow_and_merge_validation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        manifest = MagicMock()
        manifest.manifest_id = "M-run-merge"
        manifest.description = "Build portfolio site"
        manifest.risk_tier = RiskTier.C
        manifest.behavior_confidence = BehaviorConfidence.BC1
        manifest.change_class = ChangeClass.CLASS_1
        manifest.affected_files = []

        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = manifest
        saved_states: list[object] = []

        async def _capture_saved_manifest(saved_manifest: Any) -> Any:
            saved_states.append(saved_manifest.workflow_state)
            return saved_manifest

        mock_manager.save_manifest.side_effect = _capture_saved_manifest
        mock_runtime = MagicMock()
        mock_runtime.runtime_name = "codex"
        mock_runtime.generate_manifest_assist.return_value = {
            "description": "Build portfolio site",
            "risk_tier": RiskTier.C.value,
            "behavior_confidence": BehaviorConfidence.BC1.value,
            "change_class": ChangeClass.CLASS_1.value,
            "affected_files": [],
            "token_budget": 50000,
            "reasoning": "Guided local draft",
        }
        mock_runtime_registry = MagicMock()
        mock_runtime_registry.resolve_runtime.return_value = mock_runtime
        mock_runner = AsyncMock()
        mock_runner.execute_runtime.return_value = {
            "runtime_name": "codex",
            "runtime_version": "1.0.0",
            "reported_model": None,
            "invocation_ref": "run-123",
            "exit_code": 0,
            "stdout": _completion_stdout("M-run-sign"),
            "stderr": "",
            "duration_seconds": 0.5,
        }
        mock_store = MagicMock()
        mock_store.save_builder_brief.return_value = "BB-123"
        mock_synth = MagicMock()
        mock_synth.format_summary_slots = AsyncMock(return_value=MagicMock(summary="Line 1", challenge="Challenge 1"))
        mock_synth.triage = AsyncMock(
            return_value=MagicMock(
                color=MagicMock(value="green"),
                auto_approve_eligible=False,
                reason="Looks fine",
            )
        )
        mock_merge_ctrl = AsyncMock()
        mock_merge_ctrl.validate_merge = AsyncMock(return_value=MergeDecision(allowed=True, checks=[], reason=""))
        mock_workflow = AsyncMock()
        mock_workflow.submit_for_review = AsyncMock(return_value=WorkflowState.UNDER_REVIEW)
        mock_workflow.complete_review = AsyncMock(return_value=WorkflowState.APPROVED)
        mock_workflow.approve_merge = AsyncMock(return_value=WorkflowState.MERGED)

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "manifest_manager": mock_manager,
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "local_store": mock_store,
            "evidence_synthesizer": mock_synth,
            "audit_ledger": AsyncMock(),
            "sensor_orchestrator": MagicMock(run_all=AsyncMock(return_value=[])),
            "legacy_behavior_service": AsyncMock(),
            "merge_controller": mock_merge_ctrl,
        }

        monkeypatch.setattr("ces.cli.run_cmd.typer.prompt", lambda *args, **kwargs: "")
        with _patch_services(mock_services), patch("ces.cli.run_cmd.WorkflowEngine", return_value=mock_workflow):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "build",
                    "Build portfolio site",
                    "--yes",
                    "--accept-runtime-side-effects",
                    "--acceptance",
                    "Portfolio site renders",
                ],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        mock_workflow.submit_for_review.assert_awaited_once()
        mock_workflow.complete_review.assert_awaited_once()
        mock_workflow.approve_merge.assert_awaited_once()
        merge_kwargs = mock_merge_ctrl.validate_merge.call_args.kwargs
        assert merge_kwargs["required_gate_type"].value == "agent"
        assert merge_kwargs["actual_gate_type"].value == "human"
        assert saved_states == [
            WorkflowState.IN_FLIGHT,
            WorkflowState.UNDER_REVIEW,
            WorkflowState.APPROVED,
            WorkflowState.MERGED,
        ]
        assert "Merge Validation Passed" in result.stdout

    def test_build_merge_block_keeps_builder_session_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        manifest = MagicMock()
        manifest.manifest_id = "M-run-merge-blocked"
        manifest.description = "Build portfolio site"
        manifest.risk_tier = RiskTier.C
        manifest.behavior_confidence = BehaviorConfidence.BC1
        manifest.change_class = ChangeClass.CLASS_1
        manifest.affected_files = []

        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = manifest
        saved_states: list[object] = []

        async def _capture_saved_manifest(saved_manifest: Any) -> Any:
            saved_states.append(saved_manifest.workflow_state)
            return saved_manifest

        mock_manager.save_manifest.side_effect = _capture_saved_manifest
        mock_runtime = MagicMock()
        mock_runtime.runtime_name = "codex"
        mock_runtime.generate_manifest_assist.return_value = {
            "description": "Build portfolio site",
            "risk_tier": RiskTier.C.value,
            "behavior_confidence": BehaviorConfidence.BC1.value,
            "change_class": ChangeClass.CLASS_1.value,
            "affected_files": [],
            "token_budget": 50000,
            "reasoning": "Guided local draft",
        }
        mock_runtime_registry = MagicMock()
        mock_runtime_registry.resolve_runtime.return_value = mock_runtime
        mock_runner = AsyncMock()
        mock_runner.execute_runtime.return_value = {
            "runtime_name": "codex",
            "runtime_version": "1.0.0",
            "reported_model": None,
            "invocation_ref": "run-123",
            "exit_code": 0,
            "stdout": _completion_stdout("M-run-merge-blocked"),
            "stderr": "",
            "duration_seconds": 0.5,
        }
        mock_store = MagicMock()
        mock_store.save_builder_brief.return_value = "BB-123"
        mock_store.save_builder_session.return_value = "BS-123"
        mock_synth = MagicMock()
        mock_synth.format_summary_slots = AsyncMock(return_value=MagicMock(summary="Line 1", challenge="Challenge 1"))
        mock_synth.triage = AsyncMock(
            return_value=MagicMock(
                color=MagicMock(value="green"),
                auto_approve_eligible=False,
                reason="Looks fine",
            )
        )
        mock_merge_ctrl = AsyncMock()
        mock_merge_ctrl.validate_merge = AsyncMock(
            return_value=MergeDecision(allowed=False, checks=[], reason="review_complete")
        )
        mock_workflow = AsyncMock()
        mock_workflow.submit_for_review = AsyncMock(return_value=WorkflowState.UNDER_REVIEW)
        mock_workflow.complete_review = AsyncMock(return_value=WorkflowState.APPROVED)
        mock_workflow.approve_merge = AsyncMock()

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "manifest_manager": mock_manager,
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "local_store": mock_store,
            "evidence_synthesizer": mock_synth,
            "audit_ledger": AsyncMock(),
            "sensor_orchestrator": MagicMock(run_all=AsyncMock(return_value=[])),
            "legacy_behavior_service": AsyncMock(),
            "merge_controller": mock_merge_ctrl,
        }

        monkeypatch.setattr("ces.cli.run_cmd.typer.prompt", lambda *args, **kwargs: "")
        with _patch_services(mock_services), patch("ces.cli.run_cmd.WorkflowEngine", return_value=mock_workflow):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "build",
                    "Build portfolio site",
                    "--yes",
                    "--accept-runtime-side-effects",
                    "--acceptance",
                    "Portfolio site renders",
                ],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        mock_workflow.submit_for_review.assert_awaited_once()
        mock_workflow.complete_review.assert_awaited_once()
        mock_workflow.approve_merge.assert_not_awaited()
        assert saved_states == [
            WorkflowState.IN_FLIGHT,
            WorkflowState.UNDER_REVIEW,
            WorkflowState.APPROVED,
        ]
        final_session_update = mock_store.update_builder_session.call_args_list[-1].kwargs
        assert final_session_update["stage"] == "blocked"
        assert final_session_update["last_action"] == "merge_blocked"
        assert "Merge Blocked" in result.stdout

    def test_build_signs_unsigned_manifest_before_merge_validation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        manifest = TaskManifest(
            manifest_id="M-run-sign",
            description="Build portfolio site",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_1,
            affected_files=(),
            token_budget=50_000,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            workflow_state=WorkflowState.QUEUED,
            version=1,
            status=ArtifactStatus.DRAFT,
            owner="cli-user",
            created_at=datetime.now(timezone.utc),
            last_confirmed=datetime.now(timezone.utc),
        )
        signed_manifest = manifest.model_copy(
            update={
                "status": ArtifactStatus.APPROVED,
                "signature": "sig-123",
                "content_hash": "sha256:manifest-123",
            }
        )

        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = manifest
        mock_manager.sign_manifest = AsyncMock(return_value=signed_manifest)
        mock_runtime = MagicMock()
        mock_runtime.runtime_name = "codex"
        mock_runtime.generate_manifest_assist.return_value = {
            "description": "Build portfolio site",
            "risk_tier": RiskTier.C.value,
            "behavior_confidence": BehaviorConfidence.BC1.value,
            "change_class": ChangeClass.CLASS_1.value,
            "affected_files": [],
            "token_budget": 50000,
            "reasoning": "Guided local draft",
        }
        mock_runtime_registry = MagicMock()
        mock_runtime_registry.resolve_runtime.return_value = mock_runtime
        mock_runner = AsyncMock()
        mock_runner.execute_runtime.return_value = {
            "runtime_name": "codex",
            "runtime_version": "1.0.0",
            "reported_model": None,
            "invocation_ref": "run-123",
            "exit_code": 0,
            "stdout": _completion_stdout("M-run-sign"),
            "stderr": "",
            "duration_seconds": 0.5,
        }
        mock_store = MagicMock()
        mock_store.save_builder_brief.return_value = "BB-123"
        mock_synth = MagicMock()
        mock_synth.format_summary_slots = AsyncMock(return_value=MagicMock(summary="Line 1", challenge="Challenge 1"))
        mock_synth.triage = AsyncMock(
            return_value=MagicMock(
                color=MagicMock(value="green"),
                auto_approve_eligible=False,
                reason="Looks fine",
            )
        )
        mock_merge_ctrl = AsyncMock()
        mock_merge_ctrl.validate_merge = AsyncMock(return_value=MergeDecision(allowed=True, checks=[], reason=""))
        mock_workflow = AsyncMock()
        mock_workflow.submit_for_review = AsyncMock(return_value=WorkflowState.UNDER_REVIEW)
        mock_workflow.complete_review = AsyncMock(return_value=WorkflowState.APPROVED)
        mock_workflow.approve_merge = AsyncMock(return_value=WorkflowState.MERGED)

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "manifest_manager": mock_manager,
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "local_store": mock_store,
            "evidence_synthesizer": mock_synth,
            "audit_ledger": AsyncMock(),
            "sensor_orchestrator": MagicMock(run_all=AsyncMock(return_value=[])),
            "legacy_behavior_service": AsyncMock(),
            "merge_controller": mock_merge_ctrl,
        }

        monkeypatch.setattr("ces.cli.run_cmd.typer.prompt", lambda *args, **kwargs: "")
        with _patch_services(mock_services), patch("ces.cli.run_cmd.WorkflowEngine", return_value=mock_workflow):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "build",
                    "Build portfolio site",
                    "--yes",
                    "--accept-runtime-side-effects",
                    "--acceptance",
                    "Portfolio site renders",
                ],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        mock_manager.sign_manifest.assert_awaited_once_with(manifest)
        merge_kwargs = mock_merge_ctrl.validate_merge.call_args.kwargs
        assert merge_kwargs["manifest_content_hash"] == "sha256:manifest-123"
        assert merge_kwargs["evidence_manifest_hash"] == "sha256:manifest-123"

    def test_run_uses_builder_first_copy_by_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        manifest = MagicMock()
        manifest.manifest_id = "M-run123"
        manifest.description = "Build portfolio site"
        manifest.risk_tier = RiskTier.C
        manifest.behavior_confidence = BehaviorConfidence.BC1
        manifest.change_class = ChangeClass.CLASS_1
        manifest.affected_files = []

        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = manifest
        mock_runtime = MagicMock()
        mock_runtime.runtime_name = "codex"
        mock_runtime.generate_manifest_assist.return_value = {
            "description": "Build portfolio site",
            "risk_tier": RiskTier.C.value,
            "behavior_confidence": BehaviorConfidence.BC1.value,
            "change_class": ChangeClass.CLASS_1.value,
            "affected_files": [],
            "token_budget": 50000,
            "reasoning": "Guided local draft",
        }
        mock_runtime_registry = MagicMock()
        mock_runtime_registry.resolve_runtime.return_value = mock_runtime
        mock_runner = AsyncMock()
        mock_runner.execute_runtime.return_value = {
            "runtime_name": "codex",
            "runtime_version": "1.0.0",
            "reported_model": None,
            "invocation_ref": "run-123",
            "exit_code": 0,
            "stdout": "Done",
            "stderr": "",
            "duration_seconds": 0.5,
        }
        mock_store = MagicMock()
        mock_synth = MagicMock()
        mock_synth.format_summary_slots = AsyncMock(return_value=MagicMock(summary="Line 1", challenge="Challenge 1"))
        mock_synth.triage = AsyncMock(
            return_value=MagicMock(
                color=MagicMock(value="green"),
                auto_approve_eligible=False,
                reason="Looks fine",
            )
        )

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "manifest_manager": mock_manager,
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "local_store": mock_store,
            "evidence_synthesizer": mock_synth,
            "audit_ledger": AsyncMock(),
            "sensor_orchestrator": MagicMock(run_all=AsyncMock(return_value=[])),
            "legacy_behavior_service": AsyncMock(),
        }

        monkeypatch.setattr("ces.cli.run_cmd.typer.prompt", lambda *args, **kwargs: "")
        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                ["run", "Build portfolio site", "--yes", "--acceptance", "Portfolio site renders"],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "Plan For Your Request" in result.stdout
        assert "What CES Found" in result.stdout
        assert "Build Review Complete" in result.stdout
        create_kwargs = mock_manager.create_manifest.call_args.kwargs
        assert create_kwargs["verification_sensors"] == ["test_pass", "lint", "typecheck", "coverage"]
        assert create_kwargs["requires_exploration_evidence"] is True
        assert create_kwargs["requires_verification_commands"] is True
        assert create_kwargs["requires_impacted_flow_evidence"] is False

    def test_build_auto_detects_brownfield_and_reviews_candidate_behaviors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")
        (tmp_path / "legacy_app.py").write_text("print('legacy')\n")

        prompts = iter(
            [
                "Keep the existing CSV export intact",
                "Admins can still export billing rows",
                "CSV export format",
                "README and exported CSV samples",
                "Billing export and monthly reconciliation",
                "preserve",
                "",
                "preserve",
                "change",
                "under_investigation",
                "preserve",
                "",
                "preserve",
                "",
            ]
        )
        monkeypatch.setattr("ces.cli.run_cmd.typer.prompt", lambda *args, **kwargs: next(prompts))

        manifest = MagicMock()
        manifest.manifest_id = "M-brown123"
        manifest.description = "Add invoice notes"
        manifest.risk_tier = RiskTier.B
        manifest.behavior_confidence = BehaviorConfidence.BC2
        manifest.change_class = ChangeClass.CLASS_2
        manifest.affected_files = []

        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = manifest
        mock_runtime = MagicMock()
        mock_runtime.runtime_name = "codex"
        mock_runtime.generate_manifest_assist.return_value = {
            "description": "Add invoice notes",
            "risk_tier": RiskTier.B.value,
            "behavior_confidence": BehaviorConfidence.BC2.value,
            "change_class": ChangeClass.CLASS_2.value,
            "affected_files": ["legacy_app.py"],
            "token_budget": 75000,
            "reasoning": "Brownfield change in an existing codebase",
        }
        mock_runtime_registry = MagicMock()
        mock_runtime_registry.resolve_runtime.return_value = mock_runtime
        mock_runner = AsyncMock()
        mock_runner.execute_runtime.return_value = {
            "runtime_name": "codex",
            "runtime_version": "1.0.0",
            "reported_model": None,
            "invocation_ref": "run-123",
            "exit_code": 0,
            "stdout": "Done",
            "stderr": "",
            "duration_seconds": 0.5,
        }
        mock_store = MagicMock()
        mock_store.save_builder_brief.return_value = "BB-123"
        mock_synth = MagicMock()
        mock_synth.format_summary_slots = AsyncMock(return_value=MagicMock(summary="Line 1", challenge="Challenge 1"))
        mock_synth.triage = AsyncMock(
            return_value=MagicMock(
                color=MagicMock(value="yellow"),
                auto_approve_eligible=False,
                reason="Looks fine",
            )
        )
        mock_legacy = AsyncMock()
        candidate = MagicMock(entry_id="OLB-123", behavior_description="CSV export keeps current column order")
        reviewed = MagicMock(entry_id="OLB-123", disposition="preserve")
        mock_legacy.register_behavior = AsyncMock(return_value=candidate)
        mock_legacy.review_behavior = AsyncMock(return_value=reviewed)

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "manifest_manager": mock_manager,
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "local_store": mock_store,
            "evidence_synthesizer": mock_synth,
            "audit_ledger": AsyncMock(),
            "sensor_orchestrator": MagicMock(run_all=AsyncMock(return_value=[])),
            "legacy_behavior_service": mock_legacy,
            "project_config": {"preferred_runtime": "codex"},
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "build",
                    "Add invoice notes",
                    "--yes",
                    "--acceptance",
                    "Invoice notes are saved",
                    "--source-of-truth",
                    "legacy_app.py",
                    "--critical-flow",
                    "Invoice editing",
                ],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        brief_kwargs = mock_store.save_builder_brief.call_args.kwargs
        assert brief_kwargs["project_mode"] == "brownfield"
        assert brief_kwargs["source_of_truth"] == "legacy_app.py"
        assert brief_kwargs["critical_flows"] == ["Invoice editing"]

    def test_brownfield_yes_blocks_auto_approval_when_manifest_scope_is_unknown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "legacy_app.py").write_text("print('existing')\n", encoding="utf-8")
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        manifest = MagicMock()
        manifest.manifest_id = "M-brown-scope"
        manifest.description = "Modernize invoice editing"
        manifest.risk_tier = RiskTier.B
        manifest.behavior_confidence = BehaviorConfidence.BC2
        manifest.change_class = ChangeClass.CLASS_2
        manifest.affected_files = []

        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = manifest
        mock_runtime = MagicMock()
        mock_runtime.runtime_name = "codex"
        mock_runtime.generate_manifest_assist.return_value = {
            "description": "Modernize invoice editing",
            "risk_tier": RiskTier.B.value,
            "behavior_confidence": BehaviorConfidence.BC2.value,
            "change_class": ChangeClass.CLASS_2.value,
            "affected_files": [],
            "token_budget": 75000,
            "reasoning": "Brownfield change but scope was not identified",
        }
        mock_runtime_registry = MagicMock()
        mock_runtime_registry.resolve_runtime.return_value = mock_runtime
        mock_runner = AsyncMock()
        mock_runner.execute_runtime.return_value = {
            "runtime_name": "codex",
            "runtime_version": "1.0.0",
            "reported_model": None,
            "invocation_ref": "run-123",
            "exit_code": 0,
            "stdout": _completion_stdout("M-brown-scope", "Invoice editing still works"),
            "stderr": "",
            "duration_seconds": 0.5,
        }
        mock_store = MagicMock()
        mock_store.save_builder_brief.return_value = "BB-123"
        mock_synth = MagicMock()
        mock_synth.format_summary_slots = AsyncMock(return_value=MagicMock(summary="Line 1", challenge="Challenge 1"))
        mock_synth.triage = AsyncMock(
            return_value=MagicMock(
                color=MagicMock(value="yellow"),
                auto_approve_eligible=False,
                reason="Scope unclear",
            )
        )

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "manifest_manager": mock_manager,
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "local_store": mock_store,
            "evidence_synthesizer": mock_synth,
            "audit_ledger": AsyncMock(),
            "sensor_orchestrator": MagicMock(run_all=AsyncMock(return_value=[])),
            "legacy_behavior_service": AsyncMock(),
            "project_config": {"preferred_runtime": "codex"},
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "build",
                    "Modernize invoice editing",
                    "--brownfield",
                    "--yes",
                    "--accept-runtime-side-effects",
                    "--acceptance",
                    "Invoice editing still works",
                    "--source-of-truth",
                    "legacy_app.py",
                    "--critical-flow",
                    "Invoice editing",
                ],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        approval_kwargs = mock_store.save_approval.call_args.kwargs
        assert approval_kwargs["decision"] == "reject"
        assert "brownfield scope unknown" in approval_kwargs["rationale"]

    def test_build_can_export_prl_draft(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        prompts = iter(
            [
                "Expose an HTTP endpoint",
                "User can create and complete habits",
                "Existing CLI commands",
            ]
        )
        monkeypatch.setattr("ces.cli.run_cmd.typer.prompt", lambda *args, **kwargs: next(prompts))

        manifest = MagicMock()
        manifest.manifest_id = "M-build123"
        manifest.description = "Build a habit tracker"
        manifest.risk_tier = RiskTier.C
        manifest.behavior_confidence = BehaviorConfidence.BC1
        manifest.change_class = ChangeClass.CLASS_1
        manifest.affected_files = []

        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = manifest
        mock_runtime = MagicMock()
        mock_runtime.runtime_name = "codex"
        mock_runtime.generate_manifest_assist.return_value = {
            "description": "Build a habit tracker",
            "risk_tier": RiskTier.C.value,
            "behavior_confidence": BehaviorConfidence.BC1.value,
            "change_class": ChangeClass.CLASS_1.value,
            "affected_files": ["api.py"],
            "token_budget": 50000,
            "reasoning": "Low-risk greenfield request",
        }
        mock_runtime_registry = MagicMock()
        mock_runtime_registry.resolve_runtime.return_value = mock_runtime
        mock_runner = AsyncMock()
        mock_runner.execute_runtime.return_value = {
            "runtime_name": "codex",
            "runtime_version": "1.0.0",
            "reported_model": None,
            "invocation_ref": "run-123",
            "exit_code": 0,
            "stdout": "Done",
            "stderr": "",
            "duration_seconds": 0.5,
        }
        mock_store = MagicMock()
        mock_store.save_builder_brief.return_value = "BB-123"
        mock_synth = MagicMock()
        mock_synth.format_summary_slots = AsyncMock(return_value=MagicMock(summary="Line 1", challenge="Challenge 1"))
        mock_synth.triage = AsyncMock(
            return_value=MagicMock(
                color=MagicMock(value="green"),
                auto_approve_eligible=False,
                reason="Looks fine",
            )
        )

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "manifest_manager": mock_manager,
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "local_store": mock_store,
            "evidence_synthesizer": mock_synth,
            "audit_ledger": AsyncMock(),
            "sensor_orchestrator": MagicMock(run_all=AsyncMock(return_value=[])),
            "legacy_behavior_service": AsyncMock(),
            "project_config": {"preferred_runtime": "codex"},
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "build",
                    "Build a habit tracker",
                    "--yes",
                    "--acceptance",
                    "User can create and complete habits",
                    "--export-prl-draft",
                ],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "PRL draft" in result.stdout

    def test_continue_reuses_latest_builder_brief_without_prompting(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        monkeypatch.setattr(
            "ces.cli.run_cmd.typer.prompt",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("prompt should not be called")),
        )

        manifest = MagicMock()
        manifest.manifest_id = "M-continue123"
        manifest.description = "Build a habit tracker"
        manifest.risk_tier = RiskTier.C
        manifest.behavior_confidence = BehaviorConfidence.BC1
        manifest.change_class = ChangeClass.CLASS_1
        manifest.affected_files = []

        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = manifest
        mock_runtime = MagicMock()
        mock_runtime.runtime_name = "codex"
        mock_runtime.generate_manifest_assist.return_value = {
            "description": "Build a habit tracker",
            "risk_tier": RiskTier.C.value,
            "behavior_confidence": BehaviorConfidence.BC1.value,
            "change_class": ChangeClass.CLASS_1.value,
            "affected_files": ["api.py"],
            "token_budget": 50000,
            "reasoning": "Low-risk greenfield request",
        }
        mock_runtime_registry = MagicMock()
        mock_runtime_registry.resolve_runtime.return_value = mock_runtime
        mock_runner = AsyncMock()
        mock_runner.execute_runtime.return_value = {
            "runtime_name": "codex",
            "runtime_version": "1.0.0",
            "reported_model": None,
            "invocation_ref": "run-123",
            "exit_code": 0,
            "stdout": "Done",
            "stderr": "",
            "duration_seconds": 0.5,
        }
        mock_store = MagicMock()
        mock_store.get_latest_builder_brief.return_value = MagicMock(
            brief_id="BB-123",
            request="Build a habit tracker",
            project_mode="greenfield",
            constraints=["Expose an HTTP endpoint"],
            acceptance_criteria=["User can create and complete habits"],
            must_not_break=["Existing CLI commands"],
            open_questions={"constraints": "Expose an HTTP endpoint"},
            source_of_truth="",
            critical_flows=[],
            manifest_id=None,
            evidence_packet_id=None,
            prl_draft_path=None,
        )
        mock_store.save_builder_brief.return_value = "BB-124"
        mock_synth = MagicMock()
        mock_synth.format_summary_slots = AsyncMock(return_value=MagicMock(summary="Line 1", challenge="Challenge 1"))
        mock_synth.triage = AsyncMock(
            return_value=MagicMock(
                color=MagicMock(value="green"),
                auto_approve_eligible=False,
                reason="Looks fine",
            )
        )

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "manifest_manager": mock_manager,
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "local_store": mock_store,
            "evidence_synthesizer": mock_synth,
            "audit_ledger": AsyncMock(),
            "sensor_orchestrator": MagicMock(run_all=AsyncMock(return_value=[])),
            "legacy_behavior_service": AsyncMock(),
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["continue", "--yes"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        create_kwargs = mock_manager.create_manifest.call_args.kwargs
        assert create_kwargs["description"] == "Build a habit tracker"
        assert "Plan For Your Request" in result.stdout

    def test_continue_does_not_restart_completed_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        monkeypatch.setattr(
            "ces.cli.run_cmd.typer.prompt",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("prompt should not be called")),
        )

        mock_store = MagicMock()
        mock_store.get_latest_builder_session.return_value = MagicMock(
            session_id="BS-123",
            request="Build a habit tracker",
            project_mode="greenfield",
            stage="completed",
            next_action="start_new_session",
            brief_id="BB-123",
        )

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "manifest_manager": AsyncMock(),
            "runtime_registry": MagicMock(),
            "agent_runner": AsyncMock(),
            "local_store": mock_store,
            "evidence_synthesizer": MagicMock(),
            "audit_ledger": AsyncMock(),
            "sensor_orchestrator": MagicMock(run_all=AsyncMock(return_value=[])),
            "legacy_behavior_service": AsyncMock(),
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["continue", "--yes"])

        assert result.exit_code == 0
        assert "already completed" in result.stdout.lower()
        assert "ces explain" in result.stdout

    def test_continue_resumes_grouped_brownfield_review_checkpoint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        prompts = iter(["preserve", "change", "under_investigation", "", "preserve", ""])
        monkeypatch.setattr("ces.cli.run_cmd.typer.prompt", lambda *args, **kwargs: next(prompts))

        manifest = MagicMock()
        manifest.manifest_id = "M-continue123"
        manifest.description = "Modernize billing exports"
        manifest.risk_tier = RiskTier.B
        manifest.behavior_confidence = BehaviorConfidence.BC2
        manifest.change_class = ChangeClass.CLASS_2
        manifest.affected_files = []

        mock_manager = AsyncMock()
        mock_runtime = MagicMock()
        mock_runtime.runtime_name = "codex"
        mock_runtime.generate_manifest_assist.return_value = {
            "description": "Modernize billing exports",
            "risk_tier": RiskTier.B.value,
            "behavior_confidence": BehaviorConfidence.BC2.value,
            "change_class": ChangeClass.CLASS_2.value,
            "affected_files": ["billing_export.py"],
            "token_budget": 75000,
            "reasoning": "Brownfield change in an existing codebase",
        }
        mock_runtime_registry = MagicMock()
        mock_runtime_registry.resolve_runtime.return_value = mock_runtime
        mock_runner = AsyncMock()
        mock_runner.execute_runtime.return_value = {
            "runtime_name": "codex",
            "runtime_version": "1.0.0",
            "reported_model": None,
            "invocation_ref": "run-123",
            "exit_code": 0,
            "stdout": "Done",
            "stderr": "",
            "duration_seconds": 0.5,
        }
        session = MagicMock(
            session_id="BS-123",
            request="Modernize billing exports",
            project_mode="brownfield",
            stage="collecting",
            next_action="review_brownfield",
            brief_id="BB-123",
            manifest_id="M-continue123",
            brownfield_review_state={
                "groups": [
                    {
                        "key": "must_not_break",
                        "label": "Must Not Break",
                        "items": [
                            {
                                "description": "Preserve existing behavior for CSV export format",
                                "primary_group": "must_not_break",
                                "rationale": "Surfaced from the operator's must-not-break constraints.",
                                "secondary_groups": [],
                            }
                        ],
                    },
                    {
                        "key": "critical_flows",
                        "label": "Critical Flows",
                        "items": [
                            {
                                "description": "Critical flow remains intact: Billing export",
                                "primary_group": "critical_flows",
                                "rationale": "Surfaced from the operator's critical brownfield flows.",
                                "secondary_groups": [],
                            }
                        ],
                    },
                    {
                        "key": "repo_signals",
                        "label": "Repo Signals",
                        "items": [
                            {
                                "description": "Review current behavior in billing_export.py",
                                "primary_group": "repo_signals",
                                "rationale": "Surfaced from repository files that look behaviorally sensitive.",
                                "secondary_groups": [],
                            }
                        ],
                    },
                    {
                        "key": "source_of_truth",
                        "label": "Source Of Truth",
                        "items": [
                            {
                                "description": "Validate behavior against README and snapshots",
                                "primary_group": "source_of_truth",
                                "rationale": "Surfaced from the operator's named source of truth.",
                                "secondary_groups": [],
                            }
                        ],
                    },
                ],
                "group_index": 1,
                "item_index": 0,
                "reviewed_candidates": [
                    {
                        "description": "Preserve existing behavior for CSV export format",
                        "disposition": "preserve",
                    }
                ],
                "group_defaults": {"must_not_break": "preserve"},
            },
            attempt_count=0,
        )
        mock_store = MagicMock()
        mock_store.get_latest_builder_session.return_value = session
        mock_store.get_builder_session.return_value = session
        mock_store.get_manifest_row.return_value = manifest
        mock_store.get_builder_brief.return_value = MagicMock(
            brief_id="BB-123",
            request="Modernize billing exports",
            project_mode="brownfield",
            constraints=["Keep CSV compatibility"],
            acceptance_criteria=["Exports include invoice notes"],
            must_not_break=["CSV export format"],
            open_questions={"must_not_break": "CSV export format"},
            source_of_truth="README and snapshots",
            critical_flows=["Billing export"],
            manifest_id="M-continue123",
            evidence_packet_id=None,
            prl_draft_path=None,
        )
        mock_synth = MagicMock()
        mock_synth.format_summary_slots = AsyncMock(return_value=MagicMock(summary="Line 1", challenge="Challenge 1"))
        mock_synth.triage = AsyncMock(
            return_value=MagicMock(
                color=MagicMock(value="yellow"),
                auto_approve_eligible=False,
                reason="Looks fine",
            )
        )
        mock_legacy = AsyncMock()
        mock_legacy.register_behavior = AsyncMock(
            side_effect=[
                MagicMock(entry_id="OLB-2"),
                MagicMock(entry_id="OLB-3"),
                MagicMock(entry_id="OLB-4"),
            ]
        )
        mock_legacy.review_behavior = AsyncMock(
            side_effect=[
                MagicMock(entry_id="OLB-2", disposition="change"),
                MagicMock(entry_id="OLB-3", disposition="under_investigation"),
                MagicMock(entry_id="OLB-4", disposition="preserve"),
            ]
        )

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "manifest_manager": mock_manager,
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "local_store": mock_store,
            "evidence_synthesizer": mock_synth,
            "audit_ledger": AsyncMock(),
            "sensor_orchestrator": MagicMock(run_all=AsyncMock(return_value=[])),
            "legacy_behavior_service": mock_legacy,
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["continue", "--yes"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        mock_manager.create_manifest.assert_not_awaited()
        assert mock_legacy.register_behavior.await_count == 3
        reviewed_descriptions = [
            call.kwargs["behavior_description"] for call in mock_legacy.register_behavior.await_args_list
        ]
        assert "Preserve existing behavior for CSV export format" not in reviewed_descriptions

    def test_explain_overview_summarizes_latest_builder_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        mock_store = MagicMock()
        mock_store.get_latest_builder_brief.return_value = MagicMock(
            brief_id="BB-123",
            request="Modernize billing exports",
            project_mode="brownfield",
            constraints=["Keep CSV compatibility"],
            acceptance_criteria=["Exports include invoice notes"],
            must_not_break=["CSV export format"],
            source_of_truth="README and exported CSV samples",
            critical_flows=["Billing export"],
            manifest_id="M-123",
            evidence_packet_id="EP-123",
            prl_draft_path=".ces/exports/prl-draft-bb-123.md",
        )
        mock_store.get_manifest_row.return_value = MagicMock(
            manifest_id="M-123",
            workflow_state="in_flight",
            risk_tier="B",
            change_class="Class 2",
        )
        mock_store.get_evidence.return_value = {
            "summary": "Builder flow ran successfully",
            "challenge": "Check the CSV snapshots",
            "triage_color": "yellow",
        }
        mock_legacy = AsyncMock()
        mock_legacy.get_pending_behaviors = AsyncMock(return_value=[MagicMock(entry_id="OLB-1")])

        mock_store.get_latest_builder_session.return_value = MagicMock(
            session_id="BS-123",
            request="Modernize billing exports",
            project_mode="brownfield",
            stage="awaiting_review",
            next_action="review_evidence",
            last_action="evidence_ready",
            source_of_truth="README and exported CSV samples",
            critical_flows=["Billing export"],
            manifest_id="M-123",
            evidence_packet_id="EP-123",
            brief_id="BB-123",
            brownfield_review_state=None,
        )

        mock_services = {"local_store": mock_store, "legacy_behavior_service": mock_legacy}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["explain"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        out = result.stdout
        assert "CES thinks you're building: Modernize billing exports" in out
        assert "Why CES asked follow-up questions" in out
        assert "keep the work inside your technical boundaries" in out
        assert "Current stage: awaiting review" in out
        assert "Review evidence before shipping." in out

    def test_explain_translates_blocked_session_language(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        mock_store = MagicMock()
        mock_store.get_latest_builder_session.return_value = MagicMock(
            session_id="BS-123",
            request="Modernize billing exports",
            project_mode="brownfield",
            stage="blocked",
            next_action="retry_runtime",
            recovery_reason="retry_execution",
            last_error="codex exited with code 1",
            source_of_truth="README and exported CSV samples",
            critical_flows=["Billing export"],
            manifest_id="M-123",
            evidence_packet_id="EP-123",
            brief_id="BB-123",
        )
        mock_store.get_latest_builder_brief.return_value = MagicMock(
            request="Modernize billing exports",
            project_mode="brownfield",
            constraints=["Keep CSV compatibility"],
            acceptance_criteria=["Exports include invoice notes"],
            must_not_break=["CSV export format"],
            source_of_truth="README and exported CSV samples",
            critical_flows=["Billing export"],
            manifest_id="M-123",
            evidence_packet_id="EP-123",
            prl_draft_path=".ces/exports/prl-draft-bb-123.md",
        )
        mock_store.get_manifest_row.return_value = MagicMock(
            manifest_id="M-123",
            workflow_state="in_flight",
            risk_tier="B",
            change_class="Class 2",
        )
        mock_store.get_evidence.return_value = {
            "summary": "Builder flow ran successfully",
            "challenge": "Check the CSV snapshots",
            "triage_color": "yellow",
        }
        mock_legacy = AsyncMock()
        mock_legacy.get_pending_behaviors = AsyncMock(return_value=[])

        mock_services = {
            "local_store": mock_store,
            "legacy_behavior_service": mock_legacy,
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["explain"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        out = result.stdout
        assert "Current stage: blocked" in out
        assert "Waiting for a runtime retry." in out
        assert "Retry the last runtime execution with `ces continue`." in out

    def test_explain_decisioning_view_can_include_governance_details(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        mock_store = MagicMock()
        mock_store.get_latest_builder_session.return_value = MagicMock(
            session_id="BS-123",
            request="Modernize billing exports",
            project_mode="brownfield",
            stage="awaiting_review",
            next_action="review_evidence",
            last_action="evidence_ready",
            source_of_truth="README and exported CSV samples",
            critical_flows=["Billing export"],
            manifest_id="M-123",
            evidence_packet_id="EP-123",
            brief_id="BB-123",
        )
        mock_store.get_latest_builder_brief.return_value = MagicMock(
            request="Modernize billing exports",
            project_mode="brownfield",
            constraints=["Keep CSV compatibility"],
            acceptance_criteria=["Exports include invoice notes"],
            must_not_break=["CSV export format"],
            open_questions={"constraints": "Keep CSV compatibility"},
            source_of_truth="README and exported CSV samples",
            critical_flows=["Billing export"],
            manifest_id="M-123",
            evidence_packet_id="EP-123",
            prl_draft_path=".ces/exports/prl-draft-bb-123.md",
        )
        mock_store.get_manifest_row.return_value = MagicMock(
            manifest_id="M-123",
            description="Modernize billing exports",
            workflow_state="in_flight",
            risk_tier="B",
            change_class="Class 2",
        )
        mock_store.get_evidence.return_value = {
            "packet_id": "EP-123",
            "summary": "Builder flow ran successfully",
            "challenge": "Check the CSV snapshots",
            "triage_color": "yellow",
        }
        mock_services = {
            "local_store": mock_store,
            "legacy_behavior_service": AsyncMock(get_pending_behaviors=AsyncMock(return_value=[])),
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["explain", "--view", "decisioning", "--governance"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        out = result.stdout
        assert "CES planned this change as: Modernize billing exports" in out
        assert "Evidence gathered: Builder flow ran successfully" in out
        assert "Main challenge: Check the CSV snapshots" in out
        assert "Manifest ID: M-123" in out
        assert "Evidence packet: EP-123" in out

    def test_explain_brownfield_view_summarizes_review_checkpoint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        mock_store = MagicMock()
        mock_store.get_latest_builder_session.return_value = MagicMock(
            session_id="BS-123",
            request="Modernize billing exports",
            project_mode="brownfield",
            stage="collecting",
            next_action="review_brownfield",
            last_action="brownfield_review_in_progress",
            recovery_reason=None,
            last_error=None,
            source_of_truth="README and snapshots",
            critical_flows=["Billing export"],
            manifest_id="M-123",
            evidence_packet_id=None,
            brief_id="BB-123",
            brownfield_review_state={
                "groups": [
                    {
                        "key": "must_not_break",
                        "label": "Must Not Break",
                        "items": [
                            {
                                "description": "Preserve existing behavior for CSV export format",
                                "primary_group": "must_not_break",
                                "rationale": "Surfaced from the operator's must-not-break constraints.",
                                "secondary_groups": [],
                            }
                        ],
                    },
                    {
                        "key": "critical_flows",
                        "label": "Critical Flows",
                        "items": [
                            {
                                "description": "Critical flow remains intact: Billing export",
                                "primary_group": "critical_flows",
                                "rationale": "Surfaced from the operator's critical brownfield flows.",
                                "secondary_groups": [],
                            }
                        ],
                    },
                    {
                        "key": "repo_signals",
                        "label": "Repo Signals",
                        "items": [
                            {
                                "description": "Review current behavior in billing_export.py",
                                "primary_group": "repo_signals",
                                "rationale": "Surfaced from repository files that look behaviorally sensitive.",
                                "secondary_groups": [],
                            }
                        ],
                    },
                    {
                        "key": "source_of_truth",
                        "label": "Source Of Truth",
                        "items": [
                            {
                                "description": "Validate behavior against README and snapshots",
                                "primary_group": "source_of_truth",
                                "rationale": "Surfaced from the operator's named source of truth.",
                                "secondary_groups": [],
                            }
                        ],
                    },
                ],
                "group_index": 1,
                "item_index": 0,
                "reviewed_candidates": [
                    {
                        "description": "Preserve existing behavior for CSV export format",
                        "disposition": "preserve",
                    }
                ],
                "group_defaults": {"must_not_break": "preserve"},
            },
        )
        mock_store.get_builder_brief.return_value = MagicMock(
            request="Modernize billing exports",
            project_mode="brownfield",
            constraints=["Keep CSV compatibility"],
            acceptance_criteria=["Exports include invoice notes"],
            must_not_break=["CSV export format"],
            open_questions={"must_not_break": "CSV export format"},
            source_of_truth="README and snapshots",
            critical_flows=["Billing export"],
            manifest_id="M-123",
            evidence_packet_id=None,
            prl_draft_path=None,
        )
        mock_legacy = AsyncMock()
        mock_legacy.get_pending_behaviors = AsyncMock(return_value=[MagicMock(entry_id="OLB-2")])
        mock_services = {"local_store": mock_store, "legacy_behavior_service": mock_legacy}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["explain", "--view", "brownfield"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        out = result.stdout
        assert "Brownfield review progress: 1 reviewed, 3 remaining" in out
        assert "Current group: Critical Flows" in out
        assert "CES will resume this checkpoint when you run `ces continue`." in out

    def test_explain_falls_back_gracefully_for_older_brief_only_projects(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        mock_store = MagicMock()
        mock_store.get_latest_builder_session.return_value = None
        mock_store.get_latest_builder_brief.return_value = MagicMock(
            request="Build a habit tracker",
            project_mode="greenfield",
            constraints=["Expose an HTTP endpoint"],
            acceptance_criteria=["Users can create habits"],
            must_not_break=["CLI startup"],
            open_questions={"constraints": "Expose an HTTP endpoint"},
            source_of_truth="",
            critical_flows=[],
            manifest_id=None,
            evidence_packet_id=None,
            prl_draft_path=None,
        )
        mock_services = {
            "local_store": mock_store,
            "legacy_behavior_service": AsyncMock(get_pending_behaviors=AsyncMock(return_value=[])),
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["explain"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        out = result.stdout
        assert "Build a habit tracker" in out
        assert "No builder session is recorded yet." in out
        assert "CES is explaining from the saved builder brief." in out

    def test_explain_prefers_shared_snapshot_over_stale_fallback_records(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        mock_store = MagicMock()
        mock_store.get_latest_builder_session_snapshot.return_value = SimpleNamespace(
            request="Modernize billing exports",
            project_mode="brownfield",
            stage="completed",
            next_action="start_new_session",
            next_step="Start a new task with `ces build` when you're ready for the next request.",
            latest_activity="CES recorded the latest review decision.",
            latest_artifact="approval",
            brief_only_fallback=False,
            evidence={"summary": "Evidence is ready", "challenge": "Check snapshots", "packet_id": "EP-123"},
            manifest=SimpleNamespace(
                manifest_id="M-123",
                description="Modernize billing exports",
                workflow_state="approved",
                risk_tier="B",
                change_class="Class 2",
            ),
            approval=SimpleNamespace(decision="approve", rationale="Looks good"),
            session=SimpleNamespace(
                stage="completed",
                recovery_reason=None,
                last_error=None,
            ),
            brownfield=SimpleNamespace(reviewed_count=3, remaining_count=0),
        )
        mock_store.get_latest_builder_session.return_value = MagicMock(
            request="Stale session request",
            project_mode="greenfield",
            stage="blocked",
            next_action="retry_runtime",
        )
        mock_store.get_latest_builder_brief.return_value = MagicMock(
            request="Older fallback brief",
            project_mode="greenfield",
            constraints=["Expose an HTTP endpoint"],
            acceptance_criteria=["Users can create habits"],
            must_not_break=["CLI startup"],
            open_questions={"constraints": "Expose an HTTP endpoint"},
            source_of_truth="",
            critical_flows=[],
            manifest_id=None,
            evidence_packet_id=None,
            prl_draft_path=None,
        )
        mock_services = {
            "local_store": mock_store,
            "legacy_behavior_service": AsyncMock(get_pending_behaviors=AsyncMock(return_value=[])),
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["explain"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        out = result.stdout
        assert "Modernize billing exports" in out
        assert "Start a new task with `ces build`" in out
        assert "Older fallback brief" not in out
