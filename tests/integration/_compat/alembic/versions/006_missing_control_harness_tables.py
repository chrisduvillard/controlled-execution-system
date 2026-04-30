"""missing_control_harness_tables

Revision ID: 006
Revises: 005
Create Date: 2026-04-08

Adds 3 tables that were defined in ORM (tables.py) but missing from
migrations:
- control.kill_switch_state (kill switch per activity class, D-05)
- control.api_keys (API key auth with SHA-256 hashes, INFRA-03)
- harness.trust_events (trust lifecycle event history)
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- control.kill_switch_state (D-05) ---
    op.create_table(
        "kill_switch_state",
        sa.Column("activity_class", sa.String(30), primary_key=True),
        sa.Column("halted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("halted_by", sa.String(100), nullable=True),
        sa.Column("halted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="control",
    )

    # --- control.api_keys (INFRA-03) ---
    # Create sequence for auto-increment primary key
    op.execute("CREATE SEQUENCE control.api_key_id_seq")

    op.create_table(
        "api_keys",
        sa.Column(
            "id",
            sa.BigInteger(),
            server_default=sa.text("nextval('control.api_key_id_seq')"),
            primary_key=True,
        ),
        sa.Column(
            "key_hash",
            sa.String(64),
            unique=True,
            nullable=False,
            index=True,
        ),
        sa.Column("owner", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        schema="control",
    )

    # --- harness.trust_events ---
    op.create_table(
        "trust_events",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("profile_id", sa.String(64), index=True, nullable=False),
        sa.Column("old_status", sa.String(20), nullable=False),
        sa.Column("new_status", sa.String(20), nullable=False),
        sa.Column("trigger", sa.String(50), nullable=False),
        sa.Column(
            "metadata_extra",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="harness",
    )


def downgrade() -> None:
    op.drop_table("trust_events", schema="harness")
    op.drop_table("api_keys", schema="control")
    op.execute("DROP SEQUENCE IF EXISTS control.api_key_id_seq")
    op.drop_table("kill_switch_state", schema="control")
