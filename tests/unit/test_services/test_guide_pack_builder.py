"""Unit tests for GuidePackBuilder service (GUIDE-01 to GUIDE-04).

Tests:
- Token estimation via character-based proxy (chars_per_token=4)
- Budget creation at 60% default with 40/30/30 quotas (D-12)
- Assembly within budget returns success with contents
- Oversized sections truncated to quota with [TRUNCATED] marker
- Total over budget without summarizer returns oversized result
- Total over budget with summarizer attempts summarization
- Still oversized after summarization returns oversized result (D-13)
- Oversized result never splits inline (D-13)
- Kill switch blocks assembly
- Empty sections are allowed
- Budget remainder goes to harness context
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ces.harness.models.guide_pack import (
    GuidePackBudget,
    GuidePackContents,
    GuidePackResult,
)
from ces.harness.services.guide_pack_builder import GuidePackBuilder

# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    """Tests for character-based token estimation."""

    def test_estimate_tokens_basic(self):
        """'hello world' (11 chars) / 4 = 2 tokens."""
        builder = GuidePackBuilder()
        assert builder.estimate_tokens("hello world") == 2

    def test_estimate_tokens_empty_string(self):
        """Empty string returns 0 tokens."""
        builder = GuidePackBuilder()
        assert builder.estimate_tokens("") == 0

    def test_estimate_tokens_custom_chars_per_token(self):
        """Custom chars_per_token changes estimation."""
        builder = GuidePackBuilder(chars_per_token=2)
        # 11 chars / 2 = 5
        assert builder.estimate_tokens("hello world") == 5


# ---------------------------------------------------------------------------
# Budget creation (D-12)
# ---------------------------------------------------------------------------


class TestCreateBudget:
    """Tests for budget creation with 60% default and 40/30/30 quotas."""

    def test_create_budget_default_60_percent(self):
        """100k context * 0.60 = 60000 total budget tokens."""
        builder = GuidePackBuilder()
        budget = builder.create_budget(context_window_tokens=100_000)
        assert budget.total_budget_tokens == 60_000

    def test_create_budget_custom_percent(self):
        """Override default budget percent with 0.50."""
        builder = GuidePackBuilder()
        budget = builder.create_budget(context_window_tokens=100_000, budget_percent=0.50)
        assert budget.total_budget_tokens == 50_000

    def test_create_budget_quotas(self):
        """Budget has 40/30/30 default quotas."""
        builder = GuidePackBuilder()
        budget = builder.create_budget(context_window_tokens=100_000)
        assert budget.truth_artifact_quota == 0.40
        assert budget.vault_notes_quota == 0.30
        assert budget.harness_context_quota == 0.30

    def test_budget_remainder_goes_to_harness(self):
        """Harness context gets the remainder after integer division.

        For 60000 total:
          truth_artifact_tokens = int(60000 * 0.40) = 24000
          vault_notes_tokens = int(60000 * 0.30) = 18000
          harness_context_tokens = 60000 - 24000 - 18000 = 18000
        """
        builder = GuidePackBuilder()
        budget = builder.create_budget(context_window_tokens=100_000)
        truth = budget.truth_artifact_tokens
        vault = budget.vault_notes_tokens
        harness = budget.harness_context_tokens
        assert truth + vault + harness == budget.total_budget_tokens


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


class TestTruncateToBudget:
    """Tests for truncation with [TRUNCATED] marker."""

    def test_truncate_no_op_when_within_budget(self):
        """Short text returned unchanged, no truncation flag."""
        builder = GuidePackBuilder()
        text, was_truncated = builder.truncate_to_budget("short", max_tokens=100)
        assert text == "short"
        assert was_truncated is False

    def test_truncate_adds_marker(self):
        """Truncated text ends with '[TRUNCATED]'."""
        builder = GuidePackBuilder(chars_per_token=4)
        # 100 chars of text, budget = 5 tokens = 20 chars
        long_text = "a" * 100
        text, was_truncated = builder.truncate_to_budget(long_text, max_tokens=5)
        assert text.endswith("\n[TRUNCATED]")
        assert was_truncated is True
        # The content before marker should be max_tokens * chars_per_token
        content_part = text.replace("\n[TRUNCATED]", "")
        assert len(content_part) == 20


# ---------------------------------------------------------------------------
# Assembly (GUIDE-01, GUIDE-02, GUIDE-03, GUIDE-04)
# ---------------------------------------------------------------------------


class TestAssembleWithinBudget:
    """Tests for successful assembly within budget."""

    @pytest.mark.asyncio
    async def test_assemble_within_budget(self):
        """All sections fit within quotas -> success=True with contents."""
        builder = GuidePackBuilder(chars_per_token=1)
        budget = GuidePackBudget(total_budget_tokens=1000)
        # 100 chars each = 100 tokens each, well within 400/300/300 quotas
        result = await builder.assemble(
            truth_artifacts="a" * 100,
            vault_notes="b" * 100,
            harness_context="c" * 100,
            budget=budget,
        )
        assert result.success is True
        assert result.oversized is False
        assert result.contents is not None
        assert result.contents.truth_artifacts == "a" * 100
        assert result.contents.vault_notes == "b" * 100
        assert result.contents.harness_context == "c" * 100
        assert result.total_tokens_used == 300

    @pytest.mark.asyncio
    async def test_empty_sections_allowed(self):
        """Empty strings for any section work fine."""
        builder = GuidePackBuilder(chars_per_token=1)
        budget = GuidePackBudget(total_budget_tokens=1000)
        result = await builder.assemble(
            truth_artifacts="",
            vault_notes="",
            harness_context="",
            budget=budget,
        )
        assert result.success is True
        assert result.total_tokens_used == 0
        assert result.contents is not None


class TestAssembleSectionTruncation:
    """Tests for section-level truncation when a section exceeds its quota."""

    @pytest.mark.asyncio
    async def test_assemble_section_truncation(self):
        """One section oversized -> truncated to quota, still succeeds."""
        builder = GuidePackBuilder(chars_per_token=1)
        budget = GuidePackBudget(total_budget_tokens=1000)
        # truth quota = 400 tokens. Provide 500 chars -> should truncate.
        # vault and harness fit fine.
        result = await builder.assemble(
            truth_artifacts="x" * 500,
            vault_notes="y" * 100,
            harness_context="z" * 100,
            budget=budget,
        )
        assert result.success is True
        assert result.contents is not None
        assert result.contents.truth_artifacts.endswith("[TRUNCATED]")


class TestAssembleOversizedNonSummarizer:
    """Tests for oversized result without summarizer."""

    @pytest.mark.asyncio
    async def test_assemble_total_over_budget_no_summarizer(self):
        """Total exceeds budget with no summarizer -> oversized result."""
        builder = GuidePackBuilder(chars_per_token=1)
        # Very small budget: 30 tokens total
        budget = GuidePackBudget(total_budget_tokens=30)
        # truth=12, vault=9, harness=9 per quota
        # Provide more than each quota allows, even after truncation
        # total after truncation = 12+9+9=30 which equals budget
        # But let's exceed it by making all sections much larger and budget tiny
        budget_tiny = GuidePackBudget(total_budget_tokens=10)
        # truth=4, vault=3, harness=3 per quota
        # After truncation each fits in its quota, total = 4+3+3 = 10
        # That equals budget, so it should succeed. Let's use something smaller.
        budget_very_tiny = GuidePackBudget(total_budget_tokens=3)
        # truth=1, vault=0, harness=2 (remainder)
        # Truncation: 1+0+2 = 3 tokens => fits
        # We need a scenario where truncation isn't enough.
        # Let's test with chars_per_token=1 and budget=10, but the
        # truncation marker itself adds tokens.
        # "[TRUNCATED]" with newline = 12 chars. With chars_per_token=1,
        # that's 12 tokens for the marker alone.
        # So if quota=4 tokens but truncated text = 4 chars + 12 marker = 16 tokens
        # That exceeds the section budget after truncation.
        # Actually, truncate_to_budget returns text[:max_chars] + "\n[TRUNCATED]"
        # and then estimate_tokens recalculates on the whole thing.
        # With budget_tokens=3, truth quota = 1 token = 1 char, then "\n[TRUNCATED]"
        # adds 12 chars => 13 tokens total for that section.
        # Total would be 13 + something + something > 3. So oversized=True.

        result = await builder.assemble(
            truth_artifacts="x" * 100,
            vault_notes="y" * 100,
            harness_context="z" * 100,
            budget=budget_very_tiny,
        )
        assert result.success is False
        assert result.oversized is True
        assert result.contents is None
        assert "decomposed" in result.oversized_reason.lower() or "budget" in result.oversized_reason.lower()


class TestAssembleWithSummarizer:
    """Tests for assembly with SummarizerProtocol."""

    @pytest.mark.asyncio
    async def test_assemble_total_over_budget_with_summarizer(self):
        """Summarizer reduces size enough -> success."""
        mock_summarizer = AsyncMock()
        mock_summarizer.summarize = AsyncMock(return_value="short summary")

        builder = GuidePackBuilder(chars_per_token=1, summarizer=mock_summarizer)
        budget = GuidePackBudget(total_budget_tokens=100)
        # truth=40, vault=30, harness=30
        # Provide content that after truncation still exceeds total
        # With truncation markers adding ~12 chars each, if we trigger
        # truncation on all 3 sections, we get ~(40+12)+(30+12)+(30+12) = 136 > 100
        result = await builder.assemble(
            truth_artifacts="x" * 200,
            vault_notes="y" * 200,
            harness_context="z" * 200,
            budget=budget,
        )
        # Summarizer should have been called
        mock_summarizer.summarize.assert_called()
        # After summarization with "short summary" (13 chars = 13 tokens),
        # the total should be reduced enough
        assert result.success is True

    @pytest.mark.asyncio
    async def test_assemble_still_oversized_after_summarization(self):
        """Summarizer does not reduce enough -> oversized result (D-13)."""
        # Summarizer returns something still too large
        mock_summarizer = AsyncMock()
        mock_summarizer.summarize = AsyncMock(return_value="x" * 500)

        builder = GuidePackBuilder(chars_per_token=1, summarizer=mock_summarizer)
        budget = GuidePackBudget(total_budget_tokens=10)
        result = await builder.assemble(
            truth_artifacts="x" * 200,
            vault_notes="y" * 200,
            harness_context="z" * 200,
            budget=budget,
        )
        assert result.success is False
        assert result.oversized is True
        assert result.contents is None


class TestOversizedDoesNotSplitInline:
    """Verify oversized result has no decomposed contents (D-13)."""

    @pytest.mark.asyncio
    async def test_oversized_does_not_split_inline(self):
        """Oversized result returns contents=None, not partial content (D-13)."""
        builder = GuidePackBuilder(chars_per_token=1)
        budget = GuidePackBudget(total_budget_tokens=3)
        result = await builder.assemble(
            truth_artifacts="x" * 100,
            vault_notes="y" * 100,
            harness_context="z" * 100,
            budget=budget,
        )
        assert result.oversized is True
        assert result.contents is None
        assert result.success is False


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


class TestKillSwitchBlocksAssemble:
    """Kill switch active -> assembly blocked."""

    @pytest.mark.asyncio
    async def test_kill_switch_blocks_assemble(self):
        """Halted kill switch raises RuntimeError."""
        mock_ks = AsyncMock()
        mock_ks.is_halted = lambda activity_class: True

        builder = GuidePackBuilder(kill_switch=mock_ks)
        budget = GuidePackBudget(total_budget_tokens=1000)

        with pytest.raises(RuntimeError, match="[Kk]ill switch"):
            await builder.assemble(
                truth_artifacts="a",
                vault_notes="b",
                harness_context="c",
                budget=budget,
            )


class TestSummarizerRoutesToCorrectSection:
    """Summarizer must replace whichever section was largest (not always truth)."""

    @pytest.mark.asyncio
    async def test_summarizer_replaces_vault_when_vault_largest(self):
        mock_summarizer = AsyncMock()
        mock_summarizer.summarize = AsyncMock(return_value="vault-summary")

        builder = GuidePackBuilder(chars_per_token=1, summarizer=mock_summarizer)
        # budget=30 -> quotas: truth=12, vault=9, harness=9
        # After truncation: truth=5 (fits), vault=21 (truncated 9+12 marker),
        # harness=5 (fits) -> total=31 > 30 -> summarize largest = vault.
        budget = GuidePackBudget(total_budget_tokens=30)
        result = await builder.assemble(
            truth_artifacts="a" * 5,
            vault_notes="b" * 100,
            harness_context="c" * 5,
            budget=budget,
        )
        assert result.success is True
        assert result.contents is not None
        assert result.contents.vault_notes == "vault-summary"

    @pytest.mark.asyncio
    async def test_summarizer_replaces_harness_when_harness_largest(self):
        mock_summarizer = AsyncMock()
        mock_summarizer.summarize = AsyncMock(return_value="harness-summary")

        builder = GuidePackBuilder(chars_per_token=1, summarizer=mock_summarizer)
        budget = GuidePackBudget(total_budget_tokens=30)
        result = await builder.assemble(
            truth_artifacts="a" * 5,
            vault_notes="b" * 5,
            harness_context="c" * 100,
            budget=budget,
        )
        assert result.success is True
        assert result.contents is not None
        assert result.contents.harness_context == "harness-summary"


class TestAuditLedgerLogsAssembly:
    """When an audit ledger is supplied, assembly outcomes are logged."""

    @pytest.mark.asyncio
    async def test_successful_assembly_logged_to_audit_ledger(self):
        mock_ledger = AsyncMock()
        builder = GuidePackBuilder(chars_per_token=1, audit_ledger=mock_ledger)
        budget = GuidePackBudget(total_budget_tokens=1000)

        await builder.assemble(
            truth_artifacts="a" * 10,
            vault_notes="b" * 10,
            harness_context="c" * 10,
            budget=budget,
        )

        mock_ledger.append_event.assert_awaited_once()
        kwargs = mock_ledger.append_event.await_args.kwargs
        assert kwargs["actor"] == "guide_pack_builder"
        assert kwargs["decision"] == "success"
