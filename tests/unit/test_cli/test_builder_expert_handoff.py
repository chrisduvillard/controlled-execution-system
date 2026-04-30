"""Tests for builder-to-expert command handoff."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from ces.cli._builder_handoff import resolve_manifest_id
from ces.harness.models.review_assignment import ReviewAssignment, ReviewerRole
from ces.harness.models.triage_result import TriageColor, TriageDecision
from ces.harness.services.diff_extractor import DiffContext, DiffStats
from ces.shared.enums import ActorType, RiskTier, TrustStatus

_MOCK_DIFF_CONTEXT = DiffContext(
    diff_text="+ mock change",
    files_changed=("src/main.py",),
    hunks=(),
    stats=DiffStats(insertions=1, deletions=0, files_changed=1),
)

runner = CliRunner()


def _get_app():
    from ces.cli import app

    return app


def _make_builder_snapshot() -> tuple[MagicMock, dict[str, Any]]:
    manifest = MagicMock()
    manifest.manifest_id = "M-builder-123"
    manifest.description = "Build a habit tracker"
    manifest.risk_tier = RiskTier.C
    manifest.trust_status = TrustStatus.TRUSTED
    manifest.builder_agent_id = "agent-builder-1"
    manifest.builder_model_id = "gpt-5.4"
    snapshot = SimpleNamespace(
        request="Build a habit tracker",
        project_mode="greenfield",
        latest_activity="CES recorded the latest review decision.",
        next_step="Start a new task with `ces build` when you're ready for the next request.",
        manifest=manifest,
        evidence={"packet_id": "EP-builder-123"},
        session=SimpleNamespace(next_action="start_new_session"),
    )
    local_store = MagicMock()
    local_store.get_latest_builder_session_snapshot.return_value = snapshot
    local_store.get_review_findings.return_value = None
    return manifest, {"local_store": local_store}


def _patch_review_services(mock_services: dict[str, Any]):
    @asynccontextmanager
    async def _fake_get_services():
        yield mock_services

    return patch("ces.cli.review_cmd.get_services", new=_fake_get_services)


def _patch_triage_services(mock_services: dict[str, Any]):
    @asynccontextmanager
    async def _fake_get_services():
        yield mock_services

    return patch("ces.cli.triage_cmd.get_services", new=_fake_get_services)


def _patch_approve_services(mock_services: dict[str, Any]):
    @asynccontextmanager
    async def _fake_get_services():
        yield mock_services

    return patch("ces.cli.approve_cmd.get_services", new=_fake_get_services)


def _make_review_assignment() -> list[ReviewAssignment]:
    return [
        ReviewAssignment(
            role=ReviewerRole.STRUCTURAL,
            model_id="gpt-4o",
            agent_id="reviewer-structural-gpt-4o",
        )
    ]


def _make_triage_decision() -> TriageDecision:
    return TriageDecision(
        color=TriageColor.GREEN,
        risk_tier=RiskTier.C,
        trust_status=TrustStatus.TRUSTED,
        sensor_pass_rate=1.0,
        reason="Tier=C, Trust=trusted, SensorsGreen=True, PassRate=1.00",
        auto_approve_eligible=True,
    )


def test_review_without_manifest_id_uses_current_builder_snapshot(ces_project, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ces_project)
    manifest, shared = _make_builder_snapshot()
    manager = AsyncMock()
    manager.get_manifest = AsyncMock(return_value=manifest)
    review_router = MagicMock()
    review_router.assign_triad.return_value = _make_review_assignment()
    review_router.assign_single.return_value = _make_review_assignment()[0]
    review_router.dispatch_review = AsyncMock(side_effect=RuntimeError("No review executor"))
    synth = MagicMock()
    synth.format_summary_slots = AsyncMock(
        return_value=SimpleNamespace(summary="Summary line", challenge="Challenge line")
    )
    services = {
        "manifest_manager": manager,
        "review_router": review_router,
        "evidence_synthesizer": synth,
        "audit_ledger": AsyncMock(),
        "provider_registry": MagicMock(get_provider=MagicMock(side_effect=KeyError("no provider"))),
        "settings": MagicMock(default_model_id="gpt-5.4"),
        **shared,
    }

    with (
        _patch_review_services(services),
        patch("ces.cli.review_cmd.WorkflowEngine", return_value=AsyncMock(submit_for_review=AsyncMock())),
        patch(
            "ces.harness.services.diff_extractor.DiffExtractor.extract_diff",
            new=AsyncMock(return_value=_MOCK_DIFF_CONTEXT),
        ),
    ):
        result = runner.invoke(_get_app(), ["review"])

    assert result.exit_code == 0, f"stdout={result.stdout}"
    manager.get_manifest.assert_awaited_once_with("M-builder-123")


def test_review_json_includes_builder_run_context(ces_project, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ces_project)
    manifest, shared = _make_builder_snapshot()
    manager = AsyncMock()
    manager.get_manifest = AsyncMock(return_value=manifest)
    review_router = MagicMock()
    review_router.assign_triad.return_value = _make_review_assignment()
    review_router.assign_single.return_value = _make_review_assignment()[0]
    review_router.dispatch_review = AsyncMock(side_effect=RuntimeError("No review executor"))
    synth = MagicMock()
    synth.format_summary_slots = AsyncMock(
        return_value=SimpleNamespace(summary="Summary line", challenge="Challenge line")
    )
    services = {
        "manifest_manager": manager,
        "review_router": review_router,
        "evidence_synthesizer": synth,
        "audit_ledger": AsyncMock(),
        "provider_registry": MagicMock(get_provider=MagicMock(side_effect=KeyError("no provider"))),
        "settings": MagicMock(default_model_id="gpt-5.4"),
        **shared,
    }

    with (
        _patch_review_services(services),
        patch("ces.cli.review_cmd.WorkflowEngine", return_value=AsyncMock(submit_for_review=AsyncMock())),
        patch(
            "ces.harness.services.diff_extractor.DiffExtractor.extract_diff",
            new=AsyncMock(return_value=_MOCK_DIFF_CONTEXT),
        ),
    ):
        result = runner.invoke(_get_app(), ["--json", "review"])

    assert result.exit_code == 0, f"stdout={result.stdout}"
    payload = json.loads(result.stdout)
    assert payload["builder_run"]["request"] == "Build a habit tracker"
    assert payload["builder_run"]["manifest_id"] == "M-builder-123"


def test_triage_without_evidence_id_uses_current_builder_snapshot(ces_project, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ces_project)
    manifest, shared = _make_builder_snapshot()
    manager = AsyncMock()
    manager.get_manifest = AsyncMock(return_value=manifest)
    synth = MagicMock()
    synth.triage = AsyncMock(return_value=_make_triage_decision())
    sensor_orchestrator = AsyncMock(run_all=AsyncMock(return_value=[]))
    services = {
        "manifest_manager": manager,
        "evidence_synthesizer": synth,
        "sensor_orchestrator": sensor_orchestrator,
        **shared,
    }

    with _patch_triage_services(services):
        result = runner.invoke(_get_app(), ["triage"])

    assert result.exit_code == 0, f"stdout={result.stdout}"
    manager.get_manifest.assert_awaited_once_with("M-builder-123")


def test_triage_json_includes_builder_run_context(ces_project, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ces_project)
    manifest, shared = _make_builder_snapshot()
    manager = AsyncMock()
    manager.get_manifest = AsyncMock(return_value=manifest)
    synth = MagicMock()
    synth.triage = AsyncMock(return_value=_make_triage_decision())
    sensor_orchestrator = AsyncMock(run_all=AsyncMock(return_value=[]))
    services = {
        "manifest_manager": manager,
        "evidence_synthesizer": synth,
        "sensor_orchestrator": sensor_orchestrator,
        **shared,
    }

    with _patch_triage_services(services):
        result = runner.invoke(_get_app(), ["--json", "triage"])

    assert result.exit_code == 0, f"stdout={result.stdout}"
    payload = json.loads(result.stdout)
    assert payload["builder_run"]["request"] == "Build a habit tracker"
    assert payload["builder_run"]["evidence_packet_id"] == "EP-builder-123"


def test_approve_without_evidence_id_uses_current_builder_snapshot(
    ces_project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(ces_project)
    manifest, shared = _make_builder_snapshot()
    manager = AsyncMock()
    manager.get_manifest = AsyncMock(return_value=manifest)
    synth = MagicMock()
    synth.triage = AsyncMock(return_value=_make_triage_decision())
    synth.format_summary_slots = AsyncMock(return_value=SimpleNamespace(summary="Line 1", challenge="Challenge"))
    services = {
        "manifest_manager": manager,
        "evidence_synthesizer": synth,
        "audit_ledger": AsyncMock(record_approval=AsyncMock()),
        "merge_controller": AsyncMock(
            validate_merge=AsyncMock(return_value=SimpleNamespace(allowed=True, reason="", checks=[]))
        ),
        "sensor_orchestrator": AsyncMock(run_all=AsyncMock(return_value=[])),
        "provider_registry": MagicMock(get_provider=MagicMock(side_effect=KeyError("no provider"))),
        "settings": MagicMock(default_model_id="gpt-5.4"),
        **shared,
    }
    workflow = AsyncMock(
        complete_review=AsyncMock(),
        approve_merge=AsyncMock(),
    )

    with _patch_approve_services(services), patch("ces.cli.approve_cmd.WorkflowEngine", return_value=workflow):
        result = runner.invoke(_get_app(), ["approve", "--yes"])

    assert result.exit_code == 0, f"stdout={result.stdout}"
    manager.get_manifest.assert_awaited_once_with("M-builder-123")


def test_approve_json_includes_builder_run_context(ces_project, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ces_project)
    manifest, shared = _make_builder_snapshot()
    manager = AsyncMock()
    manager.get_manifest = AsyncMock(return_value=manifest)
    synth = MagicMock()
    synth.triage = AsyncMock(return_value=_make_triage_decision())
    synth.format_summary_slots = AsyncMock(return_value=SimpleNamespace(summary="Line 1", challenge="Challenge"))
    services = {
        "manifest_manager": manager,
        "evidence_synthesizer": synth,
        "audit_ledger": AsyncMock(record_approval=AsyncMock()),
        "merge_controller": AsyncMock(
            validate_merge=AsyncMock(return_value=SimpleNamespace(allowed=True, reason="", checks=[]))
        ),
        "sensor_orchestrator": AsyncMock(run_all=AsyncMock(return_value=[])),
        "provider_registry": MagicMock(get_provider=MagicMock(side_effect=KeyError("no provider"))),
        "settings": MagicMock(default_model_id="gpt-5.4"),
        **shared,
    }
    workflow = AsyncMock(
        complete_review=AsyncMock(),
        approve_merge=AsyncMock(),
    )

    with _patch_approve_services(services), patch("ces.cli.approve_cmd.WorkflowEngine", return_value=workflow):
        result = runner.invoke(_get_app(), ["--json", "approve", "--yes"])

    assert result.exit_code == 0, f"stdout={result.stdout}"
    payload = json.loads(result.stdout)
    assert payload["builder_run"]["request"] == "Build a habit tracker"
    assert payload["builder_run"]["manifest_id"] == "M-builder-123"


def test_resolve_manifest_id_maps_non_latest_evidence_packet_id() -> None:
    local_store = MagicMock()
    local_store.get_latest_builder_session_snapshot.return_value = None
    local_store.get_evidence_by_packet_id.return_value = {
        "manifest_id": "M-older-123",
        "packet_id": "EP-older-123",
    }

    manifest_id, context = resolve_manifest_id(
        provided_ref="EP-older-123",
        local_store=local_store,
        missing_message="missing",
    )

    assert manifest_id == "M-older-123"
    assert context is None
