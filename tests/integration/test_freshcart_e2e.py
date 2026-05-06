"""Builder-first integration smoke tests and CLI-surface checks.

Exercises the local builder-first CLI loop through the same entrypoints the
public quickstart documents, using deterministic mock services so the tests do
not require Postgres, Redis, or LLM API access.
"""

from __future__ import annotations

import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.integration
from typer.testing import CliRunner

from ces.shared.enums import (
    BehaviorConfidence,
    ChangeClass,
    RiskTier,
    TrustStatus,
)
from tests.support.builder_scenarios import (
    BROWNFIELD_RETRY_SCENARIO,
    BuilderScenario,
    BuilderScenarioHarness,
    _completion_stdout,
)

runner = CliRunner()

FRESHCART_BUILDER_SCENARIO = BuilderScenario(
    name="freshcart-local-quickstart",
    request="Build a FreshCart order summary service",
    fixture_name=None,
    build_args=(
        "build",
        "Build a FreshCart order summary service",
        "--yes",
        "--accept-runtime-side-effects",
        "--acceptance",
        "Shoppers can see item counts plus subtotal, tax, and shipping",
    ),
    prompt_responses=(
        "Expose an HTTP endpoint",
        "Shoppers can see item counts plus subtotal, tax, and shipping",
        "Existing CLI commands",
    ),
    proposal={
        "description": "Build a FreshCart order summary service",
        "risk_tier": RiskTier.C.value,
        "behavior_confidence": BehaviorConfidence.BC1.value,
        "change_class": ChangeClass.CLASS_1.value,
        "affected_files": ["checkout.py"],
        "token_budget": 50000,
        "reasoning": "Low-risk builder-first smoke request",
    },
    execution_results=(
        {
            "runtime_name": "codex",
            "runtime_version": "1.0.0",
            "reported_model": "gpt-5.4",
            "invocation_ref": "run-freshcart-1",
            "exit_code": 0,
            "stdout": _completion_stdout(criterion="Shoppers can see item counts plus subtotal, tax, and shipping"),
            "stderr": "",
            "duration_seconds": 0.5,
        },
    ),
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


def _make_mock_manifest(
    manifest_id: str,
    description: str = "Test task",
    risk_tier: RiskTier = RiskTier.C,
) -> MagicMock:
    """Create a mock TaskManifest."""
    manifest = MagicMock()
    manifest.manifest_id = manifest_id
    manifest.description = description
    manifest.risk_tier = risk_tier
    manifest.behavior_confidence = BehaviorConfidence.BC1
    manifest.change_class = ChangeClass.CLASS_1
    manifest.affected_files = []
    manifest.token_budget = 100_000
    manifest.owner = "cli-user"
    return manifest


def _build_e2e_services() -> tuple[dict[str, Any], dict[str, MagicMock]]:
    """Build complete mock services for E2E testing.

    Returns:
        Tuple of (services_dict, manifests_by_id_dict).
    """
    manifests_by_id: dict[str, MagicMock] = {}
    manifests_by_desc: dict[str, MagicMock] = {}
    manifest_counter = [0]

    async def _create_manifest(**kwargs: Any) -> MagicMock:
        desc = kwargs.get("description", "unknown")
        idx = manifest_counter[0]
        manifest_counter[0] += 1
        mid = f"M-fc-{idx:03d}"
        m = _make_mock_manifest(mid, desc)
        manifests_by_id[mid] = m
        manifests_by_desc[desc] = m
        return m

    async def _get_manifest(mid: str) -> MagicMock | None:
        return manifests_by_id.get(mid)

    mock_oracle = MagicMock()
    mock_oracle.classify.return_value = _make_oracle_result()

    mock_manager = AsyncMock()
    mock_manager.create_manifest = AsyncMock(side_effect=_create_manifest)
    mock_manager.get_manifest = AsyncMock(side_effect=_get_manifest)
    mock_manager.get_active_manifests = AsyncMock(return_value=[])
    mock_manager.save_manifest = AsyncMock()

    # Review router
    mock_assignment = MagicMock()
    mock_assignment.role = MagicMock(value="reviewer")
    mock_assignment.model_id = "claude-3-opus"
    mock_assignment.agent_id = "agent-reviewer-1"
    mock_review_router = MagicMock()
    mock_review_router.assign_single.return_value = mock_assignment
    mock_review_router.assign_triad.return_value = [mock_assignment]

    # Evidence synthesizer
    mock_summary_slots = MagicMock()
    mock_summary_slots.summary = "\n".join([f"Evidence summary line {i}" for i in range(1, 12)])
    mock_summary_slots.challenge = "\n".join([f"Challenge line {i}" for i in range(1, 5)])
    mock_evidence = MagicMock()
    mock_evidence.format_summary_slots = AsyncMock(return_value=mock_summary_slots)

    mock_triage_result = MagicMock()
    mock_triage_result.color = MagicMock(value="green")
    mock_triage_result.risk_tier = MagicMock(value="C")
    mock_triage_result.trust_status = MagicMock(value="candidate")
    mock_triage_result.sensor_pass_rate = 1.0
    mock_triage_result.reason = "All checks passed"
    mock_triage_result.auto_approve_eligible = True
    mock_evidence.triage = AsyncMock(return_value=mock_triage_result)

    # Audit ledger
    mock_audit = AsyncMock()
    mock_audit.record_approval = AsyncMock()

    # Trust manager mock
    mock_trust = MagicMock()

    # Ensure audit_ledger has query methods used by status_cmd and audit_cmd
    mock_audit.query_by_time_range = AsyncMock(return_value=[])
    mock_audit.query_by_event_type = AsyncMock(return_value=[])
    mock_audit.query_by_actor = AsyncMock(return_value=[])

    # Sensor orchestrator mock with run_all returning empty (no real sensors in test)
    mock_sensor_orchestrator = AsyncMock()
    mock_sensor_orchestrator.run_all = AsyncMock(return_value=[])

    mock_runtime_adapter = MagicMock()
    mock_runtime_adapter.runtime_name = "codex"
    mock_runtime_registry = MagicMock()
    mock_runtime_registry.resolve_runtime.return_value = mock_runtime_adapter

    mock_agent_runner = AsyncMock()
    mock_agent_runner.execute_runtime = AsyncMock(
        return_value={
            "runtime_name": "codex",
            "runtime_version": "1.0.0",
            "reported_model": None,
            "invocation_ref": "run-e2e-001",
            "exit_code": 0,
            "stdout": "FreshCart execution complete",
            "stderr": "",
            "duration_seconds": 0.5,
        }
    )
    mock_local_store = MagicMock()

    # Provider registry mock (returns None provider -- summary slots stay mocked)
    mock_provider_registry = MagicMock()
    mock_provider_registry.get_provider = MagicMock(side_effect=KeyError("no provider"))

    services: dict[str, Any] = {
        "settings": MagicMock(default_model_id="claude-sonnet-4-6"),
        "classification_oracle": mock_oracle,
        "manifest_manager": mock_manager,
        "review_router": mock_review_router,
        "evidence_synthesizer": mock_evidence,
        "audit_ledger": mock_audit,
        "trust_manager": mock_trust,
        "sensor_orchestrator": mock_sensor_orchestrator,
        "runtime_registry": mock_runtime_registry,
        "agent_runner": mock_agent_runner,
        "local_store": mock_local_store,
        "merge_controller": AsyncMock(
            validate_merge=AsyncMock(return_value=MagicMock(allowed=True, checks=[], reason=""))
        ),
        "provider_registry": mock_provider_registry,
    }

    return services, manifests_by_id


def _patch_services_for_module(module_path: str, services: dict[str, Any]):
    """Return a context manager that patches get_services for a specific CLI module."""

    @asynccontextmanager
    async def _fake_get_services():
        yield services

    return patch(f"ces.cli.{module_path}.get_services", new=_fake_get_services)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBuilderFirstE2EPipeline:
    """Smoke tests for the documented local builder-first workflow."""

    def test_builder_first_quickstart_pipeline(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Greenfield quickstart path completes without any infrastructure."""
        harness = BuilderScenarioHarness(tmp_path=tmp_path, monkeypatch=monkeypatch)

        result = harness.run(FRESHCART_BUILDER_SCENARIO)

        assert result.build.exit_code == 0, f"stdout={result.build.stdout}"
        assert "Build Review Complete" in result.build.stdout
        assert result.explain.exit_code == 0, f"stdout={result.explain.stdout}"
        assert "Build a FreshCart order summary service" in result.explain.stdout
        assert "Start a new task with `ces build`" in result.explain.stdout
        assert result.status.exit_code == 0, f"stdout={result.status.stdout}"
        assert "Build a FreshCart order summary service" in result.status.stdout
        assert "Start a new task with `ces build`" in result.status.stdout
        assert result.continue_.exit_code == 0
        assert "already completed" in result.continue_.stdout.lower()
        assert result.latest_snapshot is not None
        assert result.latest_snapshot.is_chain_complete is True

    def test_approved_merge_validation_block_does_not_fail_builder_session(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Approved work may be unmerged without turning the builder session into a recovery blocker."""
        scenario = BuilderScenario(
            name="freshcart-merge-validation-blocked",
            request=FRESHCART_BUILDER_SCENARIO.request,
            fixture_name=FRESHCART_BUILDER_SCENARIO.fixture_name,
            build_args=FRESHCART_BUILDER_SCENARIO.build_args,
            prompt_responses=FRESHCART_BUILDER_SCENARIO.prompt_responses,
            proposal=FRESHCART_BUILDER_SCENARIO.proposal,
            execution_results=FRESHCART_BUILDER_SCENARIO.execution_results,
            merge_allowed=False,
            merge_reason="review_complete",
            merge_checks=(SimpleNamespace(name="review_complete", passed=False),),
        )
        harness = BuilderScenarioHarness(tmp_path=tmp_path, monkeypatch=monkeypatch)

        result = harness.run(scenario)

        assert result.build.exit_code == 0, f"stdout={result.build.stdout}"
        assert "approved, but merge was not applied" in result.build.stdout
        assert "Merge Not Applied" in result.build.stdout
        assert result.latest_snapshot is not None
        assert result.latest_snapshot.stage == "completed"
        assert result.latest_snapshot.is_chain_complete is True

    def test_approved_integrity_merge_block_still_fails_builder_session(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Integrity merge failures remain blocked even when work was approved."""
        scenario = BuilderScenario(
            name="freshcart-integrity-merge-blocked",
            request=FRESHCART_BUILDER_SCENARIO.request,
            fixture_name=FRESHCART_BUILDER_SCENARIO.fixture_name,
            build_args=FRESHCART_BUILDER_SCENARIO.build_args,
            prompt_responses=FRESHCART_BUILDER_SCENARIO.prompt_responses,
            proposal=FRESHCART_BUILDER_SCENARIO.proposal,
            execution_results=FRESHCART_BUILDER_SCENARIO.execution_results,
            merge_allowed=False,
            merge_reason="evidence_exists",
            merge_checks=(SimpleNamespace(name="evidence_exists", passed=False),),
        )
        harness = BuilderScenarioHarness(tmp_path=tmp_path, monkeypatch=monkeypatch)

        result = harness.run(scenario)

        assert result.build.exit_code == 1, f"stdout={result.build.stdout}"
        assert "approved, but merge is blocked" in result.build.stdout
        assert "Merge Blocked" in result.build.stdout
        assert result.latest_snapshot is not None
        assert result.latest_snapshot.stage != "completed"
        assert result.latest_snapshot.is_chain_complete is False

    def test_builder_first_brownfield_retry_pipeline(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Brownfield builder sessions can fail, resume, and complete cleanly."""
        harness = BuilderScenarioHarness(tmp_path=tmp_path, monkeypatch=monkeypatch)

        result = harness.run(BROWNFIELD_RETRY_SCENARIO)

        assert result.build.exit_code != 0
        assert "exited with code 1" in result.build.stdout
        assert result.explain.exit_code == 0, f"stdout={result.explain.stdout}"
        assert "Retry the last runtime execution with `ces continue`." in result.explain.stdout
        assert result.status.exit_code == 0, f"stdout={result.status.stdout}"
        assert "Retry the last runtime execution with `ces continue`." in result.status.stdout
        assert result.continue_.exit_code == 0, f"stdout={result.continue_.stdout}"
        assert "Build Review Complete" in result.continue_.stdout
        assert result.final_explain is not None
        assert "Start a new task with `ces build`" in result.final_explain.stdout
        assert result.final_status is not None
        assert "Start a new task with `ces build`" in result.final_status.stdout
        assert result.runtime_retry_preserved_review_count


class TestAllCommandsRegistered:
    """Verify the current CLI command surface is registered in the app."""

    # Key top-level commands/groups expected in the current builder-first CLI.
    EXPECTED_COMMANDS = {
        "init",
        "build",
        "continue",
        "explain",
        "run",
        "manifest",
        "classify",
        "execute",
        "review",
        "triage",
        "approve",
        "gate",
        "intake",
        "status",
        "audit",
        "vault",  # subcommand group
        "emergency",  # subcommand group
        "brownfield",  # subcommand group
    }

    # Subcommands within vault and emergency
    EXPECTED_VAULT_SUBCOMMANDS = {"query", "write", "health"}
    EXPECTED_EMERGENCY_SUBCOMMANDS = {"declare"}

    def test_all_commands_registered(self) -> None:
        """All 14 top-level commands/groups are registered on the app."""
        app = _get_app()

        registered: set[str] = set()
        for cmd in app.registered_commands:
            if cmd.name:
                registered.add(cmd.name)
        for group in app.registered_groups:
            if group.name:
                registered.add(group.name)

        missing = self.EXPECTED_COMMANDS - registered
        assert not missing, f"Missing commands: {missing}"

    def test_total_command_count_covers_the_expected_surface(self) -> None:
        """The CLI command surface should not shrink below the expected floor."""
        app = _get_app()

        # Count direct commands
        direct = len(app.registered_commands)

        # Count subcommands in vault and emergency groups
        import ces.cli.emergency_cmd as emergency_mod
        import ces.cli.vault_cmd as vault_mod

        vault_sub = len(vault_mod.vault_app.registered_commands)
        emergency_sub = len(emergency_mod.emergency_app.registered_commands)

        total = direct + vault_sub + emergency_sub
        assert total >= 22, (
            f"Expected at least 22 total commands, got {total} "
            f"(direct={direct}, vault={vault_sub}, emergency={emergency_sub})"
        )

    def test_vault_subcommands(self) -> None:
        """Vault subcommand group has query, write, and health."""
        import ces.cli.vault_cmd as vault_mod

        registered = {cmd.name for cmd in vault_mod.vault_app.registered_commands if cmd.name}
        missing = self.EXPECTED_VAULT_SUBCOMMANDS - registered
        assert not missing, f"Missing vault subcommands: {missing}"

    def test_emergency_subcommands(self) -> None:
        """Emergency subcommand group has declare."""
        import ces.cli.emergency_cmd as emergency_mod

        registered = {cmd.name for cmd in emergency_mod.emergency_app.registered_commands if cmd.name}
        missing = self.EXPECTED_EMERGENCY_SUBCOMMANDS - registered
        assert not missing, f"Missing emergency subcommands: {missing}"


class TestHelpText:
    """Verify help text includes all commands."""

    def test_help_text_available(self) -> None:
        """ces --help outputs a help message listing all command names."""
        app = _get_app()
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        # Verify key commands appear in help output
        output_lower = result.output.lower()
        for cmd in [
            "init",
            "manifest",
            "classify",
            "execute",
            "review",
            "approve",
            "status",
            "audit",
            "vault",
            "emergency",
        ]:
            assert cmd in output_lower, f"Command '{cmd}' not found in --help output"

    def test_json_flag_in_help(self) -> None:
        """ces --help mentions the --json global option."""
        app = _get_app()
        result = runner.invoke(app, ["--help"])
        # Strip ANSI escape codes so the substring check is robust to Rich's
        # terminal-dependent rendering (color codes, wrapping) in CI.
        ansi = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
        cleaned = ansi.sub("", result.output)
        assert "--json" in cleaned, f"--json not found in help output: {cleaned[:400]!r}"


class TestJsonModeDataCommands:
    """Verify --json flag is accepted by data-producing commands."""

    def test_status_json_mode(self, tmp_path: Path) -> None:
        """ces --json status outputs valid JSON."""
        app = _get_app()
        services, _ = _build_e2e_services()

        @asynccontextmanager
        async def _fake_services(*args: Any, **kwargs: Any):
            del args, kwargs
            yield services

        old_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            (tmp_path / ".ces").mkdir(exist_ok=True)
            with patch("ces.cli.status_cmd.get_services", new=_fake_services):
                result = runner.invoke(app, ["--json", "status"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert isinstance(data, dict)
        finally:
            os.chdir(old_cwd)

    def test_audit_json_mode(self, tmp_path: Path) -> None:
        """ces --json audit outputs valid JSON."""
        app = _get_app()
        services, _ = _build_e2e_services()

        @asynccontextmanager
        async def _fake_services(*args: Any, **kwargs: Any):
            del args, kwargs
            yield services

        old_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            (tmp_path / ".ces").mkdir(exist_ok=True)
            with patch("ces.cli.audit_cmd.get_services", new=_fake_services):
                result = runner.invoke(app, ["--json", "audit"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert isinstance(data, list)
        finally:
            os.chdir(old_cwd)
