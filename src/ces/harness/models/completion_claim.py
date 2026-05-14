"""Completion-Gate models — structured contract between agent and verifier.

The agent emits a :class:`CompletionClaim` before exit. The
:class:`CompletionVerifier` consumes the claim plus configured sensors and
emits a :class:`VerificationResult` with a tuple of structured
:class:`VerificationFinding` entries.

These models operationalise the "feedback-loop quality is the ceiling" pattern
(harness-engineering.md §Practitioner notes) by turning agent done-ness into
machine-checkable evidence rather than trust.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from ces.harness.models.sensor_result import SensorResult
from ces.shared.base import CESBaseModel


class EvidenceKind(str, Enum):
    """How the agent proves a criterion was satisfied."""

    COMMAND_OUTPUT = "command_output"
    FILE_ARTIFACT = "file_artifact"
    MANUAL_INSPECTION = "manual_inspection"


class VerificationFindingKind(str, Enum):
    """What kind of failure the verifier detected."""

    SCHEMA_VIOLATION = "schema_violation"
    CRITERION_UNADDRESSED = "criterion_unaddressed"
    SENSOR_FAILURE = "sensor_failure"
    EVIDENCE_MISMATCH = "evidence_mismatch"
    SCOPE_VIOLATION = "scope_violation"


class CriterionEvidence(CESBaseModel):
    """One row of the agent's claim: a criterion + the evidence for it."""

    criterion: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    evidence_kind: EvidenceKind


class DependencyChangeEvidence(CESBaseModel):
    """Justification and verification evidence for a dependency file change."""

    file_path: str = Field(min_length=1)
    package: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    existing_alternative_considered: str = Field(min_length=1)
    lockfile_evidence: str = Field(min_length=1)
    audit_evidence: str = Field(min_length=1)


class ComplexityNotes(CESBaseModel):
    """Explicit agent disclosure for complexity added during a task."""

    new_abstractions: tuple[str, ...] = ()
    new_dependencies: tuple[str, ...] = ()
    simpler_alternative_considered: str = ""
    why_not_simpler: str = "No extra complexity added."


class ExplorationEvidence(CESBaseModel):
    """One concrete repo/context item inspected before editing."""

    path: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    observation: str = Field(min_length=1)


class VerificationCommandEvidence(CESBaseModel):
    """One command or tool run used to verify completion."""

    command: str = Field(min_length=1)
    exit_code: int = Field(ge=0)
    summary: str = Field(min_length=1)
    artifact_path: str | None = None


class CompletionClaim(CESBaseModel):
    """The structured 'I'm done' payload an agent must emit before exit.

    Forces the agent to:
    - Disclose what files it touched (cross-checked against manifest scope).
    - Address each acceptance criterion with explicit evidence.
    - Surface unknowns rather than hide them (open_questions).
    - Disclose any scope deviations rather than silently expand scope.
    """

    task_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    files_changed: tuple[str, ...]
    criteria_satisfied: tuple[CriterionEvidence, ...] = ()
    open_questions: tuple[str, ...] = ()
    scope_deviations: tuple[str, ...] = ()
    dependency_changes: tuple[DependencyChangeEvidence, ...] = ()
    complexity_notes: ComplexityNotes = Field(default_factory=ComplexityNotes)
    exploration_evidence: tuple[ExplorationEvidence, ...] = ()
    verification_commands: tuple[VerificationCommandEvidence, ...] = ()


class VerificationFinding(CESBaseModel):
    """One failure surfaced by the CompletionVerifier.

    Fed back to the agent as part of the repair-prompt loop (P2).
    """

    kind: VerificationFindingKind
    severity: Literal["critical", "high", "medium", "low"]
    message: str = Field(min_length=1)
    hint: str = Field(min_length=1)
    related_criterion: str | None = None
    related_sensor: str | None = None


class VerificationResult(CESBaseModel):
    """Output of CompletionVerifier.verify().

    Invariant: passed is True iff findings is empty. A passed result with
    non-empty findings is a logic error and is rejected at construction.
    """

    passed: bool
    findings: tuple[VerificationFinding, ...]
    sensor_results: tuple[SensorResult, ...]
    timestamp: datetime

    @model_validator(mode="after")
    def _passed_implies_no_findings(self) -> VerificationResult:
        if self.passed and self.findings:
            msg = "passed=True is inconsistent with non-empty findings"
            raise ValueError(msg)
        return self
