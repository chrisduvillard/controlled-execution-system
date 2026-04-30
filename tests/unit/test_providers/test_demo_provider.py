"""Tests for the DemoLLMProvider dry-run mode."""

from __future__ import annotations

import json

import pytest

from ces.execution.providers.demo_provider import DemoLLMProvider
from ces.execution.providers.protocol import LLMProviderProtocol, LLMResponse


class TestDemoLLMProvider:
    def test_implements_protocol(self) -> None:
        provider = DemoLLMProvider()
        assert isinstance(provider, LLMProviderProtocol)

    def test_provider_name(self) -> None:
        provider = DemoLLMProvider()
        assert provider.provider_name == "demo"

    @pytest.mark.asyncio
    async def test_generate_returns_llm_response(self) -> None:
        provider = DemoLLMProvider()
        result = await provider.generate(
            model_id="demo-model",
            messages=[{"role": "user", "content": "Hello"}],
        )
        assert isinstance(result, LLMResponse)
        assert result.model_id == "demo-model"
        assert result.provider_name == "demo"
        assert result.model_version == "demo-0.1"
        assert result.input_tokens > 0
        assert result.output_tokens > 0

    @pytest.mark.asyncio
    async def test_generate_content_includes_demo_mode_prefix(self) -> None:
        provider = DemoLLMProvider()
        result = await provider.generate(
            model_id="demo-model",
            messages=[{"role": "user", "content": "Hello"}],
        )
        assert result.content.startswith("[DEMO MODE]")

    @pytest.mark.asyncio
    async def test_generate_returns_valid_manifest_json_for_manifest_prompt(self) -> None:
        provider = DemoLLMProvider()
        result = await provider.generate(
            model_id="demo-model",
            messages=[
                {"role": "system", "content": "You are a CES manifest generator"},
                {"role": "user", "content": "Add user authentication"},
            ],
        )
        # The content after the prefix should be valid JSON for manifest generation
        content = result.content
        assert "[DEMO MODE]" in content
        # Extract JSON from the response
        json_start = content.find("{")
        if json_start >= 0:
            json_str = content[json_start:]
            parsed = json.loads(json_str)
            assert "description" in parsed
            assert "risk_tier" in parsed
            assert "behavior_confidence" in parsed
            assert "change_class" in parsed
            assert "affected_files" in parsed
            assert "token_budget" in parsed

    @pytest.mark.asyncio
    async def test_stream_yields_chunks(self) -> None:
        provider = DemoLLMProvider()
        chunks: list[str] = []
        async for chunk in provider.stream(
            model_id="demo-model",
            messages=[{"role": "user", "content": "Hello"}],
        ):
            chunks.append(chunk)
        assert len(chunks) > 0
        full_text = "".join(chunks)
        assert "[DEMO MODE]" in full_text

    @pytest.mark.asyncio
    async def test_generate_respects_max_tokens(self) -> None:
        provider = DemoLLMProvider()
        result = await provider.generate(
            model_id="demo-model",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=100,
        )
        assert result.output_tokens <= 100

    @pytest.mark.asyncio
    async def test_demo_review_structural_returns_json(self) -> None:
        provider = DemoLLMProvider()
        result = await provider.generate(
            model_id="demo-model",
            messages=[
                {
                    "role": "system",
                    "content": "You are a senior code architecture reviewer.",
                },
                {"role": "user", "content": "Review the following code change."},
            ],
        )
        findings = json.loads(result.content)
        assert isinstance(findings, list)
        assert len(findings) >= 1
        assert findings[0]["finding_id"] == "demo-struct-001"
        assert findings[0]["severity"] == "medium"
        assert findings[0]["category"] == "architecture"

    @pytest.mark.asyncio
    async def test_demo_review_semantic_returns_json(self) -> None:
        provider = DemoLLMProvider()
        result = await provider.generate(
            model_id="demo-model",
            messages=[
                {
                    "role": "system",
                    "content": "You are a senior logic correctness reviewer.",
                },
                {"role": "user", "content": "Review the following code change."},
            ],
        )
        findings = json.loads(result.content)
        assert isinstance(findings, list)
        assert len(findings) >= 1
        assert findings[0]["finding_id"] == "demo-semantic-001"
        assert findings[0]["severity"] == "low"
        assert findings[0]["category"] == "edge_case"

    @pytest.mark.asyncio
    async def test_demo_review_red_team_returns_json(self) -> None:
        provider = DemoLLMProvider()
        result = await provider.generate(
            model_id="demo-model",
            messages=[
                {
                    "role": "system",
                    "content": ("You are a senior security reviewer and adversarial thinker."),
                },
                {"role": "user", "content": "Review the following code change."},
            ],
        )
        findings = json.loads(result.content)
        assert isinstance(findings, list)
        assert len(findings) >= 1
        assert findings[0]["finding_id"] == "demo-redteam-001"
        assert findings[0]["severity"] == "info"
        assert findings[0]["category"] == "input_validation"

    @pytest.mark.asyncio
    async def test_demo_review_generic_returns_empty(self) -> None:
        """Non-review prompt returns normal demo text, not review JSON."""
        provider = DemoLLMProvider()
        result = await provider.generate(
            model_id="demo-model",
            messages=[
                {"role": "user", "content": "Explain how CES works."},
            ],
        )
        assert result.content.startswith("[DEMO MODE]")
        # Should NOT be parseable as a JSON array of review findings
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.content)
