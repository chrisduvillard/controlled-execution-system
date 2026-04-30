"""Alembic migration environment for CES.

Uses psycopg (sync driver) for migrations. The alembic.ini URL uses
postgresql+psycopg:// scheme. Override via CES_DATABASE_SYNC_URL env var.

Creates per-plane PostgreSQL schemas (control, harness, execution) before
running migrations to ensure table creation succeeds.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, text

# Register all table models so Base.metadata is populated (side-effect imports)
import tests.integration._compat.control_db.tables
from tests.integration._compat.control_db.base import Base

# Alembic Config object for .ini file access
config = context.config

# Set up Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# SQLAlchemy MetaData for autogenerate support
target_metadata = Base.metadata


def get_url() -> str:
    """Get database URL from environment or alembic.ini."""
    return os.getenv(
        "CES_DATABASE_SYNC_URL",
        config.get_main_option("sqlalchemy.url", ""),
    )


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL scripts without connecting to the database.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Creates a connection to the database and runs migrations
    within a transaction.
    """
    url = get_url()
    connectable = create_engine(url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        # Create per-plane schemas if they don't exist
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS control"))
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS harness"))
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS execution"))
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
