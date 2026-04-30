"""Shared provider bootstrap for CLI-backed and demo-mode execution."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from ces.execution.providers.protocol import LLMProviderProtocol, LLMResponse
from ces.execution.providers.registry import ProviderRegistry


class _NullLLMProvider:
    """Placeholder provider used when no CLI-backed or demo provider is available."""

    @property
    def provider_name(self) -> str:
        return "null"

    async def generate(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        del model_id, messages, max_tokens, temperature
        raise RuntimeError(
            "No LLM provider configured. Configure one of the following:\n"
            "  - install/authenticate the 'claude' CLI\n"
            "  - install/authenticate the 'codex' CLI\n"
            "  - export CES_DEMO_MODE=1 for an offline demo provider\n"
            "Run 'ces doctor' for a full pre-flight check."
        )

    async def stream(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> AsyncIterator[str]:
        del model_id, messages, max_tokens, temperature
        raise RuntimeError("No LLM provider configured.")
        yield ""


def register_cli_fallback(provider_registry: ProviderRegistry, settings: Any) -> LLMProviderProtocol:
    """Register CLI-backed providers or demo mode on a registry."""
    import shutil

    from ces.execution.providers.cli_provider import CLILLMProvider

    def _register_if_free(prefix: str, provider: LLMProviderProtocol) -> None:
        try:
            provider_registry.get_provider(prefix)
        except KeyError:
            provider_registry.register(prefix, provider)

    claude_available = shutil.which("claude") is not None
    codex_available = shutil.which("codex") is not None

    primary: LLMProviderProtocol | None = None
    claude_timeout = 300
    codex_timeout = 600

    if claude_available:
        claude_provider = CLILLMProvider(cli_tool="claude", timeout=claude_timeout)
        _register_if_free("claude", claude_provider)
        primary = claude_provider

    if codex_available:
        codex_provider = CLILLMProvider(cli_tool="codex", timeout=codex_timeout)
        _register_if_free("gpt", codex_provider)
        if primary is None:
            primary = codex_provider

    if claude_available and not codex_available:
        _register_if_free("gpt", CLILLMProvider(cli_tool="claude", timeout=claude_timeout))
    if codex_available and not claude_available:
        _register_if_free("claude", CLILLMProvider(cli_tool="codex", timeout=codex_timeout))

    if primary is not None:
        return primary

    if settings.demo_mode:
        from ces.execution.providers.demo_provider import DemoLLMProvider

        demo_provider = DemoLLMProvider()
        for prefix in ("claude", "gpt", "demo"):
            _register_if_free(prefix, demo_provider)
        return demo_provider

    return _NullLLMProvider()


def resolve_primary_provider(
    provider_registry: ProviderRegistry,
    default_model_id: str,
) -> LLMProviderProtocol | None:
    """Resolve the preferred provider using the default model, then known fallbacks."""
    for candidate in (default_model_id, "claude", "gpt", "demo"):
        try:
            return provider_registry.get_provider(candidate)
        except KeyError:
            continue
    return None


def build_provider_registry(settings: Any) -> tuple[ProviderRegistry, LLMProviderProtocol]:
    """Build a provider registry backed only by local CLIs or demo mode."""
    provider_registry = ProviderRegistry()
    fallback_provider = register_cli_fallback(provider_registry, settings)
    llm_provider = resolve_primary_provider(provider_registry, settings.default_model_id) or fallback_provider
    return provider_registry, llm_provider
