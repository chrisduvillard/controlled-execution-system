"""Evidence Packet model (PRD Part IV SS2.6).

Evidence Packets are produced artifacts (NOT truth artifacts). They capture
the complete evidence trail for a task: agent chain of custody, decision view
for human review, adversarial honesty disclosures, and raw evidence links.
"""

from __future__ import annotations

from datetime import datetime

from ces.shared.base import CESBaseModel
from ces.shared.enums import (
    BehaviorConfidence,
    ChangeClass,
    RiskTier,
    RollbackReadiness,
)


class ChainOfCustodyEntry(CESBaseModel):
    """Records which agent/model performed each pipeline step."""

    step: str
    agent_model: str
    agent_role: str
    timestamp: datetime
    runtime_name: str | None = None
    runtime_version: str | None = None
    reported_model: str | None = None
    invocation_ref: str | None = None


class TestOutcomes(CESBaseModel):
    """Test results summary."""

    __test__ = False

    passed: int
    failed: int
    skipped: int


class HiddenTestOutcomes(CESBaseModel):
    """Hidden (undisclosed) test results summary."""

    passed: int
    failed: int


class EconomicImpact(CESBaseModel):
    """Economic impact of the task execution."""

    tokens_consumed: int
    invocations: int
    wall_clock_minutes: float


class DecisionView(CESBaseModel):
    """Human-readable summary of the change for review decisions.

    Contains all fields needed for an approver to make an informed decision:
    risk classification, test outcomes, review summary, rollback readiness,
    economic impact, and vault references.
    """

    change_summary: str
    scope: str
    affected_artifacts: tuple[str, ...]
    risk_tier: RiskTier
    behavior_confidence_class: BehaviorConfidence
    change_class: ChangeClass
    prl_impact: str
    architecture_impact: str
    contract_impact: str
    migration_impact: str
    harness_impact: str
    assumptions: tuple[str, ...]
    unknowns: tuple[str, ...]
    test_outcomes: TestOutcomes
    hidden_test_outcomes: HiddenTestOutcomes | None = None
    review_summary: str
    unresolved_risks: tuple[str, ...]
    rollback_readiness: RollbackReadiness
    economic_impact: EconomicImpact
    recommended_decision: str
    vault_references: tuple[str, ...]


class AdversarialHonesty(CESBaseModel):
    """Mandatory adversarial honesty disclosures.

    Agents must honestly report retries, skipped checks, context
    summarization, review disagreements, and stale risks.
    """

    retries_used: int
    skipped_checks: tuple[str, ...]
    flaky_checks: tuple[str, ...]
    context_summarized: bool
    context_summarization_details: str | None = None
    exception_paths_used: tuple[str, ...]
    review_disagreements: tuple[str, ...]
    stale_approval_risk: bool
    stale_check_risk: bool
    omitted_evidence_categories: tuple[str, ...]


class RawEvidenceLinks(CESBaseModel):
    """Links to raw evidence artifacts."""

    test_logs: tuple[str, ...]
    review_outputs: tuple[str, ...]
    replay_diffs: tuple[str, ...]
    reconciliation_outputs: tuple[str, ...]
    deployment_checks: tuple[str, ...]
    observability_dashboards: tuple[str, ...]


class EvidencePacket(CESBaseModel):
    """Evidence Packet (PRD SS2.6).

    NOT a GovernedArtifactBase -- evidence packets are produced artifacts,
    not truth artifacts. They record the complete evidence trail for a task.
    """

    packet_id: str
    task_id: str
    manifest_hash: str
    agent_chain_of_custody: tuple[ChainOfCustodyEntry, ...]
    decision_view: DecisionView
    adversarial_honesty: AdversarialHonesty
    raw_evidence_links: RawEvidenceLinks
    created_at: datetime
    signature: str | None = None
