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
    async def _fake_get_services(*args: Any, **kwargs: Any):
        mock_services.setdefault("_get_services_calls", []).append({"args": args, "kwargs": kwargs})
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


def test_report_builder_accepts_project_root(tmp_path: Path) -> None:
    project = tmp_path / "target"
    project.mkdir()
    ces_dir = project / ".ces"
    ces_dir.mkdir()
    (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n", encoding="utf-8")

    mock_store = MagicMock()
    mock_store.get_latest_builder_session_snapshot.return_value = SimpleNamespace(
        request="Build MiniLog",
        project_mode="greenfield",
        stage="completed",
        next_action="start_new_session",
        next_step="Start a new task",
        latest_activity="CES recorded approval",
        latest_artifact="approval",
        brief_only_fallback=False,
        brief=SimpleNamespace(prl_draft_path=None),
        manifest=SimpleNamespace(manifest_id="M-123", workflow_state="merged"),
        runtime_execution=SimpleNamespace(exit_code=0, reported_model="gpt-5.5"),
        evidence={"packet_id": "EP-123", "triage_color": "green"},
        approval=SimpleNamespace(decision="approve"),
        session=SimpleNamespace(session_id="BS-123"),
        brownfield=None,
    )

    services = {"local_store": mock_store}
    with _patch_services(services):
        result = runner.invoke(_get_app(), ["report", "builder", "--project-root", str(project), "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["builder_run"]["request"] == "Build MiniLog"
    assert (project / ".ces" / "exports" / "builder-run-report-bs-123.md").is_file()
    assert services["_get_services_calls"][0]["kwargs"] == {"project_root": project.resolve()}


def test_builder_report_exposes_entry_level_brownfield_counts_when_item_count_is_inflated() -> None:
    """ReleasePulse RP-CES-007: one reviewed OLB entry must not display as 13 behaviors reviewed."""
    from ces.cli._builder_report import build_builder_run_report, render_builder_run_report_markdown

    snapshot = SimpleNamespace(
        request="Improve ReleasePulse brownfield CLI",
        project_mode="brownfield",
        stage="completed",
        next_action="start_new_session",
        next_step="Start a new task",
        latest_activity="CES recorded approval",
        latest_artifact="approval",
        brief=SimpleNamespace(prl_draft_path=None),
        manifest=SimpleNamespace(manifest_id="M-rp", workflow_state="approved"),
        runtime_execution=SimpleNamespace(exit_code=0, reported_model="gpt-5.5"),
        evidence={"packet_id": "EP-rp", "triage_color": "green"},
        approval=SimpleNamespace(decision="approve"),
        session=SimpleNamespace(session_id="BS-rp"),
        brownfield=SimpleNamespace(
            entry_ids=["OLB-a218da0878b7"],
            reviewed_count=13,
            remaining_count=0,
            checkpoint={"reviewed_candidates": [{"description": f"candidate {idx}"} for idx in range(13)]},
        ),
    )

    report = build_builder_run_report(snapshot)

    assert report is not None
    assert report.brownfield_entry_reviewed_count == 1
    assert report.brownfield_item_reviewed_count == 13
    assert report.brownfield_reviewed_count == 1
    markdown = render_builder_run_report_markdown(report)
    assert "1 behavior reviewed" in markdown
    assert "13 review items checked" in markdown
    assert "13 reviewed, 0 remaining" not in markdown


def test_builder_report_uses_checkpoint_entry_ids_when_snapshot_entry_ids_are_empty() -> None:
    """ReleasePulse RP-CES-013: persisted sessions may omit entry_ids but keep them in checkpoint state."""
    from ces.cli._builder_report import build_builder_run_report, render_builder_run_report_markdown

    snapshot = SimpleNamespace(
        request="Improve ReleasePulse brownfield CLI",
        project_mode="brownfield",
        stage="completed",
        next_action="start_new_session",
        next_step="Start a new task",
        latest_activity="CES recorded approval",
        latest_artifact="approval",
        brief=SimpleNamespace(prl_draft_path=None),
        manifest=SimpleNamespace(manifest_id="M-rp", workflow_state="approved"),
        runtime_execution=SimpleNamespace(exit_code=0, reported_model="gpt-5.5"),
        evidence={"packet_id": "EP-rp", "triage_color": "green"},
        approval=SimpleNamespace(decision="approve"),
        session=SimpleNamespace(session_id="BS-rp"),
        brownfield=SimpleNamespace(
            entry_ids=[],
            reviewed_count=9,
            remaining_count=0,
            checkpoint={
                "reviewed_entry_ids": ["OLB-095836dc0cab"],
                "reviewed_candidates": [{"description": f"candidate {idx}"} for idx in range(9)],
                "remaining_count": 0,
            },
        ),
    )

    report = build_builder_run_report(snapshot)

    assert report is not None
    assert report.brownfield_entry_reviewed_count == 1
    assert report.brownfield_item_reviewed_count == 9
    assert report.brownfield_reviewed_count == 1
    markdown = render_builder_run_report_markdown(report)
    assert "1 behavior reviewed, 0 behaviors remaining" in markdown
    assert "9 review items checked" in markdown
    assert "9 behaviors reviewed" not in markdown


def test_builder_report_labels_builder_auto_preserve_counts_separately_from_manual_inventory() -> None:
    """TaskLedger CES-DOG-007: build-created preservation entries should not read like manual scan review totals."""
    from ces.cli._builder_report import build_builder_run_report, render_builder_run_report_markdown

    snapshot = SimpleNamespace(
        request="Add update command while preserving TaskLedger flows",
        project_mode="brownfield",
        stage="completed",
        next_action="start_new_session",
        next_step="Start a new task",
        latest_activity="CES recorded approval",
        latest_artifact="approval",
        brief=SimpleNamespace(prl_draft_path=None),
        manifest=SimpleNamespace(manifest_id="M-taskledger", workflow_state="approved"),
        runtime_execution=SimpleNamespace(
            exit_code=0,
            reported_model="gpt-5.5",
            transcript_path=".ces/runtime-transcripts/codex-taskledger.txt",
        ),
        evidence={"packet_id": "EP-taskledger", "triage_color": "green"},
        approval=SimpleNamespace(decision="approve"),
        session=SimpleNamespace(session_id="BS-taskledger"),
        brownfield=SimpleNamespace(
            entry_ids=[f"OLB-{idx}" for idx in range(6)],
            reviewed_count=6,
            remaining_count=0,
            checkpoint={
                "groups": [
                    {"key": "must_not_break", "label": "Must Not Break", "items": []},
                    {"key": "critical_flows", "label": "Critical Flows", "items": []},
                ],
                "reviewed_entry_ids": [f"OLB-{idx}" for idx in range(6)],
                "reviewed_candidates": [{"description": f"preserve {idx}"} for idx in range(6)],
            },
        ),
    )

    report = build_builder_run_report(snapshot)

    assert report is not None
    markdown = render_builder_run_report_markdown(report)
    assert "6 build auto-preserve behaviors reviewed" in markdown
    assert "6 behaviors reviewed" not in markdown
    assert "Runtime transcript: .ces/runtime-transcripts/codex-taskledger.txt" in markdown


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
    assert report.verification_findings == ()
    assert report.superseded_verification_findings == ("Acceptance criterion has no evidence: 'export works'",)
    assert report.manual_completion_supersedes_rejected_auto_review is True


def test_recovered_builder_report_separates_active_and_superseded_verification_findings() -> None:
    """ReleasePulse RP-CES-004: recovered status must not expose stale blockers as active failures."""
    from ces.cli._builder_report import build_builder_run_report, render_builder_run_report_markdown

    snapshot = SimpleNamespace(
        request="Build ReleasePulse",
        project_mode="greenfield",
        stage="completed",
        next_action="start_new_session",
        next_step="Start a new task",
        latest_activity="CES self-recovery completed",
        latest_artifact="approval",
        brief=SimpleNamespace(prl_draft_path=None),
        manifest=SimpleNamespace(manifest_id="M-rp", workflow_state="rejected"),
        runtime_execution=SimpleNamespace(exit_code=0, reported_model="gpt-5.5"),
        evidence={
            "packet_id": "EP-recovery",
            "triage_color": "green",
            "content": {
                "recovery": {"auto_evidence": True, "auto_complete": True},
                "independent_verification": {"passed": True, "commands": []},
                "superseded_evidence": {
                    "packet_id": "EP-runtime",
                    "content": {
                        "verification_result": {
                            "passed": False,
                            "findings": [{"message": "missing artifact: coverage.json"}],
                        }
                    },
                },
            },
        },
        approval=SimpleNamespace(decision="approve"),
        session=SimpleNamespace(session_id="BS-rp"),
        brownfield=None,
    )

    report = build_builder_run_report(snapshot)

    assert report is not None
    assert report.latest_outcome == "approved"
    assert report.workflow_state == "approved"
    assert report.verification_findings == ()
    assert report.superseded_verification_findings == ("missing artifact: coverage.json",)
    assert report.manual_completion_supersedes_rejected_auto_review is True
    markdown = render_builder_run_report_markdown(report)
    assert "## Verification Findings" not in markdown
    assert "## Superseded Verification Findings" in markdown
    assert "missing artifact: coverage.json" in markdown


def test_approved_builder_report_demotes_stale_runtime_findings_when_independent_verification_passed() -> None:
    """ReleasePulse redogfood: approved runs must not keep stale red findings active."""
    from ces.cli._builder_report import build_builder_run_report, render_builder_run_report_markdown

    snapshot = SimpleNamespace(
        request="Improve ReleasePulse",
        project_mode="brownfield",
        stage="completed",
        next_action="start_new_session",
        next_step="Start a new task",
        latest_activity="CES recorded approval",
        latest_artifact="approval",
        brief=SimpleNamespace(prl_draft_path=None),
        manifest=SimpleNamespace(manifest_id="M-rp", workflow_state="merged", verification_sensors=()),
        runtime_execution=SimpleNamespace(exit_code=0, reported_model="gpt-5.5"),
        evidence={
            "packet_id": "EP-approved",
            "triage_color": "red",
            "content": {
                "verification_result": {
                    "passed": False,
                    "findings": [
                        {"message": "Verification command failed with exit code 1: python -m releasepulse unknown"},
                        {"message": "[coverage] Required coverage artifact is missing: coverage.json @ coverage.json"},
                    ],
                },
                "independent_verification": {"passed": True, "commands": ["pytest"]},
                "completion_contract_path": "project/.ces/completion-contract.json",
            },
        },
        approval=SimpleNamespace(decision="approve"),
        session=SimpleNamespace(session_id="BS-rp"),
        brownfield=SimpleNamespace(reviewed_count=1, remaining_count=0, entry_ids=("OLB-1",), checkpoint=None),
    )

    report = build_builder_run_report(snapshot)

    assert report is not None
    assert report.latest_outcome == "approved"
    assert report.triage_color == "green"
    assert report.evidence_quality_state == "passed"
    assert report.verification_findings == ()
    assert report.superseded_verification_findings == (
        "Verification command failed with exit code 1: python -m releasepulse unknown",
        "[coverage] Required coverage artifact is missing: coverage.json @ coverage.json",
    )
    markdown = render_builder_run_report_markdown(report)
    assert "## Verification Findings" not in markdown
    assert "## Superseded Verification Findings" in markdown


def test_builder_report_surfaces_completion_contract_and_independent_verification() -> None:
    from ces.cli._builder_report import build_builder_run_report, render_builder_run_report_markdown

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
            "packet_id": "EP-pv",
            "content": {
                "completion_contract_path": ".ces/completion-contract.json",
                "independent_verification": {"passed": True, "commands": []},
            },
        },
        approval=SimpleNamespace(decision="approve"),
        session=SimpleNamespace(session_id="BS-pv"),
        brownfield=None,
    )

    report = build_builder_run_report(snapshot)

    assert report is not None
    assert report.completion_contract_path == ".ces/completion-contract.json"
    assert report.independent_verification_passed is True
    markdown = render_builder_run_report_markdown(report)
    assert "Completion contract: .ces/completion-contract.json" in markdown
    assert "Independent verification passed: True" in markdown


def test_builder_report_hard_merge_block_overrides_approval() -> None:
    """TaskLedger dogfood: hard merge integrity blocks must not be reported as approved."""
    from ces.cli._builder_report import build_builder_run_report

    snapshot = SimpleNamespace(
        request="Create TaskLedger",
        project_mode="greenfield",
        stage="blocked",
        next_action="review_evidence",
        next_step="Review evidence",
        latest_activity="CES recorded approval but merge validation blocked.",
        latest_artifact="approval",
        brief=SimpleNamespace(prl_draft_path=None),
        manifest=SimpleNamespace(manifest_id="M-taskledger", workflow_state="approved"),
        runtime_execution=SimpleNamespace(exit_code=0, reported_model="gpt-5.5"),
        evidence={"packet_id": "EP-taskledger", "triage_color": "green"},
        approval=SimpleNamespace(decision="approve"),
        session=SimpleNamespace(
            session_id="BS-taskledger",
            stage="blocked",
            last_action="merge_blocked",
            last_error="evidence_exists",
            next_action="review_evidence",
        ),
        brownfield=None,
    )

    report = build_builder_run_report(snapshot)

    assert report is not None
    assert report.stage == "blocked"
    assert report.review_state == "blocked"
    assert report.latest_outcome == "blocked"
    assert "ces why" in report.next_step


def test_builder_report_soft_merge_not_applied_is_approved_unblocked() -> None:
    """Soft merge-not-applied states remain approved historical outcomes, not recovery blockers."""
    from ces.cli._builder_report import build_builder_run_report

    snapshot = SimpleNamespace(
        request="Create TaskLedger",
        project_mode="greenfield",
        stage="completed",
        next_action="start_new_session",
        next_step="Start a new task",
        latest_activity="CES recorded approval; no repository merge was applied.",
        latest_artifact="approval",
        brief=SimpleNamespace(prl_draft_path=None),
        manifest=SimpleNamespace(manifest_id="M-taskledger", workflow_state="approved"),
        runtime_execution=SimpleNamespace(exit_code=0, reported_model="gpt-5.5"),
        evidence={"packet_id": "EP-taskledger", "triage_color": "green"},
        approval=SimpleNamespace(decision="approve"),
        session=SimpleNamespace(
            session_id="BS-taskledger",
            stage="completed",
            last_action="approval_recorded_merge_not_applied",
            last_error="review_complete",
            next_action="start_new_session",
        ),
        brownfield=None,
    )

    report = build_builder_run_report(snapshot)

    assert report is not None
    assert report.review_state == "approved"
    assert report.latest_outcome == "approved_unmerged"
    assert report.next_step == "Run `ces report builder` to inspect the approved builder run."
