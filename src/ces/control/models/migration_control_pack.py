"""Migration Control Pack model (PRD Part IV SS2.5).

The most complex truth artifact, capturing the full migration plan including
inventory, disposition decisions, coexistence plan, cutover, rollback matrix,
and exit criteria for brownfield-to-greenfield migrations.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from ces.shared.base import CESBaseModel, GovernedArtifactBase
from ces.shared.enums import (
    Disposition,
    ReconciliationFrequency,
)


class InventoryItem(CESBaseModel):
    """A system in the current state inventory."""

    system: str
    role: str
    data_stores: tuple[str, ...]
    interfaces: tuple[str, ...]
    behavioral_notes: str


class DispositionDecision(CESBaseModel):
    """A disposition decision for an inventory item."""

    model_config = {"strict": True, "frozen": True}

    item: str
    disposition: Disposition
    rationale: str
    deciding_authority: str
    decided_at: datetime


class SourceOfRecord(CESBaseModel):
    """Source of record mapping during migration."""

    data_domain: str
    current_source: str
    target_source: str
    transition_phase: str


class GoldenMasterTrace(CESBaseModel):
    """A golden master trace for behavior verification."""

    trace_id: str
    behavior: str
    expected_output_ref: str


class ReconciliationRule(CESBaseModel):
    """A rule for reconciling data between old and new systems."""

    rule_id: str
    description: str
    frequency: ReconciliationFrequency
    tolerance: str


class CoexistencePlan(CESBaseModel):
    """Plan for running old and new systems side by side."""

    duration: str
    boundary: str
    routing_rules: str
    data_sync_mechanism: str


class CutoverPlan(CESBaseModel):
    """Plan for cutting over from old to new system."""

    prerequisites: tuple[str, ...]
    sequence: tuple[str, ...]
    rollback_trigger: str
    point_of_no_return: str


class RollbackScenario(CESBaseModel):
    """A scenario in the rollback matrix."""

    scenario: str
    rollback_action: str
    data_recovery: str
    max_rollback_window: str


class ExitCriterion(CESBaseModel):
    """An exit criterion for completing the migration."""

    criterion: str
    measurement: str


class MigrationControlPack(GovernedArtifactBase):
    """Migration Control Pack truth artifact (PRD SS2.5).

    The most complex truth artifact. Captures the complete migration plan
    for brownfield-to-greenfield transitions.
    Status: draft | approved | active | completed (via ArtifactStatus/MigrationStatus).
    """

    schema_type: Literal["migration_control_pack"] = "migration_control_pack"
    pack_id: str
    domain: str
    current_state_inventory: tuple[InventoryItem, ...]
    disposition_decisions: tuple[DispositionDecision, ...]
    source_of_record: tuple[SourceOfRecord, ...]
    golden_master_traces: tuple[GoldenMasterTrace, ...]
    reconciliation_rules: tuple[ReconciliationRule, ...]
    coexistence_plan: CoexistencePlan
    cutover_plan: CutoverPlan
    rollback_matrix: tuple[RollbackScenario, ...]
    exit_criteria: tuple[ExitCriterion, ...]
