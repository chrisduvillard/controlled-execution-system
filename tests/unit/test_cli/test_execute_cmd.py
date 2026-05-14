"""Tests for the local-only ``ces execute`` command."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
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
    async def _fake_get_services():
        yield mock_services

    return patch("ces.cli.execute_cmd.get_services", new=_fake_get_services)


class TestExecuteLocalMode:
    def test_execute_local_mode_uses_runtime_adapter(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        runtime_result = {
            "runtime_name": "codex",
            "runtime_version": "1.0.0",
            "reported_model": None,
            "invocation_ref": "run-123",
            "exit_code": 0,
            "stdout": "Implemented change",
            "stderr": "",
            "duration_seconds": 1.2,
        }
        mock_runtime = MagicMock(runtime_name="codex")
        mock_runner = AsyncMock()
        mock_runner.execute_runtime = AsyncMock(return_value=runtime_result)
        mock_runtime_registry = MagicMock()
        mock_runtime_registry.resolve_runtime.return_value = mock_runtime
        mock_manifest = MagicMock(
            manifest_id="M-local", description="Build cool thing", workflow_state=WorkflowState.IN_FLIGHT
        )

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "audit_ledger": AsyncMock(),
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "manifest_manager": AsyncMock(get_manifest=AsyncMock(return_value=mock_manifest)),
            "local_store": MagicMock(save_runtime_execution=MagicMock()),
        }

        with _patch_services(mock_services), patch("ces.cli.execute_cmd.WorkflowEngine", return_value=AsyncMock()):
            result = runner.invoke(
                _get_app(),
                ["execute", "M-local", "--runtime", "auto", "--accept-runtime-side-effects"],
            )

        assert result.exit_code == 0, result.stdout
        mock_runtime_registry.resolve_runtime.assert_called_once_with(runtime_name="auto", preferred_runtime="codex")
        mock_runner.execute_runtime.assert_awaited_once()
        mock_services["local_store"].save_runtime_execution.assert_called_once()

    def test_execute_blocks_unsafe_runtime_before_launch_without_explicit_consent(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        mock_runtime = MagicMock(runtime_name="codex")
        mock_runner = AsyncMock()
        mock_runner.execute_runtime = AsyncMock()
        mock_runtime_registry = MagicMock()
        mock_runtime_registry.resolve_runtime.return_value = mock_runtime
        mock_manifest = MagicMock(
            manifest_id="M-local", description="Build cool thing", workflow_state=WorkflowState.IN_FLIGHT
        )
        mock_manager = AsyncMock(get_manifest=AsyncMock(return_value=mock_manifest))

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "audit_ledger": AsyncMock(),
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "manifest_manager": mock_manager,
            "local_store": MagicMock(save_runtime_execution=MagicMock()),
        }

        with _patch_services(mock_services), patch("ces.cli.execute_cmd.WorkflowEngine", return_value=AsyncMock()):
            result = runner.invoke(_get_app(), ["execute", "M-local", "--runtime", "auto"])

        assert result.exit_code != 0
        assert "requires explicit runtime side-effect consent" in result.stdout
        assert "--accept-runtime-side-effects" in result.stdout
        mock_runtime_registry.resolve_runtime.assert_called_once_with(runtime_name="auto", preferred_runtime="codex")
        mock_runner.execute_runtime.assert_not_awaited()
        mock_manager.save_manifest.assert_not_awaited()

    def test_execute_json_output_serializes_runtime_result(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: claude\n")

        mock_runtime = MagicMock(runtime_name="claude")
        mock_runner = AsyncMock()
        mock_runner.execute_runtime = AsyncMock(
            return_value={
                "runtime_name": "claude",
                "runtime_version": "1.0.0",
                "reported_model": None,
                "invocation_ref": "run-json",
                "exit_code": 0,
                "stdout": "done",
                "stderr": "",
                "duration_seconds": 0.7,
            }
        )
        mock_runtime_registry = MagicMock(resolve_runtime=MagicMock(return_value=mock_runtime))
        mock_manifest = MagicMock(
            manifest_id="M-json", description="Do the thing", workflow_state=WorkflowState.IN_FLIGHT
        )

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "audit_ledger": AsyncMock(),
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "manifest_manager": AsyncMock(get_manifest=AsyncMock(return_value=mock_manifest)),
            "local_store": MagicMock(save_runtime_execution=MagicMock()),
        }

        with _patch_services(mock_services), patch("ces.cli.execute_cmd.WorkflowEngine", return_value=AsyncMock()):
            result = runner.invoke(_get_app(), ["--json", "execute", "M-json"])

        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        assert payload["runtime_name"] == "claude"
        assert payload["invocation_ref"] == "run-json"

    def test_local_execute_persists_in_flight_transition_from_queued(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        mock_runtime = MagicMock(runtime_name="codex")
        mock_runner = AsyncMock()
        mock_runner.execute_runtime = AsyncMock(
            return_value={
                "runtime_name": "codex",
                "runtime_version": "1.0.0",
                "reported_model": None,
                "invocation_ref": "run-queued",
                "exit_code": 0,
                "stdout": "done",
                "stderr": "",
                "duration_seconds": 1.2,
            }
        )
        mock_runtime_registry = MagicMock(resolve_runtime=MagicMock(return_value=mock_runtime))
        mock_manifest = MagicMock(
            manifest_id="M-local", description="Build cool thing", workflow_state=WorkflowState.QUEUED
        )
        mock_manager = AsyncMock(get_manifest=AsyncMock(return_value=mock_manifest))

        mock_engine = AsyncMock()
        mock_engine.start = AsyncMock(return_value=WorkflowState.IN_FLIGHT)

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "audit_ledger": AsyncMock(),
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "manifest_manager": mock_manager,
            "local_store": MagicMock(save_runtime_execution=MagicMock()),
        }

        with _patch_services(mock_services), patch("ces.cli.execute_cmd.WorkflowEngine", return_value=mock_engine):
            result = runner.invoke(_get_app(), ["execute", "M-local", "--accept-runtime-side-effects"])

        assert result.exit_code == 0, result.stdout
        mock_engine.start.assert_awaited_once()
        mock_manager.save_manifest.assert_awaited_once()

    def test_local_execute_rejects_invalid_manifest_workflow_state(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        mock_manifest = MagicMock(
            manifest_id="M-local",
            description="Build cool thing",
            workflow_state=WorkflowState.UNDER_REVIEW,
        )
        mock_manager = AsyncMock(get_manifest=AsyncMock(return_value=mock_manifest))

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "audit_ledger": AsyncMock(),
            "runtime_registry": MagicMock(),
            "agent_runner": AsyncMock(),
            "manifest_manager": mock_manager,
            "local_store": MagicMock(save_runtime_execution=MagicMock()),
        }

        with _patch_services(mock_services), patch("ces.cli.execute_cmd.WorkflowEngine", return_value=AsyncMock()):
            result = runner.invoke(_get_app(), ["execute", "M-local"])

        assert result.exit_code != 0, result.stdout
        assert "must be queued or in_flight" in result.stdout

    def test_server_mode_projects_fail_with_migration_message(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\nexecution_mode: server\n")

        result = runner.invoke(_get_app(), ["execute", "M-local"])

        assert result.exit_code != 0, result.stdout
        assert "server mode is no longer supported" in result.stdout


# ---------------------------------------------------------------------------
# Completion Gate wiring (P-CLI)
# ---------------------------------------------------------------------------


def _agent_run_result_with_claim(claim_dict: dict | None):
    """Return an AgentRunResult whose runtime_result holds the given claim (or None)."""
    from ces.execution.agent_runner import AgentRunResult
    from ces.execution.runtimes.protocol import AgentRuntimeResult
    from ces.harness.models.completion_claim import CompletionClaim

    completion_claim = CompletionClaim(**claim_dict) if claim_dict is not None else None
    runtime_result = AgentRuntimeResult(
        runtime_name="codex",
        runtime_version="1.0.0",
        reported_model=None,
        invocation_ref="gate-run",
        exit_code=0,
        stdout="ok",
        stderr="",
        duration_seconds=0.5,
        completion_claim=completion_claim,
    )
    return AgentRunResult(runtime_result=runtime_result)


class _StubVerifier:
    """Records the call and returns a configured VerificationResult.

    Pass a list of results to ``payloads`` to simulate a sequence of verify()
    calls (used by the auto-repair loop tests). Otherwise returns
    ``result_payload`` for every call.
    """

    def __init__(self, result_payload=None, payloads: list | None = None):
        self.result_payload = result_payload
        self._payloads = list(payloads) if payloads is not None else None
        self.verify_calls: list[tuple[Any, Any, Path]] = []

    async def verify(self, manifest, claim, project_root):
        self.verify_calls.append((manifest, claim, project_root))
        if self._payloads is not None:
            return self._payloads.pop(0)
        return self.result_payload


class TestCompletionGateWiring:
    def test_gate_passes_advances_to_under_review(self, tmp_path: Path, monkeypatch) -> None:
        from datetime import datetime, timezone

        from ces.harness.models.completion_claim import VerificationResult

        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        mock_runtime = MagicMock(runtime_name="codex")
        run_result = _agent_run_result_with_claim(
            {
                "task_id": "M-gate",
                "summary": "did it",
                "files_changed": ("src/auth/login.py",),
            }
        )
        mock_runner = AsyncMock()
        mock_runner.execute_runtime = AsyncMock(return_value=run_result)
        mock_runtime_registry = MagicMock(resolve_runtime=MagicMock(return_value=mock_runtime))

        mock_manifest = MagicMock(
            manifest_id="M-gate",
            description="Build",
            workflow_state=WorkflowState.IN_FLIGHT,
            verification_sensors=("test_pass",),
        )
        mock_manager = AsyncMock(get_manifest=AsyncMock(return_value=mock_manifest))

        mock_engine = AsyncMock()
        mock_engine.submit_for_verification = AsyncMock(return_value=WorkflowState.VERIFYING)
        mock_engine.verification_passed = AsyncMock(return_value=WorkflowState.UNDER_REVIEW)

        verifier = _StubVerifier(
            VerificationResult(passed=True, findings=(), sensor_results=(), timestamp=datetime.now(timezone.utc))
        )
        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "audit_ledger": AsyncMock(),
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "manifest_manager": mock_manager,
            "local_store": MagicMock(save_runtime_execution=MagicMock()),
            "completion_verifier": verifier,
        }

        with _patch_services(mock_services), patch("ces.cli.execute_cmd.WorkflowEngine", return_value=mock_engine):
            result = runner.invoke(_get_app(), ["execute", "M-gate", "--accept-runtime-side-effects"])

        assert result.exit_code == 0, result.stdout
        # Panel wrapping may break the message mid-phrase; check for stable substrings
        assert "Completion gate passed" in result.stdout
        mock_engine.submit_for_verification.assert_awaited_once()
        mock_engine.verification_passed.assert_awaited_once()
        assert len(verifier.verify_calls) == 1

    def test_gate_fails_marks_failed_and_exits_nonzero(self, tmp_path: Path, monkeypatch) -> None:
        from datetime import datetime, timezone

        from ces.harness.models.completion_claim import (
            VerificationFinding,
            VerificationFindingKind,
            VerificationResult,
        )

        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        mock_runtime = MagicMock(runtime_name="codex")
        run_result = _agent_run_result_with_claim(
            {
                "task_id": "M-gate",
                "summary": "did it",
                "files_changed": ("src/auth/login.py",),
            }
        )
        mock_runner = AsyncMock()
        mock_runner.execute_runtime = AsyncMock(return_value=run_result)
        mock_runtime_registry = MagicMock(resolve_runtime=MagicMock(return_value=mock_runtime))

        mock_manifest = MagicMock(
            manifest_id="M-gate",
            description="Build",
            workflow_state=WorkflowState.IN_FLIGHT,
            verification_sensors=("test_pass",),
        )
        mock_manager = AsyncMock(get_manifest=AsyncMock(return_value=mock_manifest))

        mock_engine = AsyncMock()
        mock_engine.submit_for_verification = AsyncMock(return_value=WorkflowState.VERIFYING)
        mock_engine.verification_failed = AsyncMock(return_value=WorkflowState.FAILED)

        finding = VerificationFinding(
            kind=VerificationFindingKind.SENSOR_FAILURE,
            severity="critical",
            message="tests are red",
            hint="fix them",
            related_sensor="test_pass",
        )
        verifier = _StubVerifier(
            VerificationResult(
                passed=False,
                findings=(finding,),
                sensor_results=(),
                timestamp=datetime.now(timezone.utc),
            )
        )
        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "audit_ledger": AsyncMock(),
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "manifest_manager": mock_manager,
            "local_store": MagicMock(save_runtime_execution=MagicMock()),
            "completion_verifier": verifier,
        }

        with _patch_services(mock_services), patch("ces.cli.execute_cmd.WorkflowEngine", return_value=mock_engine):
            result = runner.invoke(_get_app(), ["execute", "M-gate", "--accept-runtime-side-effects"])

        assert result.exit_code != 0, result.stdout
        assert "Completion Gate Failed" in result.stdout
        assert "tests are red" in result.stdout
        mock_engine.verification_failed.assert_awaited_once()

    def test_gate_skipped_when_no_claim_emitted(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        mock_runtime = MagicMock(runtime_name="codex")
        run_result = _agent_run_result_with_claim(claim_dict=None)  # no claim emitted
        mock_runner = AsyncMock()
        mock_runner.execute_runtime = AsyncMock(return_value=run_result)
        mock_runtime_registry = MagicMock(resolve_runtime=MagicMock(return_value=mock_runtime))

        mock_manifest = MagicMock(
            manifest_id="M-gate",
            description="Build",
            workflow_state=WorkflowState.IN_FLIGHT,
            verification_sensors=("test_pass",),
        )
        mock_manager = AsyncMock(get_manifest=AsyncMock(return_value=mock_manifest))

        mock_engine = AsyncMock()
        mock_engine.fail = AsyncMock(return_value=WorkflowState.FAILED)

        verifier = _StubVerifier(None)  # not used because claim is None
        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "audit_ledger": AsyncMock(),
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "manifest_manager": mock_manager,
            "local_store": MagicMock(save_runtime_execution=MagicMock()),
            "completion_verifier": verifier,
        }

        with _patch_services(mock_services), patch("ces.cli.execute_cmd.WorkflowEngine", return_value=mock_engine):
            result = runner.invoke(_get_app(), ["execute", "M-gate", "--accept-runtime-side-effects"])

        assert result.exit_code != 0, result.stdout
        assert "did not emit" in result.stdout.lower()
        mock_engine.fail.assert_awaited_once()
        # Verifier not invoked when no claim was present
        assert verifier.verify_calls == []

    def test_actual_workspace_delta_scope_enforced_even_when_no_sensors_configured(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Actual workspace changes are policy-checked even when the claim gate is disabled."""
        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        mock_runtime = MagicMock(runtime_name="codex")
        run_result = _agent_run_result_with_claim(claim_dict=None)
        mock_runner = AsyncMock()
        mock_runner.execute_runtime = AsyncMock(return_value=run_result)
        mock_runtime_registry = MagicMock(resolve_runtime=MagicMock(return_value=mock_runtime))

        mock_manifest = MagicMock(
            manifest_id="M-no-gate",
            description="Build",
            workflow_state=WorkflowState.IN_FLIGHT,
            verification_sensors=(),  # opt-out: empty tuple
            affected_files=("allowed.txt",),
            forbidden_files=(),
        )
        mock_manager = AsyncMock(get_manifest=AsyncMock(return_value=mock_manifest))

        verifier = _StubVerifier(None)
        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "audit_ledger": AsyncMock(),
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "manifest_manager": mock_manager,
            "local_store": MagicMock(save_runtime_execution=MagicMock()),
            "completion_verifier": verifier,
        }

        before_snapshot = MagicMock()
        after_snapshot = MagicMock()
        before_snapshot.diff.return_value.changed_files = ("forbidden.txt",)
        snapshot_cls = MagicMock()
        snapshot_cls.capture.side_effect = [before_snapshot, after_snapshot]

        mock_engine = AsyncMock()
        mock_engine.fail = AsyncMock(return_value=WorkflowState.FAILED)
        with (
            _patch_services(mock_services),
            patch("ces.cli.execute_cmd.WorkflowEngine", return_value=mock_engine),
            patch("ces.cli.execute_cmd.WorkspaceSnapshot", snapshot_cls, create=True),
        ):
            result = runner.invoke(_get_app(), ["execute", "M-no-gate", "--accept-runtime-side-effects"])

        assert result.exit_code != 0, result.stdout
        assert "outside manifest scope" in result.stdout
        mock_engine.fail.assert_awaited_once()
        # Claim gate did not run, so the verifier was never invoked.
        assert verifier.verify_calls == []


