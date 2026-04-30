"""federated_bindings

Revision ID: 012
Revises: 011
Create Date: 2026-04-09

Creates the polyrepo.federated_bindings table for cross-repo manifest
dependency bindings (POLY-01, POLY-05). Includes unique constraint to
prevent duplicate bindings and project_id for multi-project isolation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Ensure polyrepo schema exists (idempotent)
    op.execute("CREATE SCHEMA IF NOT EXISTS polyrepo")

    # Create federated_bindings table
    op.execute("""
        CREATE TABLE polyrepo.federated_bindings (
            id SERIAL PRIMARY KEY,
            source_repo_id VARCHAR(100) NOT NULL,
            source_manifest_id VARCHAR(64) NOT NULL,
            target_repo_id VARCHAR(100) NOT NULL,
            target_contract_id VARCHAR(64) NOT NULL,
            target_contract_type VARCHAR(50) NOT NULL,
            binding_status VARCHAR(20) NOT NULL DEFAULT 'active',
            project_id VARCHAR(100) NOT NULL DEFAULT 'default',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # Unique constraint: prevents duplicate bindings per POLY-05
    op.execute("""
        ALTER TABLE polyrepo.federated_bindings
        ADD CONSTRAINT uq_federated_binding_source_target
        UNIQUE (source_repo_id, source_manifest_id, target_repo_id, target_contract_id)
    """)

    # Index on source_repo_id for filtering bindings by source repo
    op.execute("""
        CREATE INDEX ix_fed_bindings_source_repo
        ON polyrepo.federated_bindings (source_repo_id)
    """)

    # Index on target_repo_id for filtering bindings by target repo
    op.execute("""
        CREATE INDEX ix_fed_bindings_target_repo
        ON polyrepo.federated_bindings (target_repo_id)
    """)

    # Index on project_id for multi-project isolation queries (T-15-02)
    op.execute("""
        CREATE INDEX ix_fed_bindings_project_id
        ON polyrepo.federated_bindings (project_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS polyrepo.federated_bindings")
