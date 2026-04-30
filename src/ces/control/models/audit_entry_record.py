"""Plain-dataclass audit entry record used by the runtime persistence path.

The :class:`AuditEntryRecord` is the row-shaped data carrier that
:class:`AuditLedgerService.append_event` constructs and hands to whichever
repository is configured. The local SQLite repository (``LocalAuditRepository``
in :mod:`ces.local_store`) reads attributes off the record via duck-typing;
the SQLAlchemy compatibility repository (under
``tests/integration/_compat/control_db``) accepts the same record and converts
it to the ORM-mapped :class:`AuditEntryRow` internally.

Decoupling the runtime path from the SQLAlchemy ORM types lets the published
wheel ship without ``alembic``, ``asyncpg``, or ``psycopg``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AuditEntryRecord:
    """Row-shaped audit entry. Persistence-backend-agnostic."""

    entry_id: str
    timestamp: datetime
    event_type: str
    actor: str
    actor_type: str
    scope: dict
    action_summary: str
    decision: str
    rationale: str
    project_id: str
    metadata_extra: dict | None
    prev_hash: str
    entry_hash: str | None
