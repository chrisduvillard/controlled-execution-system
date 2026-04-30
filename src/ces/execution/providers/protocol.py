"""LLM provider protocol, response model, error types, and chain of custody tracker.

Defines the core abstraction for all LLM providers in CES:
- LLMResponse: Frozen model capturing response content + token usage for chain of custody
- LLMError: Exception with provider context for error handling
- LLMProviderProtocol: Runtime-checkable protocol for provider implementations
- ChainOfCustodyTracker: Records per-LLM-call custody entries (LLM-04)

T-04-01 mitigation: CLI auth state and provider secrets are never stored in
LLMResponse or logged.
T-04-03 mitigation: max_tokens is required on every generate/stream call.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from ces.control.models.evidence_packet import ChainOfCustodyEntry
from ces.shared.base import CESBaseModel


class LLMResponse(CESBaseModel):
    """Immutable response from an LLM provider call.

    Every field is required -- callers always know exactly what model
    produced the response and how many tokens were consumed.
    """

    content: str
    model_id: str
    model_version: str
    input_tokens: int
    output_tokens: int
    provider_name: str


class LLMError(Exception):
    """Error from an LLM provider with context for diagnostics.

    Attributes:
        provider_name: Which provider raised the error (e.g. "claude-cli", "codex-cli", "demo").
        model_id: Which model was being called.
        original_error: The underlying SDK exception, if any.
    """

    def __init__(
        self,
        message: str,
        provider_name: str,
        model_id: str,
        original_error: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.provider_name = provider_name
        self.model_id = model_id
        self.original_error = original_error


@runtime_checkable
class LLMProviderProtocol(Protocol):
    """Protocol for LLM provider implementations.

    Runtime-checkable so callers can verify provider conformance
    with isinstance(provider, LLMProviderProtocol).

    All providers must support:
    - provider_name: identifier for the provider
    - generate(): single-shot response
    - stream(): async iterator of text chunks
    """

    @property
    def provider_name(self) -> str:
        """Provider identifier (e.g. 'claude-cli', 'codex-cli', or 'demo')."""
        ...

    async def generate(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Generate a complete response.

        Args:
            model_id: Model to use (e.g. 'claude-3-opus', 'gpt-5.4').
            messages: Conversation messages in [{role, content}] format.
            max_tokens: Maximum tokens in the response (T-04-03).
            temperature: Sampling temperature.

        Returns:
            LLMResponse with content and token usage.

        Raises:
            LLMError: On provider failure.
        """
        ...

    def stream(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> AsyncIterator[str]:
        """Stream response text chunks.

        Args:
            model_id: Model to use.
            messages: Conversation messages.
            max_tokens: Maximum tokens (T-04-03).
            temperature: Sampling temperature.

        Yields:
            Text chunks as they arrive from the provider.

        Raises:
            LLMError: On provider failure.
        """
        ...


class ChainOfCustodyTracker:
    """Tracks which LLM models performed each pipeline step (LLM-04).

    Records a ChainOfCustodyEntry for every LLM call, capturing the
    model_version from the response for audit trail purposes.
    """

    def __init__(self) -> None:
        self._entries: list[ChainOfCustodyEntry] = []

    def record_call(
        self,
        response: LLMResponse,
        step: str,
        agent_role: str,
    ) -> ChainOfCustodyEntry:
        """Record an LLM call in the chain of custody.

        Args:
            response: The LLMResponse from the provider call.
            step: Pipeline step name (e.g. 'classification', 'review').
            agent_role: Role of the agent making the call (e.g. 'classifier').

        Returns:
            The created ChainOfCustodyEntry.
        """
        entry = ChainOfCustodyEntry(
            step=step,
            agent_model=response.model_version,
            agent_role=agent_role,
            timestamp=datetime.now(timezone.utc),
        )
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> list[ChainOfCustodyEntry]:
        """Return a copy of all recorded entries in chronological order."""
        return list(self._entries)
