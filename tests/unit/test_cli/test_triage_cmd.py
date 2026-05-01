"""Tests for ces triage command (triage_cmd module)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from ces.harness.models.triage_result import TriageColor, TriageDecision
from ces.shared.enums import RiskTier, TrustStatus

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

    return patch("ces.cli.triage_cmd.get_services", new=_fake_get_services)


def _make_triage_decision(
    color: TriageColor = TriageColor.GREEN,
    auto_approve: bool = True,
) -> TriageDecision:
    """Create a mock TriageDecision."""
    return TriageDecision(
        color=color,
        risk_tier=RiskTier.C,
        trust_status=TrustStatus.TRUSTED,
        sensor_pass_rate=1.0,
        reason="Tier=C, Trust=trusted, SensorsGreen=True, PassRate=1.00",
        auto_approve_eligible=auto_approve,
    )


def _make_mock_manifest(manifest_id: str = "M-triage123") -> MagicMock:
    """Create a mock manifest."""
    manifest = MagicMock()
    manifest.manifest_id = manifest_id
    manifest.risk_tier = RiskTier.C
    manifest.trust_status = TrustStatus.TRUSTED
    manifest.description = "Add logging module"
    return manifest


def _make_mock_sensor_results() -> list:
    """Create a list of mock sensor results (all passing)."""
    sr = MagicMock()
    sr.passed = True
    return [sr]


class TestTriageGreenDisplay:
    """Tests for ces triage with GREEN result."""

    def test_triage_shows_green_color(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces triage displays GREEN triage color."""
        monkeypatch.chdir(ces_project)

        mock_manifest = _make_mock_manifest()
        mock_manager = AsyncMock()
        mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)

        mock_synth = MagicMock()
        mock_synth.triage = AsyncMock(return_value=_make_triage_decision(TriageColor.GREEN, True))

        mock_sensor_orch = AsyncMock()
        mock_sensor_orch.run_all = AsyncMock(return_value=[])
        mock_services = {
            "manifest_manager": mock_manager,
            "evidence_synthesizer": mock_synth,
            "sensor_orchestrator": mock_sensor_orch,
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["triage", "EP-test123"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "green" in result.stdout.lower() or "GREEN" in result.stdout


class TestTriageYellowDisplay:
    """Tests for ces triage with YELLOW result."""

    def test_triage_shows_yellow_color(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces triage displays YELLOW triage color."""
        monkeypatch.chdir(ces_project)

        mock_manifest = _make_mock_manifest()
        mock_manager = AsyncMock()
        mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)

        mock_synth = MagicMock()
        mock_synth.triage = AsyncMock(return_value=_make_triage_decision(TriageColor.YELLOW, False))

        mock_sensor_orch = AsyncMock()
        mock_sensor_orch.run_all = AsyncMock(return_value=[])
        mock_services = {
            "manifest_manager": mock_manager,
            "evidence_synthesizer": mock_synth,
            "sensor_orchestrator": mock_sensor_orch,
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["triage", "EP-yellow"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "yellow" in result.stdout.lower() or "YELLOW" in result.stdout


class TestTriageRedDisplay:
    """Tests for ces triage with RED result."""

    def test_triage_shows_red_color(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces triage displays RED triage color."""
        monkeypatch.chdir(ces_project)

        mock_manifest = _make_mock_manifest()
        mock_manager = AsyncMock()
        mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)

        mock_synth = MagicMock()
        mock_synth.triage = AsyncMock(return_value=_make_triage_decision(TriageColor.RED, False))

        mock_sensor_orch = AsyncMock()
        mock_sensor_orch.run_all = AsyncMock(return_value=[])
        mock_services = {
            "manifest_manager": mock_manager,
            "evidence_synthesizer": mock_synth,
            "sensor_orchestrator": mock_sensor_orch,
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["triage", "EP-red"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "red" in result.stdout.lower() or "RED" in result.stdout


class TestTriageAutoApprove:
    """Tests for auto-approval eligibility display."""

    def test_auto_approve_eligible_shows_note(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When auto_approve_eligible is True, shows auto-approval note."""
        monkeypatch.chdir(ces_project)

        mock_manifest = _make_mock_manifest()
        mock_manager = AsyncMock()
        mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)

        mock_synth = MagicMock()
        mock_synth.triage = AsyncMock(return_value=_make_triage_decision(TriageColor.GREEN, True))

        mock_sensor_orch = AsyncMock()
        mock_sensor_orch.run_all = AsyncMock(return_value=[])
        mock_services = {
            "manifest_manager": mock_manager,
            "evidence_synthesizer": mock_synth,
            "sensor_orchestrator": mock_sensor_orch,
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["triage", "EP-autoapprove"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "auto-approval" in result.stdout.lower() or "auto_approve" in result.stdout.lower()


class TestTriageJsonMode:
    """Tests for ces triage --json output mode."""

    def test_json_output_mode(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces --json triage outputs triage result as JSON."""
        monkeypatch.chdir(ces_project)

        mock_manifest = _make_mock_manifest()
        mock_manager = AsyncMock()
        mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)

        mock_synth = MagicMock()
        mock_synth.triage = AsyncMock(return_value=_make_triage_decision(TriageColor.GREEN, True))

        mock_sensor_orch = AsyncMock()
        mock_sensor_orch.run_all = AsyncMock(return_value=[])
        mock_services = {
            "manifest_manager": mock_manager,
            "evidence_synthesizer": mock_synth,
            "sensor_orchestrator": mock_sensor_orch,
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["--json", "triage", "EP-json"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        output = result.stdout.strip()
        parsed = json.loads(output)
        assert isinstance(parsed, dict)
        assert parsed["color"] == "green"
        assert parsed["auto_approve_eligible"] is True

    def test_command_local_json_flag(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces triage --json outputs triage result as JSON."""
        monkeypatch.chdir(ces_project)

        mock_manifest = _make_mock_manifest()
        mock_manager = AsyncMock()
        mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)
        mock_synth = MagicMock()
        mock_synth.triage = AsyncMock(return_value=_make_triage_decision(TriageColor.YELLOW, False))
        mock_sensor_orch = AsyncMock()
        mock_sensor_orch.run_all = AsyncMock(return_value=[])

        with _patch_services(
            {
                "manifest_manager": mock_manager,
                "evidence_synthesizer": mock_synth,
                "sensor_orchestrator": mock_sensor_orch,
            }
        ):
            app = _get_app()
            result = runner.invoke(app, ["triage", "EP-json", "--json"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        parsed = json.loads(result.stdout)
        assert parsed["color"] == "yellow"

    def test_triage_uses_persisted_evidence_by_default(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Persisted evidence is the default handoff source unless --refresh is used."""
        monkeypatch.chdir(ces_project)

        mock_store = MagicMock()
        mock_store.get_latest_builder_session_snapshot.return_value = None
        mock_store.get_evidence_by_packet_id.return_value = {
            "manifest_id": "M-triage123",
            "packet_id": "EP-saved",
            "triage_color": "yellow",
            "summary": "Saved evidence summary",
            "challenge": "Saved challenge",
        }
        mock_sensor_orch = AsyncMock()
        mock_sensor_orch.run_all = AsyncMock(side_effect=AssertionError("sensors should not refresh"))

        with _patch_services(
            {
                "local_store": mock_store,
                "manifest_manager": AsyncMock(),
                "evidence_synthesizer": MagicMock(),
                "sensor_orchestrator": mock_sensor_orch,
            }
        ):
            app = _get_app()
            result = runner.invoke(app, ["triage", "EP-saved"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "yellow" in result.stdout.lower()
        mock_sensor_orch.run_all.assert_not_called()
