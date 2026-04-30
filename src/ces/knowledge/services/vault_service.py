"""Knowledge vault service layer (VAULT-01 through VAULT-06).

Provides note storage, querying, trust management, and invalidation
integration for the Zettelkasten-based knowledge vault.

The knowledge vault is informational only -- it must NEVER answer
requirement, policy, or risk-acceptance questions. This is enforced
by the filter_informational_only function applied to every query result.

Threat mitigations:
- T-05-10: filter_informational_only applied at query() level
- T-05-11: Trust level changes logged to audit ledger
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Callable

from sqlalchemy import text

from ces.control.models.knowledge_vault import VaultNote
from ces.shared.enums import ActorType, VaultCategory, VaultTrustLevel


class KnowledgeVaultService:
    """Service for managing knowledge vault notes.

    Implements VaultQueryProtocol and InvalidationTriggerProtocol.
    Stores notes with trust levels across 9 categories, integrates
    with the invalidation engine, and refreshes materialized view indexes.
    """

    def __init__(
        self,
        repository: object | None = None,
        audit_ledger: object | None = None,
        query_filter: Callable[[list[VaultNote]], list[VaultNote]] | None = None,
    ) -> None:
        """Initialize the vault service.

        Args:
            repository: VaultRepository for DB persistence.
            audit_ledger: Audit ledger for logging governance events.
            query_filter: Filter function applied to every query result.
                Defaults to filter_informational_only from vault_query_filter.
        """
        self._repository = repository
        self._audit_ledger = audit_ledger
        if query_filter is not None:
            self._query_filter = query_filter
        else:
            from ces.knowledge.services.vault_query_filter import (
                filter_informational_only,
            )

            self._query_filter = filter_informational_only

    # -----------------------------------------------------------------
    # Write operations
    # -----------------------------------------------------------------

    async def write_note(
        self,
        category: VaultCategory,
        content: str,
        source: str,
        trust_level: VaultTrustLevel = VaultTrustLevel.AGENT_INFERRED,
        tags: list[str] | None = None,
        related_artifacts: list[str] | None = None,
        invalidation_trigger: str | None = None,
    ) -> VaultNote:
        """Create and persist a new vault note.

        Generates a unique note_id, defaults trust_level to AGENT_INFERRED,
        persists via repository, and logs to audit ledger.

        Args:
            category: One of 9 vault categories.
            content: The note content.
            source: Where this note came from.
            trust_level: Trust level (default: AGENT_INFERRED).
            tags: Optional list of tags for search.
            related_artifacts: Optional list of related artifact IDs.
            invalidation_trigger: Optional trigger for invalidation.

        Returns:
            The created VaultNote domain model.
        """
        note_id = f"VN-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        note = VaultNote(
            note_id=note_id,
            category=category,
            trust_level=trust_level,
            content=content,
            source=source,
            created_at=now,
            updated_at=now,
            tags=tuple(tags) if tags else (),
            related_artifacts=tuple(related_artifacts) if related_artifacts else (),
            invalidation_trigger=invalidation_trigger,
        )

        if self._repository is not None:
            row = SimpleNamespace(
                note_id=note.note_id,
                category=note.category.value,
                trust_level=note.trust_level.value,
                content=note.content,
                source=note.source,
                tags=note.tags,
                related_artifacts=note.related_artifacts,
                invalidation_trigger=note.invalidation_trigger,
            )
            await self._repository.save(row)  # type: ignore[attr-defined]

        if self._audit_ledger is not None:
            await self._audit_ledger.record_truth_change(
                artifact_id=note_id,
                actor="knowledge_vault",
                actor_type=ActorType.CONTROL_PLANE,
                action_summary=f"Vault note created: {note_id} in {category.value}",
            )

        return note

    # -----------------------------------------------------------------
    # Query operations
    # -----------------------------------------------------------------

    async def query(
        self,
        category: VaultCategory | None = None,
        tags: list[str] | None = None,
        trust_level: VaultTrustLevel | None = None,
        limit: int = 10,
    ) -> list[VaultNote]:
        """Query the knowledge vault with filters.

        Applies the informational-only filter (VAULT-06) to all results
        before returning to the caller.

        Args:
            category: Filter by vault category.
            tags: Filter by tags.
            trust_level: Filter by trust level.
            limit: Maximum number of results.

        Returns:
            List of VaultNote domain models, filtered by VAULT-06.
        """
        if self._repository is None:
            return []

        rows: list[object] = []

        if category is not None:
            rows = await self._repository.get_by_category(category.value)
        elif tags is not None:
            rows = await self._repository.search_by_tags(tags)
        elif trust_level is not None:
            rows = await self._repository.get_by_trust_level(trust_level.value)
        else:
            # No filter specified, return empty
            return []

        notes = [self._row_to_note(row) for row in rows]

        # VAULT-06: Apply informational-only filter to every query result
        notes = self._query_filter(notes)

        return notes[:limit]

    async def find_verified_answer(
        self,
        *,
        category: str,
        question_text: str,
    ) -> VaultNote | None:
        """Find a verified answer matching the question.

        Queries for VERIFIED notes in the given category, then scores
        by word overlap with the question text. Returns the best match
        if overlap score exceeds 0.3 threshold.

        Args:
            category: Vault category to search.
            question_text: The question to match against.

        Returns:
            Best matching VaultNote, or None if no good match.
        """
        if self._repository is None:
            return None

        rows = await self._repository.get_by_category(category)
        notes = [self._row_to_note(row) for row in rows]

        # Only consider VERIFIED notes
        verified = [n for n in notes if n.trust_level == VaultTrustLevel.VERIFIED]
        if not verified:
            return None

        question_words = set(question_text.lower().split())
        best_note: VaultNote | None = None
        best_score = 0.0

        for note in verified:
            content_words = set(note.content.lower().split())
            if not question_words:
                continue
            overlap = len(question_words & content_words) / len(question_words)
            if overlap > best_score:
                best_score = overlap
                best_note = note

        if best_score > 0.3:
            return best_note
        return None

    # -----------------------------------------------------------------
    # Trust management
    # -----------------------------------------------------------------

    async def update_trust_level(
        self,
        note_id: str,
        new_level: VaultTrustLevel,
    ) -> VaultNote | None:
        """Update the trust level of a vault note.

        Persists the change via repository and logs to audit ledger.

        Args:
            note_id: The note to update.
            new_level: The new trust level.

        Returns:
            Updated VaultNote, or None if not found.
        """
        if self._repository is None:
            return None

        row = await self._repository.update_trust_level(
            note_id,
            new_level.value,
        )
        if row is None:
            return None

        note = self._row_to_note(row)

        if self._audit_ledger is not None:
            await self._audit_ledger.record_truth_change(
                artifact_id=note_id,
                actor="knowledge_vault",
                actor_type=ActorType.CONTROL_PLANE,
                action_summary=(f"Vault note {note_id} trust level changed to {new_level.value}"),
            )

        return note

    # -----------------------------------------------------------------
    # Delete operations
    # -----------------------------------------------------------------

    async def delete_note(self, note_id: str) -> bool:
        """Delete a vault note.

        Removes via repository and logs to audit ledger.

        Args:
            note_id: The note to delete.

        Returns:
            True if deleted, False if not found.
        """
        if self._repository is None:
            return False

        result = await self._repository.delete(note_id)

        if result and self._audit_ledger is not None:
            await self._audit_ledger.record_truth_change(
                artifact_id=note_id,
                actor="knowledge_vault",
                actor_type=ActorType.CONTROL_PLANE,
                action_summary=f"Vault note {note_id} deleted",
            )

        return result

    # -----------------------------------------------------------------
    # Invalidation integration
    # -----------------------------------------------------------------

    async def trigger_invalidation(
        self,
        *,
        trigger_source: str,
        affected_artifact_ids: list[str],
    ) -> list[str]:
        """Trigger invalidation for notes related to changed artifacts.

        For each affected artifact, finds vault notes whose related_artifacts
        list contains the artifact ID, then changes their trust level to
        STALE_RISK. Logs each change to audit ledger.

        Args:
            trigger_source: What triggered the invalidation.
            affected_artifact_ids: List of changed artifact IDs.

        Returns:
            List of invalidated note IDs.
        """
        if self._repository is None:
            return []

        invalidated: list[str] = []

        # Get all non-stale notes to check for related artifacts
        agent_inferred_rows = await self._repository.get_by_trust_level(
            VaultTrustLevel.AGENT_INFERRED.value,
        )
        verified_rows = await self._repository.get_by_trust_level(
            VaultTrustLevel.VERIFIED.value,
        )
        all_rows = agent_inferred_rows + verified_rows

        for row in all_rows:
            related = getattr(row, "related_artifacts", []) or []
            for artifact_id in affected_artifact_ids:
                if artifact_id in related:
                    # Change trust level to STALE_RISK
                    updated = await self._repository.update_trust_level(
                        row.note_id,
                        VaultTrustLevel.STALE_RISK.value,
                    )
                    if updated is not None:
                        invalidated.append(row.note_id)

                        if self._audit_ledger is not None:
                            await self._audit_ledger.record_truth_change(
                                artifact_id=row.note_id,
                                actor="knowledge_vault",
                                actor_type=ActorType.CONTROL_PLANE,
                                action_summary=(
                                    f"Vault note {row.note_id} invalidated "
                                    f"due to change in {artifact_id} "
                                    f"(trigger: {trigger_source})"
                                ),
                            )
                    break  # Don't double-invalidate same note

        return invalidated

    # -----------------------------------------------------------------
    # Index maintenance
    # -----------------------------------------------------------------

    async def refresh_indexes(self) -> None:
        """Refresh materialized view indexes.

        Executes REFRESH MATERIALIZED VIEW CONCURRENTLY for the
        knowledge.vault_category_index view. Called after write/delete
        operations. Wraps in try/except for environments where the
        view may not exist (test, early setup).
        """
        if self._repository is None:
            return

        session = getattr(self._repository, "session", None)
        if session is None:
            return

        try:
            await session.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY knowledge.vault_category_index"))
        except Exception:  # noqa: S110 — view may not exist in test envs / pre-migration setup
            pass

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _row_to_note(row: object) -> VaultNote:
        """Convert a VaultNoteRow (or mock) to a VaultNote domain model.

        Args:
            row: A VaultNoteRow instance or mock with matching attributes.

        Returns:
            VaultNote domain model.
        """
        return VaultNote(
            note_id=row.note_id,  # type: ignore[attr-defined]
            category=VaultCategory(row.category),  # type: ignore[attr-defined]
            trust_level=VaultTrustLevel(row.trust_level),  # type: ignore[attr-defined]
            content=row.content,  # type: ignore[attr-defined]
            source=row.source,  # type: ignore[attr-defined]
            created_at=row.created_at,  # type: ignore[attr-defined]
            updated_at=row.updated_at,  # type: ignore[attr-defined]
            tags=tuple(row.tags) if row.tags else (),  # type: ignore[attr-defined]
            related_artifacts=tuple(row.related_artifacts) if row.related_artifacts else (),  # type: ignore[attr-defined]
            invalidation_trigger=row.invalidation_trigger,  # type: ignore[attr-defined]
        )
