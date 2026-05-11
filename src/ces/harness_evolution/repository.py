"""Repository facade for local harness evolution persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ces.harness_evolution.models import HarnessChangeManifest, HarnessChangeVerdict
from ces.local_store.records import LocalHarnessChangeRecord, LocalHarnessChangeVerdictRecord

if TYPE_CHECKING:
    from ces.local_store.store import LocalProjectStore


class HarnessEvolutionRepository:
    """Persistence boundary for harness change attribution records."""

    def __init__(self, store: LocalProjectStore) -> None:
        self._store = store

    def save_change(self, manifest: HarnessChangeManifest) -> LocalHarnessChangeRecord:
        """Persist or update a harness change manifest."""

        return self._store.save_harness_change(manifest)

    def get_change(self, change_id: str) -> LocalHarnessChangeRecord | None:
        """Load a harness change by id."""

        return self._store.get_harness_change(change_id)

    def list_changes(self, status: str | None = None) -> list[LocalHarnessChangeRecord]:
        """List persisted harness changes, optionally filtered by status."""

        return self._store.list_harness_changes(status=status)

    def save_verdict(self, verdict: HarnessChangeVerdict) -> LocalHarnessChangeVerdictRecord:
        """Persist an observed verdict for a known harness change."""

        return self._store.save_harness_change_verdict(verdict)

    def list_verdicts(self, change_id: str) -> list[LocalHarnessChangeVerdictRecord]:
        """List verdicts for a harness change in creation order."""

        return self._store.list_harness_change_verdicts(change_id)
