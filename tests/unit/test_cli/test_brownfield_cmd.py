"""Tests for ces brownfield command (brownfield_cmd module).

Tests all 5 subcommands: register, list, review, promote, discard.
Follows the same patterns as test_vault_cmd.py.
"""

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


def _get_app():
    """Import app lazily to avoid import errors during collection."""
    from ces.cli import app

    return app


def _patch_services(mock_services: dict[str, Any]):
    """Return a patch that replaces get_services with a fake async context manager."""

    @asynccontextmanager
    async def _fake_get_services():
        yield mock_services

    return patch("ces.cli.brownfield_cmd.get_services", new=_fake_get_services)


def _make_mock_behavior(
    entry_id: str = "OLB-abc123def456",
    system: str = "legacy-billing",
    behavior_description: str = "Applies 5% discount on invoices over $1000",
    inferred_by: str = "cli-user",
    confidence: float = 0.8,
    disposition: str | None = None,
    reviewed_by: str | None = None,
    reviewed_at: datetime | None = None,
    promoted_to_prl_id: str | None = None,
    discarded: bool = False,
) -> MagicMock:
    """Create a mock ObservedLegacyBehavior for testing."""
    mock = MagicMock()
    mock.entry_id = entry_id
    mock.system = system
    mock.behavior_description = behavior_description
    mock.inferred_by = inferred_by
    mock.inferred_at = datetime.now(timezone.utc)
    mock.confidence = confidence
    mock.disposition = disposition
    mock.reviewed_by = reviewed_by
    mock.reviewed_at = reviewed_at
    mock.promoted_to_prl_id = promoted_to_prl_id
    mock.discarded = discarded
    mock.model_dump = MagicMock(
        return_value={
            "entry_id": entry_id,
            "system": system,
            "behavior_description": behavior_description,
            "inferred_by": inferred_by,
            "inferred_at": datetime.now(timezone.utc).isoformat(),
            "confidence": confidence,
            "disposition": disposition,
            "reviewed_by": reviewed_by,
            "reviewed_at": reviewed_at,
            "promoted_to_prl_id": promoted_to_prl_id,
            "discarded": discarded,
        }
    )
    return mock


def _make_mock_prl_item(
    prl_id: str = "PRL-xyz789abc012",
    statement: str = "Applies 5% discount on invoices over $1000",
) -> MagicMock:
    """Create a mock PRLItem for testing promote command."""
    mock = MagicMock()
    mock.prl_id = prl_id
    mock.statement = statement
    mock.model_dump = MagicMock(
        return_value={
            "prl_id": prl_id,
            "statement": statement,
            "type": "constraint",
            "status": "draft",
        }
    )
    return mock


