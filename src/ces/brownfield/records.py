"""Plain-dataclass legacy-behavior record used by the runtime persistence path.

The :class:`LegacyBehaviorRecord` is the row-shaped data carrier that
:class:`LegacyBehaviorService.register_behavior` (and review/promote flows)
hand to whichever repository is configured. The local SQLite repository
(``LocalLegacyBehaviorRepository`` in :mod:`ces.local_store`) duck-types
attribute reads; the SQLAlchemy compatibility repository (under
``tests/integration/_compat/control_db``) accepts the same record and
converts it to the ORM-mapped :class:`LegacyBehaviorRow` internally.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class LegacyBehaviorRecord:
    """Row-shaped legacy-behavior register entry. Persistence-agnostic."""

    entry_id: str
    system: str
    behavior_description: str
    inferred_by: str
    inferred_at: datetime
    confidence: float
    source_manifest_id: str | None = None
    project_id: str | None = None
    disposition: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    promoted_to_prl_id: str | None = None
    discarded: bool = False
