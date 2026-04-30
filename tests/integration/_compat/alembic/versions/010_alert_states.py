"""alert_states

Revision ID: 010
Revises: 009
Create Date: 2026-04-09

Creates the observability.alert_states table for persistent alert state storage.
Not partitioned (low-volume, needs UPSERT). Includes unique constraint for
deduplication and indexes for active alert queries and history.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create alert_states table in observability schema
    op.execute("""
        CREATE TABLE observability.alert_states (
            id SERIAL PRIMARY KEY,
            alert_name VARCHAR(100) NOT NULL,
            project_id VARCHAR(100) NOT NULL DEFAULT 'default',
            severity VARCHAR(20) NOT NULL DEFAULT 'info',
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            message TEXT,
            triggered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_at TIMESTAMPTZ,
            metadata JSONB NOT NULL DEFAULT '{}'
        )
    """)

    # Unique constraint for UPSERT deduplication
    op.execute("""
        ALTER TABLE observability.alert_states
        ADD CONSTRAINT uq_alert_states_name_project_status
        UNIQUE (alert_name, project_id, status)
    """)

    # Index for active alert queries (project_id, status)
    op.execute("""
        CREATE INDEX ix_alert_states_project_status
        ON observability.alert_states (project_id, status)
    """)

    # Index for history queries (triggered_at DESC)
    op.execute("""
        CREATE INDEX ix_alert_states_triggered_at
        ON observability.alert_states (triggered_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS observability.alert_states")
