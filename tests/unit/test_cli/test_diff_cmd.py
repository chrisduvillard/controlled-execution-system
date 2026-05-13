"""Tests for CES diff helper commands."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

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

    return patch("ces.cli.diff_cmd.get_services", new=_fake_get_services)


def test_diff_since_approval_uses_latest_evidence_git_head(tmp_path: Path, monkeypatch: object) -> None:
    """Operators can ask what changed since the last reviewed evidence baseline."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    (tmp_path / ".ces").mkdir()
    (tmp_path / ".ces" / "config.yaml").write_text("project_id: local-proj\n", encoding="utf-8")
    mock_store = MagicMock()
    mock_store.get_latest_evidence_packet.return_value = {
        "packet_id": "EP-baseline",
        "manifest_id": "M-baseline",
        "git": {"head": "abc123"},
    }

    fake_completed = SimpleNamespace(returncode=0, stdout="M\tsrc/ces/cli/evidence_cmd.py\n", stderr="")
    with (
        _patch_services({"local_store": mock_store}),
        patch("ces.cli.diff_cmd.subprocess.run", return_value=fake_completed) as run,
    ):
        result = runner.invoke(_get_app(), ["diff", "--since-approval"])

    assert result.exit_code == 0, result.stdout
    assert "EP-baseline" in result.stdout
    assert "src/ces/cli/evidence_cmd.py" in result.stdout
    run.assert_called_once()
    assert run.call_args.args[0][:4] == ["git", "diff", "--name-status", "abc123"]


def test_diff_since_approval_fails_without_git_baseline(tmp_path: Path, monkeypatch: object) -> None:
    """The helper should fail clearly when there is no captured baseline head."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    (tmp_path / ".ces").mkdir()
    (tmp_path / ".ces" / "config.yaml").write_text("project_id: local-proj\n", encoding="utf-8")
    mock_store = MagicMock()
    mock_store.get_latest_evidence_packet.return_value = {"packet_id": "EP-no-git"}

    with _patch_services({"local_store": mock_store}):
        result = runner.invoke(_get_app(), ["diff", "--since-approval"])

    assert result.exit_code != 0
    assert "No git baseline" in result.stdout or "No git baseline" in str(result.exception)
