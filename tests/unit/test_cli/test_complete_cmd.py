"""Tests for manual builder-session completion/reconciliation."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

runner = CliRunner()


def _get_app():
    from ces.cli import app

    return app


def _patch_services(mock_services: dict[str, Any]):
    @asynccontextmanager
    async def _fake_get_services(*args: Any, **kwargs: Any):
        mock_services.setdefault("_get_services_calls", []).append({"args": args, "kwargs": kwargs})
        yield mock_services

    return patch("ces.cli.complete_cmd.get_services", new=_fake_get_services)


def test_complete_marks_latest_blocked_session_completed_with_manual_evidence(
    tmp_path: Path, monkeypatch: object
) -> None:
    """ces complete lets operators reconcile work finished outside the runtime."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    ces_dir = tmp_path / ".ces"
    ces_dir.mkdir()
    (ces_dir / "config.yaml").write_text("project_id: local-proj\n")
    evidence = tmp_path / "verification.txt"
    evidence.write_text("pytest passed\nruff passed\n")

    session = SimpleNamespace(
        session_id="BS-manual",
        runtime_manifest_id="M-manual",
        manifest_id="M-manual",
        evidence_packet_id=None,
        stage="blocked",
    )
    mock_store = MagicMock()
    mock_store.get_latest_builder_session.return_value = session
    mock_store.save_evidence.return_value = "EP-manual"
    mock_services = {
        "local_store": mock_store,
        "audit_ledger": AsyncMock(),
    }

    with _patch_services(mock_services):
        app = _get_app()
        result = runner.invoke(
            app,
            [
                "complete",
                "--evidence",
                str(evidence),
                "--rationale",
                "Recovered manually after runtime failure",
                "--yes",
            ],
        )

    assert result.exit_code == 0, result.stdout
    assert "reconciled" in result.stdout.lower()
    mock_store.save_evidence.assert_called_once()
    mock_store.save_approval.assert_called_once_with(
        "M-manual",
        decision="approve",
        rationale="Recovered manually after runtime failure",
    )
    mock_store.update_builder_session.assert_called_once_with(
        "BS-manual",
        stage="completed",
        next_action="start_new_session",
        last_action="manual_completion_reconciled",
        recovery_reason=None,
        last_error=None,
        evidence_packet_id="EP-manual-BS-manual",
        approval_manifest_id="M-manual",
    )
