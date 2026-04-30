"""Deterministic classification engine implementing the PRD SS8.4 decision table.

This is the entry point for CES governance: it determines what controls
apply to each task based on a pure table lookup. NO LLM involvement (LLM-05).

The classification oracle with fuzzy matching (CLASS-03, CLASS-04) is Phase 2 scope.

Exports:
    ClassificationRule: Frozen dataclass representing a single decision table row.
    CLASSIFICATION_TABLE: All 38 rows (30 from PRD SS8.4 + 8 bootstrap self-classification).
    ClassificationEngine: Deterministic lookup and aggregate classification.
"""

from __future__ import annotations

from dataclasses import dataclass

from ces.shared.enums import BehaviorConfidence, ChangeClass, RiskTier


@dataclass(frozen=True)
class ClassificationRule:
    """A single row from the PRD SS8.4 classification decision table.

    Frozen to guarantee immutability at runtime (T-05-03 mitigation).
    """

    description: str
    risk_tier: RiskTier
    behavior_confidence: BehaviorConfidence
    change_class: ChangeClass


# ---------------------------------------------------------------------------
# PRD SS8.4 — Classification decision table (30 base + 8 bootstrap)
# ---------------------------------------------------------------------------

CLASSIFICATION_TABLE: list[ClassificationRule] = [
    # Row 1
    ClassificationRule(
        description="Add a new internal utility function",
        risk_tier=RiskTier.C,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_1,
    ),
    # Row 2
    ClassificationRule(
        description="Add a new API endpoint (internal)",
        risk_tier=RiskTier.B,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_1,
    ),
    # Row 3
    ClassificationRule(
        description="Add a new API endpoint (external)",
        risk_tier=RiskTier.A,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_3,
    ),
    # Row 4
    ClassificationRule(
        description="Fix a typo in a UI string",
        risk_tier=RiskTier.C,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_2,
    ),
    # Row 5
    ClassificationRule(
        description="Fix an off-by-one in pagination",
        risk_tier=RiskTier.B,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_2,
    ),
    # Row 6
    ClassificationRule(
        description="Fix a race condition in payment flow",
        risk_tier=RiskTier.A,
        behavior_confidence=BehaviorConfidence.BC2,
        change_class=ChangeClass.CLASS_2,
    ),
    # Row 7
    ClassificationRule(
        description="Refactor internal module boundaries",
        risk_tier=RiskTier.B,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_2,
    ),
    # Row 8
    ClassificationRule(
        description="Change a database schema (add column)",
        risk_tier=RiskTier.B,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_3,
    ),
    # Row 9
    ClassificationRule(
        description="Change a database schema (modify column)",
        risk_tier=RiskTier.A,
        behavior_confidence=BehaviorConfidence.BC2,
        change_class=ChangeClass.CLASS_3,
    ),
    # Row 10
    ClassificationRule(
        description="Add a feature flag",
        risk_tier=RiskTier.C,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_1,
    ),
    # Row 11
    ClassificationRule(
        description="Remove a feature flag (enable permanently)",
        risk_tier=RiskTier.B,
        behavior_confidence=BehaviorConfidence.BC2,
        change_class=ChangeClass.CLASS_5,
    ),
    # Row 12
    ClassificationRule(
        description="Update a third-party dependency (minor)",
        risk_tier=RiskTier.C,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_2,
    ),
    # Row 13
    ClassificationRule(
        description="Update a third-party dependency (major)",
        risk_tier=RiskTier.B,
        behavior_confidence=BehaviorConfidence.BC2,
        change_class=ChangeClass.CLASS_2,
    ),
    # Row 14
    ClassificationRule(
        description="Change authentication logic",
        risk_tier=RiskTier.A,
        behavior_confidence=BehaviorConfidence.BC2,
        change_class=ChangeClass.CLASS_2,
    ),
    # Row 15
    ClassificationRule(
        description="Change authorization / permissions",
        risk_tier=RiskTier.A,
        behavior_confidence=BehaviorConfidence.BC3,
        change_class=ChangeClass.CLASS_2,
    ),
    # Row 16
    ClassificationRule(
        description="Modify a state machine",
        risk_tier=RiskTier.A,
        behavior_confidence=BehaviorConfidence.BC2,
        change_class=ChangeClass.CLASS_2,
    ),
    # Row 17
    ClassificationRule(
        description="Add a new state to a state machine",
        risk_tier=RiskTier.A,
        behavior_confidence=BehaviorConfidence.BC2,
        change_class=ChangeClass.CLASS_3,
    ),
    # Row 18
    ClassificationRule(
        description="Change error codes or error semantics",
        risk_tier=RiskTier.B,
        behavior_confidence=BehaviorConfidence.BC2,
        change_class=ChangeClass.CLASS_3,
    ),
    # Row 19
    ClassificationRule(
        description="Migrate from legacy service to new",
        risk_tier=RiskTier.A,
        behavior_confidence=BehaviorConfidence.BC2,
        change_class=ChangeClass.CLASS_4,
    ),
    # Row 20
    ClassificationRule(
        description="Replace ORM / data layer",
        risk_tier=RiskTier.A,
        behavior_confidence=BehaviorConfidence.BC3,
        change_class=ChangeClass.CLASS_4,
    ),
    # Row 21
    ClassificationRule(
        description="Shadow-deploy a replacement service",
        risk_tier=RiskTier.B,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_4,
    ),
    # Row 22
    ClassificationRule(
        description="Delete unused code",
        risk_tier=RiskTier.C,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_5,
    ),
    # Row 23
    ClassificationRule(
        description="Retire a public API version",
        risk_tier=RiskTier.A,
        behavior_confidence=BehaviorConfidence.BC2,
        change_class=ChangeClass.CLASS_5,
    ),
    # Row 24
    ClassificationRule(
        description="Remove a database table",
        risk_tier=RiskTier.A,
        behavior_confidence=BehaviorConfidence.BC3,
        change_class=ChangeClass.CLASS_5,
    ),
    # Row 25
    ClassificationRule(
        description="Change logging or telemetry format",
        risk_tier=RiskTier.C,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_3,
    ),
    # Row 26
    ClassificationRule(
        description="UX copy change (user-facing)",
        risk_tier=RiskTier.C,
        behavior_confidence=BehaviorConfidence.BC2,
        change_class=ChangeClass.CLASS_2,
    ),
    # Row 27
    ClassificationRule(
        description="New onboarding flow",
        risk_tier=RiskTier.B,
        behavior_confidence=BehaviorConfidence.BC3,
        change_class=ChangeClass.CLASS_1,
    ),
    # Row 28
    ClassificationRule(
        description="Change checkout flow",
        risk_tier=RiskTier.A,
        behavior_confidence=BehaviorConfidence.BC3,
        change_class=ChangeClass.CLASS_2,
    ),
    # Row 29
    ClassificationRule(
        description="Change pricing logic",
        risk_tier=RiskTier.A,
        behavior_confidence=BehaviorConfidence.BC2,
        change_class=ChangeClass.CLASS_2,
    ),
    # Row 30
    ClassificationRule(
        description="Infrastructure / CI config change",
        risk_tier=RiskTier.B,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_2,
    ),
    # -----------------------------------------------------------------------
    # Rows 31-38: Bootstrap rules for governance-system self-classification
    # Changes to governance infrastructure require elevated controls.
    # -----------------------------------------------------------------------
    # Row 31
    ClassificationRule(
        description="Change to classification engine or decision table",
        risk_tier=RiskTier.A,
        behavior_confidence=BehaviorConfidence.BC3,
        change_class=ChangeClass.CLASS_4,
    ),
    # Row 32
    ClassificationRule(
        description="Change to audit ledger or chain integrity",
        risk_tier=RiskTier.A,
        behavior_confidence=BehaviorConfidence.BC2,
        change_class=ChangeClass.CLASS_4,
    ),
    # Row 33
    ClassificationRule(
        description="Change to kill switch or emergency halt logic",
        risk_tier=RiskTier.A,
        behavior_confidence=BehaviorConfidence.BC2,
        change_class=ChangeClass.CLASS_4,
    ),
    # Row 34
    ClassificationRule(
        description="Change to review executor or review pipeline",
        risk_tier=RiskTier.A,
        behavior_confidence=BehaviorConfidence.BC3,
        change_class=ChangeClass.CLASS_4,
    ),
    # Row 35
    ClassificationRule(
        description="Change to gate evaluator or phase gates",
        risk_tier=RiskTier.A,
        behavior_confidence=BehaviorConfidence.BC2,
        change_class=ChangeClass.CLASS_3,
    ),
    # Row 36
    ClassificationRule(
        description="Change to merge controller or merge validation",
        risk_tier=RiskTier.A,
        behavior_confidence=BehaviorConfidence.BC2,
        change_class=ChangeClass.CLASS_3,
    ),
    # Row 37
    ClassificationRule(
        description="Change to evidence synthesizer or evidence pipeline",
        risk_tier=RiskTier.B,
        behavior_confidence=BehaviorConfidence.BC2,
        change_class=ChangeClass.CLASS_3,
    ),
    # Row 38
    ClassificationRule(
        description="Change to sensor framework or sensor pack",
        risk_tier=RiskTier.B,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_2,
    ),
]


