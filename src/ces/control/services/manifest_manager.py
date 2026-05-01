"""Manifest Manager service orchestrating the full manifest lifecycle.

Integrates:
- Crypto (D-13, D-14): Ed25519 signing, SHA-256 hash integrity
- Classification (CLASS-01): Deterministic decision table lookup
- Invalidation (INVAL-01): Hash-based dependency tracking
- Audit (AUDIT-01): Every governance event logged
- Workflow (WORK-01): State machine lifecycle

LLM-05: NO LLM calls in any operation. Pure deterministic governance logic.

Exports:
    ManifestManager: Orchestrates task manifest CRUD, validation, signing,
                     classification, expiry, and invalidation.
"""

from __future__ import annotations

import uuid
from base64 import b64decode, b64encode
from datetime import datetime, timezone

# TYPE_CHECKING import to avoid circular dependency
from typing import TYPE_CHECKING

from ces.control.models.audit_entry import AuditScope
from ces.control.models.manifest import ManifestDependency, TaskManifest
from ces.control.services.classification import ClassificationEngine
from ces.control.services.invalidation import InvalidationTracker
from ces.observability.counters import get_counters
from ces.observability.metrics_bridge import get_ces_metrics
from ces.observability.otel import attach_governance_to_current_span
from ces.observability.services.collector import get_collector
from ces.shared.crypto import (
    canonical_json,
    sha256_hash,
    sign_content,
    verify_signature,
)
from ces.shared.enums import (
    ActorType,
    ArtifactStatus,
    BehaviorConfidence,
    ChangeClass,
    EventType,
    InvalidationSeverity,
    RiskTier,
    WorkflowState,
)

if TYPE_CHECKING:
    from ces.control.services.audit_ledger import AuditLedgerService


_DEFAULT_PROJECT_ID = "default"
_TERMINAL_WORKFLOW_STATES = {
    WorkflowState.MERGED,
    WorkflowState.DEPLOYED,
    WorkflowState.REJECTED,
    WorkflowState.FAILED,
    WorkflowState.CANCELLED,
}


def _emit_control_plane_telemetry(
    *,
    manifest_issuance_rate: float = 0.0,
    invalidation_rate: float = 0.0,
    merge_queue_depth: int = 0,
    approval_queue_depth: int = 0,
    approval_latency_seconds: float = 0.0,
    stale_context_timeout_rate: float = 0.0,
    project_id: str = _DEFAULT_PROJECT_ID,
) -> None:
    """Emit a governance telemetry sample into the collector buffer."""
    get_collector().emit(
        level="control_plane",
        data={
            "project_id": project_id,
            "manifest_issuance_rate": manifest_issuance_rate,
            "invalidation_rate": invalidation_rate,
            "merge_queue_depth": merge_queue_depth,
            "approval_queue_depth": approval_queue_depth,
            "approval_latency_seconds": approval_latency_seconds,
            "stale_context_timeout_rate": stale_context_timeout_rate,
        },
    )


