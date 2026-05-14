"""Tests for manual builder-session completion/reconciliation."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from ces.shared.enums import WorkflowState

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


def test_complete_scrubs_secret_like_manual_evidence_before_persistence(tmp_path: Path, monkeypatch: object) -> None:
    """Manual completion evidence should not persist raw token-looking values."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    ces_dir = tmp_path / ".ces"
    ces_dir.mkdir()
    (ces_dir / "config.yaml").write_text("project_id: local-proj\n", encoding="utf-8")
    secret = "sk" + "-" + "syntheticManualEvidenceSecret123"
    evidence = tmp_path / "verification.txt"
    evidence.write_text(f"pytest passed\nOPENAI_API_KEY={secret}\nraw={secret}\n", encoding="utf-8")
    session = SimpleNamespace(
        session_id="BS-secret",
        runtime_manifest_id="M-secret",
        manifest_id="M-secret",
        evidence_packet_id=None,
        stage="blocked",
    )
    mock_store = MagicMock()
    mock_store.get_latest_builder_session.return_value = session
    mock_services = {"local_store": mock_store, "audit_ledger": AsyncMock()}

    with _patch_services(mock_services):
        result = runner.invoke(_get_app(), ["complete", "--evidence", str(evidence), "--yes"])

    assert result.exit_code == 0, result.stdout
    saved_content = mock_store.save_evidence.call_args.kwargs["content"]
    assert secret not in saved_content["evidence_text"]
    assert "<REDACTED>" in saved_content["evidence_text"]


