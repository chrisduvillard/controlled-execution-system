"""Tests for EvidenceSynthesizer service.

Covers: decision view assembly (D-01), exhaustive triage matrix (D-02),
auto-approval for green/TierC/BC1/Trusted (D-03), mandatory disclosure
creation (D-04), summary slot formatting (EVID-04), chain of custody
tracking with SHA-256 content hash (D-07, EVID-12), kill switch blocking,
and audit ledger logging.

Phase 08-03 additions: LLM-generated summary slots via provider.generate().
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from ces.execution.providers.multi_model import MultiModelConfig
from ces.execution.providers.protocol import LLMResponse
from ces.execution.providers.registry import ProviderRegistry
from ces.harness.models.sensor_result import SensorResult
from ces.harness.models.triage_result import TriageColor
from ces.harness.services.evidence_synthesizer import (
    ChainOfCustodyTracker,
    DecisionViewSlot,
    EvidenceSynthesizer,
    KillSwitchActiveError,
    SummarySlots,
)
from ces.shared.crypto import sha256_hash
from ces.shared.enums import BehaviorConfidence, RiskTier, TrustStatus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def kill_switch() -> MagicMock:
    """Mock kill switch that is NOT halted."""
    ks = MagicMock()
    ks.is_halted.return_value = False
    return ks


@pytest.fixture()
def halted_kill_switch() -> MagicMock:
    """Mock kill switch that IS halted."""
    ks = MagicMock()
    ks.is_halted.return_value = True
    return ks


@pytest.fixture()
def audit_ledger() -> AsyncMock:
    """Mock audit ledger with async append_event."""
    ledger = AsyncMock()
    return ledger


@pytest.fixture()
def synth(kill_switch: MagicMock, audit_ledger: AsyncMock) -> EvidenceSynthesizer:
    """EvidenceSynthesizer with mock kill switch and audit ledger."""
    return EvidenceSynthesizer(kill_switch=kill_switch, audit_ledger=audit_ledger)


@pytest.fixture()
def halted_synth(
    halted_kill_switch: MagicMock,
    audit_ledger: AsyncMock,
) -> EvidenceSynthesizer:
    """EvidenceSynthesizer with HALTED kill switch."""
    return EvidenceSynthesizer(kill_switch=halted_kill_switch, audit_ledger=audit_ledger)


def _make_sensor_result(*, passed: bool, score: float = 1.0) -> SensorResult:
    """Helper to create a SensorResult."""
    return SensorResult(
        sensor_id="test-sensor",
        sensor_pack="test-pack",
        passed=passed,
        score=score,
        details="test",
        timestamp=datetime.now(timezone.utc),
    )


def _make_mock_provider(
    summary_content: str = "Summary line 1\nSummary line 2\nSummary line 3",
    challenge_content: str = "Challenge line 1\nChallenge line 2",
) -> MagicMock:
    """Create a mock LLM provider with generate() returning LLMResponse-like objects."""
    from ces.execution.providers.protocol import LLMResponse

    provider = MagicMock()

    summary_response = LLMResponse(
        content=summary_content,
        model_id="test-model",
        model_version="1.0",
        input_tokens=100,
        output_tokens=50,
        provider_name="test-provider",
    )
    challenge_response = LLMResponse(
        content=challenge_content,
        model_id="test-model",
        model_version="1.0",
        input_tokens=80,
        output_tokens=30,
        provider_name="test-provider",
    )

    provider.generate = AsyncMock(side_effect=[summary_response, challenge_response])
    return provider


# ---------------------------------------------------------------------------
# Decision View Assembly (D-01)
# ---------------------------------------------------------------------------


class TestDecisionViewAssembly:
    """D-01: Adversarial decision views as For/Against/Neutral triad."""

    def test_returns_three_slots(self, synth: EvidenceSynthesizer) -> None:
        views = synth.assemble_decision_views()
        assert len(views) == 3

    def test_positions_are_for_against_neutral(self, synth: EvidenceSynthesizer) -> None:
        views = synth.assemble_decision_views()
        positions = [v.position for v in views]
        assert positions == ["for", "against", "neutral"]

    def test_slots_are_decision_view_slot_type(self, synth: EvidenceSynthesizer) -> None:
        views = synth.assemble_decision_views()
        for v in views:
            assert isinstance(v, DecisionViewSlot)

    def test_slots_have_empty_content(self, synth: EvidenceSynthesizer) -> None:
        """Phase 4 fills content; Phase 3 returns empty slots."""
        views = synth.assemble_decision_views()
        for v in views:
            assert v.content == ""


# ---------------------------------------------------------------------------
# Decision Views from Review Findings
# ---------------------------------------------------------------------------


class TestDecisionViewsFromReview:
    """Decision view population from AggregatedReview data."""

    def test_critical_findings_populate_against_slot(self, synth: EvidenceSynthesizer) -> None:
        review_data = {
            "findings": [
                {"severity": "critical", "title": "SQL injection", "file_path": "src/db.py"},
                {"severity": "high", "title": "Missing auth", "file_path": "src/api.py"},
                {"severity": "low", "title": "Naming", "file_path": "src/utils.py"},
            ],
            "critical_count": 1,
            "high_count": 1,
            "disagreements": [],
        }
        for_v, against_v, neutral_v = synth.assemble_decision_views_from_review(review_data)
        assert "CRITICAL" in against_v.content
        assert "SQL injection" in against_v.content
        assert against_v.position == "against"

    def test_no_critical_populates_for_slot(self, synth: EvidenceSynthesizer) -> None:
        review_data = {
            "findings": [
                {"severity": "low", "title": "Naming", "file_path": "src/utils.py"},
                {"severity": "info", "title": "Style", "file_path": "src/main.py"},
            ],
            "critical_count": 0,
            "high_count": 0,
            "disagreements": [],
        }
        for_v, against_v, neutral_v = synth.assemble_decision_views_from_review(review_data)
        assert "No critical" in for_v.content
        assert for_v.position == "for"

    def test_empty_findings(self, synth: EvidenceSynthesizer) -> None:
        review_data = {
            "findings": [],
            "critical_count": 0,
            "high_count": 0,
            "disagreements": [],
        }
        for_v, against_v, neutral_v = synth.assemble_decision_views_from_review(review_data)
        assert "no critical" in for_v.content.lower()
        assert "0" in neutral_v.content

    def test_disagreements_mentioned(self, synth: EvidenceSynthesizer) -> None:
        review_data = {
            "findings": [
                {"severity": "critical", "title": "Issue", "file_path": "src/x.py"},
            ],
            "critical_count": 1,
            "high_count": 0,
            "disagreements": ["Reviewer A flagged critical but B had nothing"],
        }
        _, against_v, neutral_v = synth.assemble_decision_views_from_review(review_data)
        assert "disagreement" in against_v.content.lower() or "disagreement" in neutral_v.content.lower()

    def test_returns_three_slots_with_correct_positions(self, synth: EvidenceSynthesizer) -> None:
        review_data = {"findings": [], "critical_count": 0, "high_count": 0, "disagreements": []}
        views = synth.assemble_decision_views_from_review(review_data)
        assert len(views) == 3
        assert [v.position for v in views] == ["for", "against", "neutral"]


# ---------------------------------------------------------------------------
# Disclosure Set Creation (D-04)
# ---------------------------------------------------------------------------


class TestDisclosureSetCreation:
    """D-04: Mandatory disclosure creation."""

    def test_create_disclosure_set(self, synth: EvidenceSynthesizer) -> None:
        ds = synth.create_disclosure_set(
            retries_used=2,
            skipped_checks=("lint",),
            summarized_context=True,
            summarization_details="Truncated to 4k tokens",
            disagreements=("Security concern",),
        )
        assert ds.retries_used == 2
        assert ds.skipped_checks == ("lint",)
        assert ds.summarized_context is True
        assert ds.summarization_details == "Truncated to 4k tokens"
        assert ds.disagreements == ("Security concern",)

    def test_disclosure_set_is_frozen(self, synth: EvidenceSynthesizer) -> None:
        ds = synth.create_disclosure_set(
            retries_used=0,
            skipped_checks=(),
            summarized_context=False,
            summarization_details=None,
            disagreements=(),
        )
        with pytest.raises(Exception):
            ds.retries_used = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Triage (D-02) -- parametrized across all 24 combinations
# ---------------------------------------------------------------------------


class TestTriage:
    """D-02: Exhaustive triage matrix with 24 combinations."""

    @pytest.mark.parametrize(
        ("tier", "trust", "all_passed", "expected_color"),
        [
            # Tier C
            (RiskTier.C, TrustStatus.TRUSTED, True, TriageColor.GREEN),
            (RiskTier.C, TrustStatus.TRUSTED, False, TriageColor.YELLOW),
            (RiskTier.C, TrustStatus.CANDIDATE, True, TriageColor.YELLOW),
            (RiskTier.C, TrustStatus.CANDIDATE, False, TriageColor.RED),
            (RiskTier.C, TrustStatus.WATCH, True, TriageColor.YELLOW),
            (RiskTier.C, TrustStatus.WATCH, False, TriageColor.RED),
            (RiskTier.C, TrustStatus.CONSTRAINED, True, TriageColor.RED),
            (RiskTier.C, TrustStatus.CONSTRAINED, False, TriageColor.RED),
            # Tier B
            (RiskTier.B, TrustStatus.TRUSTED, True, TriageColor.YELLOW),
            (RiskTier.B, TrustStatus.TRUSTED, False, TriageColor.RED),
            (RiskTier.B, TrustStatus.CANDIDATE, True, TriageColor.YELLOW),
            (RiskTier.B, TrustStatus.CANDIDATE, False, TriageColor.RED),
            (RiskTier.B, TrustStatus.WATCH, True, TriageColor.RED),
            (RiskTier.B, TrustStatus.WATCH, False, TriageColor.RED),
            (RiskTier.B, TrustStatus.CONSTRAINED, True, TriageColor.RED),
            (RiskTier.B, TrustStatus.CONSTRAINED, False, TriageColor.RED),
            # Tier A
            (RiskTier.A, TrustStatus.TRUSTED, True, TriageColor.YELLOW),
            (RiskTier.A, TrustStatus.TRUSTED, False, TriageColor.RED),
            (RiskTier.A, TrustStatus.CANDIDATE, True, TriageColor.RED),
            (RiskTier.A, TrustStatus.CANDIDATE, False, TriageColor.RED),
            (RiskTier.A, TrustStatus.WATCH, True, TriageColor.RED),
            (RiskTier.A, TrustStatus.WATCH, False, TriageColor.RED),
            (RiskTier.A, TrustStatus.CONSTRAINED, True, TriageColor.RED),
            (RiskTier.A, TrustStatus.CONSTRAINED, False, TriageColor.RED),
        ],
    )
    async def test_triage_matrix(
        self,
        synth: EvidenceSynthesizer,
        tier: RiskTier,
        trust: TrustStatus,
        all_passed: bool,
        expected_color: TriageColor,
    ) -> None:
        """Every (tier, trust, sensors_green) combination returns expected color."""
        if all_passed:
            sensors = [_make_sensor_result(passed=True)]
        else:
            sensors = [
                _make_sensor_result(passed=True, score=0.8),
                _make_sensor_result(passed=False, score=0.2),
            ]
        result = await synth.triage(tier, trust, sensors)
        assert result.color == expected_color

    async def test_triage_computes_sensor_pass_rate(
        self,
        synth: EvidenceSynthesizer,
    ) -> None:
        sensors = [
            _make_sensor_result(passed=True),
            _make_sensor_result(passed=True),
            _make_sensor_result(passed=False, score=0.3),
        ]
        result = await synth.triage(RiskTier.C, TrustStatus.TRUSTED, sensors)
        assert abs(result.sensor_pass_rate - (2.0 / 3.0)) < 0.01

    async def test_triage_logs_to_audit_ledger(
        self,
        synth: EvidenceSynthesizer,
        audit_ledger: AsyncMock,
    ) -> None:
        sensors = [_make_sensor_result(passed=True)]
        await synth.triage(RiskTier.C, TrustStatus.TRUSTED, sensors)
        audit_ledger.append_event.assert_called_once()

    async def test_triage_empty_sensors_treated_as_none_passed(
        self,
        synth: EvidenceSynthesizer,
    ) -> None:
        """Empty sensor list means 0% pass rate -> sensors_green=False."""
        result = await synth.triage(RiskTier.C, TrustStatus.TRUSTED, [])
        assert result.sensor_pass_rate == 0.0
        assert result.color == TriageColor.YELLOW  # C + Trusted + sensors_green=False


# ---------------------------------------------------------------------------
# Auto-Approval (D-03)
# ---------------------------------------------------------------------------


class TestAutoApproval:
    """D-03: Auto-approval requires all 4 criteria."""

    def test_auto_approve_when_all_criteria_met(
        self,
        synth: EvidenceSynthesizer,
    ) -> None:
        from ces.harness.models.triage_result import TriageDecision

        td = TriageDecision(
            color=TriageColor.GREEN,
            risk_tier=RiskTier.C,
            trust_status=TrustStatus.TRUSTED,
            sensor_pass_rate=1.0,
            reason="All green",
            auto_approve_eligible=True,
        )
        assert synth.evaluate_auto_approval(td, BehaviorConfidence.BC1) is True

    @pytest.mark.parametrize(
        ("color", "tier", "trust", "bc", "reason"),
        [
            (TriageColor.YELLOW, RiskTier.C, TrustStatus.TRUSTED, BehaviorConfidence.BC1, "not green"),
            (TriageColor.RED, RiskTier.C, TrustStatus.TRUSTED, BehaviorConfidence.BC1, "red"),
            (TriageColor.GREEN, RiskTier.B, TrustStatus.TRUSTED, BehaviorConfidence.BC1, "not tier C"),
            (TriageColor.GREEN, RiskTier.A, TrustStatus.TRUSTED, BehaviorConfidence.BC1, "tier A"),
            (TriageColor.GREEN, RiskTier.C, TrustStatus.CANDIDATE, BehaviorConfidence.BC1, "not trusted"),
            (TriageColor.GREEN, RiskTier.C, TrustStatus.WATCH, BehaviorConfidence.BC1, "watch"),
            (TriageColor.GREEN, RiskTier.C, TrustStatus.CONSTRAINED, BehaviorConfidence.BC1, "constrained"),
            (TriageColor.GREEN, RiskTier.C, TrustStatus.TRUSTED, BehaviorConfidence.BC2, "not BC1"),
            (TriageColor.GREEN, RiskTier.C, TrustStatus.TRUSTED, BehaviorConfidence.BC3, "BC3"),
        ],
    )
    def test_auto_approve_false_when_criteria_not_met(
        self,
        synth: EvidenceSynthesizer,
        color: TriageColor,
        tier: RiskTier,
        trust: TrustStatus,
        bc: BehaviorConfidence,
        reason: str,
    ) -> None:
        """Auto-approval is False when any of the 4 criteria is not met."""
        from ces.harness.models.triage_result import TriageDecision

        td = TriageDecision(
            color=color,
            risk_tier=tier,
            trust_status=trust,
            sensor_pass_rate=1.0,
            reason=f"Test: {reason}",
            auto_approve_eligible=False,
        )
        assert synth.evaluate_auto_approval(td, bc) is False


# ---------------------------------------------------------------------------
# Summary Slots (EVID-04) -- backward compatibility (no provider)
# ---------------------------------------------------------------------------


class TestSummarySlots:
    """EVID-04: 10-line summary + 3-line challenge slots (backward compat)."""

    async def test_format_summary_slots_no_provider(self, synth: EvidenceSynthesizer) -> None:
        """Without provider arg, returns empty SummarySlots (backward compat)."""
        slots = await synth.format_summary_slots()
        assert isinstance(slots, SummarySlots)
        assert slots.max_summary_lines == 10
        assert slots.max_challenge_lines == 3
        assert slots.summary == ""
        assert slots.challenge == ""


# ---------------------------------------------------------------------------
# Summary Slots with LLM Provider (EVID-04 Phase 08-03)
# ---------------------------------------------------------------------------


class TestSummarySlotsWithLLM:
    """EVID-04: LLM-generated summary and challenge via provider.generate()."""

    async def test_with_provider_returns_non_empty_summary(
        self,
        synth: EvidenceSynthesizer,
    ) -> None:
        provider = _make_mock_provider()
        slots = await synth.format_summary_slots(
            provider=provider,
            model_id="test-model",
            evidence_context={"key": "value"},
        )
        assert slots.summary != ""

    async def test_with_provider_returns_non_empty_challenge(
        self,
        synth: EvidenceSynthesizer,
    ) -> None:
        provider = _make_mock_provider()
        slots = await synth.format_summary_slots(
            provider=provider,
            model_id="test-model",
            evidence_context={"key": "value"},
        )
        assert slots.challenge != ""

    async def test_provider_generate_called_twice(
        self,
        synth: EvidenceSynthesizer,
    ) -> None:
        """provider.generate() called once for summary, once for challenge."""
        provider = _make_mock_provider()
        await synth.format_summary_slots(
            provider=provider,
            model_id="test-model",
            evidence_context={"key": "value"},
        )
        assert provider.generate.call_count == 2

    async def test_summary_truncated_to_10_lines(
        self,
        synth: EvidenceSynthesizer,
    ) -> None:
        """Summary longer than 10 lines is truncated."""
        long_summary = "\n".join(f"Line {i}" for i in range(20))
        provider = _make_mock_provider(summary_content=long_summary)
        slots = await synth.format_summary_slots(
            provider=provider,
            model_id="test-model",
            evidence_context={},
        )
        assert len(slots.summary.split("\n")) <= 10

    async def test_challenge_truncated_to_3_lines(
        self,
        synth: EvidenceSynthesizer,
    ) -> None:
        """Challenge longer than 3 lines is truncated."""
        long_challenge = "\n".join(f"Challenge {i}" for i in range(10))
        provider = _make_mock_provider(challenge_content=long_challenge)
        slots = await synth.format_summary_slots(
            provider=provider,
            model_id="test-model",
            evidence_context={},
        )
        assert len(slots.challenge.split("\n")) <= 3

    async def test_without_provider_returns_empty(
        self,
        synth: EvidenceSynthesizer,
    ) -> None:
        """Backward compatibility: no provider returns empty SummarySlots."""
        slots = await synth.format_summary_slots()
        assert slots.summary == ""
        assert slots.challenge == ""

    async def test_kill_switch_blocks_with_provider(
        self,
        halted_synth: EvidenceSynthesizer,
    ) -> None:
        """Kill switch blocks even when provider is given."""
        provider = _make_mock_provider()
        with pytest.raises(KillSwitchActiveError):
            await halted_synth.format_summary_slots(
                provider=provider,
                model_id="test-model",
                evidence_context={},
            )


# ---------------------------------------------------------------------------
# Chain of Custody (D-07, EVID-12)
# ---------------------------------------------------------------------------


class TestChainOfCustody:
    """D-07/EVID-12: Chain of custody with SHA-256 content hash."""

    def test_create_chain_tracker(self, synth: EvidenceSynthesizer) -> None:
        tracker = synth.create_chain_tracker()
        assert isinstance(tracker, ChainOfCustodyTracker)
        assert tracker.entries == []

    def test_append_entry(self, synth: EvidenceSynthesizer) -> None:
        tracker = synth.create_chain_tracker()
        content = {"code": "print('hello')", "test": "assert True"}
        entry = tracker.append("build", "agent-001", "claude-3-opus", content)
        assert entry.step == "build"
        assert entry.agent_model == "claude-3-opus"
        assert entry.agent_role == "agent-001"

    def test_content_hash_uses_sha256(self, synth: EvidenceSynthesizer) -> None:
        tracker = synth.create_chain_tracker()
        content = {"key": "value"}
        entry = tracker.append("step1", "agent-1", "model-1", content)
        expected_hash = sha256_hash(content)
        assert entry.content_hash == expected_hash

    def test_append_is_additive(self, synth: EvidenceSynthesizer) -> None:
        tracker = synth.create_chain_tracker()
        tracker.append("step1", "a1", "m1", {"a": 1})
        tracker.append("step2", "a2", "m2", {"b": 2})
        assert len(tracker.entries) == 2

    def test_entries_have_timestamps(self, synth: EvidenceSynthesizer) -> None:
        tracker = synth.create_chain_tracker()
        entry = tracker.append("step1", "a1", "m1", {"a": 1})
        assert entry.timestamp is not None


# ---------------------------------------------------------------------------
# Kill Switch Blocking (T-03-05)
# ---------------------------------------------------------------------------


class TestKillSwitchBlocking:
    """T-03-05: Kill switch checked before all operations."""

    def test_assemble_decision_views_blocked(
        self,
        halted_synth: EvidenceSynthesizer,
    ) -> None:
        with pytest.raises(KillSwitchActiveError):
            halted_synth.assemble_decision_views()

    def test_create_disclosure_set_blocked(
        self,
        halted_synth: EvidenceSynthesizer,
    ) -> None:
        with pytest.raises(KillSwitchActiveError):
            halted_synth.create_disclosure_set(
                retries_used=0,
                skipped_checks=(),
                summarized_context=False,
                summarization_details=None,
                disagreements=(),
            )

    async def test_triage_blocked(
        self,
        halted_synth: EvidenceSynthesizer,
    ) -> None:
        with pytest.raises(KillSwitchActiveError):
            await halted_synth.triage(
                RiskTier.C,
                TrustStatus.TRUSTED,
                [_make_sensor_result(passed=True)],
            )

    async def test_format_summary_slots_blocked(
        self,
        halted_synth: EvidenceSynthesizer,
    ) -> None:
        with pytest.raises(KillSwitchActiveError):
            await halted_synth.format_summary_slots()


# ---------------------------------------------------------------------------
# No kill switch (optional dependency)
# ---------------------------------------------------------------------------


class TestWithoutKillSwitch:
    """EvidenceSynthesizer works without kill switch (optional dependency)."""

    def test_assemble_decision_views_without_kill_switch(self) -> None:
        synth = EvidenceSynthesizer()
        views = synth.assemble_decision_views()
        assert len(views) == 3

    async def test_triage_without_audit_ledger(self) -> None:
        synth = EvidenceSynthesizer()
        sensors = [_make_sensor_result(passed=True)]
        result = await synth.triage(RiskTier.C, TrustStatus.TRUSTED, sensors)
        assert result.color == TriageColor.GREEN


# ---------------------------------------------------------------------------
# Multi-Model Summary Slots (36-02)
# ---------------------------------------------------------------------------


def _make_multi_model_fixtures() -> tuple[MagicMock, MagicMock, ProviderRegistry, MultiModelConfig]:
    """Create two distinct mock providers, a registry, and a MultiModelConfig."""
    synth_provider = MagicMock()
    synth_provider.provider_name = "anthropic-mock"
    synth_response = LLMResponse(
        content="Synth line 1\nSynth line 2\nSynth line 3",
        model_id="claude-3-opus",
        model_version="1.0",
        input_tokens=100,
        output_tokens=50,
        provider_name="anthropic-mock",
    )
    challenge_response_for_synth = LLMResponse(
        content="Synth challenge 1\nSynth challenge 2",
        model_id="claude-3-opus",
        model_version="1.0",
        input_tokens=80,
        output_tokens=30,
        provider_name="anthropic-mock",
    )
    synth_provider.generate = AsyncMock(
        side_effect=[synth_response, challenge_response_for_synth],
    )

    challenge_provider = MagicMock()
    challenge_provider.provider_name = "openai-mock"
    challenge_response = LLMResponse(
        content="Challenge line 1\nChallenge line 2\nChallenge line 3",
        model_id="gpt-4o",
        model_version="2.0",
        input_tokens=90,
        output_tokens=40,
        provider_name="openai-mock",
    )
    challenge_provider.generate = AsyncMock(return_value=challenge_response)

    # Also need a summary response for the synthesizer provider
    synth_summary_response = LLMResponse(
        content="Summary line 1\nSummary line 2\nSummary line 3",
        model_id="claude-3-opus",
        model_version="1.0",
        input_tokens=100,
        output_tokens=50,
        provider_name="anthropic-mock",
    )
    # Reset synth_provider.generate to return summary then nothing
    # (challenge comes from challenge_provider)
    synth_provider.generate = AsyncMock(return_value=synth_summary_response)

    registry = ProviderRegistry()
    registry.register("claude", synth_provider)
    registry.register("gpt", challenge_provider)

    config = MultiModelConfig(
        role_model_map={"synthesizer": "claude-3-opus", "challenger": "gpt-4o"},
    )

    return synth_provider, challenge_provider, registry, config


class TestMultiModelSummarySlots:
    """36-02: Multi-model summary slots with separate synthesis/challenge models."""

    async def test_multi_model_calls_synthesizer_for_summary(
        self,
        synth: EvidenceSynthesizer,
    ) -> None:
        """Synthesizer provider is called for the summary prompt."""
        synth_prov, challenge_prov, registry, config = _make_multi_model_fixtures()
        await synth.format_summary_slots(
            evidence_context={"key": "value"},
            multi_model_config=config,
            provider_registry=registry,
        )
        synth_prov.generate.assert_called_once()
        # First call args should contain summary prompt text
        call_kwargs = synth_prov.generate.call_args
        messages = call_kwargs.kwargs.get("messages", call_kwargs.args[1] if len(call_kwargs.args) > 1 else [])
        assert any("Summarize" in m.get("content", "") for m in messages)

    async def test_multi_model_calls_challenger_for_challenge(
        self,
        synth: EvidenceSynthesizer,
    ) -> None:
        """Challenger provider is called for the challenge prompt."""
        synth_prov, challenge_prov, registry, config = _make_multi_model_fixtures()
        await synth.format_summary_slots(
            evidence_context={"key": "value"},
            multi_model_config=config,
            provider_registry=registry,
        )
        challenge_prov.generate.assert_called_once()
        call_kwargs = challenge_prov.generate.call_args
        messages = call_kwargs.kwargs.get("messages", call_kwargs.args[1] if len(call_kwargs.args) > 1 else [])
        assert any(
            "challenger" in m.get("content", "").lower() or "challenging" in m.get("content", "").lower()
            for m in messages
        )

    async def test_multi_model_uses_correct_model_ids(
        self,
        synth: EvidenceSynthesizer,
    ) -> None:
        """Each provider is called with the correct model_id from the config."""
        synth_prov, challenge_prov, registry, config = _make_multi_model_fixtures()
        await synth.format_summary_slots(
            evidence_context={"key": "value"},
            multi_model_config=config,
            provider_registry=registry,
        )
        synth_call = synth_prov.generate.call_args
        assert synth_call.kwargs.get("model_id") == "claude-3-opus"
        challenge_call = challenge_prov.generate.call_args
        assert challenge_call.kwargs.get("model_id") == "gpt-4o"

    async def test_multi_model_backward_compat_single_provider(
        self,
        synth: EvidenceSynthesizer,
    ) -> None:
        """Existing single-provider callers still work (backward compatible)."""
        provider = _make_mock_provider()
        slots = await synth.format_summary_slots(
            provider=provider,
            model_id="test-model",
            evidence_context={"key": "value"},
        )
        assert slots.summary != ""
        assert slots.challenge != ""

    async def test_multi_model_backward_compat_no_args(
        self,
        synth: EvidenceSynthesizer,
    ) -> None:
        """No args returns empty SummarySlots (backward compatible)."""
        slots = await synth.format_summary_slots()
        assert slots.summary == ""
        assert slots.challenge == ""

    async def test_multi_model_kill_switch_blocks(
        self,
        halted_synth: EvidenceSynthesizer,
    ) -> None:
        """Kill switch blocks multi-model format_summary_slots same as single."""
        _, _, registry, config = _make_multi_model_fixtures()
        with pytest.raises(KillSwitchActiveError):
            await halted_synth.format_summary_slots(
                evidence_context={},
                multi_model_config=config,
                provider_registry=registry,
            )

    async def test_multi_model_summary_truncated_to_10_lines(
        self,
        synth: EvidenceSynthesizer,
    ) -> None:
        """Summary lines truncated to 10 in multi-model mode."""
        synth_prov, challenge_prov, registry, config = _make_multi_model_fixtures()
        long_summary = "\n".join(f"Line {i}" for i in range(20))
        synth_prov.generate = AsyncMock(
            return_value=LLMResponse(
                content=long_summary,
                model_id="claude-3-opus",
                model_version="1.0",
                input_tokens=100,
                output_tokens=200,
                provider_name="anthropic-mock",
            ),
        )
        slots = await synth.format_summary_slots(
            evidence_context={},
            multi_model_config=config,
            provider_registry=registry,
        )
        assert len(slots.summary.split("\n")) <= 10

    async def test_multi_model_raises_without_registry(
        self,
        synth: EvidenceSynthesizer,
    ) -> None:
        """ValueError raised if multi_model_config given without provider_registry."""
        config = MultiModelConfig(
            role_model_map={"synthesizer": "claude-3-opus", "challenger": "gpt-4o"},
        )
        with pytest.raises(ValueError, match="provider_registry is required"):
            await synth.format_summary_slots(
                evidence_context={},
                multi_model_config=config,
            )

    async def test_multi_model_raises_missing_roles(
        self,
        synth: EvidenceSynthesizer,
    ) -> None:
        """ValueError raised if multi_model_config missing synthesizer or challenger."""
        # Config with only synthesizer, missing challenger
        config = MultiModelConfig(
            role_model_map={"synthesizer": "claude-3-opus"},
            min_distinct_models=1,
        )
        registry = ProviderRegistry()
        with pytest.raises(ValueError, match="missing required roles"):
            await synth.format_summary_slots(
                evidence_context={},
                multi_model_config=config,
                provider_registry=registry,
            )


# ---------------------------------------------------------------------------
# Multi-Model Chain of Custody (36-02 Task 2)
# ---------------------------------------------------------------------------


class TestMultiModelChainOfCustody:
    """36-02: Chain-of-custody entries for multi-model synthesis."""

    async def test_custody_records_synthesis_entry(
        self,
        synth: EvidenceSynthesizer,
    ) -> None:
        """Multi-model mode records a 'synthesis' custody entry with synthesizer model_id."""
        synth_prov, challenge_prov, registry, config = _make_multi_model_fixtures()
        tracker = ChainOfCustodyTracker()
        await synth.format_summary_slots(
            evidence_context={"key": "value"},
            multi_model_config=config,
            provider_registry=registry,
            chain_tracker=tracker,
        )
        synthesis_entries = [e for e in tracker.entries if e.step == "synthesis"]
        assert len(synthesis_entries) == 1
        assert synthesis_entries[0].agent_model == "claude-3-opus"

    async def test_custody_records_challenge_entry(
        self,
        synth: EvidenceSynthesizer,
    ) -> None:
        """Multi-model mode records a 'challenge' custody entry with challenger model_id."""
        synth_prov, challenge_prov, registry, config = _make_multi_model_fixtures()
        tracker = ChainOfCustodyTracker()
        await synth.format_summary_slots(
            evidence_context={"key": "value"},
            multi_model_config=config,
            provider_registry=registry,
            chain_tracker=tracker,
        )
        challenge_entries = [e for e in tracker.entries if e.step == "challenge"]
        assert len(challenge_entries) == 1
        assert challenge_entries[0].agent_model == "gpt-4o"

    async def test_custody_has_two_entries(
        self,
        synth: EvidenceSynthesizer,
    ) -> None:
        """Multi-model mode produces exactly 2 custody entries."""
        synth_prov, challenge_prov, registry, config = _make_multi_model_fixtures()
        tracker = ChainOfCustodyTracker()
        await synth.format_summary_slots(
            evidence_context={"key": "value"},
            multi_model_config=config,
            provider_registry=registry,
            chain_tracker=tracker,
        )
        assert len(tracker.entries) == 2

    async def test_custody_entries_have_different_models(
        self,
        synth: EvidenceSynthesizer,
    ) -> None:
        """The two custody entries have different agent_model values."""
        synth_prov, challenge_prov, registry, config = _make_multi_model_fixtures()
        tracker = ChainOfCustodyTracker()
        await synth.format_summary_slots(
            evidence_context={"key": "value"},
            multi_model_config=config,
            provider_registry=registry,
            chain_tracker=tracker,
        )
        models = {e.agent_model for e in tracker.entries}
        assert len(models) == 2
        assert "claude-3-opus" in models
        assert "gpt-4o" in models

    async def test_single_provider_no_custody_entries(
        self,
        synth: EvidenceSynthesizer,
    ) -> None:
        """Single-provider mode does NOT record custody entries (backward compat)."""
        provider = _make_mock_provider()
        tracker = ChainOfCustodyTracker()
        await synth.format_summary_slots(
            provider=provider,
            model_id="test-model",
            evidence_context={"key": "value"},
            chain_tracker=tracker,
        )
        assert len(tracker.entries) == 0
