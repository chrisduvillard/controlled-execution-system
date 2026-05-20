"""Pydantic models for the CES Semantic Review Layer."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import Field

from ces.shared.base import CESBaseModel

SCHEMA_VERSION = "1.0"
RiskLevel = Literal["low", "medium", "high", "critical"]
VerificationStatus = Literal["passed", "failed", "skipped", "not_run", "unknown", "stale"]
CoverageStatus = Literal[
    "implemented",
    "partially_implemented",
    "not_implemented",
    "intentionally_deferred",
    "not_applicable",
    "unknown",
]


class FileClassification(CESBaseModel):
    """Deterministic semantic classification for a changed path."""

    schema_version: str = SCHEMA_VERSION
    role: str = "unknown"
    conceptual_area: str = "unknown"
    language: str = "unknown"
    generated: bool = False
    lockfile: bool = False
    signals: tuple[str, ...] = ()


class ChangedFile(CESBaseModel):
    """A changed file entry in a semantic diff index."""

    schema_version: str = SCHEMA_VERSION
    path: str
    status: str = "modified"
    old_path: str | None = None
    additions: int = 0
    deletions: int = 0
    binary: bool = False
    extension: str = ""
    top_level_dir: str = ""
    file_size_bytes: int | None = None
    content_hash: str | None = None
    patch_hash: str | None = None
    patch_available: bool = True
    hunk_count: int = 0
    classification: FileClassification = Field(default_factory=FileClassification)
    content_excerpt: str = ""


class DiffStats(CESBaseModel):
    """Aggregate line and file counts for a diff."""

    schema_version: str = SCHEMA_VERSION
    files_changed: int
    insertions: int
    deletions: int


class DiffIndex(CESBaseModel):
    """Machine-readable diff index used by the semantic review layer."""

    schema_version: str = SCHEMA_VERSION
    base_ref: str
    head_ref: str
    diff_fingerprint: str
    stats: DiffStats
    merge_base: str | None = None
    base_sha: str | None = None
    head_sha: str | None = None
    changed_files: tuple[ChangedFile, ...] = ()
    warnings: tuple[str, ...] = ()


class RiskSignal(CESBaseModel):
    """One explainable signal contributing to a risk score."""

    schema_version: str = SCHEMA_VERSION
    kind: str
    category: str
    severity: RiskLevel
    score: int
    reason: str
    evidence_refs: tuple[str, ...] = ()


class RiskItem(CESBaseModel):
    """Risk score and reasons for one file or review target."""

    schema_version: str = SCHEMA_VERSION
    path: str
    role: str = "unknown"
    conceptual_area: str = "unknown"
    score: int = 0
    level: RiskLevel = "low"
    signals: tuple[RiskSignal, ...] = ()


class AreaRisk(CESBaseModel):
    """Aggregate risk for a conceptual area."""

    schema_version: str = SCHEMA_VERSION
    area: str
    score: int = 0
    level: RiskLevel = "low"
    files: tuple[str, ...] = ()


class RiskMap(CESBaseModel):
    """Full risk map and review priorities."""

    schema_version: str = SCHEMA_VERSION
    overall_score: int = 0
    overall_level: RiskLevel = "low"
    file_risks: tuple[RiskItem, ...] = ()
    area_risks: tuple[AreaRisk, ...] = ()
    review_first: tuple[RiskItem, ...] = ()
    checkpoints: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class IntentCoverageItem(CESBaseModel):
    """Requirement-to-evidence mapping."""

    schema_version: str = SCHEMA_VERSION
    requirement_id: str
    text: str
    source: str = "objective"
    status: CoverageStatus = "unknown"
    changed_files: tuple[str, ...] = ()
    verification_refs: tuple[str, ...] = ()
    evidence_quality: str = "missing"
    confidence: str = "low"
    notes: tuple[str, ...] = ()


class IntentCoverageMap(CESBaseModel):
    """Intent coverage artifact."""

    schema_version: str = SCHEMA_VERSION
    objective: str | None = None
    items: tuple[IntentCoverageItem, ...] = ()
    summary: dict[str, int] = Field(default_factory=dict)
    sources: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class ReviewPathStep(CESBaseModel):
    """One recommended step for human review."""

    schema_version: str = SCHEMA_VERSION
    order: int
    target: str
    kind: str = "file"
    reason: str
    risk_level: RiskLevel = "low"
    files: tuple[str, ...] = ()
    checkpoints: tuple[str, ...] = ()


class ReviewPath(CESBaseModel):
    """Risk-first human review path."""

    schema_version: str = SCHEMA_VERSION
    steps: tuple[ReviewPathStep, ...] = ()
    checkpoints: tuple[str, ...] = ()


class VerificationCommandResult(CESBaseModel):
    """Summary of one verification command."""

    schema_version: str = SCHEMA_VERSION
    command: str
    status: VerificationStatus = "unknown"
    duration_seconds: float | None = None
    summary: str = ""
    evidence_ref: str | None = None


class VerificationSummary(CESBaseModel):
    """Review-safe summary of available verification/proof evidence."""

    schema_version: str = SCHEMA_VERSION
    status: VerificationStatus = "unknown"
    fresh: bool | None = None
    proof_status: str | None = None
    approval_safety: str | None = None
    binding_status: str | None = None
    commands: tuple[VerificationCommandResult, ...] = ()
    missing_required_artifacts: tuple[str, ...] = ()
    unproven_areas: tuple[str, ...] = ()
    evidence_sources: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class AgentProvenance(CESBaseModel):
    """How the reviewed change was produced, when known."""

    schema_version: str = SCHEMA_VERSION
    mode: str = "local_diff_limited"
    build_id: str | None = None
    manifest_id: str | None = None
    runtime: str | None = None
    model: str | None = None
    agent: str | None = None
    assumptions: tuple[str, ...] = ()
    dissent: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()


class ReviewMetadata(CESBaseModel):
    """Durable metadata for a review artifact bundle."""

    schema_version: str = SCHEMA_VERSION
    review_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    repo_root: str
    base_ref: str
    head_ref: str
    diff_fingerprint: str
    verification_fingerprint: str | None = None
    ces_build_id: str | None = None
    build_id: str | None = None
    schema_versions: dict[str, str] = Field(default_factory=lambda: {"semantic_review": SCHEMA_VERSION})
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    generation_options: dict[str, object] = Field(default_factory=dict)
    include_untracked: bool = True
    stale: bool = False


class ReviewArtifactBundle(CESBaseModel):
    """In-memory representation of a generated semantic review bundle."""

    schema_version: str = SCHEMA_VERSION
    metadata: ReviewMetadata
    root_path: Path
    review_brief_path: Path
    diff_index: DiffIndex
    risk_map: RiskMap
    intent_coverage: IntentCoverageMap
    review_path: ReviewPath
    verification_summary: VerificationSummary
    agent_provenance: AgentProvenance
    artifact_paths: dict[str, Path] = Field(default_factory=dict)


class GithubReviewComment(CESBaseModel):
    """Rendered GitHub review comment payload."""

    schema_version: str = SCHEMA_VERSION
    review_id: str
    body: str
    dry_run: bool = True
    pr: int | None = None
    stale: bool = False
    update_marker: str


class ReviewGenerationOptions(CESBaseModel):
    """Options controlling review artifact generation."""

    schema_version: str = SCHEMA_VERSION
    objective: str | None = None
    from_build: str | None = None
    deferred_scope: tuple[str, ...] = ()
    include_untracked: bool = True
