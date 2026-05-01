"""FreshCart end-to-end worked example script.

Demonstrates the full CES governance pipeline via CLI commands:
  ces init -> ces manifest -> ces classify -> ces execute ->
  ces review -> ces approve -> ces status -> ces audit

Uses CliRunner (in-process, no subprocess escalation -- T-06-22)
with mocked services so the script can run without Postgres, Redis, or real LLM
API keys.

Usage::

    python -m examples.freshcart.run_e2e

Exports:
    run_freshcart_pipeline: Execute the full pipeline and return results.
"""

from __future__ import annotations

import os
import tempfile
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from typer.testing import CliRunner

from ces.shared.enums import (
    BehaviorConfidence,
    ChangeClass,
    RiskTier,
)
from examples.freshcart.sample_data import PROJECT_NAME, SAMPLE_TASKS

runner = CliRunner()


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_oracle_result(
    risk_tier: RiskTier = RiskTier.C,
    behavior_confidence: BehaviorConfidence = BehaviorConfidence.BC1,
    change_class: ChangeClass = ChangeClass.CLASS_1,
) -> Any:
    """Create a mock OracleClassificationResult."""
    from ces.control.models.oracle_result import OracleClassificationResult
    from ces.control.services.classification import ClassificationRule

    rule = ClassificationRule(
        description="Test rule",
        risk_tier=risk_tier,
        behavior_confidence=behavior_confidence,
        change_class=change_class,
    )
    return OracleClassificationResult(
        matched_rule=rule,
        confidence=0.92,
        top_matches=[(rule, 0.92)],
        action="auto_accept",
    )


def _make_mock_manifest(manifest_id: str, description: str) -> MagicMock:
    """Create a mock TaskManifest."""
    manifest = MagicMock()
    manifest.manifest_id = manifest_id
    manifest.description = description
    manifest.risk_tier = RiskTier.C
    manifest.behavior_confidence = BehaviorConfidence.BC1
    manifest.change_class = ChangeClass.CLASS_1
    manifest.affected_files = []
    manifest.token_budget = 100_000
    manifest.owner = "cli-user"
    return manifest


def _build_mock_services(manifests: dict[str, MagicMock]) -> dict[str, Any]:
    """Build a complete mock services dict for the pipeline."""
    mock_oracle = MagicMock()
    mock_oracle.classify.return_value = _make_oracle_result()

    mock_manager = AsyncMock()
    mock_manager.create_manifest = AsyncMock(
        side_effect=lambda **kw: manifests.get(kw["description"], next(iter(manifests.values())))
    )
    mock_manager.get_manifest = AsyncMock(side_effect=lambda mid: manifests.get(mid))

    # Review router mock
    mock_assignment = MagicMock()
    mock_assignment.role = MagicMock(value="reviewer")
    mock_assignment.model_id = "claude-3-opus"
    mock_assignment.agent_id = "agent-reviewer-1"
    mock_review_router = MagicMock()
    mock_review_router.assign_single.return_value = mock_assignment
    mock_review_router.assign_triad.return_value = [mock_assignment]

    # Evidence synthesizer mock
    mock_summary_slots = MagicMock()
    mock_summary_slots.summary = "Evidence summary line 1\nEvidence summary line 2"
    mock_summary_slots.challenge = "Challenge line 1\nChallenge line 2"
    mock_evidence = MagicMock()
    mock_evidence.format_summary_slots.return_value = mock_summary_slots
    mock_triage_result = MagicMock()
    mock_triage_result.color = MagicMock(value="green")
    mock_triage_result.risk_tier = MagicMock(value="C")
    mock_triage_result.trust_status = MagicMock(value="candidate")
    mock_triage_result.sensor_pass_rate = 1.0
    mock_triage_result.reason = "All checks passed"
    mock_triage_result.auto_approve_eligible = True
    mock_evidence.triage = AsyncMock(return_value=mock_triage_result)

    # Audit ledger mock
    mock_audit = AsyncMock()
    mock_audit.record_approval = AsyncMock()

    mock_settings = MagicMock(api_host="localhost", api_port=8000, default_model_id="claude-3-opus")
    mock_provider_registry = MagicMock()
    mock_provider_registry.get_provider = MagicMock(side_effect=KeyError("no provider"))
    mock_sensor_orch = AsyncMock()
    mock_sensor_orch.run_all = AsyncMock(return_value=[])

    mock_merge_controller = AsyncMock()
    mock_merge_result = MagicMock()
    mock_merge_result.approved = True
    mock_merge_result.checks = []
    mock_merge_controller.validate_merge = AsyncMock(return_value=mock_merge_result)

    return {
        "settings": mock_settings,
        "session_factory": MagicMock(),
        "classification_oracle": mock_oracle,
        "manifest_manager": mock_manager,
        "review_router": mock_review_router,
        "evidence_synthesizer": mock_evidence,
        "audit_ledger": mock_audit,
        "gate_evaluator": MagicMock(),
        "kill_switch": MagicMock(),
        "intake_engine": MagicMock(),
        "vault_service": MagicMock(),
        "emergency_service": MagicMock(),
        "hidden_check_engine": MagicMock(),
        "sensor_orchestrator": mock_sensor_orch,
        "trust_manager": MagicMock(),
        "merge_controller": mock_merge_controller,
        "workflow_engine": None,
        "classification_engine": MagicMock(),
        "provider_registry": mock_provider_registry,
        "guide_pack_builder": MagicMock(),
        "note_ranker": MagicMock(),
        "legacy_behavior_service": MagicMock(),
        "manifest_generator": MagicMock(),
    }


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------


