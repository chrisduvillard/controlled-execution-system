"""webhook_delivery_transport

Revision ID: 015
Revises: 014
Create Date: 2026-04-10

Creates webhook destinations and delivery tracking for cross-network repos.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "015"
down_revision: str | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE polyrepo.webhook_destinations (
            id SERIAL PRIMARY KEY,
            repo_id VARCHAR(100) NOT NULL,
            endpoint_url VARCHAR(500) NOT NULL,
            project_id VARCHAR(100) NOT NULL DEFAULT 'default',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE polyrepo.webhook_deliveries (
            id SERIAL PRIMARY KEY,
            destination_id INTEGER NOT NULL,
            repo_id VARCHAR(100) NOT NULL,
            endpoint_url VARCHAR(500) NOT NULL,
            event_stream_id VARCHAR(100),
            event_id VARCHAR(100) NOT NULL,
            source_repo_id VARCHAR(100) NOT NULL,
            artifact_id VARCHAR(64) NOT NULL,
            artifact_type VARCHAR(50) NOT NULL,
            cascade_depth INTEGER NOT NULL DEFAULT 0,
            max_cascade_depth INTEGER NOT NULL DEFAULT 3,
            event_created_at TIMESTAMPTZ NOT NULL,
            project_id VARCHAR(100) NOT NULL DEFAULT 'default',
            status VARCHAR(30) NOT NULL DEFAULT 'pending',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_http_status INTEGER,
            last_error VARCHAR(500),
            last_attempt_at TIMESTAMPTZ,
            next_attempt_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX ix_webhook_destinations_project_repo
        ON polyrepo.webhook_destinations (project_id, repo_id)
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_webhook_deliveries_destination_event
        ON polyrepo.webhook_deliveries (destination_id, event_id, project_id)
    """)
    op.execute("""
        CREATE INDEX ix_webhook_deliveries_due
        ON polyrepo.webhook_deliveries (status, next_attempt_at)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS polyrepo.webhook_deliveries")
    op.execute("DROP TABLE IF EXISTS polyrepo.webhook_destinations")
