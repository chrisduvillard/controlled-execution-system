"""Tests for shared provider bootstrap helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ces.execution.providers.bootstrap import (
    _NullLLMProvider,
    build_provider_registry,
    register_cli_fallback,
    resolve_primary_provider,
)
from ces.execution.providers.demo_provider import DemoLLMProvider
from ces.execution.providers.registry import ProviderRegistry


def _settings(*, demo_mode: bool = False, default_model_id: str = "claude-3-opus") -> MagicMock:
    settings = MagicMock()
    settings.demo_mode = demo_mode
    settings.default_model_id = default_model_id
    return settings


class TestRegisterCliFallback:
    def test_both_clis_register_distinct_providers(self) -> None:
        registry = ProviderRegistry()
        with patch("shutil.which", side_effect=lambda tool: f"/usr/bin/{tool}"):
            result = register_cli_fallback(registry, _settings())

        assert registry.get_provider("claude").provider_name == "claude-cli"
        assert registry.get_provider("gpt").provider_name == "codex-cli"
        assert result.provider_name == "claude-cli"

    def test_demo_mode_registers_logical_prefixes_and_demo_alias(self) -> None:
        registry = ProviderRegistry()
        with patch("shutil.which", return_value=None):
            result = register_cli_fallback(registry, _settings(demo_mode=True))

        assert isinstance(result, DemoLLMProvider)
        assert registry.get_provider("claude") is result
        assert registry.get_provider("gpt") is result
        assert registry.get_provider("demo") is result

    def test_no_cli_and_no_demo_returns_null_provider(self) -> None:
        registry = ProviderRegistry()
        with patch("shutil.which", return_value=None):
            result = register_cli_fallback(registry, _settings())

        assert isinstance(result, _NullLLMProvider)
        assert registry.list_models() == []


class TestBuildProviderRegistry:
    def test_build_provider_registry_prefers_default_model_when_available(self) -> None:
        with patch("shutil.which", side_effect=lambda tool: f"/usr/bin/{tool}"):
            registry, provider = build_provider_registry(_settings(default_model_id="gpt-5.4"))

        assert provider is registry.get_provider("gpt-5.4")
        assert provider.provider_name == "codex-cli"

    def test_resolve_primary_provider_falls_back_to_known_prefixes(self) -> None:
        registry = ProviderRegistry()
        demo = DemoLLMProvider()
        registry.register("demo", demo)

        assert resolve_primary_provider(registry, "unknown-model") is demo
