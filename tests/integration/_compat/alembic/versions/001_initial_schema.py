"""initial_schema

Revision ID: 001
Revises: None
Create Date: 2026-04-06

Creates per-plane PostgreSQL schemas (control, harness, execution) and
all initial tables:
- control.truth_artifacts (polymorphic JSONB with GIN index, per D-06)
- control.manifests (task manifest storage)
- control.audit_entries (append-only audit ledger with DB trigger, per D-07)
- control.workflow_states (current workflow state, per D-11)
- harness.harness_profiles (agent harness profiles)
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create per-plane schemas
    op.execute("CREATE SCHEMA IF NOT EXISTS control")
    op.execute("CREATE SCHEMA IF NOT EXISTS harness")
    op.execute("CREATE SCHEMA IF NOT EXISTS execution")

    # --- control.truth_artifacts ---
    op.create_table(
        "truth_artifacts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("type", sa.String(50), index=True, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), index=True, nullable=False),
        sa.Column(
            "content",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("owner", sa.String(100), nullable=False),
        sa.Column("signature", sa.Text(), nullable=True),
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
        schema="control",
    )
    op.create_index(
        "ix_truth_artifacts_content",
        "truth_artifacts",
        ["content"],
        schema="control",
        postgresql_using="gin",
    )

    # --- control.manifests ---
    op.create_table(
        "manifests",
        sa.Column("manifest_id", sa.String(64), primary_key=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("risk_tier", sa.String(5), nullable=False),
        sa.Column("behavior_confidence", sa.String(5), nullable=False),
        sa.Column("change_class", sa.String(10), nullable=False),
        sa.Column(
            "content",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), index=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("classifier_id", sa.String(100), nullable=True),
        sa.Column("implementer_id", sa.String(100), nullable=True),
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
        schema="control",
    )

    # --- control.audit_entries ---
    op.execute("CREATE SEQUENCE IF NOT EXISTS control.audit_entries_seq")
    op.create_table(
        "audit_entries",
        sa.Column("entry_id", sa.String(64), primary_key=True),
        sa.Column(
            "sequence_num",
            sa.BigInteger(),
            server_default=sa.text("nextval('control.audit_entries_seq')"),
            unique=True,
            nullable=False,
        ),
        sa.Column("timestamp", sa.DateTime(timezone=True), index=True, nullable=False),
        sa.Column("event_type", sa.String(30), index=True, nullable=False),
        sa.Column("actor", sa.String(100), index=True, nullable=False),
        sa.Column("actor_type", sa.String(20), nullable=False),
        sa.Column(
            "scope",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("action_summary", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column(
            "metadata_extra",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "prev_hash",
            sa.String(64),
            server_default="GENESIS",
            nullable=False,
        ),
        sa.Column("entry_hash", sa.String(64), nullable=True),
        schema="control",
    )

    # --- Append-only audit ledger DB trigger (D-07) ---
    op.execute(
        """
        CREATE OR REPLACE FUNCTION control.prevent_audit_modification()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'Audit ledger entries may not be modified or deleted. Append a correction entry instead. Attempted operation: %', TG_OP;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_append_only
            BEFORE UPDATE OR DELETE ON control.audit_entries
            FOR EACH ROW
            EXECUTE FUNCTION control.prevent_audit_modification();
        """
    )

    # --- control.workflow_states ---
    op.create_table(
        "workflow_states",
        sa.Column(
            "manifest_id",
            sa.String(64),
            sa.ForeignKey("control.manifests.manifest_id"),
            primary_key=True,
        ),
        sa.Column("current_state", sa.String(20), index=True, nullable=False),
        sa.Column("sub_state", sa.String(30), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="control",
    )

    # --- harness.harness_profiles ---
    op.create_table(
        "harness_profiles",
        sa.Column("profile_id", sa.String(64), primary_key=True),
        sa.Column(
            "agent_id",
            sa.String(100),
            index=True,
            unique=True,
            nullable=False,
        ),
        sa.Column("trust_status", sa.String(20), nullable=False),
        sa.Column(
            "profile_data",
            postgresql.JSONB(astext_type=sa.Text()),
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
        schema="harness",
    )


def downgrade() -> None:
    # Drop tables in reverse dependency order
    op.drop_table("harness_profiles", schema="harness")
    op.drop_table("workflow_states", schema="control")

    # Drop audit trigger and function before dropping table
    op.execute("DROP TRIGGER IF EXISTS audit_append_only ON control.audit_entries")
    op.execute("DROP FUNCTION IF EXISTS control.prevent_audit_modification()")
    op.drop_table("audit_entries", schema="control")
    op.execute("DROP SEQUENCE IF EXISTS control.audit_entries_seq")

    op.drop_index(
        "ix_truth_artifacts_content",
        table_name="truth_artifacts",
        schema="control",
    )
    op.drop_table("manifests", schema="control")
    op.drop_table("truth_artifacts", schema="control")

    # Drop schemas (only if empty)
    op.execute("DROP SCHEMA IF EXISTS execution")
    op.execute("DROP SCHEMA IF EXISTS harness")
    op.execute("DROP SCHEMA IF EXISTS control")
