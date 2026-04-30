"""Tests for CES shared enumerations.

Validates all enum values, ordering behavior for orderable enums,
and string serialization per PRD specifications.
"""

from __future__ import annotations

import pytest

from ces.shared.enums import (
    ActorType,
    ArtifactStatus,
    AssumptionCategory,
    BehaviorConfidence,
    ChangeClass,
    CompatibilityRule,
    ContractStatus,
    DebtOriginType,
    DebtSeverity,
    DebtStatus,
    Disposition,
    EventType,
    GateDecision,
    GateType,
    ImpactScope,
    InterfaceType,
    InvalidationSeverity,
    LegacyDisposition,
    MigrationStatus,
    NFRCategory,
    Priority,
    PRLItemType,
    ReconciliationFrequency,
    ReviewSubState,
    RiskTier,
    RollbackReadiness,
    Sensitivity,
    TrustStatus,
    VaultCategory,
    VaultTrustLevel,
    VerificationMethod,
    VersioningRule,
    WorkflowState,
)


class TestRiskTier:
    """RiskTier enum: A (highest risk), B, C (lowest risk)."""

    def test_values(self) -> None:
        assert RiskTier.A.value == "A"
        assert RiskTier.B.value == "B"
        assert RiskTier.C.value == "C"

    def test_ordering_a_greater_than_b(self) -> None:
        assert RiskTier.A > RiskTier.B

    def test_ordering_b_greater_than_c(self) -> None:
        assert RiskTier.B > RiskTier.C

    def test_ordering_a_greatest(self) -> None:
        assert max(RiskTier.C, RiskTier.A, RiskTier.B) == RiskTier.A

    def test_member_count(self) -> None:
        assert len(RiskTier) == 3

    def test_is_string(self) -> None:
        assert isinstance(RiskTier.A, str)


class TestBehaviorConfidence:
    """BehaviorConfidence enum: BC1 (highest confidence), BC2, BC3 (lowest confidence = highest risk)."""

    def test_values(self) -> None:
        assert BehaviorConfidence.BC1.value == "BC1"
        assert BehaviorConfidence.BC2.value == "BC2"
        assert BehaviorConfidence.BC3.value == "BC3"

    def test_ordering_bc3_greater_than_bc2(self) -> None:
        assert BehaviorConfidence.BC3 > BehaviorConfidence.BC2

    def test_ordering_bc2_greater_than_bc1(self) -> None:
        assert BehaviorConfidence.BC2 > BehaviorConfidence.BC1

    def test_ordering_bc3_is_max_risk(self) -> None:
        assert max(BehaviorConfidence.BC1, BehaviorConfidence.BC3, BehaviorConfidence.BC2) == BehaviorConfidence.BC3

    def test_member_count(self) -> None:
        assert len(BehaviorConfidence) == 3


class TestChangeClass:
    """ChangeClass enum: CLASS_1 through CLASS_5, CLASS_5 is highest risk."""

    def test_values(self) -> None:
        assert ChangeClass.CLASS_1.value == "Class 1"
        assert ChangeClass.CLASS_2.value == "Class 2"
        assert ChangeClass.CLASS_3.value == "Class 3"
        assert ChangeClass.CLASS_4.value == "Class 4"
        assert ChangeClass.CLASS_5.value == "Class 5"

    def test_ordering_class_5_greater_than_class_1(self) -> None:
        assert ChangeClass.CLASS_5 > ChangeClass.CLASS_1

    def test_ordering_class_5_is_max(self) -> None:
        assert max(ChangeClass.CLASS_1, ChangeClass.CLASS_3, ChangeClass.CLASS_5) == ChangeClass.CLASS_5

    def test_member_count(self) -> None:
        assert len(ChangeClass) == 5


class TestArtifactStatus:
    """ArtifactStatus enum for truth artifact lifecycle."""

    def test_values(self) -> None:
        assert ArtifactStatus.DRAFT.value == "draft"
        assert ArtifactStatus.APPROVED.value == "approved"
        assert ArtifactStatus.SUPERSEDED.value == "superseded"
        assert ArtifactStatus.DEFERRED.value == "deferred"
        assert ArtifactStatus.RETIRED.value == "retired"
        assert ArtifactStatus.DEPRECATED.value == "deprecated"

    def test_member_count(self) -> None:
        assert len(ArtifactStatus) == 6


class TestTrustStatus:
    """TrustStatus enum for harness profile trust levels."""

    def test_values(self) -> None:
        assert TrustStatus.CANDIDATE.value == "candidate"
        assert TrustStatus.TRUSTED.value == "trusted"
        assert TrustStatus.WATCH.value == "watch"
        assert TrustStatus.CONSTRAINED.value == "constrained"

    def test_member_count(self) -> None:
        assert len(TrustStatus) == 4


