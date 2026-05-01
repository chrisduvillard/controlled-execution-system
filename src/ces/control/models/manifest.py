"""Task Manifest model - the core governance artifact.

The Task Manifest (MANIF-02) is the central governance artifact in CES.
Every agent task is bounded by a manifest that specifies what files can be
touched, what tools can be used, the token budget, risk classification,
and expiry time.

Implements:
- All PRD SS6.1 fields
- D-15 TTL by tier (48h/7d/14d for A/B/C)
- MANIF-07 independent classification rule
- D-12 max_retries field
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pydantic import ConfigDict, Field, model_validator

from ces.shared.base import CESBaseModel, GovernedArtifactBase
from ces.shared.enums import (
    BehaviorConfidence,
    ChangeClass,
    RiskTier,
    WorkflowState,
)


class ManifestDependency(CESBaseModel):
    """A reference to a truth artifact with its expected content hash.

    Used to track which truth artifacts a manifest depends on,
    enabling invalidation when upstream artifacts change.
    """

    artifact_id: str
    artifact_type: str
    content_hash: str
    source_repo_id: str | None = None


class TaskManifest(GovernedArtifactBase):
    """The core governance artifact bounding agent task execution.

    Every agent task is governed by a TaskManifest that specifies:
    - What files can be touched (affected_files, forbidden_files)
    - What tools can be used (allowed_tools, forbidden_tools)
    - Token budget for the task
    - Risk classification (tier, confidence, change class)
    - Expiry time (TTL varies by tier per D-15)
    - Dependencies on truth artifacts
    - Workflow state tracking
    - Retry limits (D-12)

    Validators enforce:
    - MANIF-07: classifier_id != implementer_id (independent classification)
    - MODEL-16: approved artifacts require signature (inherited)
    """

    model_config = ConfigDict(strict=True)

    # Core identification
    manifest_id: str
    description: str

    # Classification
    risk_tier: RiskTier
    behavior_confidence: BehaviorConfidence
    change_class: ChangeClass

    # File boundaries
    affected_files: tuple[str, ...]
    forbidden_files: tuple[str, ...] = ()

    # Tool boundaries
    allowed_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()

    # Resource limits
    token_budget: int = Field(gt=0)

    # Truth artifact dependencies
    dependencies: tuple[ManifestDependency, ...] = ()
    truth_artifact_hashes: dict[str, str] = {}  # artifact_id -> SHA-256 hash

    # Expiry
    expires_at: datetime

    # Workflow
    workflow_state: WorkflowState = WorkflowState.QUEUED

    # Classification actors
    classifier_id: str | None = None
    implementer_id: str | None = None

    # Retry limits (D-12)
    max_retries: int = Field(default=3, ge=0)
    retry_count: int = Field(default=0, ge=0)

    # Release slice
    release_slice: str | None = None

    # Spec provenance (optional; populated when manifest is derived from a
    # spec story via `ces spec`). See docs/plans/2026-04-21-ces-spec-authoring.md.
    parent_spec_id: str | None = None
    parent_story_id: str | None = None
    acceptance_criteria: tuple[str, ...] = ()

    # Completion Gate (P3): deterministic sensors that must pass before the
    # manifest can transition out of `verifying`. Empty tuple disables the gate.
    # Sensor IDs resolved by CompletionVerifier against its registered registry.
    verification_sensors: tuple[str, ...] = ()
    requires_exploration_evidence: bool = False
    requires_verification_commands: bool = False
    requires_impacted_flow_evidence: bool = False
    requires_docs_evidence_for_public_changes: bool = False
    accepted_runtime_side_effect_risk: bool = False

    # Reviewer-in-clean-context (P5): when True, review sub-agents must spawn
    # without inheriting the builder's transcript context so attention quality
    # is preserved (Pocock "smart-zone reviewer" pattern, harness-engineering.md).
    # Today this is naturally enforced by `claude -p` per-invocation isolation,
    # so the field is declarative; future wiring may use it to gate routing.
    review_in_clean_context: bool = True

    # MCP server allowlist (P7): per-task list of MCP servers that the runtime
    # adapter should expose to the agent. Empty tuple = adapter defaults.
    # Useful for grounding hallucinated APIs against live docs (Context7) or
    # for browser-driving tasks (Playwright) without polluting every task.
    mcp_servers: tuple[str, ...] = ()

    @property
    def is_expired(self) -> bool:
        """Check if the manifest has expired based on current UTC time."""
        return datetime.now(timezone.utc) > self.expires_at

    @classmethod
    def default_ttl(cls, tier: RiskTier) -> timedelta:
        """Return the default TTL for a given risk tier (D-15).

        - Tier A: 48 hours (highest risk, shortest TTL)
        - Tier B: 7 days
        - Tier C: 14 days (lowest risk, longest TTL)
        """
        ttl_map = {
            RiskTier.A: timedelta(hours=48),
            RiskTier.B: timedelta(days=7),
            RiskTier.C: timedelta(days=14),
        }
        return ttl_map[tier]

    @model_validator(mode="after")
    def independent_classification(self) -> TaskManifest:
        """Enforce MANIF-07: Implementer cannot be sole classifier.

        When both classifier_id and implementer_id are set,
        they must refer to different actors.
        """
        if (
            self.classifier_id is not None
            and self.implementer_id is not None
            and self.classifier_id == self.implementer_id
        ):
            msg = "Implementer cannot be sole classifier (MANIF-07)"
            raise ValueError(msg)
        return self
