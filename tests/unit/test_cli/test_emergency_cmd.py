"""Tests for ces emergency command (emergency_cmd module)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture(autouse=True)
def _reset_json_mode():
    """Reset JSON mode before each test to avoid leaking state."""
    from ces.cli._output import set_json_mode

    set_json_mode(False)
    yield
    set_json_mode(False)


def _get_app():
    """Import app lazily to avoid import errors during collection."""
    from ces.cli import app

    return app


def _make_emergency_manifest() -> MagicMock:
    """Create a mock emergency TaskManifest."""
    manifest = MagicMock()
    manifest.manifest_id = "M-emerg-001"
    manifest.description = "Fix critical payment bug"
    manifest.affected_files = ["src/payments/checkout.py"]
    manifest.expires_at = datetime.now(timezone.utc)
    return manifest


def _patch_services(mock_services: dict[str, Any]):
    """Return a patch that replaces get_services with a fake async context manager."""

    @asynccontextmanager
    async def _fake_get_services():
        yield mock_services

    return patch("ces.cli.emergency_cmd.get_services", new=_fake_get_services)


class TestEmergencyDeclare:
    """Tests for ces emergency declare command."""

    def test_declare_with_yes_flag(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces emergency declare --yes skips confirmation and creates manifest."""
        monkeypatch.chdir(ces_project)

        manifest = _make_emergency_manifest()
        mock_emergency = AsyncMock()
        mock_emergency.declare_emergency = AsyncMock(return_value=manifest)

        mock_services = {"emergency_service": mock_emergency}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "emergency",
                    "declare",
                    "Fix critical payment bug",
                    "--file",
                    "src/payments/checkout.py",
                    "--yes",
                ],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "M-emerg-001" in result.stdout or "emergency" in result.stdout.lower()
        assert "ces emergency resolve" not in result.stdout
        assert "operator-owned service path" in result.stdout
        mock_emergency.declare_emergency.assert_called_once()

    def test_declare_shows_blast_radius(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces emergency declare shows blast radius with affected files."""
        monkeypatch.chdir(ces_project)

        manifest = _make_emergency_manifest()
        mock_emergency = AsyncMock()
        mock_emergency.declare_emergency = AsyncMock(return_value=manifest)

        mock_services = {"emergency_service": mock_emergency}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "emergency",
                    "declare",
                    "Fix critical payment bug",
                    "--file",
                    "src/payments/checkout.py",
                    "--yes",
                ],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        out = result.stdout.lower()
        assert "blast" in out or "500" in out or "sla" in out or "15" in out

    def test_declare_json_output(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces emergency declare --json outputs manifest as JSON."""
        monkeypatch.chdir(ces_project)

        manifest = _make_emergency_manifest()
        mock_emergency = AsyncMock()
        mock_emergency.declare_emergency = AsyncMock(return_value=manifest)

        mock_services = {"emergency_service": mock_emergency}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "--json",
                    "emergency",
                    "declare",
                    "Fix critical payment bug",
                    "--file",
                    "src/payments/checkout.py",
                    "--yes",
                ],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        data = json.loads(result.stdout.strip())
        assert "manifest_id" in data

    def test_declare_without_yes_prompts_confirmation(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces emergency declare without --yes shows confirmation prompt."""
        monkeypatch.chdir(ces_project)

        manifest = _make_emergency_manifest()
        mock_emergency = AsyncMock()
        mock_emergency.declare_emergency = AsyncMock(return_value=manifest)

        mock_services = {"emergency_service": mock_emergency}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "emergency",
                    "declare",
                    "Fix critical payment bug",
                    "--file",
                    "src/payments/checkout.py",
                ],
                input="y\n",
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"


class TestEmergencyDeclareErrorHandling:
    """Each except arm in `ces emergency declare` routes to the right exit code."""

    @staticmethod
    def _invoke_with_service_error(
        ces_project: Path,
        monkeypatch: pytest.MonkeyPatch,
        exc: Exception,
    ):
        monkeypatch.chdir(ces_project)
        mock_emergency = AsyncMock()
        mock_emergency.declare_emergency = AsyncMock(side_effect=exc)
        with _patch_services({"emergency_service": mock_emergency}):
            return runner.invoke(
                _get_app(),
                ["emergency", "declare", "fix", "--file", "src/x.py", "--yes"],
            )

    def test_user_abort_exits_clean(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """typer.Abort is caught and exits 0 with a cancellation message."""
        result = self._invoke_with_service_error(ces_project, monkeypatch, __import__("typer").Abort())
        assert result.exit_code == 0
        assert "cancelled" in result.stdout.lower()

    def test_value_error_exits_user_error(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        result = self._invoke_with_service_error(ces_project, monkeypatch, ValueError("bad input"))
        assert result.exit_code == 1

    def test_runtime_error_exits_service_error(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        result = self._invoke_with_service_error(ces_project, monkeypatch, RuntimeError("downstream failure"))
        assert result.exit_code == 2

    def test_unexpected_exception_falls_through_to_user_error(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = self._invoke_with_service_error(ces_project, monkeypatch, KeyError("missing"))
        assert result.exit_code == 1
