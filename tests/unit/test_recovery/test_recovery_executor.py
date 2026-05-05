"""Tests for builder self-recovery execution."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from ces.local_store import LocalProjectStore
from ces.recovery.executor import run_auto_evidence_recovery
from ces.shared.enums import ArtifactStatus, BehaviorConfidence, ChangeClass, RiskTier, WorkflowState
from ces.verification.completion_contract import AcceptanceCriterion, CompletionContract, VerificationCommand


def _seed_project(tmp_path: Path) -> tuple[LocalProjectStore, Path]:
    project_root = tmp_path
    (project_root / ".ces").mkdir()
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
        content={"execution": {"exit_code": 0}, "runtime_safety": {"profile": "limited"}},
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
    return store, project_root


def _write_passing_contract(project_root: Path) -> Path:
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
    path = project_root / ".ces" / "completion-contract.json"
    contract.write(path)
    return path


def test_auto_evidence_dry_run_does_not_mutate_session_or_evidence(tmp_path: Path) -> None:
    store, project_root = _seed_project(tmp_path)
    _write_passing_contract(project_root)
    session_before = store.get_latest_builder_session()

    result = run_auto_evidence_recovery(project_root=project_root, local_store=store, dry_run=True, auto_complete=True)

    assert result.verification.passed is True
    assert result.completed is False
    assert result.new_evidence_packet_id is None
    session_after = store.get_latest_builder_session()
    assert session_before == session_after
    assert store.get_evidence_by_packet_id("EP-old") is not None


def test_auto_evidence_can_safely_complete_and_preserve_superseded_evidence(tmp_path: Path) -> None:
    store, project_root = _seed_project(tmp_path)
    _write_passing_contract(project_root)

    result = run_auto_evidence_recovery(project_root=project_root, local_store=store, dry_run=False, auto_complete=True)

    assert result.verification.passed is True
    assert result.completed is True
    assert result.new_evidence_packet_id is not None
    session = store.get_latest_builder_session()
    assert session is not None
    assert session.stage == "completed"
    assert session.next_action == "start_new_session"
    evidence = store.get_evidence_by_packet_id(result.new_evidence_packet_id)
    assert evidence is not None
    assert evidence["recovery"]["auto_complete"] is True
    assert evidence["superseded_evidence"]["packet_id"] == "EP-old"
    assert evidence["superseded_evidence"]["runtime_safety"] == {"profile": "limited"}
    approval = store.get_approval("M-123")
    assert approval is not None
    assert approval.decision == "approve"


def test_auto_evidence_refreshes_stale_empty_contract_after_greenfield_files_exist(tmp_path: Path) -> None:
    """ReleasePulse RP-CES-012: recovery must not get stuck on pre-runtime empty contracts."""
    store, project_root = _seed_project(tmp_path)
    tests_dir = project_root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_smoke.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    contract = CompletionContract(
        request="Build demo",
        acceptance_criteria=(AcceptanceCriterion(id="AC-001", text="Running pytest passes."),),
        project_type="unknown",
        inferred_commands=(),
    )
    contract.write(project_root / ".ces" / "completion-contract.json")

    result = run_auto_evidence_recovery(project_root=project_root, local_store=store, dry_run=True, auto_complete=True)

    assert result.verification.passed is True
    assert [command.command for command in result.verification.commands] == [
        "python -m pytest -q",
        "python -m compileall tests",
    ]


def test_auto_evidence_refuses_non_blocked_session_without_mutation(tmp_path: Path) -> None:
    store, project_root = _seed_project(tmp_path)
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
    _write_passing_contract(project_root)
    before = store.get_latest_builder_session()

    result = run_auto_evidence_recovery(project_root=project_root, local_store=store, auto_complete=True)

    assert result.completed is False
    assert result.new_evidence_packet_id is None
    assert result.next_action in {"status", "run_continue"}
    assert "not blocked" in result.message.lower() or "cannot run" in result.message.lower()
    assert store.get_latest_builder_session() == before


def test_auto_evidence_completed_session_is_explicit_planner_noop(tmp_path: Path) -> None:
    store, project_root = _seed_project(tmp_path)
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
    _write_passing_contract(project_root)
    before = store.get_latest_builder_session()

    result = run_auto_evidence_recovery(project_root=project_root, local_store=store, auto_complete=True)

    assert result.completed is False
    assert result.verification_attempted is False
    assert result.recovery_applicable is False
    assert result.new_evidence_packet_id is None
    assert result.next_action == "status"
    assert "auto-evidence recovery was not run" in result.message.lower()
    assert "not blocked" in result.message.lower()
    assert store.get_latest_builder_session() == before


def test_auto_evidence_dry_run_reports_stale_running_session_without_mutation(tmp_path: Path) -> None:
    store, project_root = _seed_project(tmp_path)
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
    with store._connect() as conn:
        conn.execute(
            "UPDATE builder_sessions SET updated_at = ? WHERE session_id = ?",
            ((datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(), session.session_id),
        )
    _write_passing_contract(project_root)

    result = run_auto_evidence_recovery(project_root=project_root, local_store=store, dry_run=True, auto_complete=True)

    assert result.completed is False
    assert result.new_evidence_packet_id is None
    assert result.next_action == "run_continue"
    unchanged = store.get_latest_builder_session()
    assert unchanged is not None
    assert unchanged.stage == "running"
    assert unchanged.last_action == "execution_started"


def test_auto_evidence_empty_verification_commands_do_not_mutate_or_fail_product(tmp_path: Path) -> None:
    store, project_root = _seed_project(tmp_path)
    contract = CompletionContract(
        request="Build demo",
        acceptance_criteria=(AcceptanceCriterion(id="AC-001", text="Unimplemented product exists"),),
        project_type="unknown",
        inferred_commands=(),
    )
    contract.write(project_root / ".ces" / "completion-contract.json")
    before = store.get_latest_builder_session()

    result = run_auto_evidence_recovery(project_root=project_root, local_store=store, auto_complete=True)

    assert result.completed is False
    assert result.verification.commands == ()
    assert result.new_evidence_packet_id is None
    assert result.next_action == "run_continue"
    assert "no verification commands" in result.message.lower()
    assert store.get_latest_builder_session() == before


def test_auto_evidence_does_not_complete_when_verification_fails(tmp_path: Path) -> None:
    store, project_root = _seed_project(tmp_path)
    contract = CompletionContract(
        request="Build demo",
        acceptance_criteria=(AcceptanceCriterion(id="AC-001", text="README exists"),),
        project_type="unknown",
        inferred_commands=(
            VerificationCommand(id="fail", kind="test", command='python -c "raise SystemExit(2)"', cwd="."),
        ),
    )
    contract.write(project_root / ".ces" / "completion-contract.json")

    result = run_auto_evidence_recovery(project_root=project_root, local_store=store, dry_run=False, auto_complete=True)

    assert result.verification.passed is False
    assert result.completed is False
    session = store.get_latest_builder_session()
    assert session is not None
    assert session.stage == "blocked"
    assert session.next_action == "fix_verification"


def test_auto_complete_refuses_generic_review_state_without_specific_evidence_marker(tmp_path: Path) -> None:
    store, project_root = _seed_project(tmp_path)
    session = store.get_latest_builder_session()
    assert session is not None
    store.update_builder_session(
        session.session_id,
        stage="blocked",
        next_action="review_evidence",
        last_action="approval_rejected",
        recovery_reason="needs_review",
        last_error="manual review required",
    )
    _write_passing_contract(project_root)

    result = run_auto_evidence_recovery(project_root=project_root, local_store=store, auto_complete=True)

    assert result.verification.passed is True
    assert result.completed is False
    assert result.new_evidence_packet_id is not None
    latest = store.get_latest_builder_session()
    assert latest is not None
    assert latest.stage == "awaiting_review"
    assert latest.next_action == "review_evidence"
    approval = store.get_approval("M-123")
    assert approval is None or approval.decision != "approve"
    assert "manual review" in result.message.lower()


def test_auto_complete_refuses_scope_blocked_session_even_if_verification_passes(tmp_path: Path) -> None:
    scoped_root = tmp_path / "scope-blocked"
    scoped_root.mkdir()
    store, project_root = _seed_project(scoped_root)
    session = store.get_latest_builder_session()
    assert session is not None
    store.update_builder_session(
        session.session_id,
        stage="blocked",
        next_action="review_evidence",
        last_action="approval_rejected",
        recovery_reason="scope_violation",
        last_error="workspace changes exceeded manifest scope",
    )
    _write_passing_contract(project_root)

    result = run_auto_evidence_recovery(project_root=project_root, local_store=store, auto_complete=True)

    assert result.verification.passed is True
    assert result.completed is False
    assert result.new_evidence_packet_id is not None
    latest = store.get_latest_builder_session()
    assert latest is not None
    assert latest.stage == "awaiting_review"
    assert latest.next_action == "review_evidence"
    approval = store.get_approval("M-123")
    assert approval is None or approval.decision != "approve"
    assert "manual review" in result.message.lower()
