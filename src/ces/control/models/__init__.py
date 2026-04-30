"""CES Control Plane Models.

Re-exports all Pydantic v2 models for the 9 PRD Part IV SS2 schemas,
plus the discriminated union TruthArtifact type for polymorphic deserialization.
"""

from typing import Annotated, Union

from pydantic import Discriminator, Tag

# Truth artifact models (SS2.1-SS2.5)
from ces.control.models.architecture_blueprint import (
    ArchitectureBlueprint,
    Component,
    ComponentBoundaries,
    DataFlow,
    NFRequirement,
    ProhibitedPattern,
    StateOwnership,
    TrustBoundary,
)
from ces.control.models.audit_entry import AuditEntry, AuditScope, CostImpact
from ces.control.models.cascade_result import CascadeResult
from ces.control.models.debt_entry import DebtEntry

# Operational artifact models (SS2.6-SS2.9)
from ces.control.models.evidence_packet import (
    AdversarialHonesty,
    ChainOfCustodyEntry,
    DecisionView,
    EconomicImpact,
    EvidencePacket,
    HiddenTestOutcomes,
    RawEvidenceLinks,
    TestOutcomes,
)
from ces.control.models.gate_evidence_packet import (
    GateClassification,
    GateCriterion,
    GateEvidencePacket,
    IntakeAssumption,
)
from ces.control.models.gate_result import GateEvaluationResult
from ces.control.models.interface_contract import InterfaceContract

# Phase 02 models
from ces.control.models.kill_switch_state import ActivityClass, KillSwitchState

# Task manifest (Plan 03)
from ces.control.models.manifest import ManifestDependency, TaskManifest
from ces.control.models.merge_decision import MergeCheck, MergeDecision
from ces.control.models.migration_control_pack import (
    CoexistencePlan,
    CutoverPlan,
    DispositionDecision,
    ExitCriterion,
    GoldenMasterTrace,
    InventoryItem,
    MigrationControlPack,
    ReconciliationRule,
    RollbackScenario,
    SourceOfRecord,
)
from ces.control.models.oracle_result import OracleClassificationResult
from ces.control.models.prl_item import AcceptanceCriterion, PRLItem

# Spec authoring layer
from ces.control.models.spec import (
    Risk,
    SignalHints,
    SpecDocument,
    SpecFrontmatter,
    Story,
)
from ces.control.models.vision_anchor import (
    HardConstraint,
    KillCriterion,
    TargetUser,
    VisionAnchor,
)

# Discriminated union for truth artifacts (5 types).
# EvidencePacket, GateEvidencePacket, DebtEntry, AuditEntry are NOT truth
# artifacts -- they are operational artifacts. Only the 5 truth artifact
# types (+ manifest from Plan 03) go in this union.
TruthArtifact = Annotated[
    Annotated[VisionAnchor, Tag("vision_anchor")]
    | Annotated[PRLItem, Tag("prl_item")]
    | Annotated[ArchitectureBlueprint, Tag("architecture_blueprint")]
    | Annotated[InterfaceContract, Tag("interface_contract")]
    | Annotated[MigrationControlPack, Tag("migration_control_pack")],
    Discriminator("schema_type"),
]

__all__ = [
    # Truth artifacts
    "VisionAnchor",
    "TargetUser",
    "HardConstraint",
    "KillCriterion",
    "PRLItem",
    "AcceptanceCriterion",
    "ArchitectureBlueprint",
    "Component",
    "ComponentBoundaries",
    "DataFlow",
    "StateOwnership",
    "TrustBoundary",
    "NFRequirement",
    "ProhibitedPattern",
    "InterfaceContract",
    "MigrationControlPack",
    "InventoryItem",
    "DispositionDecision",
    "SourceOfRecord",
    "GoldenMasterTrace",
    "ReconciliationRule",
    "CoexistencePlan",
    "CutoverPlan",
    "RollbackScenario",
    "ExitCriterion",
    # Operational artifacts
    "EvidencePacket",
    "ChainOfCustodyEntry",
    "TestOutcomes",
    "HiddenTestOutcomes",
    "EconomicImpact",
    "DecisionView",
    "AdversarialHonesty",
    "RawEvidenceLinks",
    "GateEvidencePacket",
    "GateClassification",
    "GateCriterion",
    "IntakeAssumption",
    "DebtEntry",
    "AuditEntry",
    "AuditScope",
    "CostImpact",
    # Task manifest
    "TaskManifest",
    "ManifestDependency",
    # Phase 02 models
    "ActivityClass",
    "KillSwitchState",
    "OracleClassificationResult",
    "CascadeResult",
    "GateEvaluationResult",
    "MergeCheck",
    "MergeDecision",
    # Spec authoring layer
    "SignalHints",
    "SpecFrontmatter",
    "Risk",
    "Story",
    "SpecDocument",
    # Discriminated union
    "TruthArtifact",
]
