"""knowledge_tables

Revision ID: 005
Revises: 001
Create Date: 2026-04-07

Creates the knowledge PostgreSQL schema and tables for Phase 5:
- knowledge.vault_notes (Zettelkasten vault notes with GIN index)
- knowledge.intake_sessions (intake interview session state)
- knowledge.legacy_behaviors (observed legacy behavior register)
- knowledge.vault_category_index (materialized view for auto-maintained indexes)
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create knowledge schema
    op.execute("CREATE SCHEMA IF NOT EXISTS knowledge")

    # --- knowledge.vault_notes ---
    op.create_table(
        "vault_notes",
        sa.Column("note_id", sa.String(64), primary_key=True),
        sa.Column("category", sa.String(30), index=True, nullable=False),
        sa.Column("trust_level", sa.String(20), index=True, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(255), nullable=False),
        sa.Column(
            "note_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "related_artifacts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("invalidation_trigger", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="knowledge",
    )
    # GIN index on note_metadata for efficient JSONB querying
    op.create_index(
        "ix_vault_notes_note_metadata",
        "vault_notes",
        ["note_metadata"],
        schema="knowledge",
        postgresql_using="gin",
    )
    # Composite index on (category, trust_level) for common filter queries
    op.create_index(
        "ix_vault_notes_category_trust",
        "vault_notes",
        ["category", "trust_level"],
        schema="knowledge",
    )

    # --- knowledge.intake_sessions ---
    op.create_table(
        "intake_sessions",
        sa.Column("session_id", sa.String(64), primary_key=True),
        sa.Column("phase", sa.Integer(), nullable=False),
        sa.Column("current_stage", sa.String(20), nullable=False),
        sa.Column("project_id", sa.String(100), index=True, nullable=False),
        sa.Column(
            "answers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "assumptions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "blocked_questions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="knowledge",
    )

    # --- knowledge.legacy_behaviors ---
    op.create_table(
        "legacy_behaviors",
        sa.Column("entry_id", sa.String(64), primary_key=True),
        sa.Column("system", sa.String(255), index=True, nullable=False),
        sa.Column("behavior_description", sa.Text(), nullable=False),
        sa.Column("inferred_by", sa.String(100), nullable=False),
        sa.Column("inferred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("disposition", sa.String(30), nullable=True),
        sa.Column("reviewed_by", sa.String(100), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("promoted_to_prl_id", sa.String(64), nullable=True),
        sa.Column(
            "discarded",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column("source_manifest_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="knowledge",
    )

    # --- Materialized view: knowledge.vault_category_index (VAULT-03) ---
    op.execute(
        """
        CREATE MATERIALIZED VIEW knowledge.vault_category_index AS
        SELECT
            category,
            count(*) AS note_count,
            max(updated_at) AS latest_update
        FROM knowledge.vault_notes
        WHERE trust_level != 'stale-risk'
        GROUP BY category
        WITH DATA;
        """
    )
    op.execute("CREATE UNIQUE INDEX ON knowledge.vault_category_index (category)")


def downgrade() -> None:
    # Drop materialized view first
    op.execute("DROP MATERIALIZED VIEW IF EXISTS knowledge.vault_category_index")

    # Drop tables in reverse order
    op.drop_table("legacy_behaviors", schema="knowledge")
    op.drop_table("intake_sessions", schema="knowledge")

    # Drop indexes before table
    op.drop_index(
        "ix_vault_notes_category_trust",
        table_name="vault_notes",
        schema="knowledge",
    )
    op.drop_index(
        "ix_vault_notes_note_metadata",
        table_name="vault_notes",
        schema="knowledge",
    )
    op.drop_table("vault_notes", schema="knowledge")

    # Drop schema (only if empty)
    op.execute("DROP SCHEMA IF EXISTS knowledge")