# ---------------------------------------------------------------------------
# Prompt-pack guidance (Gap #1)
# ---------------------------------------------------------------------------


class TestPromptPackBuilder:
    """_build_prompt_pack must instruct the agent to emit ces:completion when the gate is on."""

    def test_no_sensors_still_includes_charter_but_not_completion_gate(self) -> None:
        from ces.cli.execute_cmd import _build_prompt_pack

        manifest = MagicMock(
            manifest_id="M1",
            description="Build a thing",
            verification_sensors=(),
        )
        prompt = _build_prompt_pack(manifest)
        assert "Build a thing" in prompt
        assert "Explore first" in prompt
        assert "ces:completion" not in prompt
        # Gate-only sections must be absent
        assert "Completion Gate" not in prompt

    def test_with_sensors_appends_claim_instructions(self) -> None:
        from ces.cli.execute_cmd import _build_prompt_pack

        manifest = MagicMock(
            manifest_id="M1",
            description="Build a thing",
            verification_sensors=("test_pass", "lint"),
            acceptance_criteria=(),
        )
        prompt = _build_prompt_pack(manifest)
        assert "ces:completion" in prompt
        assert "Completion Gate" in prompt
        assert "test_pass" in prompt
        assert "lint" in prompt
        # Schema mentions the four required JSON fields
        assert "task_id" in prompt
        assert "files_changed" in prompt
        assert "criteria_satisfied" in prompt
        assert "scope_deviations" in prompt

    def test_acceptance_criteria_listed_in_prompt(self) -> None:
        from ces.cli.execute_cmd import _build_prompt_pack

        manifest = MagicMock(
            manifest_id="M1",
            description="Build a thing",
            verification_sensors=("test_pass",),
            acceptance_criteria=("user can log in", "user can log out"),
        )
        prompt = _build_prompt_pack(manifest)
        assert "user can log in" in prompt
        assert "user can log out" in prompt


