"""Tests for LLMReviewExecutor -- LLM-backed code review execution."""

from __future__ import annotations

import json
from typing import AsyncIterator
from unittest.mock import MagicMock

import pytest

from ces.execution.providers.protocol import (
    ChainOfCustodyTracker,
    LLMResponse,
)
from ces.execution.providers.registry import ProviderRegistry
from ces.harness.models.review_assignment import ReviewAssignment, ReviewerRole
from ces.harness.models.review_finding import ReviewFindingSeverity
from ces.harness.services.diff_extractor import DiffContext, DiffHunk, DiffStats
from ces.harness.services.review_executor import (
    LLMReviewExecutor,
    _parse_findings,
    _summarize_findings,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_diff_context() -> DiffContext:
    return DiffContext(
        diff_text="+ new_line()",
        files_changed=("src/main.py",),
        hunks=(
            DiffHunk(
                file_path="src/main.py",
                old_start=1,
                new_start=1,
                content="+ new_line()",
            ),
        ),
        stats=DiffStats(insertions=1, deletions=0, files_changed=1),
    )


def _make_assignment(
    role: ReviewerRole = ReviewerRole.STRUCTURAL,
    model_id: str = "claude-test",
) -> ReviewAssignment:
    return ReviewAssignment(
        role=role,
        model_id=model_id,
        agent_id=f"reviewer-{role.value}-{model_id}",
    )


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model_id="claude-test",
        model_version="claude-test-20240101",
        input_tokens=100,
        output_tokens=50,
        provider_name="test",
    )


_VALID_FINDINGS_JSON = json.dumps(
    [
        {
            "finding_id": "f-001",
            "severity": "high",
            "category": "logic_error",
            "file_path": "src/main.py",
            "line_number": 42,
            "title": "Off-by-one in loop",
            "description": "Loop iterates one too many times.",
            "recommendation": "Change < to <=.",
            "confidence": 0.9,
        },
        {
            "finding_id": "f-002",
            "severity": "low",
            "category": "naming",
            "file_path": "src/main.py",
            "line_number": 10,
            "title": "Unclear variable name",
            "description": "Variable 'x' is ambiguous.",
            "recommendation": "Rename to 'user_count'.",
            "confidence": 0.7,
        },
    ]
)


