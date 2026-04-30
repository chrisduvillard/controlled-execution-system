"""Tests for ces manifest command (manifest_cmd module)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from ces.shared.enums import BehaviorConfidence, ChangeClass, RiskTier

runner = CliRunner()


def _get_app():
    """Import app lazily to avoid import errors during collection."""
    from ces.cli import app

    return app


def _make_oracle_result(
    *,
    confidence: float = 0.95,
    action: str = "auto_accept",
    risk_tier: RiskTier = RiskTier.C,
    behavior_confidence: BehaviorConfidence = BehaviorConfidence.BC1,
    change_class: ChangeClass = ChangeClass.CLASS_1,
) -> Any:
    """Create a mock OracleClassificationResult."""
    from ces.control.models.oracle_result import OracleClassificationResult
    from ces.control.services.classification import ClassificationRule

    rule = ClassificationRule(
        description="Test rule",
        risk_tier=risk_tier,
        behavior_confidence=behavior_confidence,
        change_class=change_class,
    )

    return OracleClassificationResult(
        matched_rule=rule,
        confidence=confidence,
        top_matches=[(rule, confidence)],
        action=action,
    )


def _make_mock_manifest(manifest_id: str = "M-abc123def456") -> MagicMock:
    """Create a mock TaskManifest."""
    manifest = MagicMock()
    manifest.manifest_id = manifest_id
    manifest.description = "Add shopping cart checkout flow"
    manifest.risk_tier = RiskTier.C
    manifest.behavior_confidence = BehaviorConfidence.BC1
    manifest.change_class = ChangeClass.CLASS_1
    manifest.affected_files = []
    manifest.token_budget = 100000
    manifest.owner = "cli-user"
    manifest.model_dump.return_value = {
        "manifest_id": manifest_id,
        "description": "Add shopping cart checkout flow",
        "risk_tier": "C",
        "behavior_confidence": "BC1",
        "change_class": "Class 1",
    }
    return manifest


def _patch_services(mock_services: dict[str, Any]):
    """Return a patch that replaces get_services with a fake async context manager."""

    @asynccontextmanager
    async def _fake_get_services():
        yield mock_services

    return patch("ces.cli.manifest_cmd.get_services", new=_fake_get_services)


def _patch_services_error(error: Exception):
    """Return a patch that makes get_services raise an error."""

    @asynccontextmanager
    async def _fake_get_services():
        raise error
        yield  # pragma: no cover

    return patch("ces.cli.manifest_cmd.get_services", new=_fake_get_services)


class TestManifestCreateWithYes:
    """Tests for ces manifest with --yes flag (skips confirmation)."""

    def test_creates_manifest_with_yes_flag(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces manifest 'desc' --yes creates manifest without confirmation prompt."""
        monkeypatch.chdir(ces_project)
        oracle_result = _make_oracle_result()
        mock_manifest = _make_mock_manifest()

        mock_oracle = MagicMock()
        mock_oracle.classify.return_value = oracle_result

        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = mock_manifest

        mock_services = {
            "classification_oracle": mock_oracle,
            "manifest_manager": mock_manager,
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["manifest", "Add shopping cart checkout flow", "--yes"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "M-abc123def456" in result.stdout or mock_manager.create_manifest.called


class TestManifestJsonOutput:
    """Tests for ces manifest --json output mode."""

    def test_json_output_mode(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces manifest --json outputs JSON without Rich formatting."""
        monkeypatch.chdir(ces_project)
        oracle_result = _make_oracle_result()
        mock_manifest = _make_mock_manifest()

        mock_oracle = MagicMock()
        mock_oracle.classify.return_value = oracle_result

        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = mock_manifest

        mock_services = {
            "classification_oracle": mock_oracle,
            "manifest_manager": mock_manager,
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                ["--json", "manifest", "Add shopping cart checkout flow", "--yes"],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        # JSON output contains two JSON objects (proposed + saved).
        # Find the one with manifest_id (the saved manifest).
        output = result.stdout.strip()
        assert "manifest_id" in output, f"No manifest_id in output: {output}"
        # Parse all JSON objects from the output
        decoder = json.JSONDecoder()
        idx = 0
        parsed_objects: list[dict[str, Any]] = []
        while idx < len(output):
            try:
                obj, end = decoder.raw_decode(output, idx)
                parsed_objects.append(obj)
                idx = end
            except json.JSONDecodeError:
                idx += 1
        # At least one object should have manifest_id
        saved = [o for o in parsed_objects if "manifest_id" in o]
        assert saved, f"No JSON object with manifest_id in: {parsed_objects}"


class TestManifestMissingProject:
    """Tests for ces manifest when not in a CES project."""

    def test_missing_project_root_exits_with_error(self, non_ces_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces manifest outside a CES project exits with code 1."""
        monkeypatch.chdir(non_ces_dir)
        app = _get_app()
        result = runner.invoke(app, ["manifest", "Some task description", "--yes"])
        assert result.exit_code != 0


class TestManifestServiceError:
    """Tests for ces manifest when a service error occurs."""

    def test_service_error_exits_with_code_2(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces manifest exits with code 2 when service is unavailable."""
        monkeypatch.chdir(ces_project)

        with _patch_services_error(ConnectionError("Database unavailable")):
            app = _get_app()
            result = runner.invoke(app, ["manifest", "Some task", "--yes"])

        assert result.exit_code == 2, f"stdout={result.stdout}, exit={result.exit_code}"


class TestManifestOracleUsage:
    """Tests verifying the manifest command uses ClassificationOracle."""

    def test_calls_oracle_classify(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces manifest calls ClassificationOracle.classify with the description."""
        monkeypatch.chdir(ces_project)
        oracle_result = _make_oracle_result()
        mock_manifest = _make_mock_manifest()

        mock_oracle = MagicMock()
        mock_oracle.classify.return_value = oracle_result

        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = mock_manifest

        mock_services = {
            "classification_oracle": mock_oracle,
            "manifest_manager": mock_manager,
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["manifest", "Add shopping cart checkout flow", "--yes"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        mock_oracle.classify.assert_called_once_with("Add shopping cart checkout flow")
        mock_manager.create_manifest.assert_called_once()


class TestManifestNoConfidentMatch:
    """Tests for ces manifest when oracle returns no confident match."""

    def test_fallback_to_highest_risk_defaults(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces manifest uses RiskTier.A, BC3, CLASS_5 when oracle has no match."""
        monkeypatch.chdir(ces_project)

        from ces.control.models.oracle_result import OracleClassificationResult

        oracle_result = OracleClassificationResult(
            matched_rule=None,
            confidence=0.2,
            top_matches=(),
            action="human_classify",
        )
        mock_manifest = _make_mock_manifest()

        mock_oracle = MagicMock()
        mock_oracle.classify.return_value = oracle_result

        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = mock_manifest

        mock_services = {
            "classification_oracle": mock_oracle,
            "manifest_manager": mock_manager,
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["manifest", "Vague task description", "--yes"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        # Verify manager was called with highest-risk defaults
        call_kwargs = mock_manager.create_manifest.call_args
        assert call_kwargs is not None
        _, kwargs = call_kwargs
        assert kwargs["risk_tier"] == RiskTier.A
        assert kwargs["behavior_confidence"] == BehaviorConfidence.BC3
        assert kwargs["change_class"] == ChangeClass.CLASS_5


class TestManifestUserCancels:
    """Tests for ces manifest when user cancels at confirmation prompt."""

    def test_user_cancels_manifest(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces manifest shows 'Manifest discarded' when user declines confirmation."""
        monkeypatch.chdir(ces_project)
        oracle_result = _make_oracle_result()

        mock_oracle = MagicMock()
        mock_oracle.classify.return_value = oracle_result

        mock_manager = AsyncMock()

        mock_services = {
            "classification_oracle": mock_oracle,
            "manifest_manager": mock_manager,
        }

        with _patch_services(mock_services):
            app = _get_app()
            # Supply "n" to the confirmation prompt
            result = runner.invoke(app, ["manifest", "Some task"], input="n\n")

        # Should exit cleanly (code 0) with discarded message
        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "discarded" in result.stdout.lower()
        # Manager should NOT have been called
        mock_manager.create_manifest.assert_not_called()


class TestManifestRuntimeError:
    """Tests for ces manifest when a runtime error occurs during service usage."""

    def test_runtime_error_exits_with_code_2(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces manifest exits with code 2 on RuntimeError from service."""
        monkeypatch.chdir(ces_project)

        with _patch_services_error(RuntimeError("Engine failed")):
            app = _get_app()
            result = runner.invoke(app, ["manifest", "Some task", "--yes"])

        assert result.exit_code == 2, f"stdout={result.stdout}, exit={result.exit_code}"


class TestManifestAutoGeneration:
    """Tests for ces manifest --auto flag (MANIF-06)."""

    def test_create_manifest_auto_generates_from_artifacts(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ces manifest --auto --yes generates a manifest via the local runtime helper."""
        monkeypatch.chdir(ces_project)

        mock_manifest = _make_mock_manifest()
        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = mock_manifest

        runtime_adapter = MagicMock()
        runtime_adapter.runtime_name = "codex"
        runtime_adapter.generate_manifest_assist.return_value = {
            "description": "Add shopping cart",
            "risk_tier": RiskTier.B.value,
            "behavior_confidence": BehaviorConfidence.BC1.value,
            "change_class": ChangeClass.CLASS_2.value,
            "affected_files": ["src/cart.py"],
            "token_budget": 50000,
            "reasoning": "Moderate risk change to existing module",
        }

        runtime_registry = MagicMock()
        runtime_registry.resolve_runtime.return_value = runtime_adapter

        mock_services = {
            "manifest_manager": mock_manager,
            "runtime_registry": runtime_registry,
            "settings": MagicMock(default_runtime="codex"),
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                ["manifest", "Add shopping cart", "--auto", "--yes"],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        runtime_registry.resolve_runtime.assert_called_once()
        runtime_adapter.generate_manifest_assist.assert_called_once_with({}, "Add shopping cart")
        mock_manager.create_manifest.assert_called_once()
        # Verify proposal fields were passed to create_manifest
        call_kwargs = mock_manager.create_manifest.call_args.kwargs
        assert call_kwargs["risk_tier"] == RiskTier.B
        assert call_kwargs["behavior_confidence"] == BehaviorConfidence.BC1

    def test_create_manifest_auto_no_artifacts(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces manifest --auto without context still produces conservative local defaults."""
        monkeypatch.chdir(ces_project)

        mock_manifest = _make_mock_manifest()
        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = mock_manifest

        runtime_adapter = MagicMock()
        runtime_adapter.runtime_name = "codex"
        runtime_adapter.generate_manifest_assist.return_value = {
            "description": "Vague task",
            "risk_tier": RiskTier.A.value,
            "behavior_confidence": BehaviorConfidence.BC3.value,
            "change_class": ChangeClass.CLASS_5.value,
            "affected_files": [],
            "token_budget": 100000,
            "reasoning": "No additional local context provided.",
        }

        runtime_registry = MagicMock()
        runtime_registry.resolve_runtime.return_value = runtime_adapter

        mock_services = {
            "manifest_manager": mock_manager,
            "runtime_registry": runtime_registry,
            "settings": MagicMock(default_runtime="codex"),
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                ["manifest", "Vague task", "--auto", "--yes"],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        runtime_adapter.generate_manifest_assist.assert_called_once_with({}, "Vague task")

    def test_create_manifest_auto_local_runtime_path(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces manifest --auto uses the local runtime adapter."""
        monkeypatch.chdir(ces_project)

        mock_manifest = _make_mock_manifest()
        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = mock_manifest

        runtime_adapter = MagicMock()
        runtime_adapter.runtime_name = "claude"
        runtime_adapter.generate_manifest_assist.return_value = {
            "description": "Local manifest draft",
            "risk_tier": RiskTier.B.value,
            "behavior_confidence": BehaviorConfidence.BC2.value,
            "change_class": ChangeClass.CLASS_2.value,
            "affected_files": ["src/cart.py"],
            "token_budget": 75000,
            "reasoning": "Derived from local runtime assist",
        }

        runtime_registry = MagicMock()
        runtime_registry.resolve_runtime.return_value = runtime_adapter

        mock_services = {
            "manifest_manager": mock_manager,
            "runtime_registry": runtime_registry,
            "settings": MagicMock(default_runtime="codex"),
        }

        with (
            _patch_services(mock_services),
            patch("ces.cli.manifest_cmd.get_project_config", return_value={"preferred_runtime": "codex"}),
            patch("ces.cli.manifest_cmd.find_project_root", return_value=ces_project),
        ):
            app = _get_app()
            result = runner.invoke(
                app,
                ["manifest", "Local draft task", "--auto", "--yes", "--runtime", "claude"],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        runtime_registry.resolve_runtime.assert_called_once_with(
            runtime_name="claude",
            preferred_runtime="codex",
        )
        runtime_adapter.generate_manifest_assist.assert_called_once_with({}, "Local draft task")
        mock_manager.create_manifest.assert_called_once()
        assert "Local manifest draft" in result.stdout


# ---------------------------------------------------------------------------
# Completion-Gate opt-in flags (N2)
# ---------------------------------------------------------------------------


def _make_gate_mock_manifest(
    *,
    acceptance: tuple[str, ...] = (),
    sensors: tuple[str, ...] = (),
) -> MagicMock:
    """Mock manifest with the new optional fields explicit."""
    manifest = _make_mock_manifest()
    manifest.acceptance_criteria = acceptance
    manifest.verification_sensors = sensors
    return manifest


class TestManifestGateFlags:
    """`ces manifest` accepts --acceptance-criterion and --verification-sensor."""

    def test_repeatable_flags_pass_through_to_manager(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(ces_project)
        oracle_result = _make_oracle_result()
        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = _make_gate_mock_manifest(
            acceptance=("user can log in", "user can log out"),
            sensors=("test_pass", "lint"),
        )
        mock_oracle = MagicMock()
        mock_oracle.classify.return_value = oracle_result

        mock_services = {
            "classification_oracle": mock_oracle,
            "manifest_manager": mock_manager,
        }

        with _patch_services(mock_services):
            result = runner.invoke(
                _get_app(),
                [
                    "manifest",
                    "Build login flow",
                    "--yes",
                    "--acceptance-criterion",
                    "user can log in",
                    "--acceptance-criterion",
                    "user can log out",
                    "--verification-sensor",
                    "test_pass",
                    "--verification-sensor",
                    "lint",
                ],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        kwargs = mock_manager.create_manifest.await_args.kwargs
        assert kwargs["acceptance_criteria"] == ["user can log in", "user can log out"]
        assert kwargs["verification_sensors"] == ["test_pass", "lint"]

    def test_default_passes_none_for_both(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without flags the gate stays opt-out (legacy behaviour)."""
        monkeypatch.chdir(ces_project)
        oracle_result = _make_oracle_result()
        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = _make_gate_mock_manifest()
        mock_oracle = MagicMock()
        mock_oracle.classify.return_value = oracle_result

        mock_services = {
            "classification_oracle": mock_oracle,
            "manifest_manager": mock_manager,
        }

        with _patch_services(mock_services):
            result = runner.invoke(
                _get_app(),
                ["manifest", "do something simple", "--yes"],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        kwargs = mock_manager.create_manifest.await_args.kwargs
        assert kwargs["acceptance_criteria"] is None
        assert kwargs["verification_sensors"] is None

    def test_saved_panel_shows_legacy_marker_when_sensors_empty(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(ces_project)
        oracle_result = _make_oracle_result()
        mock_manager = AsyncMock()
        mock_manager.create_manifest.return_value = _make_gate_mock_manifest()
        mock_oracle = MagicMock()
        mock_oracle.classify.return_value = oracle_result

        mock_services = {
            "classification_oracle": mock_oracle,
            "manifest_manager": mock_manager,
        }

        with _patch_services(mock_services):
            result = runner.invoke(
                _get_app(),
                ["manifest", "do something simple", "--yes"],
            )

        assert result.exit_code == 0
        assert "legacy direct-to-review path" in result.stdout
