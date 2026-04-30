"""add_project_id

Revision ID: 007
Revises: 006
Create Date: 2026-04-08

Adds project_id column to 8 governance tables for multi-project support
(MULTI-01). Uses DEFAULT 'default' for backwards compatibility with
existing single-project data.

Tables modified:
- control.truth_artifacts
- control.manifests
- control.audit_entries
- control.workflow_states
- harness.harness_profiles
- harness.trust_events
- knowledge.vault_notes (nullable — shared notes have no project)
- knowledge.legacy_behaviors

Tables NOT modified (global scope):
- control.api_keys
- control.kill_switch_state
- knowledge.intake_sessions (already has project_id)
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables that need a NOT NULL project_id with default
_REQUIRED_TABLES = [
    ("control", "truth_artifacts"),
    ("control", "manifests"),
    ("control", "audit_entries"),
    ("control", "workflow_states"),
    ("harness", "harness_profiles"),
    ("harness", "trust_events"),
    ("knowledge", "legacy_behaviors"),
]

# Tables with nullable project_id (shared resources)
_OPTIONAL_TABLES = [
    ("knowledge", "vault_notes"),
]


def upgrade() -> None:
    # Add NOT NULL project_id with default to governance tables
    for schema, table in _REQUIRED_TABLES:
        op.add_column(
            table,
            sa.Column(
                "project_id",
                sa.String(100),
                server_default="default",
                nullable=False,
            ),
            schema=schema,
        )
        op.create_index(
            f"ix_{table}_project_id",
            table,
            ["project_id"],
            schema=schema,
        )

    # Add nullable project_id to shared tables
    for schema, table in _OPTIONAL_TABLES:
        op.add_column(
            table,
            sa.Column("project_id", sa.String(100), nullable=True),
            schema=schema,
        )
        op.create_index(
            f"ix_{table}_project_id",
            table,
            ["project_id"],
            schema=schema,
        )


def downgrade() -> None:
    for schema, table in _OPTIONAL_TABLES:
        op.drop_index(f"ix_{table}_project_id", table_name=table, schema=schema)
        op.drop_column(table, "project_id", schema=schema)

    for schema, table in _REQUIRED_TABLES:
        op.drop_index(f"ix_{table}_project_id", table_name=table, schema=schema)
        op.drop_column(table, "project_id", schema=schema)