class _FakeProvider:
    """Minimal LLM provider for testing."""

    def __init__(self, response_content: str = "[]") -> None:
        self._response_content = response_content

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
        return _make_llm_response(self._response_content)

    async def stream(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> AsyncIterator[str]:
        yield self._response_content  # pragma: no cover


def _make_registry(response_content: str = "[]") -> ProviderRegistry:
    reg = ProviderRegistry()
    reg.register("claude", _FakeProvider(response_content))
    return reg


# ---------------------------------------------------------------------------
# Tests: _parse_findings
# ---------------------------------------------------------------------------


class TestParseFindings:
    """Tests for JSON response parsing."""

    def test_parse_valid_json_array(self) -> None:
        findings = _parse_findings(_VALID_FINDINGS_JSON, ReviewerRole.STRUCTURAL)
        assert findings is not None
        assert len(findings) == 2
        assert findings[0].title == "Off-by-one in loop"
        assert findings[0].severity == ReviewFindingSeverity.HIGH

    def test_parse_empty_array(self) -> None:
        findings = _parse_findings("[]", ReviewerRole.STRUCTURAL)
        assert findings is not None
        assert len(findings) == 0

    def test_parse_json_in_markdown_block(self) -> None:
        content = "Here are my findings:\n```json\n" + _VALID_FINDINGS_JSON + "\n```"
        findings = _parse_findings(content, ReviewerRole.SEMANTIC)
        assert findings is not None
        assert len(findings) == 2

    def test_parse_json_with_preamble_text(self) -> None:
        content = "Let me analyze this code.\n\nHere are my findings:\n" + _VALID_FINDINGS_JSON
        findings = _parse_findings(content, ReviewerRole.STRUCTURAL)
        assert len(findings) == 2
        assert findings[0].title == "Off-by-one in loop"

    def test_fallback_on_unparseable_text(self) -> None:
        findings = _parse_findings("I found some issues but forgot JSON.", ReviewerRole.RED_TEAM)
        assert len(findings) == 1
        assert findings[0].severity == ReviewFindingSeverity.HIGH
        assert findings[0].category == "unparsed_review"

    def test_invalid_severity_defaults_to_info(self) -> None:
        bad_json = json.dumps(
            [
                {
                    "severity": "mega_critical",
                    "title": "Something",
                    "description": "Bad severity",
                }
            ]
        )
        findings = _parse_findings(bad_json, ReviewerRole.STRUCTURAL)
        assert len(findings) == 1
        assert findings[0].severity == ReviewFindingSeverity.INFO

    def test_missing_fields_get_defaults(self) -> None:
        minimal_json = json.dumps([{"title": "Minimal"}])
        findings = _parse_findings(minimal_json, ReviewerRole.STRUCTURAL)
        assert len(findings) == 1
        assert findings[0].category == "general"
        assert findings[0].recommendation == ""

    def test_non_list_json_falls_back(self) -> None:
        findings = _parse_findings('{"not": "a list"}', ReviewerRole.STRUCTURAL)
        assert len(findings) == 1
        assert findings[0].category == "unparsed_review"


# ---------------------------------------------------------------------------
# Tests: _summarize_findings
# ---------------------------------------------------------------------------


class TestSummarizeFindings:
    """Tests for finding summary generation."""

    def test_no_findings(self) -> None:
        assert _summarize_findings([]) == "No issues found."

    def test_counts_by_severity(self) -> None:
        findings = _parse_findings(_VALID_FINDINGS_JSON, ReviewerRole.STRUCTURAL)
        assert findings is not None
        summary = _summarize_findings(findings)
        assert "2 issue(s)" in summary
        assert "1 high" in summary
        assert "1 low" in summary


# ---------------------------------------------------------------------------
# Tests: LLMReviewExecutor.execute_code_review
# ---------------------------------------------------------------------------


class TestExecuteCodeReview:
    """Tests for the primary review execution method."""

    @pytest.mark.asyncio
    async def test_returns_review_result_with_findings(self) -> None:
        registry = _make_registry(_VALID_FINDINGS_JSON)
        executor = LLMReviewExecutor(provider_registry=registry)
        assignment = _make_assignment()

        result = await executor.execute_code_review(
            assignment=assignment,
            diff_context=_make_diff_context(),
            manifest_context={"description": "Test task"},
        )

        assert len(result.findings) == 2
        assert result.assignment == assignment
        assert result.model_version == "claude-test-20240101"
        assert result.tokens_used == 150  # 100 input + 50 output
        assert result.review_duration_seconds >= 0.0

    @pytest.mark.asyncio
    async def test_empty_findings_when_llm_returns_empty_array(self) -> None:
        registry = _make_registry("[]")
        executor = LLMReviewExecutor(provider_registry=registry)

        result = await executor.execute_code_review(
            assignment=_make_assignment(),
            diff_context=_make_diff_context(),
            manifest_context={},
        )

        assert len(result.findings) == 0
        assert result.summary == "No issues found."

    @pytest.mark.asyncio
    async def test_kill_switch_blocks_execution(self) -> None:
        registry = _make_registry()
        kill_switch = MagicMock()
        kill_switch.is_halted.return_value = True

        executor = LLMReviewExecutor(
            provider_registry=registry,
            kill_switch=kill_switch,
        )

        with pytest.raises(RuntimeError, match="Kill switch"):
            await executor.execute_code_review(
                assignment=_make_assignment(),
                diff_context=_make_diff_context(),
                manifest_context={},
            )

    @pytest.mark.asyncio
    async def test_chain_of_custody_recorded(self) -> None:
        registry = _make_registry("[]")
        tracker = ChainOfCustodyTracker()
        executor = LLMReviewExecutor(
            provider_registry=registry,
            chain_tracker=tracker,
        )

        await executor.execute_code_review(
            assignment=_make_assignment(role=ReviewerRole.RED_TEAM),
            diff_context=_make_diff_context(),
            manifest_context={},
        )

        assert len(tracker.entries) == 1
        entry = tracker.entries[0]
        assert entry.step == "code_review"
        assert entry.agent_role == "reviewer_red_team"

    @pytest.mark.asyncio
    async def test_fallback_on_malformed_llm_response(self) -> None:
        registry = _make_registry("This is not JSON at all")
        executor = LLMReviewExecutor(provider_registry=registry)

        result = await executor.execute_code_review(
            assignment=_make_assignment(),
            diff_context=_make_diff_context(),
            manifest_context={},
        )

        assert len(result.findings) == 1
        assert result.findings[0].severity == ReviewFindingSeverity.HIGH
        assert result.findings[0].category == "unparsed_review"


# ---------------------------------------------------------------------------
# Tests: LLMReviewExecutor.execute_review (protocol method)
# ---------------------------------------------------------------------------


class TestExecuteReview:
    """Tests for the protocol-satisfying execute_review method."""

    @pytest.mark.asyncio
    async def test_delegates_to_execute_code_review(self) -> None:
        registry = _make_registry(_VALID_FINDINGS_JSON)
        executor = LLMReviewExecutor(provider_registry=registry)

        result = await executor.execute_review(
            assignment=_make_assignment(),
            evidence={
                "diff_context": _make_diff_context(),
                "manifest_context": {"description": "Test"},
            },
        )

        assert isinstance(result, dict)
        assert "findings" in result

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_diff_context(self) -> None:
        registry = _make_registry()
        executor = LLMReviewExecutor(provider_registry=registry)

        result = await executor.execute_review(
            assignment=_make_assignment(),
            evidence={},
        )

        assert result["findings"] == []
        assert "No diff" in result["summary"]
