"""project_members

Revision ID: 008
Revises: 007
Create Date: 2026-04-08

Adds project_members table for RBAC with project-scoped roles (MULTI-02).
Each row represents a user's role within a specific project.
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_members",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("project_id", sa.String(100), nullable=False, index=True),
        sa.Column("user_id", sa.String(100), nullable=False, index=True),
        sa.Column(
            "role",
            sa.String(30),
            nullable=False,
            comment="admin, approver, implementer, viewer",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_user"),
        schema="control",
    )


def downgrade() -> None:
    op.drop_table("project_members", schema="control")
