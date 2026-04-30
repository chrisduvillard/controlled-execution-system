"""Integration test for the dogfood review pipeline.

Exercises: DiffExtractor → ClassificationOracle → ReviewRouter.dispatch_review
→ FindingsAggregator → LocalProjectStore persistence, using mocked LLM providers.
"""

from __future__ import annotations

import json
import pathlib
import tempfile
from typing import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from ces.control.services.classification_oracle import ClassificationOracle
from ces.execution.providers.protocol import LLMResponse
from ces.execution.providers.registry import ProviderRegistry
from ces.harness.models.review_assignment import ReviewerRole
from ces.harness.prompts.review_prompts import REVIEW_SYSTEM_PROMPTS
from ces.harness.services.diff_extractor import DiffContext, DiffExtractor, DiffHunk, DiffStats
from ces.harness.services.findings_aggregator import FindingsAggregator
from ces.harness.services.review_executor import LLMReviewExecutor
from ces.harness.services.review_router import ReviewRouter
from ces.local_store import LocalProjectStore

# -- Helpers --

_STRUCTURAL_FINDINGS = json.dumps(
    [
        {
            "finding_id": "int-struct-001",
            "severity": "medium",
            "category": "architecture",
            "file_path": "src/ces/cli/_factory.py",
            "line_number": 80,
            "title": "Duplicated registration logic",
            "description": "The CLI fallback is registered in two branches.",
            "recommendation": "Extract to shared helper.",
            "confidence": 0.8,
        },
    ]
)

_SEMANTIC_FINDINGS = json.dumps(
    [
        {
            "finding_id": "int-sem-001",
            "severity": "low",
            "category": "edge_case",
            "file_path": "src/ces/harness/services/review_router.py",
            "line_number": 476,
            "title": "Empty assignments list not guarded",
            "description": "dispatch_review doesn't check for empty assignments.",
            "recommendation": "Add early return for empty list.",
            "confidence": 0.6,
        },
    ]
)

_RED_TEAM_FINDINGS = json.dumps([])  # Red team finds nothing


def _make_diff_context() -> DiffContext:
    return DiffContext(
        diff_text="diff --git a/src/ces/cli/_factory.py b/src/ces/cli/_factory.py\n+    new_line()",
        files_changed=("src/ces/cli/_factory.py", "src/ces/harness/services/review_router.py"),
        hunks=(
            DiffHunk(
                file_path="src/ces/cli/_factory.py",
                old_start=80,
                new_start=80,
                content="+    new_line()",
            ),
        ),
        stats=DiffStats(insertions=1, deletions=0, files_changed=2),
    )


class _FakeProvider:
    """LLM provider that returns role-appropriate review findings."""

    def __init__(self) -> None:
        self._responses = {
            "architecture reviewer": _STRUCTURAL_FINDINGS,
            "logic correctness": _SEMANTIC_FINDINGS,
            "security reviewer": _RED_TEAM_FINDINGS,
        }

    @property
    def provider_name(self) -> str:
        return "fake-integration"

    async def generate(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        # Detect role from system prompt
        system_msg = messages[0]["content"] if messages else ""
        content = "[]"
        for keyword, response in self._responses.items():
            if keyword in system_msg:
                content = response
                break

        return LLMResponse(
            content=content,
            model_id=model_id,
            model_version=f"fake-{model_id}",
            input_tokens=100,
            output_tokens=50,
            provider_name="fake-integration",
        )

    async def stream(self, **kwargs) -> AsyncIterator[str]:
        yield ""


# -- Tests --


class TestDogfoodPipelineIntegration:
    """End-to-end integration test for the review pipeline."""

    def test_classification_oracle_matches_governance_components(self) -> None:
        """Oracle should match file-based descriptions to bootstrap rules."""
        oracle = ClassificationOracle()

        result = oracle.classify("Change to classification engine")
        assert result.matched_rule is not None
        assert result.matched_rule.risk_tier.value == "A"
        assert result.confidence >= 0.7

        result = oracle.classify("Change to sensor framework")
        assert result.matched_rule is not None
        assert result.matched_rule.risk_tier.value == "B"

    @pytest.mark.asyncio
    async def test_full_review_pipeline(self) -> None:
        """Diff → review dispatch → aggregation produces structured findings."""
        # Setup
        registry = ProviderRegistry()
        provider = _FakeProvider()
        registry.register("model", provider)

        executor = LLMReviewExecutor(provider_registry=registry)
        router = ReviewRouter(
            model_roster=["model-a", "model-b", "model-c", "model-d"],
        )
        router._review_executor = executor

        # Assign triad
        assignments = router.assign_triad(
            builder_agent_id="dogfood-builder",
            builder_model_id="model-d",
        )
        assert len(assignments) == 3

        # Dispatch (parallel via asyncio.gather)
        diff = _make_diff_context()
        aggregated = await router.dispatch_review(
            assignments=assignments,
            diff_context=diff,
            manifest_context={"description": "Integration test change"},
        )

        # Verify aggregation
        assert len(aggregated.all_findings) == 2  # structural + semantic (red team empty)
        assert aggregated.critical_count == 0
        assert aggregated.high_count == 0
        assert not aggregated.unanimous_zero_findings

    @pytest.mark.asyncio
    async def test_findings_persistence_roundtrip(self) -> None:
        """Findings can be saved and loaded from local store."""
        # Setup review
        registry = ProviderRegistry()
        registry.register("model", _FakeProvider())
        executor = LLMReviewExecutor(provider_registry=registry)
        router = ReviewRouter(model_roster=["model-a", "model-b", "model-c", "model-d"])
        router._review_executor = executor

        assignments = router.assign_triad("builder", "model-d")
        diff = _make_diff_context()
        aggregated = await router.dispatch_review(
            assignments=assignments,
            diff_context=diff,
            manifest_context={},
        )

        # Save to local store
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = pathlib.Path(tmpdir) / ".ces" / "state.db"
            store = LocalProjectStore(db_path, project_id="test")

            store.save_review_findings("M-integration-test", aggregated)

            # Load back
            loaded = store.get_review_findings("M-integration-test")
            assert loaded is not None
            assert len(loaded["findings"]) == 2
            assert loaded["critical_count"] == 0

    def test_review_prompts_include_tool_instructions(self) -> None:
        """All reviewer role prompts include tool access instructions."""
        for role in ReviewerRole:
            prompt = REVIEW_SYSTEM_PROMPTS[role]
            assert "Read" in prompt, f"{role} missing Read tool instruction"
            assert "Grep" in prompt, f"{role} missing Grep tool instruction"
            assert "Glob" in prompt, f"{role} missing Glob tool instruction"

    def test_diff_extractor_parse_and_truncate(self) -> None:
        """DiffExtractor parses and truncates correctly."""
        diff_text = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -1,3 +1,4 @@\n line1\n+new\n line2\n line3"
        ctx = DiffExtractor.extract_diff_from_text(diff_text)
        assert len(ctx.files_changed) == 1
        assert ctx.stats.insertions == 1

        # Truncation
        truncated = DiffExtractor.truncate_diff(ctx, max_chars=10)
        assert truncated.truncated is True
