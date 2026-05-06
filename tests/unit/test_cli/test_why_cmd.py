"""Tests for `ces why` blocker explanation command."""

from __future__ import annotations

import json
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

    return patch("ces.cli.why_cmd.get_services", new=_fake_get_services)


def _snapshot(**overrides: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "request": "Build PromptVault",
        "project_mode": "greenfield",
        "stage": "completed",
        "next_action": "review_evidence",
        "next_step": "Run `ces review --full`.",
        "latest_activity": "CES recorded a rejected auto-review.",
        "latest_artifact": "approval",
        "brief": SimpleNamespace(prl_draft_path=None),
        "manifest": SimpleNamespace(manifest_id="M-pv", workflow_state="rejected"),
        "runtime_execution": SimpleNamespace(exit_code=0, reported_model="codex"),
        "evidence": {
            "packet_id": "EP-pv",
            "triage_color": "red",
            "verification_result": {
                "passed": False,
                "findings": [{"message": "Acceptance criterion has no evidence: delete works"}],
            },
        },
        "approval": SimpleNamespace(decision="reject"),
        "session": SimpleNamespace(session_id="BS-pv"),
        "brownfield": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_why_reports_blocker_and_next_command(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    ces_dir = tmp_path / ".ces"
    ces_dir.mkdir()
    (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")
    mock_store = MagicMock()
    mock_store.get_latest_builder_session_snapshot.return_value = _snapshot()

    with _patch_services({"local_store": mock_store}):
        result = runner.invoke(_get_app(), ["why"])

    assert result.exit_code == 0, result.stdout
    assert "Blocked because" in result.stdout
    assert "completion evidence failed verification" in result.stdout
    assert "Next: ces recover --dry-run" in result.stdout


def test_why_json_accepts_project_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    project_root = tmp_path / "target"
    ces_dir = project_root / ".ces"
    ces_dir.mkdir(parents=True)
    (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")
    mock_store = MagicMock()
    mock_store.get_latest_builder_session_snapshot.return_value = _snapshot()

    services = {"local_store": mock_store}
    with _patch_services(services):
        result = runner.invoke(_get_app(), ["why", "--project-root", str(project_root), "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["diagnostic"]["category"] == "evidence_failed_verification"
    assert payload["diagnostic"]["next_command"] == "ces recover --dry-run"
    assert services["_get_services_calls"][0]["kwargs"]["project_root"] == project_root.resolve()


def test_why_reports_completed_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    ces_dir = tmp_path / ".ces"
    ces_dir.mkdir()
    (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")
    mock_store = MagicMock()
    mock_store.get_latest_builder_session_snapshot.return_value = _snapshot(
        approval=SimpleNamespace(decision="approve"),
        manifest=SimpleNamespace(manifest_id="M-pv", workflow_state="approved"),
        evidence={"packet_id": "EP-pv", "triage_color": "green"},
    )

    with _patch_services({"local_store": mock_store}):
        result = runner.invoke(_get_app(), ["why"])

    assert result.exit_code == 0, result.stdout
    assert "No active blocker" in result.stdout
    assert "Next: ces report builder" in result.stdout


def test_why_reports_approved_but_hard_merge_block_as_active_blocker(tmp_path: Path, monkeypatch) -> None:
    """TaskLedger dogfood: why must not say no blocker for approved-but-evidence-blocked runs."""
    monkeypatch.chdir(tmp_path)
    ces_dir = tmp_path / ".ces"
    ces_dir.mkdir()
    (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n", encoding="utf-8")
    mock_store = MagicMock()
    mock_store.get_latest_builder_session_snapshot.return_value = _snapshot(
        stage="blocked",
        next_action="review_evidence",
        manifest=SimpleNamespace(manifest_id="M-taskledger", workflow_state="approved"),
        approval=SimpleNamespace(decision="approve"),
        evidence={"packet_id": "EP-taskledger", "triage_color": "green"},
        session=SimpleNamespace(
            session_id="BS-taskledger",
            stage="blocked",
            last_action="merge_blocked",
            last_error="evidence_exists",
        ),
    )

    with _patch_services({"local_store": mock_store}):
        result = runner.invoke(_get_app(), ["why", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["diagnostic"]["category"] == "blocked"
    assert payload["diagnostic"]["next_command"] == "ces why"
    assert "No active blocker" not in json.dumps(payload)