# ---------------------------------------------------------------------------
# Auto-repair loop (Gap #2)
# ---------------------------------------------------------------------------


def _make_correction_stub(detect_no_progress: bool = False):
    """Returns a SelfCorrectionManager-shaped stub usable in CLI tests.

    Pass ``detect_no_progress=True`` to simulate the no-progress branch
    firing on every check.
    """
    stub = MagicMock()
    stub.build_repair_prompt = MagicMock(side_effect=lambda findings: f"REPAIR_PROMPT [{len(findings)} finding(s)]")
    stub.detect_no_progress = MagicMock(return_value=detect_no_progress)
    return stub


class TestAutoRepairLoop:
    def test_auto_repair_converges_on_second_attempt(self, tmp_path: Path, monkeypatch) -> None:
        from datetime import datetime, timezone

        from ces.harness.models.completion_claim import (
            VerificationFinding,
            VerificationFindingKind,
            VerificationResult,
        )

        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        # Two agent runs back to back: same successful claim, but the verifier
        # rejects the first and accepts the second.
        run1 = _agent_run_result_with_claim({"task_id": "M-gate", "summary": "v1", "files_changed": ("src/x.py",)})
        run2 = _agent_run_result_with_claim({"task_id": "M-gate", "summary": "v2", "files_changed": ("src/x.py",)})
        mock_runner = AsyncMock()
        mock_runner.execute_runtime = AsyncMock(side_effect=[run1, run2])
        mock_runtime_registry = MagicMock(resolve_runtime=MagicMock(return_value=MagicMock(runtime_name="codex")))

        mock_manifest = MagicMock(
            manifest_id="M-gate",
            description="Build",
            workflow_state=WorkflowState.IN_FLIGHT,
            verification_sensors=("test_pass",),
        )
        mock_manager = AsyncMock(get_manifest=AsyncMock(return_value=mock_manifest))

        mock_engine = AsyncMock()
        mock_engine.retry = AsyncMock(return_value=WorkflowState.IN_FLIGHT)

        finding = VerificationFinding(
            kind=VerificationFindingKind.SENSOR_FAILURE,
            severity="high",
            message="lint failed",
            hint="fix lint",
            related_sensor="lint",
        )
        verifier = _StubVerifier(
            payloads=[
                VerificationResult(
                    passed=False, findings=(finding,), sensor_results=(), timestamp=datetime.now(timezone.utc)
                ),
                VerificationResult(passed=True, findings=(), sensor_results=(), timestamp=datetime.now(timezone.utc)),
            ]
        )

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "audit_ledger": AsyncMock(),
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "manifest_manager": mock_manager,
            "local_store": MagicMock(save_runtime_execution=MagicMock()),
            "completion_verifier": verifier,
            "self_correction_manager": _make_correction_stub(),
        }

        with _patch_services(mock_services), patch("ces.cli.execute_cmd.WorkflowEngine", return_value=mock_engine):
            result = runner.invoke(
                _get_app(), ["execute", "M-gate", "--accept-runtime-side-effects", "--auto-repair", "1"]
            )

        assert result.exit_code == 0, result.stdout
        assert mock_runner.execute_runtime.await_count == 2
        # Second runtime call must have received the repair prompt
        second_call_kwargs = mock_runner.execute_runtime.await_args_list[1].kwargs
        assert "REPAIR_PROMPT" in (second_call_kwargs.get("repair_context") or "")
        assert len(verifier.verify_calls) == 2
        mock_engine.retry.assert_awaited_once()
        mock_engine.verification_passed.assert_awaited_once()

    def test_auto_repair_exhausts_and_exits_failed(self, tmp_path: Path, monkeypatch) -> None:
        from datetime import datetime, timezone

        from ces.harness.models.completion_claim import (
            VerificationFinding,
            VerificationFindingKind,
            VerificationResult,
        )

        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        run = _agent_run_result_with_claim({"task_id": "M-gate", "summary": "tried", "files_changed": ("src/x.py",)})
        mock_runner = AsyncMock()
        mock_runner.execute_runtime = AsyncMock(side_effect=[run, run])
        mock_runtime_registry = MagicMock(resolve_runtime=MagicMock(return_value=MagicMock(runtime_name="codex")))

        mock_manifest = MagicMock(
            manifest_id="M-gate",
            description="Build",
            workflow_state=WorkflowState.IN_FLIGHT,
            verification_sensors=("test_pass",),
        )
        mock_manager = AsyncMock(get_manifest=AsyncMock(return_value=mock_manifest))

        mock_engine = AsyncMock()
        mock_engine.retry = AsyncMock(return_value=WorkflowState.IN_FLIGHT)

        finding = VerificationFinding(
            kind=VerificationFindingKind.SENSOR_FAILURE,
            severity="critical",
            message="tests still failing",
            hint="fix the failing tests",
            related_sensor="test_pass",
        )
        # Two failing results — never converges.
        fail = VerificationResult(
            passed=False,
            findings=(finding,),
            sensor_results=(),
            timestamp=datetime.now(timezone.utc),
        )
        verifier = _StubVerifier(payloads=[fail, fail])

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "audit_ledger": AsyncMock(),
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "manifest_manager": mock_manager,
            "local_store": MagicMock(save_runtime_execution=MagicMock()),
            "completion_verifier": verifier,
            "self_correction_manager": _make_correction_stub(),
        }

        with _patch_services(mock_services), patch("ces.cli.execute_cmd.WorkflowEngine", return_value=mock_engine):
            result = runner.invoke(
                _get_app(), ["execute", "M-gate", "--accept-runtime-side-effects", "--auto-repair", "1"]
            )

        assert result.exit_code != 0, result.stdout
        # Loop ran twice (initial + 1 repair)
        assert mock_runner.execute_runtime.await_count == 2
        assert len(verifier.verify_calls) == 2
        # verification_failed called twice (once per attempt)
        assert mock_engine.verification_failed.await_count == 2
        # User sees the still-failing finding text
        assert "tests still failing" in result.stdout

    def test_no_progress_detected_aborts_loop(self, tmp_path: Path, monkeypatch) -> None:
        """When detect_no_progress fires, the loop aborts with a structured error (N4)."""
        from datetime import datetime, timezone

        from ces.harness.models.completion_claim import (
            VerificationFinding,
            VerificationFindingKind,
            VerificationResult,
        )

        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        run = _agent_run_result_with_claim({"task_id": "M-gate", "summary": "did it", "files_changed": ("src/x.py",)})
        mock_runner = AsyncMock()
        mock_runner.execute_runtime = AsyncMock(return_value=run)
        mock_runtime_registry = MagicMock(resolve_runtime=MagicMock(return_value=MagicMock(runtime_name="codex")))

        mock_manifest = MagicMock(
            manifest_id="M-gate",
            description="Build",
            workflow_state=WorkflowState.IN_FLIGHT,
            verification_sensors=("test_pass",),
        )
        mock_manager = AsyncMock(get_manifest=AsyncMock(return_value=mock_manifest))
        mock_engine = AsyncMock()

        finding = VerificationFinding(
            kind=VerificationFindingKind.SENSOR_FAILURE,
            severity="critical",
            message="x",
            hint="y",
        )
        verifier = _StubVerifier(
            VerificationResult(
                passed=False, findings=(finding,), sensor_results=(), timestamp=datetime.now(timezone.utc)
            )
        )

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "audit_ledger": AsyncMock(),
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "manifest_manager": mock_manager,
            "local_store": MagicMock(save_runtime_execution=MagicMock()),
            "completion_verifier": verifier,
            # Stub returns True from detect_no_progress on the very first call
            "self_correction_manager": _make_correction_stub(detect_no_progress=True),
        }

        with _patch_services(mock_services), patch("ces.cli.execute_cmd.WorkflowEngine", return_value=mock_engine):
            result = runner.invoke(
                _get_app(), ["execute", "M-gate", "--accept-runtime-side-effects", "--auto-repair", "5"]
            )

        assert result.exit_code != 0, result.stdout
        assert "No Progress Detected" in result.stdout
        # Loop aborted before invoking the verifier on this run
        assert verifier.verify_calls == []
        # Agent ran exactly once (no retries)
        assert mock_runner.execute_runtime.await_count == 1

    def test_default_auto_repair_zero_runs_one_attempt(self, tmp_path: Path, monkeypatch) -> None:
        """Without --auto-repair, the loop is single-shot — verifier called once."""
        from datetime import datetime, timezone

        from ces.harness.models.completion_claim import (
            VerificationFinding,
            VerificationFindingKind,
            VerificationResult,
        )

        monkeypatch.chdir(tmp_path)
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n")

        run = _agent_run_result_with_claim({"task_id": "M-gate", "summary": "tried", "files_changed": ("src/x.py",)})
        mock_runner = AsyncMock()
        mock_runner.execute_runtime = AsyncMock(return_value=run)
        mock_runtime_registry = MagicMock(resolve_runtime=MagicMock(return_value=MagicMock(runtime_name="codex")))

        mock_manifest = MagicMock(
            manifest_id="M-gate",
            description="Build",
            workflow_state=WorkflowState.IN_FLIGHT,
            verification_sensors=("test_pass",),
        )
        mock_manager = AsyncMock(get_manifest=AsyncMock(return_value=mock_manifest))

        mock_engine = AsyncMock()
        finding = VerificationFinding(
            kind=VerificationFindingKind.SENSOR_FAILURE,
            severity="critical",
            message="x",
            hint="y",
        )
        verifier = _StubVerifier(
            VerificationResult(
                passed=False, findings=(finding,), sensor_results=(), timestamp=datetime.now(timezone.utc)
            )
        )

        mock_services = {
            "settings": MagicMock(default_runtime="codex"),
            "audit_ledger": AsyncMock(),
            "runtime_registry": mock_runtime_registry,
            "agent_runner": mock_runner,
            "manifest_manager": mock_manager,
            "local_store": MagicMock(save_runtime_execution=MagicMock()),
            "completion_verifier": verifier,
            "self_correction_manager": _make_correction_stub(),
        }

        with _patch_services(mock_services), patch("ces.cli.execute_cmd.WorkflowEngine", return_value=mock_engine):
            result = runner.invoke(_get_app(), ["execute", "M-gate", "--accept-runtime-side-effects"])

        assert result.exit_code != 0, result.stdout
        assert mock_runner.execute_runtime.await_count == 1
        assert len(verifier.verify_calls) == 1
        mock_engine.retry.assert_not_called()
