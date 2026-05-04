"""Tests for exporting builder run reports."""

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
    async def _fake_get_services():
        yield mock_services

    return patch("ces.cli.report_cmd.get_services", new=_fake_get_services)


def test_report_builder_exports_latest_snapshot(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    ces_dir = tmp_path / ".ces"
    ces_dir.mkdir()
    (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

    mock_store = MagicMock()
    mock_store.get_latest_builder_session_snapshot.return_value = SimpleNamespace(
        request="Modernize billing exports",
        project_mode="brownfield",
        stage="completed",
        next_action="start_new_session",
        next_step="Start a new task with `ces build` when you're ready for the next request.",
        latest_activity="CES recorded the latest review decision.",
        latest_artifact="approval",
        brief_only_fallback=False,
        brief=SimpleNamespace(prl_draft_path=".ces/exports/prl-draft-bb-123.md"),
        manifest=SimpleNamespace(
            manifest_id="M-123",
            workflow_state="approved",
            description="Modernize billing exports",
        ),
        runtime_execution=SimpleNamespace(exit_code=0, reported_model="gpt-5.4"),
        evidence={"packet_id": "EP-123", "triage_color": "green"},
        approval=SimpleNamespace(decision="approve"),
        session=SimpleNamespace(session_id="BS-123"),
        brownfield=SimpleNamespace(reviewed_count=3, remaining_count=0),
    )
    services = {"local_store": mock_store}

    with _patch_services(services):
        result = runner.invoke(_get_app(), ["report", "builder"])

    assert result.exit_code == 0, f"stdout={result.stdout}"
    markdown_path = ces_dir / "exports" / "builder-run-report-bs-123.md"
    json_path = ces_dir / "exports" / "builder-run-report-bs-123.json"
    assert markdown_path.is_file()
    assert json_path.is_file()

    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Modernize billing exports" in markdown
    assert "Review state: approved" in markdown
    assert "Latest outcome: approved" in markdown

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["request"] == "Modernize billing exports"
    assert payload["manifest_id"] == "M-123"
    assert payload["evidence_packet_id"] == "EP-123"
    assert payload["latest_outcome"] == "approved"


def test_report_builder_accepts_command_local_json_flag(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    ces_dir = tmp_path / ".ces"
    ces_dir.mkdir()
    (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

    mock_store = MagicMock()
    mock_store.get_latest_builder_session_snapshot.return_value = SimpleNamespace(
        request="Modernize billing exports",
        project_mode="brownfield",
        stage="completed",
        next_action="start_new_session",
        next_step="Start a new task with `ces build` when you're ready for the next request.",
        latest_activity="CES recorded the latest review decision.",
        latest_artifact="approval",
        brief=SimpleNamespace(prl_draft_path=None),
        manifest=SimpleNamespace(manifest_id="M-123", workflow_state="approved"),
        runtime_execution=SimpleNamespace(exit_code=0, reported_model="gpt-5.4"),
        evidence={"packet_id": "EP-123", "triage_color": "green"},
        approval=SimpleNamespace(decision="approve"),
        session=SimpleNamespace(session_id="BS-123"),
        brownfield=SimpleNamespace(reviewed_count=3, remaining_count=0),
    )

    with _patch_services({"local_store": mock_store}):
        result = runner.invoke(_get_app(), ["report", "builder", "--json"])

    assert result.exit_code == 0, f"stdout={result.stdout}"
    payload = json.loads(result.stdout)
    assert payload["builder_run"]["request"] == "Modernize billing exports"


def test_builder_report_surfaces_verification_findings_and_manual_supersession(tmp_path: Path, monkeypatch) -> None:
    """PromptVault dogfood: status/report must expose why auto-approval failed after manual completion."""
    from ces.cli._builder_report import build_builder_run_report, render_builder_run_report_markdown

    snapshot = SimpleNamespace(
        request="Build PromptVault",
        project_mode="greenfield",
        stage="completed",
        next_action="start_new_session",
        next_step="Start a new task",
        latest_activity="CES recorded approval",
        latest_artifact="approval",
        brief_only_fallback=False,
        brief=SimpleNamespace(prl_draft_path=None),
        manifest=SimpleNamespace(manifest_id="M-pv", workflow_state="approved"),
        runtime_execution=SimpleNamespace(exit_code=0, reported_model="gpt-5.5"),
        evidence={
            "packet_id": "EP-pv",
            "triage_color": "red",
            "runtime_safety": {
                "tool_allowlist_enforced": False,
                "accepted_runtime_side_effect_risk": True,
            },
            "verification_result": {
                "passed": False,
                "findings": [{"message": "Acceptance criterion has no evidence: 'delete command works'"}],
            },
        },
        approval=SimpleNamespace(decision="approve"),
        session=SimpleNamespace(session_id="BS-pv"),
        brownfield=None,
    )

    report = build_builder_run_report(snapshot)

    assert report is not None
    assert report.verification_findings == ("Acceptance criterion has no evidence: 'delete command works'",)
    assert report.manual_completion_supersedes_rejected_auto_review is True
    markdown = render_builder_run_report_markdown(report)
    assert "Manual completion superseded failed auto-approval: True" in markdown
    assert "Acceptance criterion has no evidence" in markdown


def test_builder_report_reads_verification_findings_from_manual_superseded_evidence() -> None:
    """PromptVault dogfood: manual evidence must not hide the failed runtime evidence it superseded."""
    from ces.cli._builder_report import build_builder_run_report

    snapshot = SimpleNamespace(
        request="Build PromptVault",
        project_mode="greenfield",
        stage="completed",
        next_action="start_new_session",
        next_step="Start a new task",
        latest_activity="CES recorded approval",
        latest_artifact="approval",
        brief=SimpleNamespace(prl_draft_path=None),
        manifest=SimpleNamespace(manifest_id="M-pv", workflow_state="approved"),
        runtime_execution=SimpleNamespace(exit_code=0, reported_model="gpt-5.5"),
        evidence={
            "packet_id": "EP-manual",
            "manual_completion": True,
            "superseded_evidence": {
                "packet_id": "EP-runtime",
                "runtime_safety": {"tool_allowlist_enforced": False},
                "verification_result": {
                    "passed": False,
                    "findings": [{"message": "Acceptance criterion has no evidence: 'export works'"}],
                },
            },
        },
        approval=SimpleNamespace(decision="approve"),
        session=SimpleNamespace(session_id="BS-pv"),
        brownfield=None,
    )

    report = build_builder_run_report(snapshot)

    assert report is not None
    assert report.runtime_tool_allowlist_enforced is False
    assert report.verification_findings == ("Acceptance criterion has no evidence: 'export works'",)
    assert report.manual_completion_supersedes_rejected_auto_review is True