class ManifestManager:
    """Orchestrates task manifest lifecycle: create, validate, sign, expire, invalidate.

    Integrates:
    - Crypto (D-13, D-14): Ed25519 signing, SHA-256 hash integrity
    - Classification (CLASS-01): Deterministic decision table
    - Invalidation (INVAL-01): Hash-based dependency tracking
    - Audit (AUDIT-01): Every governance event logged
    - Workflow (WORK-01): State machine lifecycle

    LLM-05: NO LLM calls in any operation.
    """

    def __init__(
        self,
        private_key: bytes | None = None,
        public_key: bytes | None = None,
        audit_ledger: AuditLedgerService | None = None,
        classification_engine: ClassificationEngine | None = None,
        repository: object = None,
    ) -> None:
        """Initialize ManifestManager with optional dependencies.

        Args:
            private_key: Ed25519 private key bytes for signing (32 bytes raw).
            public_key: Ed25519 public key bytes for verification (32 bytes raw).
            audit_ledger: AuditLedgerService for governance event logging.
            classification_engine: ClassificationEngine for deterministic table lookup.
            repository: Optional repository for DB persistence (future Plan scope).
        """
        self._private_key = private_key
        self._public_key = public_key
        self._audit = audit_ledger
        self._classifier = classification_engine or ClassificationEngine()
        self._repository = repository
        self._manifests: list[TaskManifest] = []

    async def _persist_manifest(self, manifest: TaskManifest) -> None:
        """Persist a manifest through the configured repository, if any.

        The local-first product injects ``LocalManifestRepository`` which
        accepts the domain ``TaskManifest`` directly. Tests may inject a
        no-repo or alternative implementation.
        """
        if self._repository is None:
            return
        await self._repository.save(manifest)  # type: ignore[attr-defined]

    @staticmethod
    def _is_active_manifest(manifest: TaskManifest) -> bool:
        """Return True when the manifest is still in a non-terminal workflow state."""
        return manifest.workflow_state not in _TERMINAL_WORKFLOW_STATES and not manifest.is_expired

    async def create_manifest(
        self,
        description: str,
        risk_tier: RiskTier,
        behavior_confidence: BehaviorConfidence,
        change_class: ChangeClass,
        affected_files: list[str],
        token_budget: int,
        owner: str,
        truth_artifacts: dict[str, dict] | None = None,
        forbidden_files: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        forbidden_tools: list[str] | None = None,
        implementer_id: str | None = None,
        max_retries: int = 3,
        acceptance_criteria: list[str] | None = None,
        verification_sensors: list[str] | None = None,
        requires_exploration_evidence: bool = False,
        requires_verification_commands: bool = False,
        requires_impacted_flow_evidence: bool = False,
        requires_docs_evidence_for_public_changes: bool = False,
        accepted_runtime_side_effect_risk: bool = False,
    ) -> TaskManifest:
        """Create a new task manifest.

        MANIF-01: Create from description
        MANIF-02: Includes all required fields
        MANIF-03: Computes truth artifact hashes via SHA-256 (D-14)
        MANIF-04: Sets TTL expiry by tier (D-15)

        Args:
            description: Human-readable task description.
            risk_tier: Risk classification tier (A/B/C).
            behavior_confidence: Behavior confidence level (BC1/BC2/BC3).
            change_class: Change class (Class 1-5).
            affected_files: List of file paths the task may modify.
            token_budget: Maximum token budget for the task.
            owner: Identifier of the manifest creator.
            truth_artifacts: Mapping of artifact_id -> content dict for dependency tracking.
            forbidden_files: Files the task must not modify.
            allowed_tools: Allowed tool names (empty = no restriction).
            forbidden_tools: Forbidden tool names.
            implementer_id: Identifier of the agent implementing the task.
            max_retries: Maximum retry attempts (D-12).

        Returns:
            A new TaskManifest in DRAFT status with QUEUED workflow state.
        """
        manifest_id = f"M-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        # Compute truth artifact hashes (D-14)
        truth_artifact_hashes: dict[str, str] = {}
        dependencies: list[ManifestDependency] = []
        if truth_artifacts:
            for artifact_id, content in truth_artifacts.items():
                content_hash = sha256_hash(content)
                truth_artifact_hashes[artifact_id] = content_hash
                dependencies.append(
                    ManifestDependency(
                        artifact_id=artifact_id,
                        artifact_type=content.get("schema_type", "unknown"),
                        content_hash=content_hash,
                    )
                )

        # Set TTL by tier (D-15)
        ttl = TaskManifest.default_ttl(risk_tier)
        expires_at = now + ttl

        manifest = TaskManifest(
            manifest_id=manifest_id,
            description=description,
            risk_tier=risk_tier,
            behavior_confidence=behavior_confidence,
            change_class=change_class,
            affected_files=tuple(affected_files),
            forbidden_files=tuple(forbidden_files) if forbidden_files else (),
            allowed_tools=tuple(allowed_tools) if allowed_tools else (),
            forbidden_tools=tuple(forbidden_tools) if forbidden_tools else (),
            token_budget=token_budget,
            dependencies=tuple(dependencies),
            truth_artifact_hashes=truth_artifact_hashes,
            expires_at=expires_at,
            workflow_state=WorkflowState.QUEUED,
            implementer_id=implementer_id,
            max_retries=max_retries,
            acceptance_criteria=tuple(acceptance_criteria) if acceptance_criteria else (),
            verification_sensors=tuple(verification_sensors) if verification_sensors else (),
            requires_exploration_evidence=requires_exploration_evidence,
            requires_verification_commands=requires_verification_commands,
            requires_impacted_flow_evidence=requires_impacted_flow_evidence,
            requires_docs_evidence_for_public_changes=requires_docs_evidence_for_public_changes,
            accepted_runtime_side_effect_risk=accepted_runtime_side_effect_risk,
            # GovernedArtifactBase fields
            version=1,
            status=ArtifactStatus.DRAFT,
            owner=owner,
            created_at=now,
            last_confirmed=now,
        )

        # Log creation to audit ledger (AUDIT-01)
        if self._audit:
            await self._audit.append_event(
                event_type=EventType.TRUTH_CHANGE,
                actor=owner,
                actor_type=ActorType.HUMAN,
                action_summary=f"Created manifest {manifest_id}: {description}",
                scope=AuditScope(affected_manifests=(manifest_id,)),
            )

        # Track in-memory for session-scoped lookups
        self._manifests.append(manifest)
        await self._persist_manifest(manifest)

        attach_governance_to_current_span(
            manifest_id=manifest.manifest_id,
            risk_tier=manifest.risk_tier.value,
            change_class=manifest.change_class.value,
            project_id=_DEFAULT_PROJECT_ID,
        )
        get_counters().increment("manifest_issued")
        get_counters().increment("manifest_issuance_rate")
        get_ces_metrics().manifest_issued.add(1)
        _emit_control_plane_telemetry(
            manifest_issuance_rate=1.0,
            approval_queue_depth=1,
        )

        return manifest

    async def save_manifest(self, manifest: TaskManifest) -> TaskManifest:
        """Persist an updated manifest to the configured repository."""
        self._manifests = [
            manifest if existing.manifest_id == manifest.manifest_id else existing for existing in self._manifests
        ] or [manifest]
        if not any(existing.manifest_id == manifest.manifest_id for existing in self._manifests):
            self._manifests.append(manifest)
        await self._persist_manifest(manifest)
        return manifest

    async def get_manifest(self, manifest_id: str) -> TaskManifest | None:
        """Retrieve a manifest by ID.

        Used by classify_cmd, review_cmd, triage_cmd, approve_cmd to look up
        manifests before operating on them.

        Checks in-memory manifests first (created during this session),
        then falls through to repository if available.

        Args:
            manifest_id: The manifest ID to look up (e.g., "M-abc123def456").

        Returns:
            TaskManifest if found, None otherwise.
        """
        # Check in-memory manifests first (created during this session)
        for m in self._manifests:
            if m.manifest_id == manifest_id:
                return m
        # Fall through to repository if available
        if self._repository is not None:
            row = await self._repository.get_by_id(manifest_id)  # type: ignore[attr-defined]
            if row is not None:
                return self._row_to_manifest(row)
        return None

    async def list_all(self) -> list[TaskManifest]:
        """Return all manifests known to this manager (in-memory + repository).

        Used by SpecTree and other read-only views that need to inspect every
        manifest regardless of workflow state.

        Returns:
            Combined list of TaskManifest objects; in-memory entries take
            priority over repository rows (no duplicates by manifest_id).
        """
        seen: set[str] = {m.manifest_id for m in self._manifests}
        combined: list[TaskManifest] = list(self._manifests)
        if self._repository is not None and hasattr(self._repository, "get_all"):
            rows = await self._repository.get_all()  # type: ignore[attr-defined]
            for row in rows:
                manifest = self._row_to_manifest(row)
                if manifest.manifest_id not in seen:
                    combined.append(manifest)
                    seen.add(manifest.manifest_id)
        return combined

    async def get_active_manifests(self) -> list[TaskManifest]:
        """Retrieve all manifests with non-terminal workflow states.

        Used by ``ces status --expert`` to show active governed work.

        Returns:
            List of TaskManifest objects with non-terminal states
            (queued, in_flight, under_review).
        """
        active: list[TaskManifest] = [m for m in self._manifests if self._is_active_manifest(m)]
        if self._repository is not None:
            rows = await self._repository.get_active()  # type: ignore[attr-defined]
            for row in rows:
                manifest = self._row_to_manifest(row)
                # Avoid duplicates with in-memory manifests
                if self._is_active_manifest(manifest) and not any(
                    m.manifest_id == manifest.manifest_id for m in active
                ):
                    active.append(manifest)
        return active

    async def list_by_spec(self, parent_spec_id: str) -> list[TaskManifest]:
        """Return all manifests whose ``parent_spec_id`` matches.

        Used by ``ces spec tree`` / ``ces spec reconcile`` / ``ces spec decompose``
        to project a spec's decomposed work back into a manifest list.

        **Intentionally includes terminal manifests** (merged, deployed,
        rejected, expired, failed, cancelled). Both ``SpecTree`` and
        ``SpecReconciler`` need full history: a merged manifest must still
        render in the tree as "merged" and count as "unchanged" during
        reconciliation. Filtering to active-only would make ``ces spec
        reconcile`` misclassify every shipped story as "added" on each run,
        producing false positives that force gratuitous re-decomposition.

        Mirrors the hybrid lookup pattern used by ``get_active_manifests``:
        filters in-memory manifests first, then falls through to the repository
        and deduplicates. Filtering happens in Python rather than SQL because
        the spec-provenance columns live in the JSONB ``content`` blob rather
        than as dedicated indexed columns on ``ManifestRow``. The in-memory
        ``_manifests`` list retains manifests after terminal transitions, so
        its branch already works; the repository branch previously called
        ``get_active()`` and was the sole source of the bug.

        Args:
            parent_spec_id: Spec ID (e.g. ``"SP-01HX"``).

        Returns:
            List of matching TaskManifest domain models, regardless of
            workflow state. Empty if none match.
        """
        matches: list[TaskManifest] = [m for m in self._manifests if m.parent_spec_id == parent_spec_id]
        if self._repository is not None:
            # Load the full superset (including terminal states) and filter
            # in Python. See docstring for why terminal manifests matter here.
            rows = await self._repository.get_all()  # type: ignore[attr-defined]
            for row in rows:
                manifest = self._row_to_manifest(row)
                if manifest.parent_spec_id != parent_spec_id:
                    continue
                if any(m.manifest_id == manifest.manifest_id for m in matches):
                    continue
                matches.append(manifest)
        return matches

    @staticmethod
    def _row_to_manifest(row: object) -> TaskManifest:
        """Convert a ManifestRow ORM object to a TaskManifest domain model.

        Reads from the row's JSONB ``content`` column which stores the full
        manifest data, falling back to direct column attributes.

        Args:
            row: A ManifestRow instance from the database.

        Returns:
            TaskManifest domain model.
        """
        content = dict(getattr(row, "content", None) or {})
        created_at = content.get("created_at", getattr(row, "created_at", datetime.now(timezone.utc)))
        data = {
            "manifest_id": content.get("manifest_id", getattr(row, "manifest_id", "")),
            "description": content.get("description", getattr(row, "description", "")),
            "risk_tier": content.get("risk_tier", getattr(row, "risk_tier", RiskTier.C.value)),
            "behavior_confidence": content.get(
                "behavior_confidence",
                getattr(row, "behavior_confidence", BehaviorConfidence.BC1.value),
            ),
            "change_class": content.get("change_class", getattr(row, "change_class", ChangeClass.CLASS_1.value)),
            "affected_files": content.get("affected_files", ()),
            "forbidden_files": content.get("forbidden_files", ()),
            "allowed_tools": content.get("allowed_tools", ()),
            "forbidden_tools": content.get("forbidden_tools", ()),
            "token_budget": content.get("token_budget", 10000),
            "dependencies": content.get("dependencies", ()),
            "truth_artifact_hashes": content.get("truth_artifact_hashes", {}),
            "expires_at": content.get("expires_at", getattr(row, "expires_at", datetime.now(timezone.utc))),
            "workflow_state": content.get("workflow_state", getattr(row, "workflow_state", "queued")),
            "classifier_id": content.get("classifier_id", getattr(row, "classifier_id", None)),
            "implementer_id": content.get("implementer_id", getattr(row, "implementer_id", None)),
            "max_retries": content.get("max_retries", 3),
            "retry_count": content.get("retry_count", 0),
            "release_slice": content.get("release_slice"),
            "version": content.get("version", 1),
            "status": content.get("status", getattr(row, "status", ArtifactStatus.DRAFT.value)),
            "owner": content.get("owner", "unknown"),
            "created_at": created_at,
            "last_confirmed": content.get("last_confirmed", created_at),
            "signature": content.get("signature", getattr(row, "signature", None)),
            "content_hash": content.get("content_hash", getattr(row, "content_hash", None)),
            # Spec provenance: only populated when the manifest was derived
            # from a spec story. Must be rehydrated from the JSONB ``content``
            # blob so ``list_by_spec`` can match on ``parent_spec_id`` and
            # SpecTree / SpecReconciler see the full history.
            "parent_spec_id": content.get("parent_spec_id"),
            "parent_story_id": content.get("parent_story_id"),
            "acceptance_criteria": content.get("acceptance_criteria", ()),
        }
        return TaskManifest.model_validate(data, strict=False)

    async def validate_manifest(
        self,
        manifest: TaskManifest,
        current_artifacts: dict[str, dict],
    ) -> tuple[bool, list[str]]:
        """Validate manifest against truth artifacts (MANIF-03).

        Checks:
        1. Not expired
        2. Truth artifact hashes match current state (D-14)
        3. Referenced artifacts are APPROVED (MODEL-16)

        Args:
            manifest: The manifest to validate.
            current_artifacts: Mapping of artifact_id -> current content dict.

        Returns:
            Tuple of (is_valid, list of issue descriptions).
        """
        issues: list[str] = []

        # Check expiry
        if manifest.is_expired:
            issues.append(f"Manifest {manifest.manifest_id} has expired (expires_at={manifest.expires_at})")

        # Check truth artifact hashes (D-14)
        result = InvalidationTracker.check_manifest_validity(
            manifest.manifest_id,
            manifest.truth_artifact_hashes,
            current_artifacts,
        )
        if not result.is_valid:
            for artifact_id in result.mismatched_artifacts:
                expected, actual = result.details.get(artifact_id, ("?", "?"))
                issues.append(
                    f"Truth artifact {artifact_id} hash mismatch: expected={expected[:8]}..., actual={actual[:8]}..."
                )

        # Check referenced artifacts are APPROVED (MODEL-16)
        for artifact_id, content in current_artifacts.items():
            if artifact_id in manifest.truth_artifact_hashes:
                status = content.get("status", "")
                if status == "draft":
                    issues.append(
                        f"Truth artifact {artifact_id} is DRAFT -- "
                        f"control plane rejects draft for governance (MODEL-16)"
                    )

        return (len(issues) == 0, issues)

    async def sign_manifest(
        self,
        manifest: TaskManifest,
    ) -> TaskManifest:
        """Sign a manifest with Ed25519 (MANIF-04, D-13).

        Computes content_hash and Ed25519 signature. Changes status to APPROVED.

        Args:
            manifest: The manifest to sign.

        Returns:
            A new TaskManifest with signature, content_hash, and APPROVED status.

        Raises:
            ValueError: If no private key is configured.
        """
        if not self._private_key:
            msg = "Private key required for signing"
            raise ValueError(msg)

        # Compute content hash
        manifest_data = manifest.model_dump(mode="json", exclude={"signature", "content_hash", "status"})
        content_hash = sha256_hash(manifest_data)

        # Sign the canonical JSON representation
        content_bytes = canonical_json(manifest_data).encode("utf-8")
        signature_bytes = sign_content(content_bytes, self._private_key)
        signature_b64 = b64encode(signature_bytes).decode("ascii")

        # Create signed manifest (frozen model, use model_copy)
        signed = manifest.model_copy(
            update={
                "content_hash": content_hash,
                "signature": signature_b64,
                "status": ArtifactStatus.APPROVED,
            }
        )
        approval_latency_seconds = max(
            (datetime.now(timezone.utc) - manifest.created_at).total_seconds(),
            0.0,
        )

        # Log signing event (AUDIT-01)
        if self._audit:
            await self._audit.append_event(
                event_type=EventType.APPROVAL,
                actor="manifest_manager",
                actor_type=ActorType.CONTROL_PLANE,
                action_summary=f"Signed manifest {manifest.manifest_id}",
                scope=AuditScope(affected_manifests=(manifest.manifest_id,)),
            )

        attach_governance_to_current_span(
            manifest_id=signed.manifest_id,
            risk_tier=signed.risk_tier.value,
            change_class=signed.change_class.value,
            review_outcome="approved",
            project_id=_DEFAULT_PROJECT_ID,
        )
        get_ces_metrics().approval_latency.record(approval_latency_seconds)
        _emit_control_plane_telemetry(
            approval_latency_seconds=approval_latency_seconds,
        )

        return signed

    async def verify_manifest(self, manifest: TaskManifest) -> bool:
        """Verify manifest signature (D-13).

        Recomputes the canonical JSON from manifest fields (excluding
        signature, content_hash, status) and verifies the Ed25519 signature.

        Args:
            manifest: The signed manifest to verify.

        Returns:
            True if signature is valid against the configured public key.
        """
        if not self._public_key or not manifest.signature:
            return False

        manifest_data = manifest.model_dump(mode="json", exclude={"signature", "content_hash", "status"})
        content_bytes = canonical_json(manifest_data).encode("utf-8")
        signature_bytes = b64decode(manifest.signature)

        return verify_signature(content_bytes, signature_bytes, self._public_key)

    async def check_expiry(self, manifest: TaskManifest) -> bool:
        """Check if a manifest has expired.

        Args:
            manifest: The manifest to check.

        Returns:
            True if the manifest has expired, False otherwise.
        """
        return manifest.is_expired

    async def classify_manifest(
        self,
        manifest: TaskManifest,
        classifier_id: str,
    ) -> TaskManifest:
        """Classify a manifest using the deterministic decision table (CLASS-01).

        MANIF-07: classifier_id must differ from implementer_id.
        LLM-05: NO LLM calls -- pure table lookup.

        Args:
            manifest: The manifest to classify.
            classifier_id: Identifier of the classifier.

        Returns:
            A new TaskManifest with updated classification fields.

        Raises:
            ValueError: If classifier_id equals implementer_id (MANIF-07 violation).
        """
        # Enforce MANIF-07: independent classification rule
        if manifest.implementer_id and classifier_id == manifest.implementer_id:
            msg = (
                f"Independent classification rule violated (MANIF-07): "
                f"classifier '{classifier_id}' cannot be the "
                f"implementer '{manifest.implementer_id}'"
            )
            raise ValueError(msg)

        rule = self._classifier.classify_by_description(manifest.description)
        if rule:
            manifest = manifest.model_copy(
                update={
                    "risk_tier": rule.risk_tier,
                    "behavior_confidence": rule.behavior_confidence,
                    "change_class": rule.change_class,
                    "classifier_id": classifier_id,
                }
            )
        else:
            # No match -- preserve original classification, just set classifier
            manifest = manifest.model_copy(update={"classifier_id": classifier_id})

        # Log classification (AUDIT-01)
        if self._audit:
            await self._audit.record_classification(
                manifest_id=manifest.manifest_id,
                actor=classifier_id,
                actor_type=ActorType.CONTROL_PLANE,
                classification_summary=(
                    f"Classified as {manifest.risk_tier.value}/"
                    f"{manifest.behavior_confidence.value}/"
                    f"{manifest.change_class.value}"
                ),
            )

        return manifest

    async def on_truth_artifact_changed(
        self,
        artifact_id: str,
        manifests: dict[str, dict[str, str]],
    ) -> list[str]:
        """Handle truth artifact change: invalidate affected manifests (MANIF-05).

        Finds all manifests that reference the changed artifact and records
        the invalidation event in the audit ledger.

        Args:
            artifact_id: ID of the truth artifact that changed.
            manifests: Mapping of manifest_id -> {artifact_id: hash}.

        Returns:
            List of invalidated manifest IDs.
        """
        affected = InvalidationTracker.find_affected_manifests(artifact_id, manifests)

        if affected and self._audit:
            await self._audit.record_invalidation(
                artifact_id=artifact_id,
                affected_manifests=affected,
                severity=InvalidationSeverity.HIGH,
                rationale=(f"Truth artifact {artifact_id} changed, invalidating {len(affected)} manifest(s)"),
            )
            get_counters().increment("invalidation_rate")
            get_ces_metrics().manifest_invalidated.add(len(affected))
            _emit_control_plane_telemetry(
                invalidation_rate=float(len(affected)),
            )

        return affected
