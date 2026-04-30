"""Tests for ces vault command (vault_cmd module)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from ces.control.models.knowledge_vault import VaultNote
from ces.shared.enums import VaultCategory, VaultTrustLevel

runner = CliRunner()


@pytest.fixture(autouse=True)
def _reset_json_mode():
    """Reset CLI JSON output mode between tests."""
    from ces.cli._output import set_json_mode

    set_json_mode(False)
    yield
    set_json_mode(False)


def _get_app():
    """Import app lazily to avoid import errors during collection."""
    from ces.cli import app

    return app


def _make_vault_note(
    note_id: str = "VN-abc123",
    category: VaultCategory = VaultCategory.PATTERNS,
    trust_level: VaultTrustLevel = VaultTrustLevel.AGENT_INFERRED,
    content: str = "Pattern: use dependency injection for services",
) -> VaultNote:
    """Create a VaultNote for testing."""
    now = datetime.now(timezone.utc)
    return VaultNote(
        note_id=note_id,
        category=category,
        trust_level=trust_level,
        content=content,
        source="test",
        created_at=now,
        updated_at=now,
        tags=("testing",),
    )


def _patch_services(mock_services: dict[str, Any]):
    """Return a patch that replaces get_services with a fake async context manager."""

    @asynccontextmanager
    async def _fake_get_services():
        yield mock_services

    return patch("ces.cli.vault_cmd.get_services", new=_fake_get_services)


class TestVaultQuery:
    """Tests for ces vault query subcommand."""

    def test_vault_query_shows_results(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces vault query <topic> displays matching notes in table."""
        monkeypatch.chdir(ces_project)

        notes = [
            _make_vault_note("VN-001", content="DI pattern for services"),
            _make_vault_note("VN-002", content="Repository pattern for DB"),
        ]

        mock_vault = AsyncMock()
        mock_vault.query = AsyncMock(return_value=notes)

        mock_services = {"vault_service": mock_vault}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["vault", "query", "patterns"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "VN-001" in result.stdout or "DI pattern" in result.stdout

    def test_vault_query_json_output(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces vault query --json outputs as JSON array."""
        monkeypatch.chdir(ces_project)

        notes = [_make_vault_note()]

        mock_vault = AsyncMock()
        mock_vault.query = AsyncMock(return_value=notes)

        mock_services = {"vault_service": mock_vault}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["--json", "vault", "query", "patterns"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        data = json.loads(result.stdout.strip())
        assert isinstance(data, list)

    def test_vault_query_no_results_shows_message(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces vault query shows an empty-state message when no notes match."""
        monkeypatch.chdir(ces_project)

        mock_vault = AsyncMock()
        mock_vault.query = AsyncMock(return_value=[])

        mock_services = {"vault_service": mock_vault}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["vault", "query", "patterns"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "no notes found" in result.stdout.lower()


class TestVaultWrite:
    """Tests for ces vault write subcommand."""

    def test_vault_write_with_content_flag(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces vault write <category> --content creates a note."""
        monkeypatch.chdir(ces_project)

        created_note = _make_vault_note()
        mock_vault = AsyncMock()
        mock_vault.write_note = AsyncMock(return_value=created_note)

        mock_services = {"vault_service": mock_vault}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                ["vault", "write", "patterns", "--content", "New pattern note"],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "VN-abc123" in result.stdout or "created" in result.stdout.lower()
        mock_vault.write_note.assert_called_once()

    def test_vault_write_interactive_prompt(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces vault write without --content prompts for input."""
        monkeypatch.chdir(ces_project)

        created_note = _make_vault_note()
        mock_vault = AsyncMock()
        mock_vault.write_note = AsyncMock(return_value=created_note)

        mock_services = {"vault_service": mock_vault}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                ["vault", "write", "patterns"],
                input="Interactive content\n",
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        mock_vault.write_note.assert_called_once()

    def test_vault_write_json_output(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces vault write --json returns a serialized note payload."""
        monkeypatch.chdir(ces_project)

        created_note = _make_vault_note()
        mock_vault = AsyncMock()
        mock_vault.write_note = AsyncMock(return_value=created_note)

        mock_services = {"vault_service": mock_vault}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                ["--json", "vault", "write", "patterns", "--content", "New pattern note"],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        data = json.loads(result.stdout.strip())
        assert data["note_id"] == created_note.note_id
        assert data["created"] is True

    def test_vault_write_invalid_category_exits_with_error(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ces vault write rejects categories outside the enum."""
        monkeypatch.chdir(ces_project)

        mock_vault = AsyncMock()
        mock_services = {"vault_service": mock_vault}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                ["vault", "write", "not-a-category", "--content", "New pattern note"],
            )

        assert result.exit_code == 1, f"stdout={result.stdout}, exit={result.exit_code}"
        assert "invalid category" in result.stdout.lower()
        mock_vault.write_note.assert_not_called()


class TestVaultHealth:
    """Tests for ces vault health subcommand."""

    def test_vault_health_calls_refresh(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces vault health calls refresh_indexes and shows summary."""
        monkeypatch.chdir(ces_project)

        mock_vault = AsyncMock()
        mock_vault.refresh_indexes = AsyncMock()
        mock_vault.query = AsyncMock(return_value=[])

        mock_services = {"vault_service": mock_vault}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["vault", "health"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        mock_vault.refresh_indexes.assert_called_once()

    def test_vault_health_json_output(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces vault health --json outputs health as JSON."""
        monkeypatch.chdir(ces_project)

        mock_vault = AsyncMock()
        mock_vault.refresh_indexes = AsyncMock()
        mock_vault.query = AsyncMock(return_value=[])

        mock_services = {"vault_service": mock_vault}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["--json", "vault", "health"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        data = json.loads(result.stdout.strip())
        assert "index_refreshed" in data

    def test_vault_health_reports_stale_notes(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces vault health shows stale-note counts when stale-risk notes exist."""
        monkeypatch.chdir(ces_project)

        mock_vault = AsyncMock()
        mock_vault.refresh_indexes = AsyncMock()
        mock_vault.query = AsyncMock(
            side_effect=[
                [_make_vault_note(category=VaultCategory.DECISIONS)],
                [],
                [],
                [],
                [],
                [],
                [],
                [],
                [],
                [_make_vault_note(trust_level=VaultTrustLevel.STALE_RISK, note_id="VN-stale")],
            ]
        )

        mock_services = {"vault_service": mock_vault}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["vault", "health"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "stale notes" in result.stdout.lower()
        assert "1" in result.stdout

    def test_vault_health_tolerates_query_failures(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces vault health falls back to zero counts when category queries fail."""
        monkeypatch.chdir(ces_project)

        mock_vault = AsyncMock()
        mock_vault.refresh_indexes = AsyncMock()
        mock_vault.query = AsyncMock(
            side_effect=[
                RuntimeError("query failed"),
                [],
                [],
                [],
                [],
                [],
                [],
                [],
                [],
                RuntimeError("stale query failed"),
            ]
        )

        mock_services = {"vault_service": mock_vault}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["--json", "vault", "health"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        data = json.loads(result.stdout.strip())
        assert data["categories"][VaultCategory.DECISIONS.value] == 0
        assert data["stale_notes"] == 0
