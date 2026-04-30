"""Local runtime adapters for external agent CLIs."""

from ces.execution.runtimes.adapters import ClaudeRuntimeAdapter, CodexRuntimeAdapter
from ces.execution.runtimes.protocol import AgentRuntimeProtocol, AgentRuntimeResult
from ces.execution.runtimes.registry import RuntimeRegistry

__all__ = [
    "AgentRuntimeProtocol",
    "AgentRuntimeResult",
    "ClaudeRuntimeAdapter",
    "CodexRuntimeAdapter",
    "RuntimeRegistry",
]
