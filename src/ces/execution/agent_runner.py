"""Agent execution engine (EXEC-01, EXEC-02, EXEC-03).

Orchestrates the complete agent execution flow:
1. Kill switch check (KILL-04 hard enforcement)
2. Manifest boundary validation (WORK-04 via PolicyEngine)
3. LLM call with token budget enforcement
4. Local runtime adapter execution
5. Chain of custody tracking (LLM-04)

Threat mitigations:
- T-04-08: PolicyEngine.check_tool_access validates command before execution
- T-04-09: Kill switch can halt all task_issuance activity

Exports:
    KillSwitchActiveError: Raised when kill switch blocks execution.
    AgentRunResult: Frozen result model with output, LLM response, custody, violations.
    AgentRunner: Service orchestrating LLM/runtime execution + policy enforcement.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ces.control.models.evidence_packet import ChainOfCustodyEntry
from ces.control.models.manifest import TaskManifest
from ces.control.services.kill_switch import KillSwitchProtocol
from ces.control.services.policy_engine import PolicyEngine
from ces.execution.completion_parser import parse_completion_claim
from ces.execution.output_capture import CapturedOutput
from ces.execution.providers.protocol import (
    ChainOfCustodyTracker,
    LLMProviderProtocol,
    LLMResponse,
)
from ces.execution.runtimes.protocol import AgentRuntimeProtocol, AgentRuntimeResult
from ces.shared.base import CESBaseModel
from ces.shared.enums import WorkflowState


class KillSwitchActiveError(RuntimeError):
    """Raised when an operation is blocked by the kill switch (KILL-04)."""


class AgentRunResult(CESBaseModel):
    """Result of an agent execution.

    Frozen model capturing the complete execution result:
    - output: Captured stdout/stderr from legacy direct command execution
    - llm_response: LLM provider response (if LLM was called)
    - chain_of_custody: All LLM call entries for audit trail
    - policy_violations: Any policy violations detected
    - truncated_output: True if output was truncated (for DisclosureSet)
    """

    output: CapturedOutput | None = None
    llm_response: LLMResponse | None = None
    runtime_result: AgentRuntimeResult | None = None
    chain_of_custody: list[ChainOfCustodyEntry] = []
    policy_violations: list[str] = []
    truncated_output: bool = False


class AgentRunner:
    """Agent execution engine (EXEC-01, EXEC-02, EXEC-03).

    Orchestrates:
    1. Kill switch check (KILL-04 hard enforcement)
    2. Manifest boundary validation (WORK-04 via PolicyEngine)
    3. LLM call with token budget enforcement
    4. Local runtime adapter execution
    5. Chain of custody tracking (LLM-04)
    """

    def __init__(
        self,
        kill_switch: KillSwitchProtocol,
        provider: LLMProviderProtocol | None = None,
    ) -> None:
        """Initialize the agent runner.

        Args:
            provider: LLM provider for generate/stream calls.
            kill_switch: Kill switch for hard enforcement checks.
        """
        self._provider = provider
        self._kill_switch = kill_switch
        self._custody_tracker = ChainOfCustodyTracker()

    def _enforce_execution_preconditions(self, manifest: TaskManifest) -> None:
        """Fail closed when execution is halted, stale, or in the wrong state."""
        if self._kill_switch.is_halted("task_issuance"):
            raise KillSwitchActiveError("Agent execution halted by kill switch")

        if manifest.is_expired:
            msg = f"Manifest {manifest.manifest_id} has expired"
            raise ValueError(msg)

        if manifest.workflow_state != WorkflowState.IN_FLIGHT:
            msg = f"Manifest must be IN_FLIGHT, got {manifest.workflow_state}"
            raise ValueError(msg)

    async def execute(
        self,
        manifest: TaskManifest,
        messages: list[dict[str, str]],
        model_id: str,
    ) -> AgentRunResult:
        """Execute an LLM call within manifest boundaries.

        Steps:
        1. Check kill switch -- abort if halted
        2. Validate manifest is IN_FLIGHT
        3. Call LLM with token budget
        4. Record chain of custody

        Args:
            manifest: TaskManifest bounding the execution.
            messages: Conversation messages for the LLM.
            model_id: Model to use for the call.

        Returns:
            AgentRunResult with LLM response and chain of custody.

        Raises:
            KillSwitchActiveError: If kill switch is active for task_issuance.
            ValueError: If manifest workflow_state is not IN_FLIGHT.
        """
        # 1-2. Kill switch + manifest state checks
        self._enforce_execution_preconditions(manifest)

        # 3. LLM call with token budget
        if self._provider is None:
            raise RuntimeError("No LLM provider configured for direct provider execution")
        response = await self._provider.generate(
            model_id=model_id,
            messages=messages,
            max_tokens=manifest.token_budget,
        )

        # 4. Track chain of custody (LLM-04)
        self._custody_tracker.record_call(response, step="builder_execution", agent_role="builder")

        return AgentRunResult(
            llm_response=response,
            chain_of_custody=self._custody_tracker.entries,
        )

    async def execute_runtime(
        self,
        manifest: TaskManifest,
        runtime: AgentRuntimeProtocol,
        prompt_pack: str,
        working_dir: Path,
        repair_context: str | None = None,
    ) -> AgentRunResult:
        """Execute a task using a local runtime adapter.

        Parses the agent's ``ces:completion`` block from stdout and attaches
        the resulting :class:`CompletionClaim` to the runtime result so the
        Completion Gate can verify it (P1d).

        ``repair_context`` is appended to the prompt_pack on retry attempts so
        the agent sees the verification findings from the previous run (P2).
        """
        self._enforce_execution_preconditions(manifest)

        full_prompt = prompt_pack if not repair_context else f"{prompt_pack}\n\n{repair_context}"

        result = runtime.run_task(
            manifest_description=manifest.description,
            prompt_pack=full_prompt,
            working_dir=working_dir,
            allowed_tools=tuple(manifest.allowed_tools),
        )

        # Parse the agent's completion claim from stdout (P1d).
        claim = parse_completion_claim(result.stdout)
        if claim is not None:
            result = result.model_copy(update={"completion_claim": claim})

        entry = ChainOfCustodyEntry(
            step="builder_execution",
            agent_model=result.reported_model or f"{result.runtime_name}:default",
            agent_role="builder",
            timestamp=datetime.now(timezone.utc),
            runtime_name=result.runtime_name,
            runtime_version=result.runtime_version,
            reported_model=result.reported_model,
            invocation_ref=result.invocation_ref,
        )
        return AgentRunResult(
            runtime_result=result,
            chain_of_custody=[entry],
        )

    def execute_command(
        self,
        manifest: TaskManifest,
        command: str,
    ) -> AgentRunResult:
        """Reject legacy direct command execution after policy validation.

        Steps:
        1. Check kill switch -- abort if halted
        2. Validate command against manifest allowlist/blocklist
        3. Fail closed and require a local runtime adapter

        Args:
            manifest: TaskManifest bounding the execution.
            command: Shell command requested by legacy callers.

        Returns:
            AgentRunResult with policy violations for blocked or unsupported execution.

        Raises:
            KillSwitchActiveError: If kill switch is active for task_issuance.
        """
        # 1. Kill switch + manifest state checks (KILL-04 hard enforcement)
        self._enforce_execution_preconditions(manifest)

        # 2. Policy check -- validate command tool against manifest boundaries
        tool = command.split(maxsplit=1)[0] if command.strip() else ""
        if not PolicyEngine.check_tool_access(tool, manifest.allowed_tools, manifest.forbidden_tools):
            return AgentRunResult(policy_violations=[f"Tool '{tool}' not allowed by manifest"])

        return AgentRunResult(
            policy_violations=[
                "Direct command execution is no longer supported; use execute_runtime() with a local runtime adapter"
            ],
        )
