"""event_bus_schema

Revision ID: 011
Revises: 010
Create Date: 2026-04-09

Creates the polyrepo schema with invalidation_events and subscriptions tables
for cross-repo event tracking, deduplication, and subscription management.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create polyrepo schema
    op.execute("CREATE SCHEMA IF NOT EXISTS polyrepo")

    # Create invalidation_events table
    op.execute("""
        CREATE TABLE polyrepo.invalidation_events (
            id SERIAL PRIMARY KEY,
            event_stream_id VARCHAR(100) NOT NULL,
            source_repo_id VARCHAR(100) NOT NULL,
            artifact_id VARCHAR(64) NOT NULL,
            artifact_type VARCHAR(50) NOT NULL,
            cascade_depth INTEGER DEFAULT 0,
            status VARCHAR(20) DEFAULT 'received',
            processed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # Create subscriptions table
    op.execute("""
        CREATE TABLE polyrepo.subscriptions (
            id SERIAL PRIMARY KEY,
            repo_id VARCHAR(100) NOT NULL UNIQUE,
            consumer_group VARCHAR(200) NOT NULL,
            subscribed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_event_id VARCHAR(100),
            is_active BOOLEAN DEFAULT TRUE
        )
    """)

    # Index on source_repo_id for filtering by source repo
    op.execute("""
        CREATE INDEX ix_invalidation_events_source_repo
        ON polyrepo.invalidation_events (source_repo_id)
    """)

    # Composite index on status and created_at for recent-event queries
    op.execute("""
        CREATE INDEX ix_invalidation_events_status
        ON polyrepo.invalidation_events (status, created_at)
    """)

    # Unique index on repo_id already enforced by UNIQUE constraint
    # but add explicit index for query performance
    op.execute("""
        CREATE INDEX ix_subscriptions_repo_id
        ON polyrepo.subscriptions (repo_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS polyrepo.subscriptions")
    op.execute("DROP TABLE IF EXISTS polyrepo.invalidation_events")
    op.execute("DROP SCHEMA IF EXISTS polyrepo CASCADE")