def _step_result(name: str, exit_code: int, output: str) -> dict[str, Any]:
    """Create a step result dict."""
    return {
        "step": name,
        "passed": exit_code == 0,
        "exit_code": exit_code,
        "output_snippet": output[:200] if output else "",
    }


def run_freshcart_pipeline() -> list[dict[str, Any]]:
    """Execute the full FreshCart governance pipeline.

    Returns a list of step results, each with step name, pass/fail,
    exit code, and output snippet.
    """
    from unittest.mock import patch

    from ces.cli import app

    results: list[dict[str, Any]] = []
    manifest_ids: list[str] = {}  # type: ignore[assignment]
    manifest_ids = []

    # Prepare mock manifests keyed by description
    mock_manifests_by_desc: dict[str, MagicMock] = {}
    mock_manifests_by_id: dict[str, MagicMock] = {}
    for i, task in enumerate(SAMPLE_TASKS):
        mid = f"M-freshcart-{i:03d}"
        m = _make_mock_manifest(mid, task["description"])
        mock_manifests_by_desc[task["description"]] = m
        mock_manifests_by_id[mid] = m

    # Build mock services
    services = _build_mock_services(mock_manifests_by_id)
    # Also wire up create_manifest to return by description
    services["manifest_manager"].create_manifest = AsyncMock(
        side_effect=lambda **kw: mock_manifests_by_desc.get(kw["description"])
    )
    services["manifest_manager"].get_manifest = AsyncMock(side_effect=lambda mid: mock_manifests_by_id.get(mid))

    @asynccontextmanager
    async def _fake_get_services():
        yield services

    # Step 1: Init
    with tempfile.TemporaryDirectory() as tmpdir:
        old_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            result = runner.invoke(app, ["init", PROJECT_NAME])
            results.append(_step_result("init", result.exit_code, result.output))

            # Create .ces dir for subsequent commands that need project root
            ces_dir = os.path.join(tmpdir, ".ces")
            if not os.path.exists(ces_dir):
                os.makedirs(ces_dir)

            # Step 2: Manifest (create for each sample task)
            for task in SAMPLE_TASKS:
                with patch("ces.cli.manifest_cmd.get_services", new=_fake_get_services):
                    result = runner.invoke(app, ["manifest", task["description"], "--yes"])
                    results.append(
                        _step_result(
                            f"manifest:{task['description'][:40]}",
                            result.exit_code,
                            result.output,
                        )
                    )
                    # Extract manifest_id from mock
                    if task["description"] in mock_manifests_by_desc:
                        mid = mock_manifests_by_desc[task["description"]].manifest_id
                        manifest_ids.append(mid)

            # Step 3: Classify each manifest
            for mid in manifest_ids:
                with patch("ces.cli.classify_cmd.get_services", new=_fake_get_services):
                    result = runner.invoke(app, ["classify", mid])
                    results.append(_step_result(f"classify:{mid}", result.exit_code, result.output))

            # Step 4: Execute (mock Celery dispatch + SSE)
            with (
                patch("ces.cli.execute_cmd.get_services", new=_fake_get_services),
                patch("ces.cli.execute_cmd.execute_agent_task") as mock_task,
                patch(
                    "ces.cli.execute_cmd._stream_events",
                    return_value=[
                        {
                            "event": "status",
                            "data": {"status": "running"},
                        },
                        {
                            "event": "complete",
                            "data": {"result": "success"},
                        },
                    ],
                ),
            ):
                mock_task.delay.return_value = MagicMock(id="task-123")
                for mid in manifest_ids[:1]:  # Execute first task only
                    result = runner.invoke(app, ["execute", mid])
                    results.append(_step_result(f"execute:{mid}", result.exit_code, result.output))

            # Step 5: Review
            for mid in manifest_ids[:1]:
                with patch("ces.cli.review_cmd.get_services", new=_fake_get_services):
                    result = runner.invoke(app, ["review", mid])
                    results.append(_step_result(f"review:{mid}", result.exit_code, result.output))

            # Step 6: Approve
            for mid in manifest_ids[:1]:
                with patch("ces.cli.approve_cmd.get_services", new=_fake_get_services):
                    result = runner.invoke(app, ["approve", mid, "--yes"])
                    results.append(_step_result(f"approve:{mid}", result.exit_code, result.output))

            # Step 7: Status
            with patch("ces.cli.status_cmd.get_services", new=_fake_get_services):
                result = runner.invoke(app, ["--json", "status"])
                results.append(_step_result("status", result.exit_code, result.output))

            # Step 8: Audit
            with patch("ces.cli.audit_cmd.get_services", new=_fake_get_services):
                result = runner.invoke(app, ["--json", "audit"])
                results.append(_step_result("audit", result.exit_code, result.output))

        finally:
            os.chdir(old_cwd)

    return results


def test_freshcart() -> None:
    """Run the FreshCart pipeline as a standalone test."""
    results = run_freshcart_pipeline()
    passed = sum(1 for r in results if r["passed"])
    total = len(results)

    print(f"\nFreshCart E2E Pipeline: {passed}/{total} steps passed\n")
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"  [{status}] {r['step']} (exit={r['exit_code']})")

    if passed < total:
        failed = [r for r in results if not r["passed"]]
        for f in failed:
            print(f"\n  FAILED: {f['step']}")
            print(f"  Output: {f['output_snippet']}")

    if passed != total:
        raise AssertionError(f"FreshCart pipeline: {passed}/{total} passed")


if __name__ == "__main__":
    test_freshcart()
