"""Tests for wizard helper functions and wizard flow in ces run command."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import typer
from rich.console import Console
from typer.testing import CliRunner

from ces.cli._wizard_helpers import (
    WIZARD_STEPS,
    ProjectDefaults,
)
from ces.cli._wizard_helpers import (
    build_confirmation_table as _build_confirmation_table,
)
from ces.cli._wizard_helpers import (
    format_scan_results as _format_scan_results,
)
from ces.cli._wizard_helpers import (
    scan_project_defaults as _scan_project_defaults,
)
from ces.cli._wizard_helpers import (
    wizard_step_panel as _wizard_step_panel,
)

runner = CliRunner()


def _get_app():
    from ces.cli import app

    return app


def _patch_services(mock_services: dict[str, Any]):
    @asynccontextmanager
    async def _fake_get_services():
        yield mock_services

    return patch("ces.cli.run_cmd.get_services", new=_fake_get_services)


class TestWizardHelpers:
    """Unit tests for wizard helpers covering WIZ-01, WIZ-02, WIZ-04."""

    # --- ProjectDefaults dataclass ---

    def test_project_defaults_dataclass(self) -> None:
        """ProjectDefaults is a frozen dataclass with the expected fields."""
        defaults = ProjectDefaults(
            project_mode="greenfield",
            has_pytest=False,
            has_ci=False,
            has_coverage_data=False,
            manifest_count=0,
            suggested_risk_tier="B",
        )
        assert defaults.project_mode == "greenfield"
        assert defaults.has_pytest is False
        assert defaults.has_ci is False
        assert defaults.has_coverage_data is False
        assert defaults.manifest_count == 0
        assert defaults.suggested_risk_tier == "B"

        # Frozen: mutation must raise
        with pytest.raises(AttributeError):
            defaults.project_mode = "brownfield"  # type: ignore[misc]

    # --- _scan_project_defaults ---

    def test_scan_project_defaults_greenfield(self, tmp_path: Path) -> None:
        """Empty directory returns greenfield defaults."""
        result = _scan_project_defaults(tmp_path)
        assert result.project_mode == "greenfield"
        assert result.has_pytest is False
        assert result.has_ci is False
        assert result.has_coverage_data is False
        assert result.manifest_count == 0
        assert result.suggested_risk_tier == "B"

    def test_scan_project_defaults_brownfield(self, tmp_path: Path) -> None:
        """Directory with marker files returns brownfield with detected features."""
        # Create conftest.py (pytest marker)
        (tmp_path / "conftest.py").write_text("# conftest", encoding="utf-8")
        # Create CI workflow
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").write_text("name: CI", encoding="utf-8")
        # Create coverage file
        (tmp_path / ".coverage").write_text("", encoding="utf-8")

        result = _scan_project_defaults(tmp_path)
        assert result.project_mode == "brownfield"
        assert result.has_pytest is True
        assert result.has_ci is True
        assert result.has_coverage_data is True

    def test_scan_project_defaults_pyproject_pytest(self, tmp_path: Path) -> None:
        """Detects pytest from pyproject.toml containing [tool.pytest.ini_options]."""
        (tmp_path / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\nminversion = '6.0'\n",
            encoding="utf-8",
        )

        result = _scan_project_defaults(tmp_path)
        assert result.has_pytest is True

    def test_scan_performance(self, tmp_path: Path) -> None:
        """_scan_project_defaults completes in under 2 seconds."""
        # Create some files to make the scan non-trivial
        for i in range(50):
            (tmp_path / f"file_{i}.py").write_text(f"# file {i}", encoding="utf-8")

        start = time.monotonic()
        _scan_project_defaults(tmp_path)
        elapsed = time.monotonic() - start

        assert elapsed < 2.0, f"Scan took {elapsed:.2f}s, exceeds 2s limit"

    # --- _wizard_step_panel ---

    def test_wizard_step_panel_rendering(self) -> None:
        """_wizard_step_panel renders a Panel with 'Step N/M' in output."""
        buf = StringIO()
        test_console = Console(file=buf, force_terminal=True, width=80)

        # Patch the module console temporarily
        import ces.cli._wizard_helpers as run_mod

        original_console = run_mod.console
        run_mod.console = test_console
        try:
            _wizard_step_panel(2, 5, "Risk Classification", "Tier: B")
        finally:
            run_mod.console = original_console

        output = buf.getvalue()
        assert "Step 2/5" in output
        assert "Risk Classification" in output

    def test_wizard_step_panel_with_help(self) -> None:
        """_wizard_step_panel with help_text prints dim help text."""
        buf = StringIO()
        test_console = Console(file=buf, force_terminal=True, width=80)

        import ces.cli._wizard_helpers as run_mod

        original_console = run_mod.console
        run_mod.console = test_console
        try:
            _wizard_step_panel(1, 5, "Project Scan", "Scanning...", help_text="This scans your project")
        finally:
            run_mod.console = original_console

        output = buf.getvalue()
        assert "Step 1/5" in output
        assert "This scans your project" in output

    # --- _build_confirmation_table ---

    def test_confirmation_table_all_fields(self) -> None:
        """_build_confirmation_table returns a Rich Table with 6 rows."""
        table = _build_confirmation_table(
            risk_tier="B",
            affected_files_count=12,
            acceptance_criteria=["Tests pass", "No regressions"],
            runtime="codex",
            brownfield_count=3,
            governance=True,
        )

        assert table.row_count == 6
        assert len(table.columns) == 2

    # --- WIZARD_STEPS constant ---

    def test_wizard_steps_constant(self) -> None:
        """WIZARD_STEPS equals 5."""
        assert WIZARD_STEPS == 5


class TestFormatScanResults:
    """Tests for _format_scan_results helper."""

    def test_format_scan_results_brownfield(self) -> None:
        """_format_scan_results returns human-readable string with all fields."""
        defaults = ProjectDefaults(
            project_mode="brownfield",
            has_pytest=True,
            has_ci=True,
            has_coverage_data=False,
            manifest_count=3,
            suggested_risk_tier="B",
        )
        result = _format_scan_results(defaults)
        assert "brownfield" in result
        assert "Pytest detected: yes" in result
        assert "CI detected: yes" in result
        assert "Coverage data: no" in result
        assert "Existing manifests: 3" in result
        assert "Suggested risk tier: B" in result

    def test_format_scan_results_greenfield(self) -> None:
        """_format_scan_results shows greenfield mode correctly."""
        defaults = ProjectDefaults(
            project_mode="greenfield",
            has_pytest=False,
            has_ci=False,
            has_coverage_data=False,
            manifest_count=0,
            suggested_risk_tier="B",
        )
        result = _format_scan_results(defaults)
        assert "greenfield" in result
        assert "Pytest detected: no" in result
        assert "CI detected: no" in result
        assert "Existing manifests: 0" in result


class TestWizardFlow:
    """Integration tests for _wizard_flow activation, panels, confirmation, spinner."""

    def _make_mock_services(self, tmp_path: Path) -> dict[str, Any]:
        """Create standard mock services for wizard flow tests."""
        from ces.shared.enums import BehaviorConfidence, ChangeClass, RiskTier

        manifest = MagicMock()
        manifest.manifest_id = "M-wiz123"
        manifest.description = "Test wizard task"
        manifest.risk_tier = RiskTier.C
        manifest.behavior_confidence = BehaviorConfidence.BC1
        manifest.change_class = ChangeClass.CLASS_1
        manifest.affected_files = []

        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = manifest

        mock_runtime = MagicMock()
        mock_runtime.runtime_name = "codex"
        mock_runtime.generate_manifest_assist.return_value = {
            "description": "Test wizard task",
            "risk_tier": RiskTier.C.value,
            "behavior_confidence": BehaviorConfidence.BC1.value,
            "change_class": ChangeClass.CLASS_1.value,
            "affected_files": ["api.py"],
            "token_budget": 50000,
        }

        mock_runtime_registry = MagicMock()
        mock_runtime_registry.resolve_runtime.return_value = mock_runtime

        mock_runner = AsyncMock()
        mock_runner.execute_runtime.return_value = {
            "runtime_name": "codex",
            "runtime_version": "1.0.0",
            "reported_model": None,
            "invocation_ref": "run-wiz",
            "exit_code": 0,
            "stdout": (
                "Done\n"
                "```ces:completion\n"
                '{"task_id": "M-wizard", "summary": "did it", "files_changed": [], '
                '"criteria_satisfied": [{"criterion": "tests pass", "evidence": "manual", '
                '"evidence_kind": "manual_inspection"}], "open_questions": [], "scope_deviations": []}\n'
                "```"
            ),
            "stderr": "",
            "duration_seconds": 0.5,
        }

        mock_store = MagicMock()
        mock_store.save_builder_brief.return_value = "BB-wiz"

        mock_synth = MagicMock()
        mock_synth.format_summary_slots = AsyncMock(return_value=MagicMock(summary="Summary", challenge="Challenge"))
        mock_synth.triage = AsyncMock(
            return_value=MagicMock(
                color=MagicMock(value="green"),
                auto_approve_eligible=False,
                reason="OK",
            )
        )

        mock_provider_registry = MagicMock()
        mock_provider_registry.get_provider.side_effect = KeyError("no provider")

        return {
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

    def test_wizard_activates_without_yes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces build without --yes calls _wizard_flow."""
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        mock_services = self._make_mock_services(tmp_path)
        mock_wizard = AsyncMock()

        with _patch_services(mock_services), patch("ces.cli.run_cmd._wizard_flow", mock_wizard):
            app = _get_app()
            result = runner.invoke(app, ["build", "Add endpoint"])

        mock_wizard.assert_called_once()

    def test_yes_bypasses_wizard(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces build --yes does NOT call _wizard_flow."""
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        mock_services = self._make_mock_services(tmp_path)
        mock_wizard = AsyncMock()

        with _patch_services(mock_services), patch("ces.cli.run_cmd._wizard_flow", mock_wizard):
            app = _get_app()
            result = runner.invoke(app, ["build", "Add endpoint", "--yes"])

        mock_wizard.assert_not_called()

    def test_wizard_flow_shows_all_steps(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """_wizard_flow prints panels containing Step 1/5 through Step 5/5."""
        from ces.cli.run_cmd import _wizard_flow

        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        mock_services = self._make_mock_services(tmp_path)
        buf = StringIO()
        test_console = Console(file=buf, force_terminal=True, width=120)

        import ces.cli._wizard_helpers as run_mod

        original_console = run_mod.console
        run_mod.console = test_console

        # Mock typer.prompt to auto-answer and typer.confirm to approve
        prompts = iter(["Add endpoint", "none", "tests pass", "none"])
        monkeypatch.setattr("ces.cli.run_cmd.typer.prompt", lambda *a, **kw: next(prompts, ""))
        monkeypatch.setattr("ces.cli.run_cmd.typer.confirm", lambda *a, **kw: True)

        try:
            asyncio.run(
                _wizard_flow(
                    services=mock_services,
                    project_config={},
                    runtime="auto",
                    brief=False,
                    full=False,
                    governance=False,
                    export_prl_draft=False,
                    project_root=tmp_path,
                    description="Add endpoint",
                    greenfield=False,
                    brownfield_flag=False,
                    accept_runtime_side_effects=True,
                )
            )
        finally:
            run_mod.console = original_console

        output = buf.getvalue()
        for i in range(1, 6):
            assert f"Step {i}/5" in output, f"Step {i}/5 not found in output"

    def test_wizard_inline_help_rendered(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """_wizard_flow output contains dim-markup help text."""
        from ces.cli.run_cmd import _wizard_flow

        monkeypatch.chdir(tmp_path)

        mock_services = self._make_mock_services(tmp_path)
        buf = StringIO()
        test_console = Console(file=buf, force_terminal=True, width=120)

        import ces.cli._wizard_helpers as run_mod

        original_console = run_mod.console
        run_mod.console = test_console

        prompts = iter(["Add endpoint", "none", "tests pass", "none"])
        monkeypatch.setattr("ces.cli.run_cmd.typer.prompt", lambda *a, **kw: next(prompts, ""))
        monkeypatch.setattr("ces.cli.run_cmd.typer.confirm", lambda *a, **kw: True)

        try:
            asyncio.run(
                _wizard_flow(
                    services=mock_services,
                    project_config={},
                    runtime="auto",
                    brief=False,
                    full=False,
                    governance=False,
                    export_prl_draft=False,
                    project_root=tmp_path,
                    description="Add endpoint",
                    greenfield=False,
                    brownfield_flag=False,
                    accept_runtime_side_effects=True,
                )
            )
        finally:
            run_mod.console = original_console

        output = buf.getvalue()
        # Help text should appear in the output (it gets rendered by Rich even
        # though the dim markup is consumed)
        assert "scope the work contract" in output.lower() or "governance" in output.lower()

    def test_wizard_confirmation_abort(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When typer.confirm returns False, typer.Abort is raised."""
        from ces.cli.run_cmd import _wizard_flow

        monkeypatch.chdir(tmp_path)

        mock_services = self._make_mock_services(tmp_path)

        prompts = iter(["Add endpoint", "none", "tests pass", "none"])
        monkeypatch.setattr("ces.cli.run_cmd.typer.prompt", lambda *a, **kw: next(prompts, ""))
        monkeypatch.setattr("ces.cli.run_cmd.typer.confirm", lambda *a, **kw: False)

        with pytest.raises(typer.Abort):
            asyncio.run(
                _wizard_flow(
                    services=mock_services,
                    project_config={},
                    runtime="auto",
                    brief=False,
                    full=False,
                    governance=False,
                    export_prl_draft=False,
                    project_root=tmp_path,
                    description="Add endpoint",
                    greenfield=False,
                    brownfield_flag=False,
                )
            )

    def test_wizard_calls_run_brief_flow_with_yes_true(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """After confirmation, _wizard_flow calls _run_brief_flow with yes=True."""
        monkeypatch.chdir(tmp_path)

        mock_services = self._make_mock_services(tmp_path)
        mock_brief_flow = AsyncMock()

        prompts = iter(["Add endpoint", "none", "tests pass", "none"])
        monkeypatch.setattr("ces.cli.run_cmd.typer.prompt", lambda *a, **kw: next(prompts, ""))
        monkeypatch.setattr("ces.cli.run_cmd.typer.confirm", lambda *a, **kw: True)

        with patch("ces.cli.run_cmd._run_brief_flow", mock_brief_flow):
            from ces.cli.run_cmd import _wizard_flow

            asyncio.run(
                _wizard_flow(
                    services=mock_services,
                    project_config={},
                    runtime="auto",
                    brief=False,
                    full=False,
                    governance=False,
                    export_prl_draft=False,
                    project_root=tmp_path,
                    description="Add endpoint",
                    greenfield=False,
                    brownfield_flag=False,
                )
            )

        mock_brief_flow.assert_called_once()
        call_kwargs = mock_brief_flow.call_args.kwargs
        assert call_kwargs["yes"] is True, "Wizard should pass yes=True to avoid double-prompting"

    def test_wizard_spinner_during_execution(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """console.status is used during _run_brief_flow execution."""
        monkeypatch.chdir(tmp_path)

        mock_services = self._make_mock_services(tmp_path)

        prompts = iter(["Add endpoint", "none", "tests pass", "none"])
        monkeypatch.setattr("ces.cli.run_cmd.typer.prompt", lambda *a, **kw: next(prompts, ""))
        monkeypatch.setattr("ces.cli.run_cmd.typer.confirm", lambda *a, **kw: True)

        import ces.cli.run_cmd as run_cmd_mod

        original_run_console = run_cmd_mod.console
        mock_console = MagicMock()
        mock_status_ctx = MagicMock()
        mock_console.status.return_value = mock_status_ctx
        mock_console.print = MagicMock()
        run_cmd_mod.console = mock_console

        mock_brief_flow = AsyncMock()

        try:
            with patch("ces.cli.run_cmd._run_brief_flow", mock_brief_flow):
                from ces.cli.run_cmd import _wizard_flow

                asyncio.run(
                    _wizard_flow(
                        services=mock_services,
                        project_config={},
                        runtime="auto",
                        brief=False,
                        full=False,
                        governance=False,
                        export_prl_draft=False,
                        project_root=tmp_path,
                        description="Add endpoint",
                        greenfield=False,
                        brownfield_flag=False,
                    )
                )
        finally:
            run_cmd_mod.console = original_run_console

        mock_console.status.assert_called_once()
