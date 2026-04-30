"""Evidence Synthesizer service (EVID-01 to EVID-06, EVID-12).

Assembles evidence packets with adversarial decision views, mandatory
disclosures, triage, auto-approval evaluation, and chain of custody tracking.

All structural assembly is deterministic (Phase 3). Phase 4 plugs in
actual LLM content for decision views, summaries, and challenges.
Phase 8 wires format_summary_slots() to real LLM providers.

Threat mitigations:
- T-03-01: Triage matrix is exhaustive with RED default for unknowns
- T-03-02: Content hash via sha256_hash from ces.shared.crypto
- T-03-03: Auto-approval requires 4-condition AND gate
- T-03-05: Kill switch checked before all operations
- T-08-15: Kill switch checked before LLM calls in format_summary_slots
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

from ces.harness.models.disclosure_set import DisclosureSet
from ces.harness.models.sensor_result import SensorResult
from ces.harness.models.triage_result import (
    TriageColor,
    TriageDecision,
    triage_lookup,
)
from ces.shared.base import CESBaseModel
from ces.shared.crypto import sha256_hash
from ces.shared.enums import (
    ActorType,
    BehaviorConfidence,
    EventType,
    RiskTier,
    TrustStatus,
)

if TYPE_CHECKING:
    from ces.execution.providers.multi_model import MultiModelConfig
    from ces.execution.providers.protocol import LLMProviderProtocol
    from ces.execution.providers.registry import ProviderRegistry


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class KillSwitchActiveError(RuntimeError):
    """Raised when an operation is blocked by the kill switch."""


# ---------------------------------------------------------------------------
# Supporting models
# ---------------------------------------------------------------------------


class DecisionViewSlot(CESBaseModel):
    """Structural container for adversarial decision views (D-01).

    Phase 3 creates the structural slots with empty content.
    Phase 4 LLM fills the actual content.

    Positions: "for" (supports change), "against" (opposes change),
    "neutral" (balanced assessment).
    """

    position: Literal["for", "against", "neutral"]
    content: str = ""


class SummarySlots(CESBaseModel):
    """Summary and challenge slot structure (EVID-04).

    10-line summary + 3-line challenge template.
    Phase 4 fills the actual text.
    """

    summary: str = ""
    challenge: str = ""
    max_summary_lines: int = 10
    max_challenge_lines: int = 3


class HarnessChainOfCustodyEntry(CESBaseModel):
    """Extended chain of custody entry with content hash (D-07).

    Extends the control plane's ChainOfCustodyEntry with a content_hash
    field computed via SHA-256 from ces.shared.crypto.
    """

    step: str
    agent_model: str
    agent_role: str
    timestamp: datetime
    content_hash: str


# ---------------------------------------------------------------------------
# Chain of Custody Tracker (D-07, EVID-12)
# ---------------------------------------------------------------------------


class ChainOfCustodyTracker:
    """Append-only chain of custody tracker (D-07).

    Tracks which agent/model performed each pipeline step, with
    content_hash computed via sha256_hash (T-03-02 mitigation).
    """

    def __init__(self) -> None:
        self._entries: list[HarnessChainOfCustodyEntry] = []

    @property
    def entries(self) -> list[HarnessChainOfCustodyEntry]:
        """Return the list of chain of custody entries."""
        return list(self._entries)

    def append(
        self,
        stage: str,
        agent_id: str,
        model_id: str,
        content: dict,  # type: ignore[type-arg]
    ) -> HarnessChainOfCustodyEntry:
        """Append a new entry to the chain of custody.

        Args:
            stage: Pipeline stage name (e.g., "build", "review", "triage").
            agent_id: ID of the agent performing the step.
            model_id: ID of the model used.
            content: Content dictionary to hash for integrity.

        Returns:
            The newly created HarnessChainOfCustodyEntry.
        """
        entry = HarnessChainOfCustodyEntry(
            step=stage,
            agent_model=model_id,
            agent_role=agent_id,
            timestamp=datetime.now(timezone.utc),
            content_hash=sha256_hash(content),
        )
        self._entries.append(entry)
        return entry


# ---------------------------------------------------------------------------
# Evidence Synthesizer Service
# ---------------------------------------------------------------------------


class EvidenceSynthesizer:
    """Evidence synthesizer service (EVID-01 to EVID-06, EVID-12).

    Assembles evidence packets with:
    - 3-position adversarial decision views (D-01)
    - Mandatory disclosures (D-04)
    - Exhaustive triage matrix lookup (D-02)
    - Auto-approval evaluation (D-03)
    - Summary and challenge slots (EVID-04)
    - Chain of custody tracking with SHA-256 content hash (D-07, EVID-12)

    All operations check the kill switch before proceeding (T-03-05).
    Triage decisions and auto-approvals are logged to the audit ledger.
    """

    def __init__(
        self,
        kill_switch: object | None = None,
        audit_ledger: object | None = None,
    ) -> None:
        """Initialize the evidence synthesizer.

        Args:
            kill_switch: Optional KillSwitchProtocol implementation.
                         If provided, is_halted("task_issuance") is checked
                         before all operations.
            audit_ledger: Optional object with append_event method for
                          audit logging.
        """
        self._kill_switch = kill_switch
        self._audit_ledger = audit_ledger

    def _check_kill_switch(self) -> None:
        """Check kill switch before operations (T-03-05).

        Raises:
            KillSwitchActiveError: If the kill switch is halted for task_issuance.
        """
        if self._kill_switch is not None:
            if self._kill_switch.is_halted("task_issuance"):  # type: ignore[union-attr]
                msg = "Kill switch is active for task_issuance"
                raise KillSwitchActiveError(msg)

    # ---- Decision Views (D-01) ----

    def assemble_decision_views(
        self,
    ) -> tuple[DecisionViewSlot, DecisionViewSlot, DecisionViewSlot]:
        """Assemble the For/Against/Neutral decision view slots.

        Returns three structural containers. Phase 4 fills the actual
        content via LLM calls.

        Returns:
            Tuple of (For, Against, Neutral) DecisionViewSlot instances.

        Raises:
            KillSwitchActiveError: If kill switch is active.
        """
        self._check_kill_switch()
        return (
            DecisionViewSlot(position="for"),
            DecisionViewSlot(position="against"),
            DecisionViewSlot(position="neutral"),
        )

    def assemble_decision_views_from_review(
        self,
        review_data: dict,
    ) -> tuple[DecisionViewSlot, DecisionViewSlot, DecisionViewSlot]:
        """Populate decision view slots from persisted review findings.

        Args:
            review_data: Dict from LocalProjectStore.get_review_findings()
                with keys: findings, critical_count, high_count, disagreements.

        Returns:
            Tuple of (For, Against, Neutral) DecisionViewSlot instances
            with content derived from actual review findings.

        Raises:
            KillSwitchActiveError: If kill switch is active.
        """
        self._check_kill_switch()

        findings = review_data.get("findings", [])
        critical = review_data.get("critical_count", 0)
        high = review_data.get("high_count", 0)
        disagreements = review_data.get("disagreements", [])

        # "For" slot: summarize why the change might be safe
        safe_count = sum(1 for f in findings if f["severity"] in ("low", "info"))
        total = len(findings)
        if critical == 0 and high == 0:
            for_content = f"No critical or high-severity findings across {total} review item(s)."
        elif total == 0:
            for_content = "No review findings — reviewers found no issues."
        else:
            for_content = f"{safe_count} of {total} finding(s) are low/info severity."

        # "Against" slot: list critical and high findings
        serious = [f for f in findings if f["severity"] in ("critical", "high")]
        if serious:
            lines = [f"{critical} critical, {high} high finding(s):"]
            for f in serious[:10]:
                loc = f["file_path"] or "unknown"
                lines.append(f"  [{f['severity'].upper()}] {f['title']} ({loc})")
            if disagreements:
                lines.append(f"Reviewer disagreements: {len(disagreements)}")
            against_content = "\n".join(lines)
        else:
            against_content = "No critical or high-severity findings."

        # "Neutral" slot: balanced summary
        neutral_lines = [f"Total findings: {total}"]
        if critical:
            neutral_lines.append(f"Critical: {critical}")
        if high:
            neutral_lines.append(f"High: {high}")
        medium = sum(1 for f in findings if f["severity"] == "medium")
        if medium:
            neutral_lines.append(f"Medium: {medium}")
        if disagreements:
            neutral_lines.append(f"Disagreements between reviewers: {len(disagreements)}")
        neutral_content = "\n".join(neutral_lines)

        return (
            DecisionViewSlot(position="for", content=for_content),
            DecisionViewSlot(position="against", content=against_content),
            DecisionViewSlot(position="neutral", content=neutral_content),
        )

    # ---- Disclosure Set (D-04) ----

    def create_disclosure_set(
        self,
        retries_used: int,
        skipped_checks: list[str],
        summarized_context: bool,
        summarization_details: str | None,
        disagreements: list[str],
    ) -> DisclosureSet:
        """Create a frozen DisclosureSet for mandatory adversarial honesty.

        Args:
            retries_used: Number of retry attempts consumed.
            skipped_checks: List of skipped check IDs.
            summarized_context: Whether context was summarized/truncated.
            summarization_details: Details about summarization.
            disagreements: List of reviewer disagreement descriptions.

        Returns:
            Frozen DisclosureSet instance.

        Raises:
            KillSwitchActiveError: If kill switch is active.
        """
        self._check_kill_switch()
        return DisclosureSet(
            retries_used=retries_used,
            skipped_checks=skipped_checks,
            summarized_context=summarized_context,
            summarization_details=summarization_details,
            disagreements=disagreements,
        )

    # ---- Triage (D-02) ----

    async def triage(
        self,
        risk_tier: RiskTier,
        trust_status: TrustStatus,
        sensor_results: list[SensorResult],
    ) -> TriageDecision:
        """Perform approval triage via the exhaustive matrix (D-02).

        Computes sensor pass rate and looks up the triage color from
        the _TRIAGE_MATRIX. Logs the decision to the audit ledger.

        Args:
            risk_tier: Risk tier classification.
            trust_status: Agent trust status.
            sensor_results: List of sensor execution results.

        Returns:
            TriageDecision with computed color and pass rate.

        Raises:
            KillSwitchActiveError: If kill switch is active.
        """
        self._check_kill_switch()

        # Compute sensor pass rate
        if not sensor_results:
            sensor_pass_rate = 0.0
            sensors_green = False
        else:
            passed_count = sum(1 for s in sensor_results if s.passed)
            sensor_pass_rate = passed_count / len(sensor_results)
            sensors_green = all(s.passed for s in sensor_results)

        # Look up triage color from exhaustive matrix
        color = triage_lookup(risk_tier, trust_status, sensors_green)

        # Determine auto-approve eligibility
        auto_approve = color == TriageColor.GREEN and risk_tier == RiskTier.C and trust_status == TrustStatus.TRUSTED

        reason = (
            f"Tier={risk_tier.value}, Trust={trust_status.value}, "
            f"SensorsGreen={sensors_green}, PassRate={sensor_pass_rate:.2f}"
        )

        decision = TriageDecision(
            color=color,
            risk_tier=risk_tier,
            trust_status=trust_status,
            sensor_pass_rate=sensor_pass_rate,
            reason=reason,
            auto_approve_eligible=auto_approve,
        )

        # Log to audit ledger
        if self._audit_ledger is not None:
            await self._audit_ledger.append_event(  # type: ignore[union-attr]
                event_type=EventType.CLASSIFICATION,
                actor="evidence_synthesizer",
                actor_type=ActorType.CONTROL_PLANE,
                action_summary=f"Triage: {color.value} - {reason}",
                decision=color.value,
                rationale=reason,
            )

        return decision

    # ---- Auto-Approval (D-03) ----

    def evaluate_auto_approval(
        self,
        triage: TriageDecision,
        bc: BehaviorConfidence,
    ) -> bool:
        """Evaluate whether a task qualifies for auto-approval (D-03).

        Four-condition AND gate (T-03-03 mitigation):
        1. Triage color must be GREEN
        2. Risk tier must be C (lowest)
        3. Behavior confidence must be BC1 (highest)
        4. Trust status must be TRUSTED

        Any missing condition returns False.

        Args:
            triage: The triage decision to evaluate.
            bc: Behavior confidence classification.

        Returns:
            True only when all 4 criteria are met.
        """
        return (
            triage.color == TriageColor.GREEN
            and triage.risk_tier == RiskTier.C
            and bc == BehaviorConfidence.BC1
            and triage.trust_status == TrustStatus.TRUSTED
        )

    # ---- Summary Slots (EVID-04) ----

    async def format_summary_slots(
        self,
        provider: LLMProviderProtocol | None = None,
        model_id: str = "",
        evidence_context: dict | None = None,
        *,
        multi_model_config: MultiModelConfig | None = None,
        provider_registry: ProviderRegistry | None = None,
        chain_tracker: ChainOfCustodyTracker | None = None,
    ) -> SummarySlots:
        """Create summary and challenge slots, optionally via LLM (EVID-04).

        When called without a provider or multi_model_config, returns empty
        SummarySlots for backward compatibility with Phase 3 callers.

        When called with a single provider, generates content using that
        provider for both summary and challenge (original behavior).

        When called with multi_model_config + provider_registry, uses the
        "synthesizer" role model for the summary and the "challenger" role
        model for the adversarial challenge, providing model diversity per
        PRD section 5.2.

        Summary and challenge are truncated to their line limits if the
        LLM returns more lines than allowed.

        Args:
            provider: Optional LLM provider for single-model generation.
            model_id: Model ID to use for single-model generation.
            evidence_context: Evidence data to summarize and challenge.
            multi_model_config: Optional role-to-model mapping for diverse
                synthesis. Requires provider_registry when set.
            provider_registry: Registry to resolve model IDs to providers.
                Required when multi_model_config is provided.
            chain_tracker: Optional ChainOfCustodyTracker to record per-step
                custody entries in multi-model mode. Ignored in single-provider mode.

        Returns:
            SummarySlots with content from LLM or empty if no provider.

        Raises:
            KillSwitchActiveError: If kill switch is active (T-08-15).
            ValueError: If multi_model_config provided without provider_registry,
                or if multi_model_config is missing required roles.
        """
        self._check_kill_switch()

        # Multi-model mode: use different models for synthesis and challenge
        if multi_model_config is not None:
            if provider_registry is None:
                msg = "provider_registry is required when multi_model_config is provided"
                raise ValueError(msg)
            required_roles = {"synthesizer", "challenger"}
            missing = required_roles - set(multi_model_config.role_model_map.keys())
            if missing:
                msg = f"multi_model_config missing required roles: {missing}"
                raise ValueError(msg)

            resolved = provider_registry.resolve_roles(multi_model_config)
            synth_provider, synth_model = resolved["synthesizer"]
            challenge_provider, challenge_model = resolved["challenger"]

            context_str = json.dumps(evidence_context or {}, indent=2, default=str)

            summary_prompt = [
                {
                    "role": "user",
                    "content": (
                        "You are reviewing an evidence packet for a governed AI agent task. "
                        "Summarize the following evidence in exactly 10 lines, covering: "
                        "what was done, key findings, risks identified, and recommendation.\n\n"
                        f"Evidence:\n{context_str}"
                    ),
                }
            ]
            summary_response = await synth_provider.generate(
                model_id=synth_model,
                messages=summary_prompt,
                max_tokens=500,
                temperature=0.0,
            )

            if chain_tracker is not None:
                chain_tracker.append(
                    stage="synthesis",
                    agent_id="evidence_synthesizer",
                    model_id=synth_model,
                    content={"summary": summary_response.content},
                )

            challenge_prompt = [
                {
                    "role": "user",
                    "content": (
                        "You are an adversarial challenger reviewing an evidence packet. "
                        "Write exactly 3 lines challenging the strongest assumptions or "
                        "weakest evidence in this work.\n\n"
                        f"Evidence:\n{context_str}"
                    ),
                }
            ]
            challenge_response = await challenge_provider.generate(
                model_id=challenge_model,
                messages=challenge_prompt,
                max_tokens=200,
                temperature=0.0,
            )

            if chain_tracker is not None:
                chain_tracker.append(
                    stage="challenge",
                    agent_id="evidence_synthesizer",
                    model_id=challenge_model,
                    content={"challenge": challenge_response.content},
                )

            summary_lines = summary_response.content.strip().split("\n")[:10]
            challenge_lines = challenge_response.content.strip().split("\n")[:3]
            return SummarySlots(
                summary="\n".join(summary_lines),
                challenge="\n".join(challenge_lines),
            )

        if provider is None:
            return SummarySlots()

        # Build and send summary prompt
        context_str = json.dumps(evidence_context or {}, indent=2, default=str)

        summary_prompt = [
            {
                "role": "user",
                "content": (
                    "You are reviewing an evidence packet for a governed AI agent task. "
                    "Summarize the following evidence in exactly 10 lines, covering: "
                    "what was done, key findings, risks identified, and recommendation.\n\n"
                    f"Evidence:\n{context_str}"
                ),
            },
        ]
        summary_response = await provider.generate(
            model_id=model_id,
            messages=summary_prompt,
            max_tokens=500,
            temperature=0.0,
        )

        # Build and send adversarial challenge prompt
        challenge_prompt = [
            {
                "role": "user",
                "content": (
                    "You are an adversarial challenger reviewing an evidence packet. "
                    "Write exactly 3 lines challenging the strongest assumptions or "
                    "weakest evidence in this work.\n\n"
                    f"Evidence:\n{context_str}"
                ),
            },
        ]
        challenge_response = await provider.generate(
            model_id=model_id,
            messages=challenge_prompt,
            max_tokens=200,
            temperature=0.0,
        )

        # Truncate to line limits
        summary_lines = summary_response.content.strip().split("\n")[:10]
        challenge_lines = challenge_response.content.strip().split("\n")[:3]

        return SummarySlots(
            summary="\n".join(summary_lines),
            challenge="\n".join(challenge_lines),
        )

    # ---- Chain of Custody (D-07, EVID-12) ----

    def create_chain_tracker(self) -> ChainOfCustodyTracker:
        """Create a new chain of custody tracker.

        Returns:
            Empty ChainOfCustodyTracker ready for entries.
        """
        return ChainOfCustodyTracker()
