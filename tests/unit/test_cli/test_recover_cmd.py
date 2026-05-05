"""Tests for `ces recover`."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from ces.local_store import LocalProjectStore
from ces.shared.enums import ArtifactStatus, BehaviorConfidence, ChangeClass, RiskTier, WorkflowState
from ces.verification.completion_contract import AcceptanceCriterion, CompletionContract, VerificationCommand

runner = CliRunner()


def _get_app():
    from ces.cli import app

    return app


def _seed_project(project_root: Path) -> None:
    (project_root / ".ces").mkdir()
    (project_root / ".ces" / "config.yaml").write_text("project_id: proj\npreferred_runtime: codex\n", encoding="utf-8")
    (project_root / "README.md").write_text("# demo\n", encoding="utf-8")
    store = LocalProjectStore(project_root / ".ces" / "state.db", project_id="proj")
    brief_id = store.save_builder_brief(
        request="Build demo",
        project_mode="greenfield",
        constraints=[],
        acceptance_criteria=["README exists"],
        must_not_break=[],
        open_questions={},
        manifest_id="M-123",
        evidence_packet_id="EP-old",
    )
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    manifest = SimpleNamespace(
        manifest_id="M-123",
        description="Build demo",
        risk_tier=RiskTier.C,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_3,
        status=ArtifactStatus.DRAFT,
        workflow_state=WorkflowState.REJECTED,
        content_hash=None,
        expires_at=now,
        created_at=now,
        model_dump=lambda mode="json": {"manifest_id": "M-123", "description": "Build demo"},
    )
    store.save_manifest(manifest)
    store.save_evidence(
        "M-123",
        packet_id="EP-old",
        summary="Original blocked evidence",
        challenge="No independent verification yet",
        triage_color="yellow",
        content={
            "execution": {"exit_code": 0},
            "verification_result": {
                "passed": False,
                "findings": [{"message": "original missing artifact"}],
            },
        },
    )
    store.save_builder_session(
        brief_id=brief_id,
        request="Build demo",
        project_mode="greenfield",
        stage="blocked",
        next_action="review_evidence",
        last_action="approval_rejected",
        recovery_reason="needs_review",
        last_error="completion evidence failed verification",
        manifest_id="M-123",
        runtime_manifest_id="M-123",
        evidence_packet_id="EP-old",
        approval_manifest_id="M-123",
    )
    contract = CompletionContract(
        request="Build demo",
        acceptance_criteria=(AcceptanceCriterion(id="AC-001", text="README exists"),),
        project_type="unknown",
        inferred_commands=(
            VerificationCommand(
                id="readme-smoke",
                kind="smoke",
                command="python -c \"from pathlib import Path; assert Path('README.md').is_file()\"",
                cwd=".",
            ),
        ),
    )
    contract.write(project_root / ".ces" / "completion-contract.json")


def _seed_running_project(project_root: Path) -> None:
    _seed_project(project_root)
    store = LocalProjectStore(project_root / ".ces" / "state.db", project_id="proj")
    session = store.get_latest_builder_session()
    assert session is not None
    store.update_builder_session(
        session.session_id,
        stage="running",
        next_action="review_evidence",
        last_action="execution_started",
        recovery_reason=None,
        last_error=None,
    )


def test_recover_dry_run_json_shows_plan_without_mutation(tmp_path: Path, monkeypatch) -> None:
    _seed_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(_get_app(), ["recover", "--dry-run", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["mode"] == "plan"
    assert payload["plan"]["blocked"] is True
    assert "ces recover --auto-evidence" in payload["plan"]["next_commands"]
    store = LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj")
    assert store.get_latest_builder_session().stage == "blocked"  # type: ignore[union-attr]


def test_recover_auto_evidence_json_refuses_non_blocked_without_mutation(tmp_path: Path, monkeypatch) -> None:
    _seed_running_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    store = LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj")
    before = store.get_latest_builder_session()

    result = runner.invoke(_get_app(), ["recover", "--auto-evidence", "--auto-complete", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["result"]["completed"] is False
    assert payload["result"]["new_evidence_packet_id"] is None
    assert "not blocked" in payload["result"]["message"].lower()
    assert LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj").get_latest_builder_session() == before


def test_recover_dry_run_reports_stale_running_session_without_mutation(tmp_path: Path, monkeypatch) -> None:
    _seed_running_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    store = LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj")
    session = store.get_latest_builder_session()
    assert session is not None
    with store._connect() as conn:
        conn.execute(
            "UPDATE builder_sessions SET updated_at = ? WHERE session_id = ?",
            ((datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(), session.session_id),
        )

    result = runner.invoke(_get_app(), ["recover", "--dry-run", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["plan"]["blocked"] is True
    assert payload["plan"]["next_commands"][0] == "ces continue"
    unchanged = LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj").get_latest_builder_session()
    assert unchanged is not None
    assert unchanged.stage == "running"
    assert unchanged.last_action == "execution_started"


def test_recover_auto_evidence_json_completed_session_reports_noop_not_failed_verification(
    tmp_path: Path, monkeypatch
) -> None:
    _seed_project(tmp_path)
    store = LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj")
    session = store.get_latest_builder_session()
    assert session is not None
    store.update_builder_session(
        session.session_id,
        stage="completed",
        next_action="start_new_session",
        last_action="runtime_approved",
        recovery_reason=None,
        last_error=None,
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(_get_app(), ["recover", "--auto-evidence", "--auto-complete", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["mode"] == "auto-evidence"
    assert payload["result"]["verification_attempted"] is False
    assert payload["result"]["recovery_applicable"] is False
    assert payload["result"]["next_action"] == "status"
    assert "auto-evidence recovery was not run" in payload["result"]["message"].lower()
    assert (
        LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj").get_latest_builder_session().stage
        == "completed"
    )  # type: ignore[union-attr]


def test_recover_auto_evidence_text_completed_session_labels_planner_noop(tmp_path: Path, monkeypatch) -> None:
    _seed_project(tmp_path)
    store = LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj")
    session = store.get_latest_builder_session()
    assert session is not None
    store.update_builder_session(
        session.session_id,
        stage="completed",
        next_action="start_new_session",
        last_action="runtime_approved",
        recovery_reason=None,
        last_error=None,
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(_get_app(), ["recover", "--auto-evidence", "--auto-complete"])

    assert result.exit_code == 0, result.stdout
    assert "Self-Recovery Skipped" in result.stdout
    assert "Auto-evidence recovery was not run" in result.stdout


def test_recover_auto_evidence_json_can_complete(tmp_path: Path, monkeypatch) -> None:
    _seed_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(_get_app(), ["recover", "--auto-evidence", "--auto-complete", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["mode"] == "auto-evidence"
    assert payload["result"]["verification"]["passed"] is True
    assert payload["result"]["completed"] is True
    store = LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj")
    assert store.get_latest_builder_session().stage == "completed"  # type: ignore[union-attr]

    from ces.cli._builder_report import build_builder_run_report

    report = build_builder_run_report(store.get_latest_builder_session_snapshot())
    assert report is not None
    assert report.verification_findings == ()
    assert report.superseded_verification_findings == ("original missing artifact",)
