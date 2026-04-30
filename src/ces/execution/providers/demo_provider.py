"""Demo LLM provider for dry-run mode.

Returns canned responses so the full CES pipeline can be exercised
without a real CLI-backed provider. All output is prefixed with ``[DEMO MODE]``
to make it obvious that no real LLM call occurred.

Activated when ``CES_DEMO_MODE=1`` is set in the environment and
no real provider is available.

This module lives in the execution plane; it does NOT violate the
LLM-05 constraint (no LLM calls in the control plane).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from ces.execution.providers.protocol import LLMResponse

_DEMO_MANIFEST_PROPOSAL: dict[str, Any] = {
    "description": "[DEMO MODE] Sample manifest proposal",
    "risk_tier": "C",
    "behavior_confidence": "BC1",
    "change_class": "Class 1",
    "affected_files": ["demo_example.py"],
    "token_budget": 50000,
    "reasoning": "[DEMO MODE] This is a canned demo response. No real LLM was called.",
}

_DEMO_GENERIC_RESPONSE = (
    "[DEMO MODE] This is a simulated response from the CES demo provider. "
    "No real CLI-backed LLM call was made. Install/authenticate the "
    "`claude` or `codex` CLI for actual LLM responses."
)

# ---------------------------------------------------------------------------
# Canned review findings keyed by reviewer role keyword
# ---------------------------------------------------------------------------

_DEMO_REVIEW_STRUCTURAL: list[dict[str, Any]] = [
    {
        "finding_id": "demo-struct-001",
        "severity": "medium",
        "category": "architecture",
        "file_path": None,
        "line_number": None,
        "title": "Module coupling could be reduced",
        "description": (
            "The change introduces direct dependencies between layers that could be mediated through protocols."
        ),
        "recommendation": "Consider using dependency injection or a protocol interface.",
        "confidence": 0.6,
    }
]

_DEMO_REVIEW_SEMANTIC: list[dict[str, Any]] = [
    {
        "finding_id": "demo-semantic-001",
        "severity": "low",
        "category": "edge_case",
        "file_path": None,
        "line_number": None,
        "title": "Missing boundary check",
        "description": "No validation for empty input in the new code path.",
        "recommendation": "Add a guard clause for empty collections.",
        "confidence": 0.5,
    }
]

_DEMO_REVIEW_RED_TEAM: list[dict[str, Any]] = [
    {
        "finding_id": "demo-redteam-001",
        "severity": "info",
        "category": "input_validation",
        "file_path": None,
        "line_number": None,
        "title": "Input not sanitized at trust boundary",
        "description": "User-provided values pass through without validation.",
        "recommendation": "Add input validation before processing.",
        "confidence": 0.4,
    }
]


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 characters per token."""
    return max(1, len(text) // 4)


def _is_manifest_prompt(messages: list[dict[str, str]]) -> bool:
    """Detect whether the prompt is asking for manifest generation."""
    for msg in messages:
        content = msg.get("content", "").lower()
        if "manifest generator" in content or ("manifest" in content and "json" in content):
            return True
    return False


def _detect_review_role(messages: list[dict[str, str]]) -> str | None:
    """Detect whether the prompt is a review request and which role it targets.

    Checks the first message (system prompt) for role-specific keywords
    matching the prompts in ``ces.harness.prompts.review_prompts``.

    Returns:
        ``"structural"``, ``"semantic"``, ``"red_team"``, or ``None``
        if the prompt is not a review request.
    """
    if not messages:
        return None
    system_content = messages[0].get("content", "").lower()
    if "architecture reviewer" in system_content:
        return "structural"
    if "logic correctness" in system_content:
        return "semantic"
    if "security reviewer" in system_content:
        return "red_team"
    return None


class DemoLLMProvider:
    """LLM provider that returns canned responses for demo/dry-run mode.

    Implements the same interface as LLMProviderProtocol so it can be
    registered in the ProviderRegistry as a drop-in replacement.
    """

    @property
    def provider_name(self) -> str:
        return "demo"

    async def generate(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Return a canned LLMResponse.

        If the prompt looks like a manifest generation request, returns
        a valid JSON manifest proposal.  Otherwise returns a generic
        demo message.
        """
        review_role = _detect_review_role(messages)
        if review_role is not None:
            findings_map: dict[str, list[dict[str, Any]]] = {
                "structural": _DEMO_REVIEW_STRUCTURAL,
                "semantic": _DEMO_REVIEW_SEMANTIC,
                "red_team": _DEMO_REVIEW_RED_TEAM,
            }
            content = json.dumps(findings_map.get(review_role, []))
        elif _is_manifest_prompt(messages):
            content = "[DEMO MODE]\n" + json.dumps(_DEMO_MANIFEST_PROPOSAL, indent=2)
        else:
            content = _DEMO_GENERIC_RESPONSE

        output_tokens = min(_estimate_tokens(content), max_tokens)

        # Estimate input tokens from all messages
        input_text = " ".join(m.get("content", "") for m in messages)
        input_tokens = _estimate_tokens(input_text)

        return LLMResponse(
            content=content,
            model_id=model_id,
            model_version="demo-0.1",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider_name="demo",
        )

    async def stream(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> AsyncIterator[str]:
        """Yield the demo response in chunks."""
        response = await self.generate(
            model_id=model_id,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        # Yield in small chunks to simulate streaming
        text = response.content
        chunk_size = 40
        for i in range(0, len(text), chunk_size):
            yield text[i : i + chunk_size]
