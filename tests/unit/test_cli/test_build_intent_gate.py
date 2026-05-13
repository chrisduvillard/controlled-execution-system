from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import typer

from ces.cli._builder_flow import BuilderBriefDraft
from ces.execution.providers.protocol import LLMResponse
from ces.execution.providers.registry import ProviderRegistry
from ces.intent_gate.classifier import classify_intent
from ces.intent_gate.llm_preflight import FALLBACK_NOTE


class _Settings:
    default_model_id = "test-model"
    reverse_preflight_mode = "rules"


class _FakeProvider:
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
        del messages, max_tokens, temperature
        return LLMResponse(
            content='{"decision":"proceed","ledger":{"goal":"LLM accepted task","deliverable":"Tests","audience":"Maintainers","scope":["Tests"],"non_goals":[],"constraints":[],"inputs":["Request"],"tool_permissions":["Inspect"],"assumptions":[],"open_questions":[],"decisions":["LLM preflight accepted."],"acceptance_criteria":["Tests pass"],"verification_plan":["Run tests"],"risks":[]},"safe_next_step":"Run the task."}',
            model_id=model_id,
            model_version=model_id,
            input_tokens=1,
            output_tokens=1,
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


def _brief(request: str, *, preflight=None) -> BuilderBriefDraft:
    return BuilderBriefDraft(
        request=request,
        project_mode="greenfield",
        constraints=[],
        acceptance_criteria=[],
        must_not_break=[],
        open_questions={},
        intent_preflight=preflight,
    )


def test_normalize_reverse_preflight_mode_defaults_to_rules() -> None:
    from ces.cli.run_cmd import _normalize_reverse_preflight_mode

    assert _normalize_reverse_preflight_mode("rules") == "rules"
    assert _normalize_reverse_preflight_mode("  LLM ") == "llm"


def test_resolve_reverse_preflight_mode_uses_config_when_cli_left_at_default() -> None:
    from ces.cli.run_cmd import _resolve_reverse_preflight_mode

    assert _resolve_reverse_preflight_mode("rules", project_config={"reverse_preflight": "strict"}) == "strict"
    assert _resolve_reverse_preflight_mode("llm", project_config={"reverse_preflight": "off"}) == "llm"


@pytest.mark.parametrize("mode", ["", "disabled", "deterministic", "ask"])
def test_normalize_reverse_preflight_mode_rejects_invalid_values(mode: str) -> None:
    from ces.cli.run_cmd import _normalize_reverse_preflight_mode

    with pytest.raises(typer.BadParameter, match="Intent Gate mode"):
        _normalize_reverse_preflight_mode(mode)


def test_reverse_preflight_off_skips_existing_intent_gate_preflight() -> None:
    from ces.cli.run_cmd import _validate_intent_gate_allows_runtime

    deterministic = classify_intent("Change auth behavior", (), (), (), "greenfield", non_interactive=False)
    brief = _brief("Change auth behavior", preflight=deterministic)

    result = _validate_intent_gate_allows_runtime(brief, non_interactive=False, reverse_preflight="off")

    assert result.intent_preflight is None


def test_reverse_preflight_strict_converts_ask_to_blocked() -> None:
    from ces.cli.run_cmd import _intent_preflight_for_brief

    preflight = _intent_preflight_for_brief(
        _brief("Change auth behavior"),
        non_interactive=False,
        reverse_preflight="strict",
    )

    assert preflight.decision == "blocked"
    assert any("Strict Intent Gate mode" in decision for decision in preflight.ledger.decisions)


def test_reverse_preflight_llm_uses_schema_valid_payload() -> None:
    from ces.cli.run_cmd import _intent_preflight_for_brief

    payload = '{"decision":"proceed","ledger":{"goal":"Add tests","deliverable":"Tests","audience":"Maintainers","scope":["Tests only"],"non_goals":["Behavior changes"],"constraints":["Keep API"],"inputs":["Request"],"tool_permissions":["Inspect","Edit tests","Run tests"],"assumptions":[],"open_questions":[],"decisions":["LLM preflight accepted."],"acceptance_criteria":["Tests pass"],"verification_plan":["Run tests"],"risks":[]},"safe_next_step":"Inspect tests and add the missing coverage."}'

    preflight = _intent_preflight_for_brief(
        _brief("Add tests"),
        non_interactive=False,
        reverse_preflight="llm",
        llm_preflight_payload=payload,
    )

    assert preflight.decision == "proceed"
    assert preflight.ledger.goal == "Add tests"
    assert FALLBACK_NOTE not in preflight.ledger.assumptions


def test_reverse_preflight_llm_falls_back_to_rules_with_note_when_payload_unavailable() -> None:
    from ces.cli.run_cmd import _intent_preflight_for_brief

    preflight = _intent_preflight_for_brief(
        _brief("Tighten README wording"),
        non_interactive=False,
        reverse_preflight="llm",
    )

    assert preflight.decision == "assume_and_proceed"
    assert FALLBACK_NOTE in preflight.ledger.assumptions


@pytest.mark.asyncio
async def test_reverse_preflight_llm_fetches_payload_from_configured_provider() -> None:
    from ces.cli.run_cmd import _llm_preflight_payload_from_services, _validate_intent_gate_allows_runtime

    registry = ProviderRegistry()
    registry.register("test", _FakeProvider())
    brief = _brief("Change auth behavior")

    payload = await _llm_preflight_payload_from_services(
        {"provider_registry": registry, "settings": _Settings()},
        brief,
        reverse_preflight="llm",
    )

    result = _validate_intent_gate_allows_runtime(
        brief,
        non_interactive=False,
        reverse_preflight="llm",
        llm_preflight_payload=payload,
    )

    assert result.intent_preflight is not None
    assert result.intent_preflight.decision == "proceed"
    assert result.intent_preflight.ledger.goal == "LLM accepted task"
