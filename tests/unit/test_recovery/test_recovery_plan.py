"""Tests for builder self-recovery planning."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from ces.local_store import LocalProjectStore
from ces.recovery.planner import build_recovery_plan
from ces.shared.enums import ArtifactStatus, BehaviorConfidence, ChangeClass, RiskTier, WorkflowState


def _seed_blocked_session(tmp_path: Path) -> tuple[LocalProjectStore, Path]:
    project_root = tmp_path
    (project_root / ".ces").mkdir()
    store = LocalProjectStore(project_root / ".ces" / "state.db", project_id="proj")
    brief_id = store.save_builder_brief(
        request="Build a task tracker",
        project_mode="greenfield",
        constraints=[],
        acceptance_criteria=["Users can add tasks"],
        must_not_break=[],
        open_questions={},
        manifest_id="M-123",
        evidence_packet_id="EP-old",
    )
    manifest = SimpleNamespace(
        manifest_id="M-123",
        description="Build a task tracker",
        risk_tier=RiskTier.C,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_3,
        status=ArtifactStatus.DRAFT,
        workflow_state=WorkflowState.REJECTED,
        content_hash=None,
        expires_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        model_dump=lambda mode="json": {"manifest_id": "M-123", "description": "Build a task tracker"},
    )
    store.save_manifest(manifest)
    store.save_evidence(
        "M-123",
        packet_id="EP-old",
        summary="Runtime succeeded but evidence was incomplete",
        challenge="Missing verification proof",
        triage_color="yellow",
        content={"execution": {"exit_code": 0}, "verification_result": {"passed": False}},
    )
    store.save_builder_session(
        brief_id=brief_id,
        request="Build a task tracker",
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


def _seed_running_session(tmp_path: Path) -> tuple[LocalProjectStore, Path, str]:
    project_root = tmp_path
    (project_root / ".ces").mkdir()
    store = LocalProjectStore(project_root / ".ces" / "state.db", project_id="proj")
    brief_id = store.save_builder_brief(
        request="Build MiniLog",
        project_mode="greenfield",
        constraints=[],
        acceptance_criteria=["CLI works"],
        must_not_break=[],
        open_questions={},
        manifest_id="M-stale",
    )
    session_id = store.save_builder_session(
        brief_id=brief_id,
        request="Build MiniLog",
        project_mode="greenfield",
        stage="running",
        next_action="review_evidence",
        last_action="execution_started",
        manifest_id="M-stale",
        runtime_manifest_id="M-stale",
    )
    stale_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    with store._connect() as conn:
        conn.execute(
            "UPDATE builder_sessions SET updated_at = ? WHERE session_id = ?",
            (stale_at, session_id),
        )
    return store, project_root, session_id


def test_plan_recommends_auto_evidence_when_contract_exists(tmp_path: Path) -> None:
    store, project_root = _seed_blocked_session(tmp_path)
    contract_path = project_root / ".ces" / "completion-contract.json"
    contract_path.write_text('{"inferred_commands": []}', encoding="utf-8")

    plan = build_recovery_plan(project_root=project_root, local_store=store)

    assert plan.session_id.startswith("BS-")
    assert plan.blocked is True
    assert plan.can_run_auto_evidence is True
    assert plan.can_auto_complete is False
    assert "ces recover --auto-evidence" in plan.next_commands
    assert str(contract_path) in plan.explanation


def test_plan_recommends_dry_run_when_no_verification_contract(tmp_path: Path) -> None:
    store, project_root = _seed_blocked_session(tmp_path)

    plan = build_recovery_plan(project_root=project_root, local_store=store)

    assert plan.can_run_auto_evidence is False
    assert plan.can_auto_complete is False
    assert "ces verify --json" in plan.next_commands
    assert "completion contract" in plan.explanation


def test_plan_treats_stale_running_session_as_interrupted_and_retryable(tmp_path: Path) -> None:
    store, project_root, session_id = _seed_running_session(tmp_path)

    plan = build_recovery_plan(project_root=project_root, local_store=store)

    assert plan.session_id == session_id
    assert plan.blocked is True
    assert plan.can_run_auto_evidence is False
    assert "stale" in plan.explanation.lower() or "interrupted" in plan.explanation.lower()
    assert "ces continue" in plan.next_commands
    assert "ces recover --auto-evidence" not in plan.next_commands
