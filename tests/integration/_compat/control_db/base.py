"""SQLAlchemy 2.0 declarative base and engine/session factories.

Provides:
- Base: DeclarativeBase with AsyncAttrs for all ORM models
- get_async_engine: Creates async engine for runtime queries (asyncpg)
- get_async_session_factory: Creates async session factory
- get_sync_engine: Creates sync engine for Alembic migrations (psycopg)
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all CES ORM models.

    Combines DeclarativeBase with AsyncAttrs for lazy-load support
    in async contexts.
    """


def get_async_engine(url: str, *, echo: bool = False) -> AsyncEngine:
    """Create async engine for runtime queries (asyncpg).

    Args:
        url: Database URL using postgresql+asyncpg:// scheme.
        echo: If True, log all SQL statements.

    Returns:
        AsyncEngine configured with connection pooling.
    """
    return create_async_engine(
        url,
        echo=echo,
        pool_size=5,
        max_overflow=10,
    )


def get_async_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Create async session factory.

    Args:
        engine: AsyncEngine to bind sessions to.

    Returns:
        Session factory that produces AsyncSession instances.
    """
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


def get_sync_engine(url: str, *, echo: bool = False) -> Engine:
    """Create sync engine for Alembic migrations (psycopg).

    Args:
        url: Database URL using postgresql+psycopg:// scheme.
        echo: If True, log all SQL statements.

    Returns:
        Synchronous Engine for migration operations.
    """
    return create_engine(url, echo=echo)
