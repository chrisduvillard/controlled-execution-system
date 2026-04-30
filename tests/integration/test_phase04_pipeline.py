"""Phase 4 integration tests -- cross-service pipeline validation.

Tests the full LLM + Agent Execution pipeline:
1. LLM Provider protocol conformance and model swapping
2. Agent Runner with kill switch integration
3. Sandbox execution with secret stripping
4. Chain of custody tracking across pipeline stages
5. End-to-end manifest-to-evidence flow
6. LLM-05 import boundary verification
"""

from __future__ import annotations

import ast
import os
import pathlib
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from ces.control.models.evidence_packet import ChainOfCustodyEntry
from ces.control.models.manifest import TaskManifest
from ces.control.services.kill_switch import KillSwitchProtocol, KillSwitchService
from ces.execution.agent_runner import (
    AgentRunner,
    AgentRunResult,
    KillSwitchActiveError,
)
from ces.execution.output_capture import CapturedOutput, OutputCapture
from ces.execution.providers.cli_provider import CLILLMProvider
from ces.execution.providers.demo_provider import DemoLLMProvider
from ces.execution.providers.protocol import (
    ChainOfCustodyTracker,
    LLMProviderProtocol,
    LLMResponse,
)
from ces.execution.providers.registry import ProviderRegistry
from ces.execution.sandbox import AgentSandbox, SandboxConfig
from ces.shared.enums import (
    ArtifactStatus,
    BehaviorConfidence,
    ChangeClass,
    RiskTier,
    WorkflowState,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(**overrides: object) -> TaskManifest:
    """Create a valid TaskManifest for testing with sensible defaults."""
    defaults: dict = dict(
        manifest_id="test-manifest-001",
        description="Test task",
        version=1,
        status=ArtifactStatus.APPROVED,
        owner="test-user",
        created_at=datetime.now(timezone.utc),
        last_confirmed=datetime.now(timezone.utc),
        signature="test-signature",
        risk_tier=RiskTier.B,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_2,
        affected_files=("src/test.py",),
        allowed_tools=("python", "pytest"),
        forbidden_tools=("rm",),
        token_budget=4096,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        workflow_state=WorkflowState.IN_FLIGHT,
    )
    defaults.update(overrides)
    return TaskManifest(**defaults)


class MockProvider:
    """Mock LLM provider that satisfies LLMProviderProtocol."""

    def __init__(self, name: str = "mock") -> None:
        self._name = name

    @property
    def provider_name(self) -> str:
        return self._name

    async def generate(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        return LLMResponse(
            content="mock response",
            model_id=model_id,
            model_version=f"{model_id}-20240101",
            input_tokens=100,
            output_tokens=50,
            provider_name=self._name,
        )

    async def stream(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ):  # type: ignore[no-untyped-def]
        for chunk in ["mock ", "stream ", "output"]:
            yield chunk


class MockKillSwitch:
    """Mock kill switch for testing."""

    def __init__(self, halted: bool = False) -> None:
        self._halted = halted

    def is_halted(self, activity_class: str) -> bool:
        return self._halted


# ---------------------------------------------------------------------------
# Test 1: Provider protocol conformance
# ---------------------------------------------------------------------------


class TestProviderProtocolConformance:
    """CLI and demo providers pass isinstance checks."""

    def test_provider_protocol_conformance(self) -> None:
        """CLILLMProvider and DemoLLMProvider satisfy LLMProviderProtocol."""
        with patch("shutil.which", return_value="/usr/bin/claude"):
            assert isinstance(CLILLMProvider("claude"), LLMProviderProtocol)
        assert isinstance(DemoLLMProvider(), LLMProviderProtocol)

    def test_mock_provider_also_conforms(self) -> None:
        """MockProvider also satisfies the protocol."""
        assert isinstance(MockProvider(), LLMProviderProtocol)


# ---------------------------------------------------------------------------
# Test 2: Model swapping via registry
# ---------------------------------------------------------------------------


class TestModelSwappingViaRegistry:
    """Register providers by prefix and verify correct resolution."""

    def test_model_swapping_via_registry(self) -> None:
        """Register mock Anthropic on 'claude' prefix and mock OpenAI on 'gpt' prefix."""
        registry = ProviderRegistry()
        anthropic_mock = MockProvider("anthropic")
        openai_mock = MockProvider("openai")

        registry.register("claude", anthropic_mock)
        registry.register("gpt", openai_mock)

        # Resolve by model_id prefix
        assert registry.get_provider("claude-3-opus").provider_name == "anthropic"
        assert registry.get_provider("gpt-4o").provider_name == "openai"

    def test_registry_unknown_prefix_raises(self) -> None:
        """Requesting an unregistered prefix raises KeyError."""
        registry = ProviderRegistry()
        with pytest.raises(KeyError, match="No provider registered"):
            registry.get_provider("llama-3")


# ---------------------------------------------------------------------------
# Test 3: Agent execution with LLM
# ---------------------------------------------------------------------------


class TestAgentExecutionWithLLM:
    """AgentRunner.execute() with mocked provider returns chain of custody."""

    @pytest.mark.asyncio
    async def test_agent_execution_with_llm(self) -> None:
        """Execute returns AgentRunResult with chain of custody containing model_version."""
        provider = MockProvider()
        kill_switch = MockKillSwitch(halted=False)
        runner = AgentRunner(provider=provider, kill_switch=kill_switch)

        manifest = _make_manifest()
        messages = [{"role": "user", "content": "Write a test"}]
        result = await runner.execute(manifest, messages, "mock-model")

        assert isinstance(result, AgentRunResult)
        assert result.llm_response is not None
        assert result.llm_response.content == "mock response"
        assert result.llm_response.model_version == "mock-model-20240101"
        assert len(result.chain_of_custody) == 1
        assert result.chain_of_custody[0].agent_model == "mock-model-20240101"


# ---------------------------------------------------------------------------
# Test 4: Kill switch blocks execution
# ---------------------------------------------------------------------------


class TestAgentExecutionKillSwitchBlocks:
    """AgentRunner.execute() raises KillSwitchActiveError when halted."""

    @pytest.mark.asyncio
    async def test_agent_execution_kill_switch_blocks(self) -> None:
        """Kill switch halted for task_issuance blocks execute()."""
        provider = MockProvider()
        kill_switch = MockKillSwitch(halted=True)
        runner = AgentRunner(provider=provider, kill_switch=kill_switch)

        manifest = _make_manifest()
        messages = [{"role": "user", "content": "Write a test"}]

        with pytest.raises(KillSwitchActiveError, match="halted by kill switch"):
            await runner.execute(manifest, messages, "mock-model")

    def test_kill_switch_blocks_command_execution(self) -> None:
        """Kill switch halted for task_issuance blocks execute_command()."""
        provider = MockProvider()
        kill_switch = MockKillSwitch(halted=True)
        runner = AgentRunner(provider=provider, kill_switch=kill_switch)

        manifest = _make_manifest()

        with pytest.raises(KillSwitchActiveError, match="halted by kill switch"):
            runner.execute_command(manifest, "python test.py")


# ---------------------------------------------------------------------------
# Test 5: Sandbox command policy enforcement
# ---------------------------------------------------------------------------


class TestSandboxCommandPolicyEnforcement:
    """AgentRunner.execute_command() enforces tool policy from manifest."""

    def test_sandbox_command_policy_enforcement(self) -> None:
        """Forbidden tool 'rm' returns policy_violations in AgentRunResult."""
        provider = MockProvider()
        kill_switch = MockKillSwitch(halted=False)
        runner = AgentRunner(provider=provider, kill_switch=kill_switch)

        manifest = _make_manifest(
            allowed_tools=("python", "pytest"),
            forbidden_tools=("rm", "curl"),
        )

        # "rm" is forbidden -- should return violation without creating container
        result = runner.execute_command(manifest, "rm -rf /tmp/data")

        assert isinstance(result, AgentRunResult)
        assert len(result.policy_violations) > 0
        assert any("rm" in v for v in result.policy_violations)


# ---------------------------------------------------------------------------
# Test 6: Sandbox secret stripping
# ---------------------------------------------------------------------------


class TestSandboxSecretStripping:
    """AgentSandbox._build_env strips secret-like keys from allowlist."""

    def test_sandbox_secret_stripping(self) -> None:
        """_build_env with allowlist strips API_KEY but keeps PATH."""
        # Set up host environment with both safe and secret vars
        with patch.dict(os.environ, {"PATH": "/usr/bin", "API_KEY": "sk-secret123"}):
            env = AgentSandbox._build_env(allowlist=["PATH", "API_KEY"])

        # PATH should be kept (not secret-like)
        assert "PATH" in env
        # API_KEY should be stripped (matches SECRET_KEY_PATTERNS)
        assert "API_KEY" not in env

    def test_strip_secrets_removes_value_prefixes(self) -> None:
        """_strip_secrets removes values starting with known API key prefixes."""
        env = {
            "SAFE_VAR": "some_value",
            "ANOTHER": "sk-live-secret-key-12345",
            "GITHUB": "ghp_abcdef123456",
        }
        result = AgentSandbox._strip_secrets(env)

        assert "SAFE_VAR" in result
        assert "ANOTHER" not in result  # sk- prefix
        assert "GITHUB" not in result  # ghp_ prefix

    def test_build_env_empty_without_allowlist(self) -> None:
        """_build_env returns empty dict when no allowlist is given."""
        env = AgentSandbox._build_env(allowlist=None)
        assert env == {}


# ---------------------------------------------------------------------------
# Test 7: Output capture truncation
# ---------------------------------------------------------------------------


class TestOutputCaptureTruncation:
    """OutputCapture with size limit truncates large output."""

    def test_output_capture_truncation(self) -> None:
        """OutputCapture with 100-byte limit on container producing 500 bytes."""
        mock_container = MagicMock()
        # 250 bytes stdout + 250 bytes stderr = 500 total
        mock_container.attach.return_value = iter([(b"x" * 250, b"e" * 250)])

        capture = OutputCapture(max_bytes=100)
        result = capture.capture(mock_container)

        assert isinstance(result, CapturedOutput)
        assert result.truncated is True
        assert result.bytes_read <= 100

    def test_output_capture_no_truncation(self) -> None:
        """Output within limit is not truncated."""
        mock_container = MagicMock()
        mock_container.attach.return_value = iter([(b"ok", b"")])

        capture = OutputCapture(max_bytes=1000)
        result = capture.capture(mock_container)

        assert result.truncated is False
        assert result.stdout == "ok"


# ---------------------------------------------------------------------------
# Test 8: Chain of custody tracks model version
# ---------------------------------------------------------------------------


class TestChainOfCustodyTracksModelVersion:
    """ChainOfCustodyTracker records correct model_version from LLMResponse."""

    def test_chain_of_custody_tracks_model_version(self) -> None:
        """record_call captures model_version from the LLMResponse."""
        tracker = ChainOfCustodyTracker()

        response = LLMResponse(
            content="test output",
            model_id="claude-3-opus",
            model_version="claude-3-opus-20240229",
            input_tokens=100,
            output_tokens=50,
            provider_name="anthropic",
        )

        entry = tracker.record_call(response, step="classification", agent_role="classifier")

        assert isinstance(entry, ChainOfCustodyEntry)
        assert entry.agent_model == "claude-3-opus-20240229"
        assert entry.step == "classification"
        assert entry.agent_role == "classifier"

    def test_chain_of_custody_multiple_entries(self) -> None:
        """Multiple record_call invocations accumulate entries."""
        tracker = ChainOfCustodyTracker()

        for i, model in enumerate(["claude-3", "gpt-4o", "claude-3.5"]):
            resp = LLMResponse(
                content=f"output-{i}",
                model_id=model,
                model_version=f"{model}-v1",
                input_tokens=50,
                output_tokens=25,
                provider_name="test",
            )
            tracker.record_call(resp, step=f"step-{i}", agent_role="agent")

        assert len(tracker.entries) == 3
        assert tracker.entries[0].agent_model == "claude-3-v1"
        assert tracker.entries[2].agent_model == "claude-3.5-v1"


# ---------------------------------------------------------------------------
# Test 9: End-to-end manifest to evidence
# ---------------------------------------------------------------------------


class TestEndToEndManifestToEvidence:
    """Create manifest -> run agent (mocked LLM) -> capture output -> chain of custody."""

    @pytest.mark.asyncio
    async def test_end_to_end_manifest_to_evidence(self) -> None:
        """Complete pipeline: manifest -> agent execution -> chain of custody -> all fields populated."""
        # 1. Create manifest
        manifest = _make_manifest(
            manifest_id="e2e-test-001",
            description="End-to-end pipeline test",
            allowed_tools=("python", "pytest"),
            forbidden_tools=("rm",),
            token_budget=8192,
        )
        assert manifest.workflow_state == WorkflowState.IN_FLIGHT

        # 2. Create AgentRunner with MockProvider + MockKillSwitch
        provider = MockProvider("test-provider")
        kill_switch = MockKillSwitch(halted=False)
        runner = AgentRunner(provider=provider, kill_switch=kill_switch)

        # 3. Execute LLM call and verify chain of custody
        messages = [{"role": "user", "content": "Implement the feature"}]
        result = await runner.execute(manifest, messages, "test-model-v1")

        # Verify all AgentRunResult fields
        assert result.llm_response is not None
        assert result.llm_response.content == "mock response"
        assert result.llm_response.model_id == "test-model-v1"
        assert result.llm_response.model_version == "test-model-v1-20240101"
        assert result.llm_response.provider_name == "test-provider"
        assert result.llm_response.input_tokens == 100
        assert result.llm_response.output_tokens == 50

        # Chain of custody is populated
        assert len(result.chain_of_custody) == 1
        custody_entry = result.chain_of_custody[0]
        assert custody_entry.agent_model == "test-model-v1-20240101"
        assert custody_entry.step == "builder_execution"
        assert custody_entry.agent_role == "builder"
        assert custody_entry.timestamp is not None

        # 4. Verify command execution with mocked Docker returns policy violation
        #    for forbidden tool
        forbidden_result = runner.execute_command(manifest, "rm -rf /data")
        assert len(forbidden_result.policy_violations) > 0

        # 5. Verify allowed command proceeds to sandbox (will hit Docker mock)
        #    We patch docker.from_env to avoid needing a real Docker daemon
        with patch("ces.execution.sandbox.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_container = MagicMock()
            mock_client.containers.run.return_value = mock_container
            mock_container.attach.return_value = iter([(b"test output", b"")])

            allowed_runner = AgentRunner(
                provider=provider,
                kill_switch=kill_switch,
                sandbox_config=SandboxConfig(max_output_bytes=1_048_576),
            )
            cmd_result = allowed_runner.execute_command(manifest, "python test.py")

            assert cmd_result.output is not None
            assert cmd_result.output.stdout == "test output"
            assert cmd_result.output.truncated is False
            assert len(cmd_result.policy_violations) == 0


# ---------------------------------------------------------------------------
# Test 10: LLM-05 import boundary verification
# ---------------------------------------------------------------------------

# Prohibited top-level modules (same as test_no_llm_imports.py)
_PROHIBITED_MODULES = frozenset(
    {
        "anthropic",
        "openai",
        "litellm",
        "langchain",
        "langchain_core",
        "langchain_community",
        "langchain_openai",
        "langchain_anthropic",
    }
)

_CONTROL_PLANE_DIRS = [
    pathlib.Path(__file__).resolve().parents[2] / "src" / "ces" / "control",
    pathlib.Path(__file__).resolve().parents[2] / "src" / "ces" / "shared",
]


class TestLLM05NoImportsInControlPlane:
    """LLM-05: After all Phase 4 additions, no LLM imports in control/shared planes."""

    def test_llm05_no_imports_in_control_plane(self) -> None:
        """Scan all .py files in ces/control/ and ces/shared/ for prohibited imports."""
        violations: list[str] = []

        for directory in _CONTROL_PLANE_DIRS:
            if not directory.is_dir():
                continue
            for filepath in sorted(directory.rglob("*.py")):
                source = filepath.read_text(encoding="utf-8")
                try:
                    tree = ast.parse(source, filename=str(filepath))
                except SyntaxError:
                    continue

                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            root = alias.name.split(".")[0]
                            if root in _PROHIBITED_MODULES:
                                relative = filepath.relative_to(pathlib.Path(__file__).resolve().parents[2] / "src")
                                violations.append(f"  {relative}:{node.lineno} imports '{root}'")
                    elif isinstance(node, ast.ImportFrom):
                        if node.module is not None:
                            root = node.module.split(".")[0]
                            if root in _PROHIBITED_MODULES:
                                relative = filepath.relative_to(pathlib.Path(__file__).resolve().parents[2] / "src")
                                violations.append(f"  {relative}:{node.lineno} imports '{root}'")

        assert violations == [], (
            f"LLM-05 violation after Phase 4: found {len(violations)} prohibited "
            f"LLM import(s) in control/shared plane:\n" + "\n".join(violations)
        )
