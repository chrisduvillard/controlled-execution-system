from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest

from ces.execution.providers.protocol import LLMResponse
from ces.intent_gate.classifier import classify_intent
from ces.intent_gate.llm_preflight import (
    FALLBACK_NOTE,
    build_llm_preflight_messages,
    generate_llm_preflight_payload,
    parse_llm_preflight,
    preflight_with_fallback_note,
)


class _FakeProvider:
    def __init__(self, content: str, *, fail: bool = False) -> None:
        self.content = content
        self.fail = fail
        self.messages: list[dict[str, str]] | None = None

    @property
    def provider_name(self) -> str:
        return "fake"

    async def generate(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        del max_tokens, temperature
        if self.fail:
            raise RuntimeError("provider unavailable")
        self.messages = messages
        return LLMResponse(
            content=self.content,
            model_id=model_id,
            model_version=model_id,
            input_tokens=10,
            output_tokens=20,
            provider_name=self.provider_name,
        )

    def stream(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> AsyncIterator[str]:
        del model_id, messages, max_tokens, temperature
        raise NotImplementedError


def _valid_payload() -> str:
    return json.dumps(
        {
            "decision": "proceed",
            "ledger": {
                "goal": "Add tests for parser edge cases",
                "deliverable": "Parser tests covering edge cases",
                "audience": "Project maintainers",
                "scope": ["Test-only parser coverage"],
                "non_goals": ["No parser behavior changes"],
                "constraints": ["Keep public API unchanged"],
                "inputs": ["Operator request"],
                "tool_permissions": ["Inspect files", "Edit tests", "Run focused tests"],
                "assumptions": [],
                "open_questions": [],
                "decisions": ["Acceptance criteria are explicit enough to proceed."],
                "acceptance_criteria": ["Parser edge cases are covered"],
                "verification_plan": ["Run parser tests"],
                "risks": [],
            },
            "safe_next_step": "Inspect parser tests, add missing cases, then run focused tests.",
        }
    )


def test_parse_llm_preflight_accepts_schema_valid_json_payload() -> None:
    preflight = parse_llm_preflight(_valid_payload())

    assert preflight.decision == "proceed"
    assert preflight.ledger.goal == "Add tests for parser edge cases"
    assert preflight.ledger.acceptance_criteria == ("Parser edge cases are covered",)
    assert preflight.preflight_id is not None


def test_parse_llm_preflight_returns_none_for_invalid_or_non_json_payload() -> None:
    assert parse_llm_preflight("not json") is None
    assert parse_llm_preflight(json.dumps({"decision": "proceed", "extra": "field"})) is None
    assert parse_llm_preflight(json.dumps({"decision": "proceed", "safe_next_step": "***"})) is None


def test_preflight_with_fallback_note_records_clear_fallback_note() -> None:
    deterministic = classify_intent(
        request="Tighten README wording",
        constraints=(),
        acceptance_criteria=(),
        must_not_break=(),
        project_mode="greenfield",
        non_interactive=False,
    )

    preflight = preflight_with_fallback_note(deterministic)

    assert preflight.decision == deterministic.decision
    assert FALLBACK_NOTE in preflight.ledger.assumptions
    assert FALLBACK_NOTE not in deterministic.ledger.assumptions


def test_build_llm_preflight_messages_demands_json_only_and_no_nice_to_have_questions() -> None:
    messages = build_llm_preflight_messages(
        request="Fix login",
        project_mode="brownfield",
        constraints=["Keep API"],
        acceptance_criteria=["Login works"],
        must_not_break=["Existing sessions"],
    )

    assert "Return JSON only" in messages[0]["content"]
    assert "Do not ask nice-to-have questions" in messages[0]["content"]
    assert json.loads(messages[1]["content"])["request"] == "Fix login"


def test_build_llm_preflight_messages_scrubs_secret_like_input_before_provider_call() -> None:
    messages = build_llm_preflight_messages(
        request="Use token sk-live123456",
        project_mode="greenfield",
        constraints=["API_KEY=abc123"],
        acceptance_criteria=[],
        must_not_break=[],
    )

    payload = messages[1]["content"]
    assert "sk-live123456" not in payload
    assert "abc123" not in payload
    assert "<REDACTED>" in payload


@pytest.mark.asyncio
async def test_generate_llm_preflight_payload_calls_provider_with_json_prompt() -> None:
    provider = _FakeProvider(_valid_payload())

    payload = await generate_llm_preflight_payload(
        provider,
        model_id="test-model",
        request="Fix parser",
        project_mode="greenfield",
        constraints=[],
        acceptance_criteria=["Tests pass"],
        must_not_break=[],
    )

    assert payload == _valid_payload()
    assert provider.messages is not None
    assert "Return JSON only" in provider.messages[0]["content"]


@pytest.mark.asyncio
async def test_generate_llm_preflight_payload_returns_none_when_provider_unavailable() -> None:
    payload = await generate_llm_preflight_payload(
        _FakeProvider("", fail=True),
        model_id="test-model",
        request="Fix parser",
        project_mode="greenfield",
        constraints=[],
        acceptance_criteria=[],
        must_not_break=[],
    )

    assert payload is None
