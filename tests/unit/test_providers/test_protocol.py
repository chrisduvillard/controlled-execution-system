"""Tests for LLM provider protocol, response model, and error types.

Validates:
- LLMResponse is a frozen CESBaseModel with all required fields
- LLMProviderProtocol is runtime_checkable with generate() and stream()
- LLMError carries provider_name, model_id, original_error
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from ces.execution.providers.protocol import (
    LLMError,
    LLMProviderProtocol,
    LLMResponse,
)
from ces.shared.base import CESBaseModel


class TestLLMResponse:
    """Test 1: LLMResponse is a frozen CESBaseModel with 6 fields."""

    def test_llm_response_is_ces_base_model(self) -> None:
        """LLMResponse inherits from CESBaseModel."""
        assert issubclass(LLMResponse, CESBaseModel)

    def test_llm_response_has_all_fields(self) -> None:
        """LLMResponse has content, model_id, model_version, input_tokens, output_tokens, provider_name."""
        response = LLMResponse(
            content="Hello world",
            model_id="claude-3-opus",
            model_version="claude-3-opus-20240229",
            input_tokens=10,
            output_tokens=5,
            provider_name="anthropic",
        )
        assert response.content == "Hello world"
        assert response.model_id == "claude-3-opus"
        assert response.model_version == "claude-3-opus-20240229"
        assert response.input_tokens == 10
        assert response.output_tokens == 5
        assert response.provider_name == "anthropic"

    def test_llm_response_is_frozen(self) -> None:
        """LLMResponse instances are immutable (frozen)."""
        response = LLMResponse(
            content="Hello",
            model_id="claude-3-opus",
            model_version="claude-3-opus-20240229",
            input_tokens=10,
            output_tokens=5,
            provider_name="anthropic",
        )
        with pytest.raises(Exception):
            response.content = "Modified"  # type: ignore[misc]


class TestLLMProviderProtocol:
    """Test 2-3: LLMProviderProtocol is runtime_checkable and can be implemented."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """LLMProviderProtocol has @runtime_checkable decorator."""
        assert getattr(LLMProviderProtocol, "_is_runtime_protocol", False) is True

    def test_mock_class_passes_isinstance_check(self) -> None:
        """A class implementing all protocol methods passes isinstance check."""

        class MockProvider:
            @property
            def provider_name(self) -> str:
                return "mock"

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
                    model_version="mock-v1",
                    input_tokens=0,
                    output_tokens=0,
                    provider_name="mock",
                )

            async def stream(
                self,
                model_id: str,
                messages: list[dict[str, str]],
                max_tokens: int = 4096,
                temperature: float = 0.0,
            ) -> AsyncIterator[str]:
                yield "mock"  # pragma: no cover

        provider = MockProvider()
        assert isinstance(provider, LLMProviderProtocol)

    def test_non_implementing_class_fails_isinstance(self) -> None:
        """A class missing protocol methods fails isinstance check."""

        class NotAProvider:
            pass

        assert not isinstance(NotAProvider(), LLMProviderProtocol)


class TestLLMError:
    """Test 4: LLMError is an Exception with provider_name, model_id, original_error."""

    def test_llm_error_is_exception(self) -> None:
        """LLMError inherits from Exception."""
        assert issubclass(LLMError, Exception)

    def test_llm_error_fields(self) -> None:
        """LLMError stores provider_name, model_id, original_error."""
        original = ValueError("API broke")
        error = LLMError(
            message="Something failed",
            provider_name="anthropic",
            model_id="claude-3-opus",
            original_error=original,
        )
        assert error.provider_name == "anthropic"
        assert error.model_id == "claude-3-opus"
        assert error.original_error is original
        assert "Something failed" in str(error)

    def test_llm_error_without_original(self) -> None:
        """LLMError works without original_error."""
        error = LLMError(
            message="Something failed",
            provider_name="openai",
            model_id="gpt-4o",
        )
        assert error.original_error is None
