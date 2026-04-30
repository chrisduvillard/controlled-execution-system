"""Public execution/provider export smoke tests."""

from __future__ import annotations

import pytest

import ces.execution
import ces.execution.providers


def test_execution_all_only_exposes_real_symbols() -> None:
    exports = {name: getattr(ces.execution, name) for name in ces.execution.__all__}

    assert exports["AgentRunner"] is not None
    assert exports["CLILLMProvider"] is not None
    assert exports["DemoLLMProvider"] is not None
    assert "AnthropicProvider" not in exports
    assert "OpenAIProvider" not in exports


def test_provider_all_only_exposes_shipped_providers() -> None:
    exports = {name: getattr(ces.execution.providers, name) for name in ces.execution.providers.__all__}

    assert exports["CLILLMProvider"] is not None
    assert exports["DemoLLMProvider"] is not None
    assert exports["ProviderRegistry"] is not None
    assert "AnthropicProvider" not in exports
    assert "OpenAIProvider" not in exports


def test_unknown_attribute_raises_attribute_error() -> None:
    """The PEP 562 __getattr__ must raise AttributeError for unknown names (line 101)."""
    with pytest.raises(AttributeError, match="DefinitelyNotARealExport"):
        ces.execution.DefinitelyNotARealExport  # noqa: B018
