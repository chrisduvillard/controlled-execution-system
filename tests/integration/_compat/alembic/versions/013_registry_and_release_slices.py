"""registry_and_release_slices

Revision ID: 013
Revises: 012
Create Date: 2026-04-09

Creates the polyrepo.registry_entries, polyrepo.release_slices, and
polyrepo.release_slice_repos tables for the shared control plane
registry (POLY-03) and aggregate release coordination (POLY-06).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Ensure polyrepo schema exists (idempotent)
    op.execute("CREATE SCHEMA IF NOT EXISTS polyrepo")

    # Create registry_entries table
    op.execute("""
        CREATE TABLE polyrepo.registry_entries (
            id SERIAL PRIMARY KEY,
            repo_id VARCHAR(100) NOT NULL UNIQUE,
            display_name VARCHAR(255) NOT NULL,
            registry_url VARCHAR(500),
            is_active BOOLEAN NOT NULL DEFAULT true,
            registered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # Create release_slices table
    op.execute("""
        CREATE TABLE polyrepo.release_slices (
            id SERIAL PRIMARY KEY,
            slice_id VARCHAR(64) NOT NULL UNIQUE,
            name VARCHAR(255) NOT NULL,
            aggregate_risk_tier VARCHAR(5),
            aggregate_behavior_confidence VARCHAR(5),
            aggregate_change_class VARCHAR(10),
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # Create release_slice_repos table
    op.execute("""
        CREATE TABLE polyrepo.release_slice_repos (
            id SERIAL PRIMARY KEY,
            slice_id VARCHAR(64) NOT NULL
                REFERENCES polyrepo.release_slices(slice_id),
            repo_id VARCHAR(100) NOT NULL,
            repo_risk_tier VARCHAR(5),
            readiness_status VARCHAR(20) NOT NULL DEFAULT 'pending',
            CONSTRAINT uq_slice_repo UNIQUE (slice_id, repo_id)
        )
    """)

    # Index on release_slice_repos for slice lookups
    op.execute("""
        CREATE INDEX ix_release_slice_repos_slice_id
        ON polyrepo.release_slice_repos (slice_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS polyrepo.release_slice_repos")
    op.execute("DROP TABLE IF EXISTS polyrepo.release_slices")
    op.execute("DROP TABLE IF EXISTS polyrepo.registry_entries")
