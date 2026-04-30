"""Append-only audit ledger service with HMAC-SHA256 hash chain integrity.

Enforces:
- Append-only: No update or delete operations (D-07)
- Hash chain: Every entry links to the previous via HMAC (D-16)
- All event types: Supports all 16 governance event types (AUDIT-02, AUDIT-03)
- Query: By event type, actor, time range (AUDIT-05)
- Verification: Chain integrity via HMAC recomputation

Threat mitigations:
- T-06-01: Only append() exists -- no update/delete at service layer
- T-06-02: HMAC-SHA256 with timing-safe comparison via verify_chain
- T-06-03: Every event recorded with actor, actor_type, timestamp, rationale
- T-06-04: Secret key passed at construction, never stored in entries
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from ces.control.models.audit_entry import AuditEntry, AuditScope, CostImpact
from ces.control.models.audit_entry_record import AuditEntryRecord
from ces.shared.crypto import compute_entry_hash
from ces.shared.enums import ActorType, EventType, InvalidationSeverity


class AuditLedgerService:
    """Append-only audit ledger with HMAC-SHA256 hash chain integrity.

    This service enforces:
    - Append-only: No update or delete operations (D-07)
    - Hash chain: Every entry links to the previous via HMAC (D-16)
    - All event types: Supports all 16 governance event types (AUDIT-02, AUDIT-03)
    """

    def __init__(
        self,
        secret_key: bytes,
        repository: object | None = None,
        project_id: str = "default",
    ) -> None:
        """Initialize with HMAC secret key for chain integrity.

        Args:
            secret_key: HMAC-SHA256 key for hash chain computation.
            repository: Repository adapter for persistence (e.g.
                ``LocalAuditRepository``). Duck-typed: any object exposing the
                expected ``append`` / ``get_last_entry`` / query methods works.
                Optional for unit testing.
        """
        self._secret_key = secret_key
        self._repository = repository
        self._project_id = project_id
        self._last_hash_by_project: dict[str, str] = {}

    def _resolve_project_id(self, project_id: str | None = None) -> str:
        return project_id or self._project_id

    async def _get_last_hash(self, project_id: str | None = None) -> str:
        """Get the hash of the most recent entry for chain continuation."""
        resolved_project_id = self._resolve_project_id(project_id)
        if self._repository is not None:
            last_entry = await self._repository.get_last_entry(project_id=resolved_project_id)
            if last_entry is not None and last_entry.entry_hash:
                return last_entry.entry_hash
            return "GENESIS"
        return self._last_hash_by_project.get(resolved_project_id, "GENESIS")

    async def append_event(
        self,
        event_type: EventType,
        actor: str,
        actor_type: ActorType,
        action_summary: str,
        decision: str = "",
        rationale: str = "",
        scope: AuditScope | None = None,
        evidence_refs: list[str] | None = None,
        # Optional metadata
        previous_state: str | None = None,
        new_state: str | None = None,
        invalidation_severity: InvalidationSeverity | None = None,
        model_version: str | None = None,
        cost_impact: CostImpact | None = None,
        # Multi-project support (v1.2 MULTI-04)
        project_id: str | None = None,
    ) -> AuditEntry:
        """Append a new event to the audit ledger.

        Computes HMAC hash chain linking this entry to the previous one.
        This is the ONLY write operation. No update or delete exists.

        Args:
            event_type: One of the 16 governance event types.
            actor: Identifier of the actor performing the action.
            actor_type: Whether actor is human, agent, or control_plane.
            action_summary: Human-readable description of what happened.
            decision: The decision made (e.g., "approve", "reject").
            rationale: Why the decision was made.
            scope: Affected artifacts, tasks, and manifests.
            evidence_refs: References to evidence packets.
            previous_state: For state transitions -- the prior workflow state.
            new_state: For state transitions -- the new workflow state.
            invalidation_severity: For invalidation events -- severity level.
            model_version: For LLM-involved events -- model identifier.
            cost_impact: Economic impact of the event.

        Returns:
            The appended AuditEntry with computed entry_hash.
        """
        entry_id = f"AE-{uuid.uuid4().hex[:12]}"
        timestamp = datetime.now(timezone.utc)
        resolved_project_id = self._resolve_project_id(project_id)
        prev_hash = await self._get_last_hash(project_id=resolved_project_id)

        entry = AuditEntry(
            entry_id=entry_id,
            timestamp=timestamp,
            event_type=event_type,
            actor=actor,
            actor_type=actor_type,
            scope=scope if scope is not None else AuditScope(),
            action_summary=action_summary,
            decision=decision,
            rationale=rationale,
            evidence_refs=tuple(evidence_refs) if evidence_refs is not None else (),
            previous_state=previous_state,
            new_state=new_state,
            invalidation_severity=invalidation_severity,
            model_version=model_version,
            cost_impact=cost_impact,
            project_id=resolved_project_id,
            prev_hash=prev_hash,
        )

        # Compute HMAC hash chain
        entry_data = entry.model_dump(mode="json", exclude={"entry_hash"})
        entry_hash = compute_entry_hash(entry_data, prev_hash, self._secret_key)

        # Set hash on frozen model via model_copy
        entry = entry.model_copy(update={"entry_hash": entry_hash})

        # Update in-memory chain head
        self._last_hash_by_project[resolved_project_id] = entry_hash

        # Persist if repository available
        if self._repository is not None:
            record = AuditEntryRecord(
                entry_id=entry.entry_id,
                timestamp=entry.timestamp,
                event_type=entry.event_type.value,
                actor=entry.actor,
                actor_type=entry.actor_type.value,
                scope=entry.scope.model_dump(mode="json"),
                action_summary=entry.action_summary,
                decision=entry.decision,
                rationale=entry.rationale,
                project_id=resolved_project_id,
                metadata_extra={
                    k: v
                    for k, v in {
                        "previous_state": entry.previous_state,
                        "new_state": entry.new_state,
                        "invalidation_severity": (
                            entry.invalidation_severity.value if entry.invalidation_severity else None
                        ),
                        "model_version": entry.model_version,
                        "cost_impact": (entry.cost_impact.model_dump(mode="json") if entry.cost_impact else None),
                        "evidence_refs": entry.evidence_refs,
                    }.items()
                    if v is not None
                },
                prev_hash=entry.prev_hash,
                entry_hash=entry.entry_hash,
            )
            await self._repository.append(record)

        return entry

    # -----------------------------------------------------------------
    # Convenience methods for common event types
    # -----------------------------------------------------------------

    async def record_state_transition(
        self,
        manifest_id: str,
        actor: str,
        actor_type: ActorType,
        from_state: str,
        to_state: str,
        rationale: str = "",
        project_id: str | None = None,
    ) -> AuditEntry:
        """Record a workflow state transition event.

        Args:
            manifest_id: The manifest undergoing state change.
            actor: Who initiated the transition.
            actor_type: Type of actor.
            from_state: Previous workflow state.
            to_state: New workflow state.
            rationale: Why the transition occurred.

        Returns:
            The appended AuditEntry.
        """
        return await self.append_event(
            event_type=EventType.STATE_TRANSITION,
            actor=actor,
            actor_type=actor_type,
            action_summary=f"Workflow transition: {from_state} -> {to_state}",
            decision=f"Transition to {to_state}",
            rationale=rationale,
            scope=AuditScope(affected_manifests=(manifest_id,)),
            previous_state=from_state,
            new_state=to_state,
            project_id=project_id,
        )

    async def record_approval(
        self,
        manifest_id: str,
        actor: str,
        decision: str,
        rationale: str,
        project_id: str | None = None,
    ) -> AuditEntry:
        """Record an approval decision event.

        Args:
            manifest_id: The manifest being approved/rejected.
            actor: The human reviewer.
            decision: The approval decision (e.g., "approve", "reject").
            rationale: Why the decision was made.

        Returns:
            The appended AuditEntry.
        """
        return await self.append_event(
            event_type=EventType.APPROVAL,
            actor=actor,
            actor_type=ActorType.HUMAN,
            action_summary=f"Approval decision for manifest {manifest_id}",
            decision=decision,
            rationale=rationale,
            scope=AuditScope(affected_manifests=(manifest_id,)),
            project_id=project_id,
        )

    async def record_invalidation(
        self,
        artifact_id: str,
        affected_manifests: list[str],
        severity: InvalidationSeverity,
        rationale: str,
        project_id: str | None = None,
    ) -> AuditEntry:
        """Record a truth artifact invalidation event.

        Args:
            artifact_id: The truth artifact that changed.
            affected_manifests: Manifests invalidated by the change.
            severity: How severe the invalidation is.
            rationale: Why invalidation occurred.

        Returns:
            The appended AuditEntry.
        """
        return await self.append_event(
            event_type=EventType.INVALIDATION,
            actor="control_plane",
            actor_type=ActorType.CONTROL_PLANE,
            action_summary=(
                f"Truth artifact {artifact_id} changed, invalidating {len(affected_manifests)} manifest(s)"
            ),
            decision="invalidate",
            rationale=rationale,
            scope=AuditScope(
                affected_artifacts=(artifact_id,),
                affected_manifests=tuple(affected_manifests),
            ),
            invalidation_severity=severity,
            project_id=project_id,
        )

    async def record_truth_change(
        self,
        artifact_id: str,
        actor: str,
        actor_type: ActorType,
        action_summary: str,
        project_id: str | None = None,
    ) -> AuditEntry:
        """Record a truth artifact change event.

        Args:
            artifact_id: The truth artifact that changed.
            actor: Who made the change.
            actor_type: Type of actor.
            action_summary: Description of the change.

        Returns:
            The appended AuditEntry.
        """
        return await self.append_event(
            event_type=EventType.TRUTH_CHANGE,
            actor=actor,
            actor_type=actor_type,
            action_summary=action_summary,
            scope=AuditScope(affected_artifacts=(artifact_id,)),
            project_id=project_id,
        )

    async def record_classification(
        self,
        manifest_id: str,
        actor: str,
        actor_type: ActorType,
        classification_summary: str,
        project_id: str | None = None,
    ) -> AuditEntry:
        """Record a classification event.

        Args:
            manifest_id: The manifest being classified.
            actor: Who performed the classification.
            actor_type: Type of actor.
            classification_summary: Description of the classification.

        Returns:
            The appended AuditEntry.
        """
        return await self.append_event(
            event_type=EventType.CLASSIFICATION,
            actor=actor,
            actor_type=actor_type,
            action_summary=classification_summary,
            scope=AuditScope(affected_manifests=(manifest_id,)),
            project_id=project_id,
        )

    # -----------------------------------------------------------------
    # Query methods (delegate to repository)
    # -----------------------------------------------------------------

    async def query_by_event_type(
        self,
        event_type: EventType,
        limit: int = 50,
        project_id: str | None = None,
    ) -> list[AuditEntry]:
        """Query audit entries by event type.

        Args:
            event_type: The event type to filter by.
            limit: Maximum number of results.

        Returns:
            List of matching AuditEntry instances.

        Raises:
            RuntimeError: If no repository is configured.
        """
        if self._repository is None:
            msg = "Repository not configured for queries"
            raise RuntimeError(msg)
        rows = await self._repository.get_by_event_type(event_type.value, project_id=project_id)
        return [self._row_to_entry(r) for r in rows[:limit]]

    async def query_by_actor(
        self,
        actor: str,
        limit: int = 50,
        project_id: str | None = None,
    ) -> list[AuditEntry]:
        """Query audit entries by actor.

        Args:
            actor: The actor identifier to filter by.
            limit: Maximum number of results.

        Returns:
            List of matching AuditEntry instances.

        Raises:
            RuntimeError: If no repository is configured.
        """
        if self._repository is None:
            msg = "Repository not configured for queries"
            raise RuntimeError(msg)
        rows = await self._repository.get_by_actor(actor, project_id=project_id)
        return [self._row_to_entry(r) for r in rows[:limit]]

    async def query_by_time_range(
        self,
        start: datetime,
        end: datetime,
        project_id: str | None = None,
    ) -> list[AuditEntry]:
        """Query audit entries within a time range.

        Args:
            start: Start of the time window (inclusive).
            end: End of the time window (inclusive).

        Returns:
            List of matching AuditEntry instances.

        Raises:
            RuntimeError: If no repository is configured.
        """
        if self._repository is None:
            msg = "Repository not configured for queries"
            raise RuntimeError(msg)
        rows = await self._repository.get_by_time_range(start, end, project_id=project_id)
        return [self._row_to_entry(r) for r in rows]

    # -----------------------------------------------------------------
    # Chain integrity verification
    # -----------------------------------------------------------------

    async def verify_integrity(
        self,
        entries: list[AuditEntry] | None = None,
        project_id: str | None = None,
    ) -> bool:
        """Verify the HMAC hash chain integrity.

        Walks the chain from GENESIS, recomputing each entry's expected
        hash and comparing. Returns False on first mismatch.

        Args:
            entries: Ordered list of entries to verify (oldest first).
                     If not provided, fetches from repository.
            project_id: Optional project scope for repository-backed verification.

        Returns:
            True if chain is valid, False if tampered or broken.
        """
        if entries is None and self._repository is not None:
            rows = await self._repository.get_latest(limit=10000, project_id=project_id)
            entries = [self._row_to_entry(r) for r in reversed(rows)]

        if not entries:
            return True

        prev_hash = "GENESIS"
        for entry in entries:
            entry_data = entry.model_dump(mode="json", exclude={"entry_hash"})
            expected_hash = compute_entry_hash(entry_data, prev_hash, self._secret_key)
            if entry.entry_hash != expected_hash:
                return False
            prev_hash = entry.entry_hash

        return True

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _row_to_entry(row: object) -> AuditEntry:
        """Convert a DB row to an AuditEntry model.

        Args:
            row: An AuditEntryRow instance from the database.

        Returns:
            AuditEntry domain model.
        """
        metadata = getattr(row, "metadata_extra", None) or {}
        return AuditEntry(
            entry_id=row.entry_id,  # type: ignore[attr-defined]
            timestamp=row.timestamp,  # type: ignore[attr-defined]
            event_type=EventType(row.event_type),  # type: ignore[attr-defined]
            actor=row.actor,  # type: ignore[attr-defined]
            actor_type=ActorType(row.actor_type),  # type: ignore[attr-defined]
            scope=AuditScope.model_validate(row.scope, strict=False),  # type: ignore[attr-defined]
            action_summary=row.action_summary,  # type: ignore[attr-defined]
            decision=row.decision,  # type: ignore[attr-defined]
            rationale=row.rationale,  # type: ignore[attr-defined]
            evidence_refs=tuple(metadata.get("evidence_refs", ())),
            previous_state=metadata.get("previous_state"),
            new_state=metadata.get("new_state"),
            invalidation_severity=(
                InvalidationSeverity(metadata["invalidation_severity"])
                if metadata.get("invalidation_severity")
                else None
            ),
            model_version=metadata.get("model_version"),
            cost_impact=(
                CostImpact.model_validate(metadata["cost_impact"], strict=False)
                if metadata.get("cost_impact")
                else None
            ),
            project_id=getattr(row, "project_id", None),
            prev_hash=row.prev_hash,  # type: ignore[attr-defined]
            entry_hash=row.entry_hash,  # type: ignore[attr-defined]
        )
