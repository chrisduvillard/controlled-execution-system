"""SQLite-backed local persistence for local-first CES projects.

Public surface:
- :class:`LocalProjectStore` — the SQLite-backed store.
- ``Local*Repository`` — adapters that wrap the store for each domain service.
- ``Local*Record`` / ``LocalManifestRow`` — frozen dataclasses for rows.

Existing imports of the form ``from ces.local_store import X`` continue to
work because every public symbol is re-exported here.
"""

from ces.local_store.records import (
    LocalApprovalRecord,
    LocalBrownfieldSessionSummary,
    LocalBuilderBriefRecord,
    LocalBuilderSessionRecord,
    LocalBuilderSessionSnapshot,
    LocalManifestRow,
    LocalRuntimeExecutionRecord,
)
from ces.local_store.repositories import (
    LocalAuditRepository,
    LocalLegacyBehaviorRepository,
    LocalManifestRepository,
)
from ces.local_store.store import LocalProjectStore

__all__ = [
    "LocalApprovalRecord",
    "LocalAuditRepository",
    "LocalBrownfieldSessionSummary",
    "LocalBuilderBriefRecord",
    "LocalBuilderSessionRecord",
    "LocalBuilderSessionSnapshot",
    "LocalLegacyBehaviorRepository",
    "LocalManifestRepository",
    "LocalManifestRow",
    "LocalProjectStore",
    "LocalRuntimeExecutionRecord",
]