class TestEventType:
    """EventType enum must have all 15+ event types from PRD SS2.9."""

    def test_core_event_types(self) -> None:
        assert EventType.APPROVAL.value == "approval"
        assert EventType.MERGE.value == "merge"
        assert EventType.INVALIDATION.value == "invalidation"
        assert EventType.EXCEPTION.value == "exception"
        assert EventType.OVERRIDE.value == "override"
        assert EventType.DEPLOYMENT.value == "deployment"
        assert EventType.ROLLBACK.value == "rollback"

    def test_additional_event_types(self) -> None:
        assert EventType.HARNESS_CHANGE.value == "harness_change"
        assert EventType.TRUTH_CHANGE.value == "truth_change"
        assert EventType.CLASSIFICATION.value == "classification"
        assert EventType.ESCALATION.value == "escalation"
        assert EventType.KILL_SWITCH.value == "kill_switch"
        assert EventType.RECOVERY.value == "recovery"
        assert EventType.DELEGATION.value == "delegation"
        assert EventType.CALIBRATION.value == "calibration"
        assert EventType.STATE_TRANSITION.value == "state_transition"

    def test_minimum_member_count(self) -> None:
        assert len(EventType) >= 16


class TestActorType:
    """ActorType enum for governance event attribution."""

    def test_values(self) -> None:
        assert ActorType.HUMAN.value == "human"
        assert ActorType.AGENT.value == "agent"
        assert ActorType.CONTROL_PLANE.value == "control_plane"

    def test_member_count(self) -> None:
        assert len(ActorType) == 3


class TestGateType:
    """GateType enum for review gate assignment."""

    def test_values(self) -> None:
        assert GateType.AGENT.value == "agent"
        assert GateType.HYBRID.value == "hybrid"
        assert GateType.HUMAN.value == "human"

    def test_member_count(self) -> None:
        assert len(GateType) == 3


class TestWorkflowState:
    """WorkflowState enum for the main workflow state machine."""

    def test_core_states(self) -> None:
        assert WorkflowState.QUEUED.value == "queued"
        assert WorkflowState.IN_FLIGHT.value == "in_flight"
        assert WorkflowState.VERIFYING.value == "verifying"
        assert WorkflowState.UNDER_REVIEW.value == "under_review"
        assert WorkflowState.APPROVED.value == "approved"
        assert WorkflowState.MERGED.value == "merged"
        assert WorkflowState.DEPLOYED.value == "deployed"

    def test_error_states(self) -> None:
        assert WorkflowState.REJECTED.value == "rejected"
        assert WorkflowState.FAILED.value == "failed"
        assert WorkflowState.CANCELLED.value == "cancelled"

    def test_member_count(self) -> None:
        assert len(WorkflowState) == 10


class TestReviewSubState:
    """ReviewSubState enum for the review sub-workflow."""

    def test_values(self) -> None:
        assert ReviewSubState.PENDING_REVIEW.value == "pending_review"
        assert ReviewSubState.CHALLENGER_BRIEF.value == "challenger_brief"
        assert ReviewSubState.TRIAGE.value == "triage"
        assert ReviewSubState.DECISION.value == "decision"


class TestPRLItemType:
    """PRLItemType enum for PRL item classification."""

    def test_values(self) -> None:
        assert PRLItemType.FEATURE.value == "feature"
        assert PRLItemType.CONSTRAINT.value == "constraint"
        assert PRLItemType.QUALITY.value == "quality"
        assert PRLItemType.INTEGRATION.value == "integration"
        assert PRLItemType.MIGRATION.value == "migration"
        assert PRLItemType.OPERATIONAL.value == "operational"


class TestPriority:
    """Priority enum for prioritization."""

    def test_values(self) -> None:
        assert Priority.CRITICAL.value == "critical"
        assert Priority.HIGH.value == "high"
        assert Priority.MEDIUM.value == "medium"
        assert Priority.LOW.value == "low"


class TestStringEnumBehavior:
    """All enums should be str-based for JSON serialization."""

    @pytest.mark.parametrize(
        "enum_cls",
        [
            RiskTier,
            BehaviorConfidence,
            ChangeClass,
            ArtifactStatus,
            TrustStatus,
            EventType,
            ActorType,
            GateType,
            WorkflowState,
            ReviewSubState,
            PRLItemType,
            Priority,
            InterfaceType,
            VersioningRule,
            CompatibilityRule,
            ImpactScope,
            Sensitivity,
            DebtOriginType,
            DebtSeverity,
            Disposition,
            LegacyDisposition,
            ReconciliationFrequency,
            AssumptionCategory,
            VaultTrustLevel,
            VaultCategory,
            InvalidationSeverity,
            RollbackReadiness,
            NFRCategory,
            VerificationMethod,
            GateDecision,
            DebtStatus,
            MigrationStatus,
            ContractStatus,
        ],
    )
    def test_enum_is_string_based(self, enum_cls: type) -> None:
        """Every enum member should be an instance of str for JSON serialization."""
        for member in enum_cls:
            assert isinstance(member, str), f"{enum_cls.__name__}.{member.name} is not str-based"


class TestEnumCount:
    """Verify we have at least 25 enum classes total."""

    def test_minimum_enum_count(self) -> None:
        from ces.shared import enums

        enum_classes = [
            attr
            for attr in dir(enums)
            if isinstance(getattr(enums, attr), type)
            and issubclass(getattr(enums, attr), enums.Enum)
            and attr != "Enum"
        ]
        assert len(enum_classes) >= 25, f"Only found {len(enum_classes)} enum classes, need at least 25"
