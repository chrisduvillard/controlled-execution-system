"""Tests for ProviderRegistry -- model-to-provider mapping.

Validates:
- register() stores model prefix to provider mapping
- get_provider() resolves model_id by longest matching prefix
- get_provider() raises KeyError for unknown models
- list_models() returns sorted registered prefixes
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from ces.execution.providers.protocol import LLMProviderProtocol, LLMResponse
from ces.execution.providers.registry import ProviderRegistry


class MockProvider:
    """Minimal provider for registry tests."""

    def __init__(self, name: str) -> None:
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
            content="mock",
            model_id=model_id,
            model_version="v1",
            input_tokens=0,
            output_tokens=0,
            provider_name=self._name,
        )

    async def stream(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> AsyncIterator[str]:
        yield "mock"  # pragma: no cover


class TestProviderRegistry:
    """Tests 5-7: ProviderRegistry maps prefixes to providers."""

    def test_register_and_get_provider(self) -> None:
        """Test 5: register() stores mapping; get_provider() resolves by prefix."""
        registry = ProviderRegistry()
        provider = MockProvider("anthropic")
        registry.register("claude", provider)

        result = registry.get_provider("claude-3-opus")
        assert result is provider

    def test_get_provider_unknown_raises_key_error(self) -> None:
        """Test 6: get_provider() raises KeyError with descriptive message for unknown models."""
        registry = ProviderRegistry()
        registry.register("claude", MockProvider("anthropic"))

        with pytest.raises(KeyError, match="unknown-model"):
            registry.get_provider("unknown-model")

    def test_list_models_returns_sorted_prefixes(self) -> None:
        """Test 7: list_models() returns all registered prefixes sorted."""
        registry = ProviderRegistry()
        registry.register("gpt", MockProvider("openai"))
        registry.register("claude", MockProvider("anthropic"))

        result = registry.list_models()
        assert result == ["claude", "gpt"]

    def test_get_provider_longest_prefix_match(self) -> None:
        """get_provider() matches the longest prefix for ambiguous model_ids."""
        registry = ProviderRegistry()
        generic = MockProvider("generic")
        specific = MockProvider("specific")
        registry.register("claude", generic)
        registry.register("claude-3", specific)

        result = registry.get_provider("claude-3-opus")
        assert result is specific

    def test_empty_registry_raises_key_error(self) -> None:
        """get_provider() on empty registry raises KeyError."""
        registry = ProviderRegistry()
        with pytest.raises(KeyError):
            registry.get_provider("any-model")


class TestProviderRegistryMultiModel:
    """Tests for ProviderRegistry.resolve_roles() with MultiModelConfig."""

    def test_resolve_roles_returns_provider_tuples(self) -> None:
        """resolve_roles() returns dict mapping each role to (provider, model_id) tuple."""
        from ces.execution.providers.multi_model import MultiModelConfig

        registry = ProviderRegistry()
        anthropic = MockProvider("anthropic")
        openai = MockProvider("openai")
        registry.register("claude", anthropic)
        registry.register("gpt", openai)

        config = MultiModelConfig(
            role_model_map={"synthesizer": "claude-3-opus", "challenger": "gpt-4o"},
        )
        result = registry.resolve_roles(config)

        assert len(result) == 2
        assert "synthesizer" in result
        assert "challenger" in result

    def test_resolve_roles_correct_provider_per_role(self) -> None:
        """resolve_roles() maps claude models to anthropic provider and gpt to openai."""
        from ces.execution.providers.multi_model import MultiModelConfig

        registry = ProviderRegistry()
        anthropic = MockProvider("anthropic")
        openai = MockProvider("openai")
        registry.register("claude", anthropic)
        registry.register("gpt", openai)

        config = MultiModelConfig(
            role_model_map={"synthesizer": "claude-3-opus", "challenger": "gpt-4o"},
        )
        result = registry.resolve_roles(config)

        assert result["synthesizer"][0] is anthropic
        assert result["challenger"][0] is openai

    def test_resolve_roles_unknown_model_raises_key_error(self) -> None:
        """resolve_roles() raises KeyError when config contains an unregistered model."""
        from ces.execution.providers.multi_model import MultiModelConfig

        registry = ProviderRegistry()
        registry.register("claude", MockProvider("anthropic"))

        config = MultiModelConfig(
            role_model_map={"synthesizer": "claude-3-opus", "challenger": "unknown-model"},
        )
        with pytest.raises(KeyError, match="unknown-model"):
            registry.resolve_roles(config)

    def test_resolve_roles_preserves_exact_model_id(self) -> None:
        """resolve_roles() tuple[1] is the exact model_id string, not the prefix."""
        from ces.execution.providers.multi_model import MultiModelConfig

        registry = ProviderRegistry()
        registry.register("claude", MockProvider("anthropic"))
        registry.register("gpt", MockProvider("openai"))

        config = MultiModelConfig(
            role_model_map={"synthesizer": "claude-3-opus", "challenger": "gpt-4o"},
        )
        result = registry.resolve_roles(config)

        assert result["synthesizer"][1] == "claude-3-opus"
        assert result["challenger"][1] == "gpt-4o"

    def test_resolve_roles_single_role_config(self) -> None:
        """resolve_roles() works correctly with a single-role config."""
        from ces.execution.providers.multi_model import MultiModelConfig

        registry = ProviderRegistry()
        anthropic = MockProvider("anthropic")
        registry.register("claude", anthropic)

        config = MultiModelConfig(role_model_map={"sole_agent": "claude-3-opus"})
        result = registry.resolve_roles(config)

        assert len(result) == 1
        assert result["sole_agent"] == (anthropic, "claude-3-opus")
