"""Integration test proving the Completion Gate composes end-to-end.

This is the proof point for the P0-P2 critical path:

1. Agent emits stdout containing a `ces:completion` block.
2. agent_runner parses the claim and attaches it to the runtime result.
3. CompletionVerifier inspects the claim + runs sensors and produces findings.
4. SelfCorrectionManager.build_repair_prompt converts findings into a prompt.
5. agent_runner.execute_runtime, called with repair_context, sends those
   findings into the next agent run — closing the evidence-driven retry loop.

It does NOT exercise the workflow state machine end-to-end (that's covered in
test_workflow_engine.py); it confirms the harness/execution glue composes.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ces.control.models.manifest import TaskManifest
from ces.execution.agent_runner import AgentRunner
from ces.execution.runtimes.protocol import AgentRuntimeResult
from ces.harness.sensors.completion_gate import LintSensor
from ces.harness.services.completion_verifier import CompletionVerifier
from ces.harness.services.self_correction_manager import SelfCorrectionManager
from ces.shared.enums import (
    ArtifactStatus,
    BehaviorConfidence,
    ChangeClass,
    RiskTier,
    WorkflowState,
)


class _MockKillSwitch:
    def is_halted(self, activity_class: str) -> bool:
        return False


class _MockProvider:
    pass


class _ScriptedRuntime:
    """Runtime that returns a different stdout per call (simulates an agent across retries)."""

    runtime_name = "scripted"

    def __init__(self, stdouts: list[str]) -> None:
        self._stdouts = list(stdouts)
        self.calls: list[str] = []  # captured prompts

    def run_task(self, manifest_description, prompt_pack, working_dir, allowed_tools=()):
        self.calls.append(prompt_pack)
        stdout = self._stdouts.pop(0) if self._stdouts else ""
        return AgentRuntimeResult(
            runtime_name="scripted",
            runtime_version="0.0",
            reported_model=None,
            invocation_ref=f"call-{len(self.calls)}",
            exit_code=0,
            stdout=stdout,
            stderr="",
            duration_seconds=0.1,
        )


def _make_manifest(verification_sensors=("lint",)) -> TaskManifest:
    now = datetime.now(timezone.utc)
    return TaskManifest(
        manifest_id="MANIF-INT-001",
        description="Integration test",
        version=1,
        status=ArtifactStatus.APPROVED,
        owner="test",
        created_at=now,
        last_confirmed=now,
        signature="sig",
        risk_tier=RiskTier.B,
        behavior_confidence=BehaviorConfidence.BC2,
        change_class=ChangeClass.CLASS_2,
        affected_files=("src/auth/*.py",),
        token_budget=5000,
        expires_at=now + timedelta(days=7),
        workflow_state=WorkflowState.IN_FLIGHT,
        verification_sensors=verification_sensors,
    )


@pytest.mark.asyncio
async def test_failing_run_produces_repair_prompt_seen_by_next_run(tmp_path: Path) -> None:
    # Round 1 — agent claims done; lint artifact shows violations.
    (tmp_path / "ruff-report.json").write_text(
        json.dumps(
            [
                {
                    "code": "F401",
                    "message": "unused import",
                    "filename": "src/auth/login.py",
                    "location": {"row": 3, "column": 1},
                }
            ]
        ),
        encoding="utf-8",
    )

    round1_stdout = (
        "Done.\n\n"
        "```ces:completion\n"
        '{"task_id": "MANIF-INT-001", "summary": "did the work", "files_changed": ["src/auth/login.py"]}\n'
        "```\n"
    )
    round2_stdout = (
        "Fixed lint.\n\n"
        "```ces:completion\n"
        '{"task_id": "MANIF-INT-001", "summary": "fixed lint", "files_changed": ["src/auth/login.py"]}\n'
        "```\n"
    )

    runner = AgentRunner(provider=_MockProvider(), kill_switch=_MockKillSwitch())
    runtime = _ScriptedRuntime([round1_stdout, round2_stdout])
    verifier = CompletionVerifier(sensors={"lint": LintSensor()})
    correction = SelfCorrectionManager()
    manifest = _make_manifest()

    # ---- Round 1 ----
    run1 = await runner.execute_runtime(
        manifest=manifest,
        runtime=runtime,
        prompt_pack="initial",
        working_dir=tmp_path,
    )
    assert run1.runtime_result is not None
    claim1 = run1.runtime_result.completion_claim
    assert claim1 is not None

    result1 = await verifier.verify(manifest, claim1, tmp_path)
    assert result1.passed is False
    assert len(result1.findings) >= 1

    repair = correction.build_repair_prompt(result1.findings)
    assert "F401" in repair or "unused import" in repair.lower()

    # ---- Round 2: agent re-runs with the repair prompt; lint artifact now clean.
    (tmp_path / "ruff-report.json").write_text("[]", encoding="utf-8")

    run2 = await runner.execute_runtime(
        manifest=manifest,
        runtime=runtime,
        prompt_pack="initial",
        working_dir=tmp_path,
        repair_context=repair,
    )
    # The runtime saw the repair_context appended to its prompt
    assert "Verification failed" in runtime.calls[1] or "repair" in runtime.calls[1].lower()
    claim2 = run2.runtime_result.completion_claim
    assert claim2 is not None

    result2 = await verifier.verify(manifest, claim2, tmp_path)
    assert result2.passed is True
    assert result2.findings == ()
