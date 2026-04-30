"""prune_legacy_server_state

Revision ID: 016
Revises: 015
Create Date: 2026-04-23

Drops stale server-era schemas and tables so a fresh migration produces the
current local-first CES database shape.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "016"
down_revision: str | None = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove server-era tables and schemas from the live migration head."""
    op.execute("DROP TABLE IF EXISTS control.project_members CASCADE")
    op.execute("DROP TABLE IF EXISTS control.api_keys CASCADE")
    op.execute("DROP SEQUENCE IF EXISTS control.api_key_id_seq CASCADE")
    op.execute("DROP SCHEMA IF EXISTS polyrepo CASCADE")
    op.execute("DROP SCHEMA IF EXISTS observability CASCADE")


def downgrade() -> None:
    """Downgrade is intentionally unsupported for removed server-era state."""
    msg = "Downgrading revision 016 is not supported because it would restore removed server-era schemas and tables."
    raise RuntimeError(msg)
