"""Repository adapters that present the LocalProjectStore as the contract
each domain service expects.

These adapters duck-type the same methods as the SQLAlchemy compatibility
repositories under ``tests/integration/_compat/control_db/repository.py``
so that swapping persistence backends does not require service changes.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from ces.brownfield.records import LegacyBehaviorRecord
from ces.control.models.audit_entry_record import AuditEntryRecord
from ces.local_store.records import LocalManifestRow

if TYPE_CHECKING:
    from ces.local_store.store import LocalProjectStore


class LocalManifestRepository:
    """Repository adapter for ManifestManager backed by LocalProjectStore."""

    def __init__(self, store: LocalProjectStore) -> None:
        self._store = store

    async def save(self, manifest: Any) -> None:
        self._store.save_manifest(manifest)

    async def get_by_id(self, manifest_id: str) -> LocalManifestRow | None:
        return self._store.get_manifest_row(manifest_id)

    async def get_active(self) -> list[LocalManifestRow]:
        return self._store.get_active_manifest_rows()

    async def get_all(self) -> list[LocalManifestRow]:
        """Return every manifest row, including terminal workflow states."""
        return self._store.get_all_manifest_rows()


class LocalAuditRepository:
    """Repository adapter for AuditLedgerService backed by LocalProjectStore."""

    def __init__(self, store: LocalProjectStore) -> None:
        self._store = store

    async def append(self, row: Any) -> None:
        self._store.append_audit_entry(row)

    async def get_last_entry(self, project_id: str | None = None) -> AuditEntryRecord | None:
        return self._store.get_last_audit_entry(project_id=project_id)

    async def get_by_event_type(self, event_type: str, project_id: str | None = None) -> list[AuditEntryRecord]:
        return self._store.get_audit_by_event_type(event_type, project_id=project_id)

    async def get_by_actor(self, actor: str, project_id: str | None = None) -> list[AuditEntryRecord]:
        return self._store.get_audit_by_actor(actor, project_id=project_id)

    async def get_by_time_range(
        self, start: datetime, end: datetime, project_id: str | None = None
    ) -> list[AuditEntryRecord]:
        return self._store.get_audit_by_time_range(start, end, project_id=project_id)

    async def get_latest(self, limit: int = 1000, project_id: str | None = None) -> list[AuditEntryRecord]:
        return self._store.get_latest_audit(limit=limit, project_id=project_id)


class LocalLegacyBehaviorRepository:
    """Repository adapter for LegacyBehaviorService backed by LocalProjectStore."""

    def __init__(self, store: LocalProjectStore) -> None:
        self._store = store

    async def save(self, row: Any) -> None:
        self._store.save_legacy_behavior_row(row)

    async def get_pending(self) -> list[LegacyBehaviorRecord]:
        return self._store.get_pending_legacy_behavior_rows()

    async def get_by_system(self, system: str) -> list[LegacyBehaviorRecord]:
        return self._store.get_legacy_behavior_rows_by_system(system)

    async def get_by_id(self, entry_id: str) -> LegacyBehaviorRecord | None:
        return self._store.get_legacy_behavior_row(entry_id)

    async def update_disposition(
        self,
        *,
        entry_id: str,
        disposition: str,
        reviewed_by: str,
        reviewed_at: datetime,
    ) -> LegacyBehaviorRecord | None:
        return self._store.update_legacy_behavior_disposition(
            entry_id=entry_id,
            disposition=disposition,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at,
        )

    async def mark_promoted(self, entry_id: str, prl_id: str) -> LegacyBehaviorRecord | None:
        return self._store.mark_legacy_behavior_promoted(
            entry_id=entry_id,
            prl_id=prl_id,
        )

    async def save_prl_item(self, prl_item: Any) -> None:
        self._store.save_prl_item(prl_item)