def test_complete_caps_large_manual_evidence_before_persistence(tmp_path: Path, monkeypatch: object) -> None:
    """Manual completion evidence should be bounded before writing to state.db."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    ces_dir = tmp_path / ".ces"
    ces_dir.mkdir()
    (ces_dir / "config.yaml").write_text("project_id: local-proj\n", encoding="utf-8")
    evidence = tmp_path / "large-verification.txt"
    evidence.write_text("A" * (1_048_576 + 128), encoding="utf-8")
    session = SimpleNamespace(
        session_id="BS-large",
        runtime_manifest_id="M-large",
        manifest_id="M-large",
        evidence_packet_id=None,
        stage="blocked",
    )
    mock_store = MagicMock()
    mock_store.get_latest_builder_session.return_value = session
    mock_services = {"local_store": mock_store, "audit_ledger": AsyncMock()}

    with _patch_services(mock_services):
        result = runner.invoke(_get_app(), ["complete", "--evidence", str(evidence), "--yes"])

    assert result.exit_code == 0, result.stdout
    saved_text = mock_store.save_evidence.call_args.kwargs["content"]["evidence_text"]
    assert len(saved_text) < 1_049_000
    assert "[truncated manual evidence]" in saved_text


def test_complete_blocks_external_manual_evidence_without_explicit_consent(tmp_path: Path, monkeypatch: object) -> None:
    """Evidence outside the project root should require explicit operator consent."""
    project = tmp_path / "project"
    project.mkdir()
    ces_dir = project / ".ces"
    ces_dir.mkdir()
    (ces_dir / "config.yaml").write_text("project_id: local-proj\n", encoding="utf-8")
    evidence = tmp_path / "external-verification.txt"
    evidence.write_text("pytest passed\n", encoding="utf-8")
    monkeypatch.chdir(project)  # type: ignore[attr-defined]
    session = SimpleNamespace(
        session_id="BS-external",
        runtime_manifest_id="M-external",
        manifest_id="M-external",
        evidence_packet_id=None,
        stage="blocked",
    )
    mock_store = MagicMock()
    mock_store.get_latest_builder_session.return_value = session
    mock_services = {"local_store": mock_store, "audit_ledger": AsyncMock()}

    with _patch_services(mock_services):
        result = runner.invoke(_get_app(), ["complete", "--evidence", str(evidence), "--yes"])

    assert result.exit_code != 0
    mock_store.save_evidence.assert_not_called()


def test_complete_allows_external_manual_evidence_with_explicit_consent(tmp_path: Path, monkeypatch: object) -> None:
    """Explicit consent keeps external evidence available for recovery workflows."""
    project = tmp_path / "project"
    project.mkdir()
    ces_dir = project / ".ces"
    ces_dir.mkdir()
    (ces_dir / "config.yaml").write_text("project_id: local-proj\n", encoding="utf-8")
    evidence = tmp_path / "external-verification.txt"
    evidence.write_text("pytest passed\n", encoding="utf-8")
    monkeypatch.chdir(project)  # type: ignore[attr-defined]
    session = SimpleNamespace(
        session_id="BS-external-ok",
        runtime_manifest_id="M-external-ok",
        manifest_id="M-external-ok",
        evidence_packet_id=None,
        stage="blocked",
    )
    mock_store = MagicMock()
    mock_store.get_latest_builder_session.return_value = session
    mock_services = {"local_store": mock_store, "audit_ledger": AsyncMock()}

    with _patch_services(mock_services):
        result = runner.invoke(
            _get_app(),
            ["complete", "--evidence", str(evidence), "--allow-external-evidence", "--yes"],
        )

    assert result.exit_code == 0, result.stdout
    mock_store.save_evidence.assert_called_once()


def test_complete_with_real_local_store_saves_manual_evidence_without_crashing(
    tmp_path: Path, monkeypatch: object
) -> None:
    """RunLens dogfood regression: real LocalProjectStore.save_evidence has no findings kwarg."""
    from ces.local_store.store import LocalProjectStore

    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    ces_dir = tmp_path / ".ces"
    ces_dir.mkdir()
    (ces_dir / "config.yaml").write_text("project_id: local-proj\n", encoding="utf-8")
    evidence = tmp_path / "verification.md"
    evidence.write_text("pytest passed\nruff passed\n", encoding="utf-8")

    store = LocalProjectStore(ces_dir / "state.db", project_id="local-proj")
    session_id = store.save_builder_session(
        brief_id=None,
        request="Build RunLens",
        project_mode="greenfield",
        stage="blocked",
        next_action="review_evidence",
        last_action="approval_rejected",
        manifest_id="M-runlens",
        runtime_manifest_id="M-runlens",
    )
    store.save_evidence(
        "M-runlens",
        packet_id="EP-runtime-failed",
        summary="Runtime evidence failed verification.",
        challenge="Criteria missing.",
        triage_color="red",
        content={
            "runtime_safety": {"tool_allowlist_enforced": False},
            "verification_result": {
                "passed": False,
                "findings": [{"message": "Acceptance criterion has no evidence: 'export works'"}],
            },
        },
    )
    mock_services = {"local_store": store, "audit_ledger": AsyncMock()}

    with _patch_services(mock_services):
        app = _get_app()
        result = runner.invoke(app, ["complete", "--evidence", str(evidence), "--yes"])

    try:
        assert result.exit_code == 0, f"stdout={result.stdout} exc={result.exception}"
        session = store.get_builder_session(session_id)
        assert session is not None
        assert session.stage == "completed"
        assert session.evidence_packet_id == f"EP-manual-{session_id}"
        packet = store.get_evidence_by_packet_id(f"EP-manual-{session_id}")
        assert packet is not None
        assert packet["manual_completion"] is True
        assert "pytest passed" in packet["evidence_text"]
        assert packet["superseded_evidence"]["packet_id"] == "EP-runtime-failed"
        assert packet["superseded_evidence"]["verification_result"]["passed"] is False
    finally:
        store.close()


def test_complete_reconciles_manifest_approval_through_workflow_engine(tmp_path: Path, monkeypatch: object) -> None:
    """Manual completion must use the workflow service, not direct state writes."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    ces_dir = tmp_path / ".ces"
    ces_dir.mkdir()
    (ces_dir / "config.yaml").write_text("project_id: local-proj\n", encoding="utf-8")
    session = SimpleNamespace(
        session_id="BS-approved",
        runtime_manifest_id="M-approved",
        manifest_id="M-approved",
        evidence_packet_id="EP-existing",
        stage="blocked",
    )
    manifest = MagicMock(workflow_state="under_review")
    approved_manifest = MagicMock()
    manifest.model_copy.return_value = approved_manifest
    manifest_manager = AsyncMock()
    manifest_manager.get_manifest = AsyncMock(return_value=manifest)
    manifest_manager.save_manifest = AsyncMock()
    mock_store = MagicMock()
    mock_store.get_latest_builder_session.return_value = session
    mock_services = {
        "local_store": mock_store,
        "manifest_manager": manifest_manager,
        "audit_ledger": AsyncMock(),
    }

    mock_engine = AsyncMock()
    mock_engine.reconcile_manual_completion = AsyncMock(return_value=WorkflowState.APPROVED)
    with (
        _patch_services(mock_services),
        patch("ces.cli.complete_cmd.WorkflowEngine", return_value=mock_engine) as workflow_cls,
    ):
        app = _get_app()
        result = runner.invoke(app, ["complete", "--yes"])

    assert result.exit_code == 0, result.stdout
    workflow_cls.assert_called_once()
    mock_engine.reconcile_manual_completion.assert_awaited_once()
    manifest.model_copy.assert_called_once()
    kwargs = manifest.model_copy.call_args.kwargs["update"]
    assert str(kwargs["workflow_state"].value) == "approved"
    manifest_manager.save_manifest.assert_awaited_once_with(approved_manifest)


def test_complete_accepts_project_root_from_outside_target(tmp_path: Path) -> None:
    """TaskLedger dogfood: source-checkout users can complete a separate target via --project-root."""
    project = tmp_path / "target"
    project.mkdir()
    ces_dir = project / ".ces"
    ces_dir.mkdir()
    (ces_dir / "config.yaml").write_text("project_id: local-proj\n", encoding="utf-8")

    session = SimpleNamespace(
        session_id="BS-target",
        runtime_manifest_id="M-target",
        manifest_id="M-target",
        evidence_packet_id="EP-existing",
        stage="blocked",
    )
    mock_store = MagicMock()
    mock_store.get_latest_builder_session.return_value = session
    mock_services = {"local_store": mock_store, "audit_ledger": AsyncMock()}

    with _patch_services(mock_services):
        result = runner.invoke(_get_app(), ["complete", "--project-root", str(project), "--yes"])

    assert result.exit_code == 0, result.stdout
    assert mock_services["_get_services_calls"][0]["kwargs"] == {"project_root": project.resolve()}
    mock_store.update_builder_session.assert_called_once()
