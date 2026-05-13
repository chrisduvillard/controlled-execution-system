"""Tests for first-class evidence attachment UX."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
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

    return patch("ces.cli.evidence_cmd.get_services", new=_fake_get_services)


def test_evidence_attach_persists_scrubbed_file_and_command_provenance(tmp_path: Path, monkeypatch: object) -> None:
    """Operators should be able to attach evidence without manual DB plumbing."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    (tmp_path / ".ces").mkdir()
    (tmp_path / ".ces" / "config.yaml").write_text("project_id: local-proj\n", encoding="utf-8")
    secret = "sk" + "-" + "syntheticEvidenceAttachSecret123"
    evidence_file = tmp_path / "evidence.md"
    evidence_file.write_text(f"npm test PASS\nOPENAI_API_KEY={secret}\n", encoding="utf-8")
    mock_store = MagicMock()
    mock_services = {"local_store": mock_store}

    with _patch_services(mock_services):
        result = runner.invoke(
            _get_app(),
            [
                "evidence",
                "attach",
                "--manifest-id",
                "M-attach",
                "--file",
                str(evidence_file),
                "--command",
                "npm test -- --run",
                "--summary",
                "Desktop shell verification passed",
            ],
        )

    assert result.exit_code == 0, result.stdout
    assert "Evidence Attached" in result.stdout
    mock_store.save_evidence.assert_called_once()
    assert mock_store.save_evidence.call_args.args[0] == "M-attach"
    content = mock_store.save_evidence.call_args.kwargs["content"]
    assert content["manual_attachment"] is True
    assert content["command_provenance"][0]["command"] == "npm test -- --run"
    assert content["command_provenance"][0]["cwd"] == str(tmp_path)
    saved_file = content["evidence_files"][0]
    assert saved_file["path"] == str(evidence_file.resolve())
    assert saved_file["sha256"]
    assert secret not in saved_file["text"]
    assert "<REDACTED>" in saved_file["text"]


def test_evidence_attach_blocks_external_file_without_consent(tmp_path: Path, monkeypatch: object) -> None:
    """Evidence attach should default to project-confined files."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".ces").mkdir()
    (project / ".ces" / "config.yaml").write_text("project_id: local-proj\n", encoding="utf-8")
    external = tmp_path / "outside.txt"
    external.write_text("pytest passed\n", encoding="utf-8")
    monkeypatch.chdir(project)  # type: ignore[attr-defined]
    mock_store = MagicMock()

    with _patch_services({"local_store": mock_store}):
        result = runner.invoke(
            _get_app(),
            ["evidence", "attach", "--manifest-id", "M-ext", "--file", str(external)],
        )

    assert result.exit_code != 0
    mock_store.save_evidence.assert_not_called()
