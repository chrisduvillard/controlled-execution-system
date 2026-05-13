"""Optional LLM-assisted Intent Gate preflight parsing and fallback helpers."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from ces.execution.providers.protocol import LLMProviderProtocol
from ces.execution.secrets import scrub_secrets_from_text
from ces.intent_gate.models import IntentGatePreflight

FALLBACK_NOTE = "LLM preflight unavailable; deterministic Intent Gate rules used."

INTENT_GATE_LLM_PREFLIGHT_PROMPT = """\
Ask only when missing information changes output, plan, tool calls, safety, or acceptance criteria.
Do not ask nice-to-have questions.
Do not include secrets.
Return JSON only for the Intent Gate preflight decision. Do not include markdown.
The JSON must validate against the IntentGatePreflight schema fields: decision,
ledger, and safe_next_step. The ledger must include goal, deliverable, audience,
scope, non_goals, constraints, inputs, tool_permissions, assumptions,
open_questions, decisions, acceptance_criteria, verification_plan, and risks.
Never include raw secrets or credentials. If secret-like content is present,
refuse by returning a blocked decision with scrubbed context only.
"""


def build_llm_preflight_messages(
    *,
    request: str,
    project_mode: str,
    constraints: list[str],
    acceptance_criteria: list[str],
    must_not_break: list[str],
) -> list[dict[str, str]]:
    """Build a minimal, inert JSON-only preflight prompt for an LLM provider."""

    def scrub_values(values: list[str]) -> list[str]:
        return [scrub_secrets_from_text(value) for value in values]

    user_payload: dict[str, Any] = {
        "request": scrub_secrets_from_text(request),
        "project_mode": scrub_secrets_from_text(project_mode),
        "constraints": scrub_values(constraints),
        "acceptance_criteria": scrub_values(acceptance_criteria),
        "must_not_break": scrub_values(must_not_break),
    }
    return [
        {"role": "system", "content": INTENT_GATE_LLM_PREFLIGHT_PROMPT},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, sort_keys=True)},
    ]


async def generate_llm_preflight_payload(
    provider: LLMProviderProtocol | None,
    *,
    model_id: str,
    request: str,
    project_mode: str,
    constraints: list[str],
    acceptance_criteria: list[str],
    must_not_break: list[str],
    max_tokens: int = 1800,
) -> str | None:
    """Return provider JSON for opt-in LLM preflight, or ``None`` on failure."""
    if provider is None:
        return None
    try:
        response = await provider.generate(
            model_id=model_id,
            messages=build_llm_preflight_messages(
                request=request,
                project_mode=project_mode,
                constraints=constraints,
                acceptance_criteria=acceptance_criteria,
                must_not_break=must_not_break,
            ),
            max_tokens=max_tokens,
            temperature=0.0,
        )
    except Exception:
        return None
    return response.content


def parse_llm_preflight(payload: str | bytes | bytearray | None) -> IntentGatePreflight | None:
    """Parse a JSON-only LLM preflight payload into the schema-backed model.

    Invalid JSON, schema violations, and secret-like content are treated as an
    unavailable LLM preflight so callers can fall back deterministically.
    """
    if payload is None:
        return None
    try:
        raw = payload.decode() if isinstance(payload, (bytes, bytearray)) else payload
        decoded = json.loads(raw)
        if not isinstance(decoded, dict):
            return None
        return IntentGatePreflight.model_validate_json(raw)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
        return None


def preflight_with_fallback_note(preflight: IntentGatePreflight) -> IntentGatePreflight:
    """Return a copy of ``preflight`` with the standard LLM fallback note."""
    assumptions = preflight.ledger.assumptions
    if FALLBACK_NOTE in assumptions:
        return preflight
    ledger = preflight.ledger.model_copy(update={"assumptions": (*assumptions, FALLBACK_NOTE)})
    return IntentGatePreflight(
        decision=preflight.decision,
        ledger=ledger,
        safe_next_step=preflight.safe_next_step,
    )
