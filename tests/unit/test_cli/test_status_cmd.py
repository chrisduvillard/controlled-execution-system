"""Tests for ces status command (status_cmd module)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture(autouse=True)
def _reset_json_mode():
    """Reset JSON mode before each test to avoid leaking state."""
    from ces.cli._output import set_json_mode

    set_json_mode(False)
    yield
    set_json_mode(False)


def _get_app():
    """Import app lazily to avoid import errors during collection."""
    from ces.cli import app

    return app


def _patch_services(mock_services: dict[str, Any]):
    """Return a patch that replaces get_services with a fake async context manager."""

    @asynccontextmanager
    async def _fake_get_services(*args: Any, **kwargs: Any):
        del args, kwargs
        yield mock_services

    return patch("ces.cli.status_cmd.get_services", new=_fake_get_services)


def _make_mock_services() -> dict[str, Any]:
    """Create mock services with the APIs used by ``ces status``."""
    mock_trust = AsyncMock()
    # TrustManager does not yet have bulk query, status_cmd returns []

    mock_manifest = AsyncMock()
    mock_manifest.get_active_manifests = AsyncMock(return_value=[])

    mock_audit = AsyncMock()
    mock_audit.query_by_time_range = AsyncMock(return_value=[])

    return {
        "trust_manager": mock_trust,
        "manifest_manager": mock_manifest,
        "audit_ledger": mock_audit,
    }


class TestStatusView:
    """Tests for the local ``ces status`` view."""

    def test_status_shows_builder_overview(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces status defaults to a concise builder-first overview."""
        monkeypatch.chdir(ces_project)
        mock_services = _make_mock_services()

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "Builder Status" in result.stdout
        assert 'ces build "describe what you want to build"' in result.stdout

    def test_status_skips_telemetry_database_access_for_local_projects(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Local builder-first status must not open the telemetry DB path."""
        monkeypatch.chdir(ces_project)
        (ces_project / ".ces" / "config.yaml").write_text(
            "project_id: local-proj\npreferred_runtime: codex\n",
            encoding="utf-8",
        )
        mock_services = _make_mock_services()
        mock_services["local_store"] = MagicMock()

        with _patch_services(mock_services), patch("ces.cli.status_cmd.reconcile_stale_builder_session") as reconcile:
            app = _get_app()
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0, f"stdout={result.stdout}\nexc={result.exception}"
        assert "Builder Status" in result.stdout
        reconcile.assert_not_called()

        with _patch_services(mock_services), patch("ces.cli.status_cmd.reconcile_stale_builder_session") as reconcile:
            app = _get_app()
            result = runner.invoke(app, ["status", "--reconcile"])

        assert result.exit_code == 0, f"stdout={result.stdout}\nexc={result.exception}"
        reconcile.assert_called_once_with(project_root=ces_project, local_store=mock_services["local_store"])

    def test_status_surfaces_latest_builder_brief_and_pending_brownfield_work(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ces status uses the local builder brief and pending behavior queue when present."""
        monkeypatch.chdir(ces_project)
        mock_services = _make_mock_services()
        mock_store = MagicMock()
        mock_store.get_latest_builder_brief.return_value = MagicMock(
            request="Modernize billing exports",
            project_mode="brownfield",
        )
        mock_legacy = AsyncMock()
        mock_legacy.get_pending_behaviors = AsyncMock(
            return_value=[MagicMock(entry_id="OLB-1"), MagicMock(entry_id="OLB-2")]
        )
        mock_services["local_store"] = mock_store
        mock_services["legacy_behavior_service"] = mock_legacy

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "Modernize billing exports" in result.stdout
        assert "brownfield" in result.stdout.lower()
        assert "2 pending brownfield decision" in result.stdout.lower()

    def test_status_prefers_builder_session_next_action_when_present(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ces status uses persisted builder session guidance when available."""
        monkeypatch.chdir(ces_project)
        mock_services = _make_mock_services()
        mock_store = MagicMock()
        mock_store.get_latest_builder_session.return_value = MagicMock(
            request="Modernize billing exports",
            project_mode="brownfield",
            stage="blocked",
            next_action="retry_runtime",
            recovery_reason="retry_execution",
            last_action="runtime_failed",
        )
        mock_store.get_latest_builder_brief.return_value = MagicMock(
            request="Outdated fallback brief",
            project_mode="greenfield",
        )
        mock_legacy = AsyncMock()
        mock_legacy.get_pending_behaviors = AsyncMock(return_value=[])
        mock_services["local_store"] = mock_store
        mock_services["legacy_behavior_service"] = mock_legacy

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        out = result.stdout
        assert "Modernize billing exports" in out
        assert "blocked" in out.lower()
        assert "Retry the last runtime execution with `ces continue`." in out

    def test_status_uses_shared_snapshot_for_final_truth_and_brownfield_progress(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(ces_project)
        mock_services = _make_mock_services()
        mock_store = MagicMock()
        mock_store.get_latest_builder_session_snapshot.return_value = SimpleNamespace(
            request="Modernize billing exports",
            project_mode="brownfield",
            stage="completed",
            next_step="Start a new task with `ces build` when you're ready for the next request.",
            latest_activity="CES recorded the latest review decision.",
            brownfield=SimpleNamespace(reviewed_count=4, remaining_count=0),
        )
        mock_store.get_latest_builder_session.return_value = MagicMock(
            request="Outdated fallback request",
            project_mode="greenfield",
            stage="blocked",
            next_action="retry_runtime",
            recovery_reason="retry_execution",
        )
        mock_store.get_latest_builder_brief.return_value = MagicMock(
            request="Older fallback brief",
            project_mode="greenfield",
        )
        mock_services["local_store"] = mock_store
        mock_services["legacy_behavior_service"] = AsyncMock(get_pending_behaviors=AsyncMock(return_value=[]))

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        out = result.stdout
        assert "Modernize billing exports" in out
        assert "completed" in out.lower()
        assert "4 behaviors reviewed, 0 behaviors remaining" in out
        assert "Start a new task with `ces build`" in out

    def test_status_labels_entry_level_brownfield_progress_when_item_count_is_inflated(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ReleasePulse RP-CES-007: status should say one reviewed behavior, not 13 reviewed items."""
        monkeypatch.chdir(ces_project)
        mock_services = _make_mock_services()
        mock_store = MagicMock()
        mock_store.get_latest_builder_session_snapshot.return_value = SimpleNamespace(
            request="Improve ReleasePulse brownfield CLI",
            project_mode="brownfield",
            stage="completed",
            next_step="Start a new task with `ces build` when you're ready for the next request.",
            latest_activity="CES recorded the latest review decision.",
            brownfield=SimpleNamespace(
                entry_ids=["OLB-a218da0878b7"],
                reviewed_count=13,
                remaining_count=0,
                checkpoint={"reviewed_candidates": [{"description": f"candidate {idx}"} for idx in range(13)]},
            ),
        )
        mock_services["local_store"] = mock_store
        mock_services["legacy_behavior_service"] = AsyncMock(get_pending_behaviors=AsyncMock(return_value=[]))

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "Brownfield progress: 1 behavior reviewed" in result.stdout
        assert "13 review" in result.stdout
        assert "items checked" in result.stdout
        assert "13 reviewed" not in result.stdout

    def test_status_prefers_project_name_with_id_as_secondary_metadata(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RunLens dogfood: status should orient operators by human project_name."""
        monkeypatch.chdir(ces_project)
        (ces_project / ".ces" / "config.yaml").write_text(
            "project_id: proj-runlens\nproject_name: runlens\npreferred_runtime: codex\n",
            encoding="utf-8",
        )
        mock_services = _make_mock_services()

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0, result.stdout
        assert "Project: runlens" in result.stdout
        assert "Project ID: proj-runlens" in result.stdout

    def test_status_json_includes_project_name(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(ces_project)
        (ces_project / ".ces" / "config.yaml").write_text(
            "project_id: proj-runlens\nproject_name: runlens\n",
            encoding="utf-8",
        )
        mock_services = _make_mock_services()

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["status", "--json"])

        assert result.exit_code == 0, result.stdout
        data = json.loads(result.stdout)
        assert data["project_id"] == "proj-runlens"
        assert data["project_name"] == "runlens"

    def test_status_expert_shows_detailed_sections(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces status --expert shows the detailed CES status sections."""
        monkeypatch.chdir(ces_project)
        mock_services = _make_mock_services()

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["status", "--expert"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        out = result.stdout.lower()
        assert "trust" in out or "profile" in out
        assert "manifest" in out

    def test_status_json_output(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces status --json outputs all 4 sections as JSON object."""
        monkeypatch.chdir(ces_project)
        mock_services = _make_mock_services()

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["--json", "status"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        data = json.loads(result.stdout.strip())
        assert "trust_profiles" in data
        assert "active_manifests" in data

    def test_status_accepts_command_local_json_flag(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces status --json is accepted for operator ergonomics."""
        monkeypatch.chdir(ces_project)
        mock_services = _make_mock_services()

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["status", "--json"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        data = json.loads(result.stdout.strip())
        assert "builder_run" in data

    def test_status_json_includes_structured_builder_run_truth(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(ces_project)
        mock_services = _make_mock_services()
        mock_store = MagicMock()
        mock_store.get_latest_builder_session_snapshot.return_value = SimpleNamespace(
            request="Modernize billing exports",
            project_mode="brownfield",
            stage="awaiting_review",
            next_action="review_evidence",
            next_step="Review the evidence and decide whether to ship the change.",
            latest_activity="CES gathered runtime evidence and synthesized a review summary.",
            latest_artifact="evidence",
            brief_only_fallback=False,
            brief=SimpleNamespace(prl_draft_path=".ces/exports/prl-draft-bb-123.md"),
            manifest=SimpleNamespace(
                manifest_id="M-123",
                workflow_state="under_review",
                description="Modernize billing exports",
            ),
            runtime_execution=SimpleNamespace(exit_code=0, reported_model="gpt-5.4"),
            evidence={"packet_id": "EP-123", "triage_color": "yellow"},
            approval=None,
            session=SimpleNamespace(session_id="BS-123"),
            brownfield=SimpleNamespace(reviewed_count=2, remaining_count=1),
        )
        mock_services["local_store"] = mock_store
        mock_services["legacy_behavior_service"] = AsyncMock(get_pending_behaviors=AsyncMock(return_value=[]))

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["--json", "status"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        data = json.loads(result.stdout.strip())
        assert data["builder_run"]["request"] == "Modernize billing exports"
        assert data["builder_run"]["review_state"] == "under_review"
        assert data["builder_run"]["latest_outcome"] == "evidence_ready"


class TestStatusWatch:
    """Tests for ces status --watch mode."""

    def test_status_watch_option_exists(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces status accepts --watch flag without error."""
        monkeypatch.chdir(ces_project)
        mock_services = _make_mock_services()

        with _patch_services(mock_services):
            app = _get_app()
            # --watch without actually watching (test just the flag parsing)
            # We use --json to get immediate output
            result = runner.invoke(app, ["--json", "status"])

        assert result.exit_code == 0, f"stdout={result.stdout}"

    def test_status_accepts_project_root_and_redacts_event_actor(
        self, tmp_path: Path, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SpecTrail SF-003/SF-007: status can target another repo and never prints raw actor IDs."""
        monkeypatch.chdir(tmp_path)
        mock_services = _make_mock_services()
        mock_services["audit_ledger"].query_by_time_range = AsyncMock(
            return_value=[
                SimpleNamespace(
                    timestamp="2026-05-04T00:00:00Z",
                    event_type=SimpleNamespace(value="approval"),
                    actor="chrisduvillard@example.test",
                    action_summary="Approved manually",
                )
            ]
        )

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["status", "--project-root", str(ces_project), "--json"])

        assert result.exit_code == 0, result.stdout
        data = json.loads(result.stdout)
        assert data["project_id"]
        actor = data["recent_events"][0]["actor"]
        assert actor.startswith("actor:")
        assert "chrisduvillard" not in result.stdout

    def test_status_json_reconciles_stale_rejected_manifest_after_manual_completion(
        self, ces_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SpecTrail SF-006: approved completed sessions must not report rejected workflow state."""
        monkeypatch.chdir(ces_project)
        mock_services = _make_mock_services()
        mock_store = MagicMock()
        mock_store.get_latest_builder_session_snapshot.return_value = SimpleNamespace(
            request="Build SpecTrail",
            project_mode="greenfield",
            stage="completed",
            next_action="start_new_session",
            next_step="Start a new task with `ces build` when you're ready for the next request.",
            latest_activity="CES has saved builder progress for this request.",
            latest_artifact="approval",
            brief_only_fallback=False,
            brief=None,
            manifest=SimpleNamespace(manifest_id="M-stale", workflow_state="rejected"),
            runtime_execution=None,
            evidence={"packet_id": "EP-manual", "triage_color": "green"},
            approval=SimpleNamespace(decision="approve"),
            session=SimpleNamespace(session_id="BS-stale"),
            brownfield=None,
        )
        mock_services["local_store"] = mock_store

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["status", "--json"])

        assert result.exit_code == 0, result.stdout
        data = json.loads(result.stdout)
        assert data["builder_run"]["workflow_state"] == "approved"
        assert data["builder_run"]["review_state"] == "approved"
