"""Tests for ChainOfCustodyTracker -- records per-LLM-call custody entries.

Validates:
- record_call() creates a ChainOfCustodyEntry with model_version from the response
- entries property returns chronological list[ChainOfCustodyEntry]
"""

from __future__ import annotations

from ces.control.models.evidence_packet import ChainOfCustodyEntry
from ces.execution.providers.protocol import ChainOfCustodyTracker, LLMResponse


class TestChainOfCustodyTracker:
    """Tests 8-9: ChainOfCustodyTracker records and retrieves custody entries."""

    def test_record_call_creates_entry(self) -> None:
        """Test 8: record_call() appends a ChainOfCustodyEntry with model_version from response."""
        tracker = ChainOfCustodyTracker()
        response = LLMResponse(
            content="Hello",
            model_id="claude-3-opus",
            model_version="claude-3-opus-20240229",
            input_tokens=10,
            output_tokens=5,
            provider_name="anthropic",
        )

        entry = tracker.record_call(response, step="classification", agent_role="classifier")

        assert isinstance(entry, ChainOfCustodyEntry)
        assert entry.agent_model == "claude-3-opus-20240229"
        assert entry.step == "classification"
        assert entry.agent_role == "classifier"

    def test_entries_returns_chronological_list(self) -> None:
        """Test 9: entries property returns list in chronological order."""
        tracker = ChainOfCustodyTracker()

        response1 = LLMResponse(
            content="First",
            model_id="claude-3-opus",
            model_version="claude-3-opus-20240229",
            input_tokens=10,
            output_tokens=5,
            provider_name="anthropic",
        )
        response2 = LLMResponse(
            content="Second",
            model_id="gpt-4o",
            model_version="gpt-4o-2024-05-13",
            input_tokens=15,
            output_tokens=8,
            provider_name="openai",
        )

        tracker.record_call(response1, step="classify", agent_role="classifier")
        tracker.record_call(response2, step="review", agent_role="reviewer")

        entries = tracker.entries
        assert len(entries) == 2
        assert entries[0].step == "classify"
        assert entries[1].step == "review"
        assert entries[0].agent_model == "claude-3-opus-20240229"
        assert entries[1].agent_model == "gpt-4o-2024-05-13"

    def test_entries_returns_copy(self) -> None:
        """entries property returns a copy -- mutating it doesn't affect tracker."""
        tracker = ChainOfCustodyTracker()
        response = LLMResponse(
            content="Hello",
            model_id="claude-3-opus",
            model_version="claude-3-opus-20240229",
            input_tokens=10,
            output_tokens=5,
            provider_name="anthropic",
        )
        tracker.record_call(response, step="classify", agent_role="classifier")

        entries = tracker.entries
        entries.clear()
        assert len(tracker.entries) == 1  # Original unaffected
