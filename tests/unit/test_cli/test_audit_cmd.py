"""Tests for ces audit command (audit_cmd module)."""

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


def _make_mock_entry(
    entry_id: str = "AE-001",
    event_type_value: str = "approval",
    actor: str = "reviewer-1",
    summary: str = "Approved manifest M-001",
) -> MagicMock:
    """Create a mock AuditEntry object."""
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.timestamp = datetime.now(timezone.utc)
    entry.event_type = MagicMock()
    entry.event_type.value = event_type_value
    entry.actor = actor
    entry.action_summary = summary
    return entry


def _patch_services(mock_services: dict[str, Any]):
    """Return a patch that replaces get_services with a fake async context manager."""

    @asynccontextmanager
    async def _fake_get_services():
        yield mock_services

    return patch("ces.cli.audit_cmd.get_services", new=_fake_get_services)


class TestAuditQuery:
    """Tests for ces audit with filters."""

    def test_audit_shows_entries(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces audit displays entries in a table."""
        monkeypatch.chdir(ces_project)

        entries = [
            _make_mock_entry("AE-001", "approval", "reviewer-1", "Approved M-001"),
            _make_mock_entry("AE-002", "classification", "oracle", "Classified M-002"),
        ]

        mock_audit = AsyncMock()
        mock_audit.query_by_time_range = AsyncMock(return_value=entries)
        mock_services = {"audit_ledger": mock_audit}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["audit"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "AE-001" in result.stdout or "approval" in result.stdout.lower()

    def test_audit_with_event_type_filter(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces audit --event-type approval shows only matching entries."""
        monkeypatch.chdir(ces_project)

        entries = [
            _make_mock_entry("AE-001", "approval", "reviewer-1", "Approved M-001"),
        ]

        mock_audit = AsyncMock()
        mock_audit.query_by_event_type = AsyncMock(return_value=entries)
        mock_services = {"audit_ledger": mock_audit}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["audit", "--event-type", "approval"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "AE-001" in result.stdout or "approval" in result.stdout.lower()
        mock_audit.query_by_event_type.assert_awaited_once()

    def test_audit_json_output(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces audit --json outputs entries as JSON array."""
        monkeypatch.chdir(ces_project)

        entries = [
            _make_mock_entry("AE-001", "approval", "reviewer-1", "Approved M-001"),
        ]

        mock_audit = AsyncMock()
        mock_audit.query_by_time_range = AsyncMock(return_value=entries)
        mock_services = {"audit_ledger": mock_audit}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["--json", "audit"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        data = json.loads(result.stdout.strip())
        assert isinstance(data, list)
        assert len(data) == 1
        assert "entry_id" in data[0]
        assert "event_type" in data[0]
        assert "actor" in data[0]

    def test_audit_pagination(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces audit --limit 1 --offset 0 paginates results."""
        monkeypatch.chdir(ces_project)

        entries = [
            _make_mock_entry("AE-001", "approval", "reviewer-1", "Approved M-001"),
            _make_mock_entry("AE-002", "classification", "oracle", "Classified M-002"),
        ]

        mock_audit = AsyncMock()
        mock_audit.query_by_time_range = AsyncMock(return_value=entries)
        mock_services = {"audit_ledger": mock_audit}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["--json", "audit", "--limit", "1"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        data = json.loads(result.stdout.strip())
        assert len(data) == 1
