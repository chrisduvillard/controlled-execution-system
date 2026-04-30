"""alert_calibrations

Revision ID: 014
Revises: 013
Create Date: 2026-04-10

Creates project-scoped calibration state for predictive alerts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "014"
down_revision: str | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE observability.alert_calibrations (
            project_id VARCHAR(100) PRIMARY KEY,
            status VARCHAR(20) NOT NULL DEFAULT 'warming_up',
            observation_only BOOLEAN NOT NULL DEFAULT TRUE,
            force_observation_only BOOLEAN NOT NULL DEFAULT FALSE,
            baseline_window_hours INTEGER NOT NULL DEFAULT 168,
            minimum_data_points INTEGER NOT NULL DEFAULT 10,
            stale_after_hours INTEGER NOT NULL DEFAULT 24,
            last_refreshed_at TIMESTAMPTZ,
            last_sample_at TIMESTAMPTZ,
            data_points INTEGER NOT NULL DEFAULT 0,
            threshold_overrides JSONB NOT NULL DEFAULT '{}'
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS observability.alert_calibrations")
