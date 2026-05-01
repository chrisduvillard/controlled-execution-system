"""Tests for AgentRunner service orchestrating LLM/runtime execution and policy.

Tests verify:
- AgentRunner accepts LLMProviderProtocol and KillSwitchProtocol
- Kill switch halts execution before any work
- Manifest workflow state validation
- LLM calls with token budget enforcement
- Chain of custody tracking for every LLM call
- Policy enforcement via PolicyEngine.check_tool_access
- AgentRunResult model with correct fields
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from ces.control.models.evidence_packet import ChainOfCustodyEntry
from ces.control.models.manifest import TaskManifest
from ces.control.services.policy_engine import PolicyEngine
from ces.execution.agent_runner import AgentRunner, AgentRunResult, KillSwitchActiveError
from ces.execution.output_capture import CapturedOutput
from ces.execution.providers.protocol import (
    ChainOfCustodyTracker,
    LLMProviderProtocol,
    LLMResponse,
)
from ces.shared.base import CESBaseModel
from ces.shared.enums import (
    ArtifactStatus,
    BehaviorConfidence,
    ChangeClass,
    RiskTier,
    WorkflowState,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_manifest(
    workflow_state: WorkflowState = WorkflowState.IN_FLIGHT,
    allowed_tools: tuple[str, ...] | None = None,
    forbidden_tools: tuple[str, ...] | None = None,
    token_budget: int = 4096,
    expires_at: datetime | None = None,
) -> TaskManifest:
    """Create a minimal TaskManifest for testing."""
    now = datetime.now(timezone.utc)
    return TaskManifest(
        manifest_id="test-manifest-001",
        description="Test manifest",
        version=1,
        status=ArtifactStatus.APPROVED,
        owner="test-owner",
        created_at=now,
        last_confirmed=now,
        signature="test-sig",
        risk_tier=RiskTier.C,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_1,
        affected_files=("src/**/*.py",),
        forbidden_files=(),
        allowed_tools=allowed_tools or ("python", "pytest", "ruff"),
        forbidden_tools=forbidden_tools or ("rm", "curl"),
        token_budget=token_budget,
        expires_at=expires_at or datetime(2099, 1, 1, tzinfo=timezone.utc),
        workflow_state=workflow_state,
    )


def _make_llm_response() -> LLMResponse:
    """Create a minimal LLMResponse for testing."""
    return LLMResponse(
        content="Generated code here",
        model_id="claude-3-opus",
        model_version="claude-3-opus-20240229",
        input_tokens=100,
        output_tokens=200,
        provider_name="anthropic",
    )


class MockProvider:
    """Mock LLM provider implementing LLMProviderProtocol."""

    def __init__(self, response: LLMResponse | None = None) -> None:
        self._response = response or _make_llm_response()
        self.generate = AsyncMock(return_value=self._response)
        self.stream = AsyncMock()

    @property
    def provider_name(self) -> str:
        return "mock"


class MockKillSwitch:
    """Mock kill switch implementing KillSwitchProtocol."""

    def __init__(self, halted: bool = False) -> None:
        self._halted = halted

    def is_halted(self, activity_class: str) -> bool:
        return self._halted


class MockRuntime:
    """Mock runtime implementing AgentRuntimeProtocol."""

    runtime_name = "mock-runtime"

    def __init__(self) -> None:
        self.run_task = MagicMock()
        self.run_task.return_value = MagicMock(
            runtime_name="mock-runtime",
            runtime_version="1.0",
            reported_model=None,
            invocation_ref="run-123",
            exit_code=0,
            stdout="done",
            stderr="",
            duration_seconds=1.0,
        )


# ---------------------------------------------------------------------------
# Test AgentRunResult model
# ---------------------------------------------------------------------------


class TestAgentRunResult:
    """Test AgentRunResult frozen model."""

    def test_agent_run_result_is_ces_base_model(self) -> None:
        """AgentRunResult inherits from CESBaseModel."""
        assert issubclass(AgentRunResult, CESBaseModel)

    def test_agent_run_result_fields(self) -> None:
        """AgentRunResult has output, llm_response, chain_of_custody, policy_violations fields."""
        result = AgentRunResult(
            output=CapturedOutput(stdout="hi", stderr="", truncated=False, bytes_read=2),
            llm_response=_make_llm_response(),
            chain_of_custody=[],
            policy_violations=[],
            truncated_output=False,
        )
        assert result.output is not None
        assert result.llm_response is not None
        assert result.chain_of_custody == []
        assert result.policy_violations == []
        assert result.truncated_output is False

    def test_agent_run_result_defaults(self) -> None:
        """AgentRunResult has sensible defaults for optional fields."""
        result = AgentRunResult()
        assert result.output is None
        assert result.llm_response is None
        assert result.chain_of_custody == []
        assert result.policy_violations == []
        assert result.truncated_output is False


# ---------------------------------------------------------------------------
# Test AgentRunner.__init__
# ---------------------------------------------------------------------------


class TestAgentRunnerInit:
    """Test AgentRunner constructor."""

    def test_accepts_protocols(self) -> None:
        """AgentRunner.__init__ accepts LLMProviderProtocol and KillSwitchProtocol."""
        provider = MockProvider()
        kill_switch = MockKillSwitch()

        runner = AgentRunner(
            provider=provider,
            kill_switch=kill_switch,
        )

        assert runner._provider is provider
        assert runner._kill_switch is kill_switch


# ---------------------------------------------------------------------------
# Test AgentRunner.execute (LLM calls)
# ---------------------------------------------------------------------------


class TestAgentRunnerExecute:
    """Test AgentRunner.execute() for LLM calls."""

    @pytest.mark.asyncio
    async def test_kill_switch_blocks_execution(self) -> None:
        """execute() raises KillSwitchActiveError when kill switch is halted."""
        runner = AgentRunner(
            provider=MockProvider(),
            kill_switch=MockKillSwitch(halted=True),
        )
        manifest = _make_manifest()

        with pytest.raises(KillSwitchActiveError, match="kill switch"):
            await runner.execute(manifest, messages=[], model_id="claude-3-opus")

    @pytest.mark.asyncio
    async def test_validates_workflow_state_in_flight(self) -> None:
        """execute() raises ValueError if manifest.workflow_state != IN_FLIGHT."""
        runner = AgentRunner(
            provider=MockProvider(),
            kill_switch=MockKillSwitch(),
        )
        manifest = _make_manifest(workflow_state=WorkflowState.QUEUED)

        with pytest.raises(ValueError, match="IN_FLIGHT"):
            await runner.execute(manifest, messages=[], model_id="claude-3-opus")

    @pytest.mark.asyncio
    async def test_rejects_expired_manifest(self) -> None:
        """execute() raises ValueError when the manifest has expired."""
        runner = AgentRunner(
            provider=MockProvider(),
            kill_switch=MockKillSwitch(),
        )
        manifest = _make_manifest(expires_at=datetime(2000, 1, 1, tzinfo=timezone.utc))

        with pytest.raises(ValueError, match="expired"):
            await runner.execute(manifest, messages=[], model_id="claude-3-opus")

    @pytest.mark.asyncio
    async def test_calls_llm_with_token_budget(self) -> None:
        """execute() calls LLM provider.generate() with manifest.token_budget as max_tokens."""
        provider = MockProvider()
        runner = AgentRunner(
            provider=provider,
            kill_switch=MockKillSwitch(),
        )
        manifest = _make_manifest(token_budget=2048)
        messages = [{"role": "user", "content": "Generate code"}]

        result = await runner.execute(manifest, messages=messages, model_id="claude-3-opus")

        provider.generate.assert_awaited_once_with(
            model_id="claude-3-opus",
            messages=messages,
            max_tokens=2048,
        )
        assert result.llm_response is not None

    @pytest.mark.asyncio
    async def test_chain_of_custody_tracked(self) -> None:
        """execute() tracks chain of custody via ChainOfCustodyTracker.record_call()."""
        provider = MockProvider()
        runner = AgentRunner(
            provider=provider,
            kill_switch=MockKillSwitch(),
        )
        manifest = _make_manifest()

        result = await runner.execute(
            manifest,
            messages=[{"role": "user", "content": "test"}],
            model_id="claude-3-opus",
        )

        assert len(result.chain_of_custody) == 1
        entry = result.chain_of_custody[0]
        assert entry.step == "builder_execution"
        assert entry.agent_role == "builder"
        assert entry.agent_model == "claude-3-opus-20240229"


# ---------------------------------------------------------------------------
# Test AgentRunner.execute_command (legacy direct command path)
# ---------------------------------------------------------------------------


class TestAgentRunnerExecuteCommand:
    """Test AgentRunner.execute_command() policy and fail-closed behavior."""

    def test_policy_violation_blocks_command(self) -> None:
        """execute_command() returns policy_violations when command is blocked."""
        runner = AgentRunner(
            provider=MockProvider(),
            kill_switch=MockKillSwitch(),
        )
        manifest = _make_manifest(
            allowed_tools=("python", "pytest"),
            forbidden_tools=("rm", "curl"),
        )

        result = runner.execute_command(manifest, "curl http://example.com")

        assert len(result.policy_violations) > 0
        assert "curl" in result.policy_violations[0]

    def test_allowed_direct_command_fails_closed(self) -> None:
        """execute_command() rejects allowed direct commands and points callers at runtimes."""
        runner = AgentRunner(
            provider=MockProvider(),
            kill_switch=MockKillSwitch(),
        )
        manifest = _make_manifest(allowed_tools=("python",))

        result = runner.execute_command(manifest, "python script.py")

        assert result.output is None
        assert result.truncated_output is False
        assert result.policy_violations == [
            "Direct command execution is no longer supported; use execute_runtime() with a local runtime adapter"
        ]

    def test_kill_switch_blocks_command(self) -> None:
        """execute_command raises KillSwitchActiveError when kill switch is halted."""
        runner = AgentRunner(
            provider=MockProvider(),
            kill_switch=MockKillSwitch(halted=True),
        )
        manifest = _make_manifest()

        with pytest.raises(KillSwitchActiveError, match="kill switch"):
            runner.execute_command(manifest, "python script.py")

    def test_expired_manifest_blocks_command(self) -> None:
        """execute_command() rejects expired manifests before sandboxing."""
        runner = AgentRunner(
            provider=MockProvider(),
            kill_switch=MockKillSwitch(),
        )
        manifest = _make_manifest(expires_at=datetime(2000, 1, 1, tzinfo=timezone.utc))

        with pytest.raises(ValueError, match="expired"):
            runner.execute_command(manifest, "python script.py")


class TestAgentRunnerExecuteRuntime:
    """Test AgentRunner.execute_runtime() preconditions and custody."""

    @pytest.mark.asyncio
    async def test_runtime_rejects_non_in_flight_manifest(self) -> None:
        runner = AgentRunner(
            provider=MockProvider(),
            kill_switch=MockKillSwitch(),
        )
        manifest = _make_manifest(workflow_state=WorkflowState.QUEUED)

        with pytest.raises(ValueError, match="IN_FLIGHT"):
            await runner.execute_runtime(
                manifest=manifest,
                runtime=MockRuntime(),
                prompt_pack="prompt",
                working_dir=MagicMock(),
            )

    @pytest.mark.asyncio
    async def test_runtime_rejects_expired_manifest(self) -> None:
        runner = AgentRunner(
            provider=MockProvider(),
            kill_switch=MockKillSwitch(),
        )
        manifest = _make_manifest(expires_at=datetime(2000, 1, 1, tzinfo=timezone.utc))

        with pytest.raises(ValueError, match="expired"):
            await runner.execute_runtime(
                manifest=manifest,
                runtime=MockRuntime(),
                prompt_pack="prompt",
                working_dir=MagicMock(),
            )


# ---------------------------------------------------------------------------
# CompletionClaim parsing + repair_context (P1d, P2)
# ---------------------------------------------------------------------------


class _RuntimeStub:
    """Lightweight runtime stub returning a real AgentRuntimeResult."""

    runtime_name = "stub"

    def __init__(self, stdout: str) -> None:
        from ces.execution.runtimes.protocol import AgentRuntimeResult

        self._result = AgentRuntimeResult(
            runtime_name="stub",
            runtime_version="0.0",
            reported_model=None,
            invocation_ref="stub-123",
            exit_code=0,
            stdout=stdout,
            stderr="",
            duration_seconds=0.1,
        )
        self.last_prompt: str | None = None

    def run_task(
        self,
        manifest_description: str,
        prompt_pack: str,
        working_dir,
        allowed_tools=(),
    ):
        self.last_prompt = prompt_pack
        return self._result


class TestAgentRunnerClaimParsing:
    """execute_runtime parses the agent's ces:completion block and attaches it."""

    @pytest.mark.asyncio
    async def test_claim_attached_when_present(self) -> None:
        runner = AgentRunner(provider=MockProvider(), kill_switch=MockKillSwitch())
        manifest = _make_manifest()
        stdout = (
            "Working...\n\n"
            "```ces:completion\n"
            '{"task_id": "test-manifest-001", "summary": "did it", "files_changed": ["src/a.py"]}\n'
            "```\n"
            "Done.\n"
        )
        runtime = _RuntimeStub(stdout=stdout)
        result = await runner.execute_runtime(
            manifest=manifest,
            runtime=runtime,
            prompt_pack="initial prompt",
            working_dir=MagicMock(),
        )
        assert result.runtime_result is not None
        assert result.runtime_result.completion_claim is not None
        assert result.runtime_result.completion_claim.task_id == "test-manifest-001"
        assert result.runtime_result.completion_claim.files_changed == ("src/a.py",)

    @pytest.mark.asyncio
    async def test_claim_none_when_no_block(self) -> None:
        runner = AgentRunner(provider=MockProvider(), kill_switch=MockKillSwitch())
        manifest = _make_manifest()
        runtime = _RuntimeStub(stdout="agent forgot to emit a claim\n")
        result = await runner.execute_runtime(
            manifest=manifest,
            runtime=runtime,
            prompt_pack="initial prompt",
            working_dir=MagicMock(),
        )
        assert result.runtime_result is not None
        assert result.runtime_result.completion_claim is None

    @pytest.mark.asyncio
    async def test_repair_context_appended_to_prompt(self) -> None:
        runner = AgentRunner(provider=MockProvider(), kill_switch=MockKillSwitch())
        manifest = _make_manifest()
        runtime = _RuntimeStub(stdout="ok")
        await runner.execute_runtime(
            manifest=manifest,
            runtime=runtime,
            prompt_pack="initial prompt",
            working_dir=MagicMock(),
            repair_context="VERIFICATION FINDINGS:\n- tests failing",
        )
        assert runtime.last_prompt is not None
        assert "initial prompt" in runtime.last_prompt
        assert "VERIFICATION FINDINGS" in runtime.last_prompt

    @pytest.mark.asyncio
    async def test_no_repair_context_keeps_prompt_unchanged(self) -> None:
        runner = AgentRunner(provider=MockProvider(), kill_switch=MockKillSwitch())
        manifest = _make_manifest()
        runtime = _RuntimeStub(stdout="ok")
        await runner.execute_runtime(
            manifest=manifest,
            runtime=runtime,
            prompt_pack="initial prompt",
            working_dir=MagicMock(),
        )
        assert runtime.last_prompt == "initial prompt"