class ClassificationEngine:
    """Deterministic classification engine. NO LLM involvement (LLM-05).

    Implements PRD SS8.4 decision table lookup and SS8.5 aggregate
    release-slice classification (CLASS-02).

    The classification oracle with fuzzy matching is Phase 2 scope
    (CLASS-03, CLASS-04). This engine provides exact-match lookup only.
    """

    def __init__(self, table: list[ClassificationRule] | None = None) -> None:
        self.table = table or CLASSIFICATION_TABLE
        # Build index for fast lookup by description (case-insensitive)
        self._index: dict[str, ClassificationRule] = {rule.description.lower(): rule for rule in self.table}

    def classify_by_description(self, description: str) -> ClassificationRule | None:
        """Look up classification by exact description match (case-insensitive).

        Returns None if no match found (T-05-01 mitigation: exact string match
        prevents fuzzy exploitation via prompt injection).

        In Phase 2, CLASS-03 adds oracle with fuzzy matching.
        """
        return self._index.get(description.lower())

    def classify_by_rule_index(self, index: int) -> ClassificationRule:
        """Get classification rule by table index (0-based).

        Raises:
            IndexError: If index is out of range.
        """
        return self.table[index]

    @staticmethod
    def aggregate(rules: list[ClassificationRule]) -> ClassificationRule:
        """Aggregate release-slice classification: max risk of constituent tasks (CLASS-02).

        Returns a synthetic ClassificationRule with:
        - risk_tier = max(all risk tiers)
        - behavior_confidence = max(all behavior confidences)
        - change_class = max(all change classes)

        The max() calls work because RiskTier, BehaviorConfidence, and ChangeClass
        implement __lt__ ordering (from Plan 01 enums).

        Args:
            rules: List of classification rules to aggregate.

        Raises:
            ValueError: If rules list is empty.
        """
        if not rules:
            raise ValueError("Cannot aggregate empty classification list")
        return ClassificationRule(
            description="aggregate",
            risk_tier=max(r.risk_tier for r in rules),
            behavior_confidence=max(r.behavior_confidence for r in rules),
            change_class=max(r.change_class for r in rules),
        )
