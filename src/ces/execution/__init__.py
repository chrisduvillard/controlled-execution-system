"""Execution plane public exports.

The module keeps imports lazy so plain installs can import ``ces`` and run the
core CLI without optional LLM provider packages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ces.execution.agent_runner import AgentRunner, AgentRunResult, KillSwitchActiveError
    from ces.execution.output_capture import CapturedOutput, OutputCapture
    from ces.execution.providers import (
        ChainOfCustodyTracker,
        CLILLMProvider,
        DemoLLMProvider,
        LLMError,
        LLMProviderProtocol,
        LLMResponse,
        ProviderRegistry,
    )
    from ces.execution.runtimes import (
        AgentRuntimeProtocol,
        AgentRuntimeResult,
        ClaudeRuntimeAdapter,
        CodexRuntimeAdapter,
        RuntimeRegistry,
    )
    from ces.execution.secrets import build_allowed_env, scrub_secrets_from_text, strip_secret_env

__all__ = [
    "AgentRunResult",
    "AgentRunner",
    "AgentRuntimeProtocol",
    "AgentRuntimeResult",
    "CLILLMProvider",
    "CapturedOutput",
    "ChainOfCustodyTracker",
    "ClaudeRuntimeAdapter",
    "CodexRuntimeAdapter",
    "DemoLLMProvider",
    "KillSwitchActiveError",
    "LLMError",
    "LLMProviderProtocol",
    "LLMResponse",
    "OutputCapture",
    "ProviderRegistry",
    "RuntimeRegistry",
    "build_allowed_env",
    "scrub_secrets_from_text",
    "strip_secret_env",
]


def __getattr__(name: str) -> Any:
    """Resolve execution exports lazily to keep optional deps optional."""
    if name in {"AgentRunner", "AgentRunResult", "KillSwitchActiveError"}:
        from ces.execution.agent_runner import AgentRunner, AgentRunResult, KillSwitchActiveError

        return {
            "AgentRunner": AgentRunner,
            "AgentRunResult": AgentRunResult,
            "KillSwitchActiveError": KillSwitchActiveError,
        }[name]
    if name in {"CapturedOutput", "OutputCapture"}:
        from ces.execution.output_capture import CapturedOutput, OutputCapture

        return {
            "CapturedOutput": CapturedOutput,
            "OutputCapture": OutputCapture,
        }[name]
    if name in {
        "CLILLMProvider",
        "ChainOfCustodyTracker",
        "DemoLLMProvider",
        "LLMError",
        "LLMProviderProtocol",
        "LLMResponse",
        "ProviderRegistry",
    }:
        from ces.execution import providers as providers_module

        return getattr(providers_module, name)
    if name in {
        "AgentRuntimeProtocol",
        "AgentRuntimeResult",
        "ClaudeRuntimeAdapter",
        "CodexRuntimeAdapter",
        "RuntimeRegistry",
    }:
        from ces.execution import runtimes as runtimes_module

        return getattr(runtimes_module, name)
    if name in {"build_allowed_env", "scrub_secrets_from_text", "strip_secret_env"}:
        from ces.execution import secrets as secrets_module

        return getattr(secrets_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
