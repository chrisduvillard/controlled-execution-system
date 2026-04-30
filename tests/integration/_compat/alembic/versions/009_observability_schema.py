"""observability_schema

Revision ID: 009
Revises: 008
Create Date: 2026-04-09

Creates the observability schema with 5 range-partitioned telemetry tables
(task_metrics, agent_metrics, harness_metrics, control_plane_metrics,
system_metrics), indexes, default partitions, initial daily partitions,
a materialized view for agent aggregation, and 5 hourly rollup tables.

Uses raw DDL because SQLAlchemy cannot manage partitioned tables automatically.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Table names for all 5 telemetry levels
_TABLE_NAMES = [
    "task_metrics",
    "agent_metrics",
    "harness_metrics",
    "control_plane_metrics",
    "system_metrics",
]


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # 1. Create observability schema
    # -----------------------------------------------------------------------
    op.execute("CREATE SCHEMA IF NOT EXISTS observability")

    # -----------------------------------------------------------------------
    # 2. Create 5 partitioned parent tables
    # -----------------------------------------------------------------------
    op.execute("""
        CREATE TABLE observability.task_metrics (
            id BIGSERIAL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id VARCHAR(100) NOT NULL DEFAULT 'default',
            manifest_id VARCHAR(64) NOT NULL,
            task_id VARCHAR(64) NOT NULL,
            agent_id VARCHAR(100) NOT NULL,
            tokens_consumed INTEGER NOT NULL DEFAULT 0,
            wall_clock_seconds DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            invocation_count INTEGER NOT NULL DEFAULT 0,
            self_correction_count INTEGER NOT NULL DEFAULT 0,
            context_window_utilization DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            boundary_violations_attempted INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (id, recorded_at)
        ) PARTITION BY RANGE (recorded_at)
    """)

    op.execute("""
        CREATE TABLE observability.agent_metrics (
            id BIGSERIAL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id VARCHAR(100) NOT NULL DEFAULT 'default',
            agent_id VARCHAR(100) NOT NULL,
            error_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            hallucination_detection_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            output_accepted_ratio DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            cost_per_task_by_class JSONB NOT NULL DEFAULT '{}',
            PRIMARY KEY (id, recorded_at)
        ) PARTITION BY RANGE (recorded_at)
    """)

    op.execute("""
        CREATE TABLE observability.harness_metrics (
            id BIGSERIAL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id VARCHAR(100) NOT NULL DEFAULT 'default',
            guide_effectiveness DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            sensor_tpr DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            sensor_fpr DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            review_catch_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            review_disagreement_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            PRIMARY KEY (id, recorded_at)
        ) PARTITION BY RANGE (recorded_at)
    """)

    op.execute("""
        CREATE TABLE observability.control_plane_metrics (
            id BIGSERIAL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id VARCHAR(100) NOT NULL DEFAULT 'default',
            manifest_issuance_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            invalidation_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            merge_queue_depth INTEGER NOT NULL DEFAULT 0,
            approval_queue_depth INTEGER NOT NULL DEFAULT 0,
            approval_latency_seconds DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            stale_context_timeout_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            PRIMARY KEY (id, recorded_at)
        ) PARTITION BY RANGE (recorded_at)
    """)

    op.execute("""
        CREATE TABLE observability.system_metrics (
            id BIGSERIAL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id VARCHAR(100) NOT NULL DEFAULT 'default',
            total_cost_burn_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            total_active_agent_count INTEGER NOT NULL DEFAULT 0,
            delegation_chain_depth_distribution JSONB NOT NULL DEFAULT '{}',
            concurrent_task_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (id, recorded_at)
        ) PARTITION BY RANGE (recorded_at)
    """)

    # -----------------------------------------------------------------------
    # 3. Create indexes on parent tables (propagated to partitions)
    # -----------------------------------------------------------------------
    op.execute("CREATE INDEX ix_task_metrics_project_id ON observability.task_metrics (project_id)")
    op.execute("CREATE INDEX ix_task_metrics_manifest_id ON observability.task_metrics (manifest_id)")
    op.execute("CREATE INDEX ix_task_metrics_agent_id ON observability.task_metrics (agent_id)")
    op.execute("CREATE INDEX ix_agent_metrics_project_id ON observability.agent_metrics (project_id)")
    op.execute("CREATE INDEX ix_agent_metrics_agent_id ON observability.agent_metrics (agent_id)")
    op.execute("CREATE INDEX ix_harness_metrics_project_id ON observability.harness_metrics (project_id)")
    op.execute("CREATE INDEX ix_control_plane_metrics_project_id ON observability.control_plane_metrics (project_id)")
    op.execute("CREATE INDEX ix_system_metrics_project_id ON observability.system_metrics (project_id)")

    # -----------------------------------------------------------------------
    # 4. Create DEFAULT partitions (catch rows if dated partition missing)
    # -----------------------------------------------------------------------
    for table_name in _TABLE_NAMES:
        op.execute(f"CREATE TABLE observability.{table_name}_default PARTITION OF observability.{table_name} DEFAULT")

    # -----------------------------------------------------------------------
    # 5. Create initial daily partitions (today + 7 days ahead)
    # -----------------------------------------------------------------------
    today = date.today()
    for table_name in _TABLE_NAMES:
        for i in range(8):
            d = today + timedelta(days=i)
            next_d = d + timedelta(days=1)
            partition_name = f"{table_name}_{d.strftime('%Y%m%d')}"
            op.execute(
                f"CREATE TABLE IF NOT EXISTS observability.{partition_name} "
                f"PARTITION OF observability.{table_name} "
                f"FOR VALUES FROM ('{d.isoformat()}') TO ('{next_d.isoformat()}')"
            )

    # -----------------------------------------------------------------------
    # 6. Create materialized view for agent-level aggregation (OBS-02)
    # -----------------------------------------------------------------------
    op.execute("""
        CREATE MATERIALIZED VIEW observability.agent_metrics_agg AS
        SELECT
            agent_id,
            project_id,
            COUNT(*) FILTER (WHERE tokens_consumed > 0) AS task_count,
            COALESCE(AVG(wall_clock_seconds), 0) AS avg_wall_clock,
            COALESCE(SUM(tokens_consumed), 0) AS total_tokens,
            COALESCE(SUM(self_correction_count), 0) AS total_corrections,
            COALESCE(SUM(boundary_violations_attempted), 0) AS total_violations,
            date_trunc('hour', recorded_at) AS hour_bucket
        FROM observability.task_metrics
        WHERE recorded_at > now() - interval '24 hours'
        GROUP BY agent_id, project_id, date_trunc('hour', recorded_at)
        WITH NO DATA
    """)

    op.execute("CREATE UNIQUE INDEX ON observability.agent_metrics_agg (agent_id, project_id, hour_bucket)")

    # -----------------------------------------------------------------------
    # 7. Create hourly rollup tables for 90-day retention
    # -----------------------------------------------------------------------

    # Task metrics rollup
    op.execute("""
        CREATE TABLE observability.task_metrics_hourly (
            hour_bucket TIMESTAMPTZ NOT NULL,
            project_id VARCHAR(100) NOT NULL DEFAULT 'default',
            task_count INTEGER NOT NULL DEFAULT 0,
            total_tokens BIGINT NOT NULL DEFAULT 0,
            avg_wall_clock DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            total_corrections INTEGER NOT NULL DEFAULT 0,
            total_violations INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (hour_bucket, project_id)
        )
    """)

    # Agent metrics rollup
    op.execute("""
        CREATE TABLE observability.agent_metrics_hourly (
            hour_bucket TIMESTAMPTZ NOT NULL,
            project_id VARCHAR(100) NOT NULL DEFAULT 'default',
            agent_count INTEGER NOT NULL DEFAULT 0,
            avg_error_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            avg_hallucination_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            avg_output_accepted DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            PRIMARY KEY (hour_bucket, project_id)
        )
    """)

    # Harness metrics rollup
    op.execute("""
        CREATE TABLE observability.harness_metrics_hourly (
            hour_bucket TIMESTAMPTZ NOT NULL,
            project_id VARCHAR(100) NOT NULL DEFAULT 'default',
            avg_guide_effectiveness DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            avg_sensor_tpr DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            avg_sensor_fpr DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            avg_review_catch_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            avg_review_disagreement_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            PRIMARY KEY (hour_bucket, project_id)
        )
    """)

    # Control plane metrics rollup
    op.execute("""
        CREATE TABLE observability.control_plane_metrics_hourly (
            hour_bucket TIMESTAMPTZ NOT NULL,
            project_id VARCHAR(100) NOT NULL DEFAULT 'default',
            avg_manifest_issuance_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            avg_invalidation_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            max_merge_queue_depth INTEGER NOT NULL DEFAULT 0,
            max_approval_queue_depth INTEGER NOT NULL DEFAULT 0,
            avg_approval_latency DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            avg_stale_context_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            PRIMARY KEY (hour_bucket, project_id)
        )
    """)

    # System metrics rollup
    op.execute("""
        CREATE TABLE observability.system_metrics_hourly (
            hour_bucket TIMESTAMPTZ NOT NULL,
            project_id VARCHAR(100) NOT NULL DEFAULT 'default',
            avg_cost_burn_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            max_active_agent_count INTEGER NOT NULL DEFAULT 0,
            max_concurrent_task_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (hour_bucket, project_id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS observability CASCADE")
