"""Runtime protocol and result models for local agent CLI execution."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from ces.harness.models.completion_claim import CompletionClaim
from ces.shared.base import CESBaseModel


class AgentRuntimeResult(CESBaseModel):
    """Captured result from invoking an external agent runtime.

    ``completion_claim`` is populated post-hoc by ``AgentRunner.execute_runtime``
    when the agent emitted a ``ces:completion`` block in its stdout. Adapters
    leave it ``None``; the agent runner re-creates the result with the parsed
    claim attached. See ``ces.execution.completion_parser``.
    """

    runtime_name: str
    runtime_version: str
    reported_model: str | None = None
    invocation_ref: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    transcript_path: str | None = None
    completion_claim: CompletionClaim | None = None


@runtime_checkable
class AgentRuntimeProtocol(Protocol):
    """Protocol implemented by local runtime adapters."""

    runtime_name: str

    def detect(self) -> bool:
        """Return True when the runtime binary is available."""

    def version(self) -> str:
        """Return the runtime version string."""

    def run_task(
        self,
        manifest_description: str,
        prompt_pack: str,
        working_dir: Path,
        allowed_tools: tuple[str, ...] = (),
    ) -> AgentRuntimeResult:
        """Execute a task non-interactively in the given working directory.

        Args:
            manifest_description: Human-readable task description.
            prompt_pack: Full prompt content for the runtime.
            working_dir: Directory to run in (passed via --add-dir / -C).
            allowed_tools: Allowlist of agent tools (empty tuple = runtime
                default; explicit tuple = exactly those tools). Adapters
                that understand tool allowlists (e.g. Claude) honour this;
                others (e.g. Codex) rely on their own runtime-boundary flags.
        """

    def summarize_evidence(self, evidence_context: dict) -> tuple[str, str]:
        """Return summary/challenge text for the evidence context."""

    def generate_manifest_assist(
        self,
        truth_artifacts: dict,
        description: str,
    ) -> dict:
        """Return a manifest proposal-like dictionary for the task."""