class TestBrownfieldRegister:
    """Tests for ces brownfield register subcommand."""

    def test_register_calls_service_with_correct_args(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces brownfield register calls register_behavior() with correct kwargs."""
        monkeypatch.chdir(ces_project)

        mock_behavior = _make_mock_behavior()
        mock_service = AsyncMock()
        mock_service.register_behavior = AsyncMock(return_value=mock_behavior)

        mock_services = {"legacy_behavior_service": mock_service}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "brownfield",
                    "register",
                    "--system",
                    "legacy-billing",
                    "--description",
                    "Applies 5% discount on invoices over $1000",
                    "--inferred-by",
                    "test-agent",
                    "--confidence",
                    "0.8",
                ],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        mock_service.register_behavior.assert_called_once()
        call_kwargs = mock_service.register_behavior.call_args.kwargs
        assert call_kwargs["system"] == "legacy-billing"
        assert call_kwargs["behavior_description"] == "Applies 5% discount on invoices over $1000"
        assert call_kwargs["inferred_by"] == "test-agent"
        assert call_kwargs["confidence"] == 0.8

    def test_register_returns_behavior_not_prl(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """BROWN-02: register creates entry in register, NOT PRL."""
        monkeypatch.chdir(ces_project)

        mock_behavior = _make_mock_behavior()
        mock_service = AsyncMock()
        mock_service.register_behavior = AsyncMock(return_value=mock_behavior)

        mock_services = {"legacy_behavior_service": mock_service}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "brownfield",
                    "register",
                    "--system",
                    "legacy-billing",
                    "--description",
                    "Some behavior",
                ],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        # Verify register_behavior was called (not promote_to_prl)
        mock_service.register_behavior.assert_called_once()
        assert not mock_service.promote_to_prl.called

    def test_register_json_output(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces brownfield register --json outputs as JSON."""
        monkeypatch.chdir(ces_project)

        mock_behavior = _make_mock_behavior()
        mock_service = AsyncMock()
        mock_service.register_behavior = AsyncMock(return_value=mock_behavior)

        mock_services = {"legacy_behavior_service": mock_service}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "--json",
                    "brownfield",
                    "register",
                    "--system",
                    "legacy-billing",
                    "--description",
                    "Some behavior",
                ],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        data = json.loads(result.stdout.strip())
        assert "entry_id" in data
        assert data["entry_id"] == "OLB-abc123def456"

    def test_register_rich_output_shows_entry_id(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces brownfield register shows entry_id in Rich output."""
        monkeypatch.chdir(ces_project)

        mock_behavior = _make_mock_behavior()
        mock_service = AsyncMock()
        mock_service.register_behavior = AsyncMock(return_value=mock_behavior)

        mock_services = {"legacy_behavior_service": mock_service}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "brownfield",
                    "register",
                    "--system",
                    "legacy-billing",
                    "--description",
                    "Some behavior",
                ],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "OLB-abc123def456" in result.stdout


class TestBrownfieldList:
    """Tests for ces brownfield list subcommand."""

    def test_list_calls_get_pending_behaviors(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces brownfield list calls get_pending_behaviors() by default."""
        monkeypatch.chdir(ces_project)

        behaviors = [_make_mock_behavior("OLB-001"), _make_mock_behavior("OLB-002")]
        mock_service = AsyncMock()
        mock_service.get_pending_behaviors = AsyncMock(return_value=behaviors)

        mock_services = {"legacy_behavior_service": mock_service}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["brownfield", "list"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        mock_service.get_pending_behaviors.assert_called_once()

    def test_list_with_system_calls_get_behaviors_by_system(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ces brownfield list --system X calls get_behaviors_by_system("X")."""
        monkeypatch.chdir(ces_project)

        behaviors = [_make_mock_behavior("OLB-001")]
        mock_service = AsyncMock()
        mock_service.get_behaviors_by_system = AsyncMock(return_value=behaviors)

        mock_services = {"legacy_behavior_service": mock_service}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["brownfield", "list", "--system", "legacy-billing"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        mock_service.get_behaviors_by_system.assert_called_once_with("legacy-billing")

    def test_list_json_output(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces brownfield list --json outputs as JSON array."""
        monkeypatch.chdir(ces_project)

        behaviors = [_make_mock_behavior()]
        mock_service = AsyncMock()
        mock_service.get_pending_behaviors = AsyncMock(return_value=behaviors)

        mock_services = {"legacy_behavior_service": mock_service}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["--json", "brownfield", "list"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        data = json.loads(result.stdout.strip())
        assert isinstance(data, list)
        assert len(data) == 1


class TestBrownfieldReview:
    """Tests for ces brownfield review subcommand."""

    def test_review_calls_review_behavior(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces brownfield review calls review_behavior() with correct args."""
        monkeypatch.chdir(ces_project)

        mock_behavior = _make_mock_behavior(disposition="preserve", reviewed_by="human")
        mock_service = AsyncMock()
        mock_service.review_behavior = AsyncMock(return_value=mock_behavior)

        mock_services = {"legacy_behavior_service": mock_service}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "brownfield",
                    "review",
                    "OLB-abc123def456",
                    "--reviewer",
                    "human",
                    "--disposition",
                    "preserve",
                ],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        mock_service.review_behavior.assert_called_once()

    def test_review_invalid_disposition_fails(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces brownfield review with invalid disposition exits non-zero."""
        monkeypatch.chdir(ces_project)

        mock_service = AsyncMock()
        mock_services = {"legacy_behavior_service": mock_service}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "brownfield",
                    "review",
                    "OLB-abc123",
                    "--reviewer",
                    "human",
                    "--disposition",
                    "invalid-value",
                ],
            )

        assert result.exit_code != 0

    def test_review_json_output(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces brownfield review --json outputs as JSON."""
        monkeypatch.chdir(ces_project)

        mock_behavior = _make_mock_behavior(disposition="preserve", reviewed_by="human")
        mock_service = AsyncMock()
        mock_service.review_behavior = AsyncMock(return_value=mock_behavior)

        mock_services = {"legacy_behavior_service": mock_service}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "--json",
                    "brownfield",
                    "review",
                    "OLB-abc123def456",
                    "--reviewer",
                    "human",
                    "--disposition",
                    "preserve",
                ],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        data = json.loads(result.stdout.strip())
        assert "entry_id" in data


class TestBrownfieldPromote:
    """Tests for ces brownfield promote subcommand."""

    def test_promote_calls_promote_to_prl(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces brownfield promote calls promote_to_prl() and shows PRL item."""
        monkeypatch.chdir(ces_project)

        mock_behavior = _make_mock_behavior(
            disposition="preserve",
            promoted_to_prl_id="PRL-xyz789abc012",
        )
        mock_prl = _make_mock_prl_item()
        mock_service = AsyncMock()
        mock_service.promote_to_prl = AsyncMock(return_value=(mock_behavior, mock_prl))

        mock_services = {"legacy_behavior_service": mock_service}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "brownfield",
                    "promote",
                    "OLB-abc123def456",
                    "--approver",
                    "human",
                ],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        mock_service.promote_to_prl.assert_called_once_with(
            entry_id="OLB-abc123def456",
            approver="human",
        )

    def test_promote_json_output(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces brownfield promote --json outputs PRL item as JSON."""
        monkeypatch.chdir(ces_project)

        mock_behavior = _make_mock_behavior(
            disposition="preserve",
            promoted_to_prl_id="PRL-xyz789abc012",
        )
        mock_prl = _make_mock_prl_item()
        mock_service = AsyncMock()
        mock_service.promote_to_prl = AsyncMock(return_value=(mock_behavior, mock_prl))

        mock_services = {"legacy_behavior_service": mock_service}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "--json",
                    "brownfield",
                    "promote",
                    "OLB-abc123def456",
                    "--approver",
                    "human",
                ],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        data = json.loads(result.stdout.strip())
        assert "prl_id" in data


class TestBrownfieldDiscard:
    """Tests for ces brownfield discard subcommand."""

    def test_discard_calls_discard_behavior(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces brownfield discard calls discard_behavior() with correct args."""
        monkeypatch.chdir(ces_project)

        mock_behavior = _make_mock_behavior(discarded=True)
        mock_service = AsyncMock()
        mock_service.discard_behavior = AsyncMock(return_value=mock_behavior)

        mock_services = {"legacy_behavior_service": mock_service}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "brownfield",
                    "discard",
                    "OLB-abc123def456",
                    "--reason",
                    "not relevant",
                ],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        mock_service.discard_behavior.assert_called_once_with(
            entry_id="OLB-abc123def456",
            reviewed_by="cli-user",
            reason="not relevant",
        )

    def test_discard_json_output(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces brownfield discard --json outputs as JSON."""
        monkeypatch.chdir(ces_project)

        mock_behavior = _make_mock_behavior(discarded=True)
        mock_service = AsyncMock()
        mock_service.discard_behavior = AsyncMock(return_value=mock_behavior)

        mock_services = {"legacy_behavior_service": mock_service}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "--json",
                    "brownfield",
                    "discard",
                    "OLB-abc123def456",
                    "--reason",
                    "not relevant",
                ],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        data = json.loads(result.stdout.strip())
        assert "entry_id" in data

    def test_discard_rich_output_shows_discarded(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces brownfield discard shows discarded entry in Rich output."""
        monkeypatch.chdir(ces_project)

        mock_behavior = _make_mock_behavior(discarded=True, disposition="retire")
        mock_service = AsyncMock()
        mock_service.discard_behavior = AsyncMock(return_value=mock_behavior)

        mock_services = {"legacy_behavior_service": mock_service}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(
                app,
                [
                    "brownfield",
                    "discard",
                    "OLB-abc123def456",
                    "--reason",
                    "not relevant",
                ],
            )

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "OLB-abc123def456" in result.stdout
