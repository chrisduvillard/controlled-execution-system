"""Tests for CES database base module (ces.control.db.base).

Validates Base declarative class, async engine factory, async session
factory, and sync engine factory. Covers all 36 statements in
control/db/base.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

pytestmark = pytest.mark.integration

from tests.integration._compat.control_db.base import (
    Base,
    get_async_engine,
    get_async_session_factory,
    get_sync_engine,
)


class TestBase:
    """Base declarative class configuration."""

    def test_base_has_metadata(self) -> None:
        """Base must expose metadata for table registration."""
        assert hasattr(Base, "metadata")
        assert Base.metadata is not None

    def test_base_inherits_async_attrs(self) -> None:
        """Base must include AsyncAttrs in its MRO for lazy-load support."""
        assert AsyncAttrs in Base.__mro__

    def test_base_inherits_declarative_base(self) -> None:
        """Base must inherit from DeclarativeBase."""
        assert DeclarativeBase in Base.__mro__

    def test_base_registry_exists(self) -> None:
        """Base must have a registry for ORM model tracking."""
        assert hasattr(Base, "registry")


class TestGetAsyncEngine:
    """Async engine factory must produce correctly configured engines."""

    @patch("tests.integration._compat.control_db.base.create_async_engine")
    def test_returns_async_engine(self, mock_create: MagicMock) -> None:
        """get_async_engine should call create_async_engine and return result."""
        mock_engine = MagicMock(spec=AsyncEngine)
        mock_create.return_value = mock_engine

        result = get_async_engine("postgresql+asyncpg://test:test@localhost/test")

        assert result is mock_engine
        mock_create.assert_called_once_with(
            "postgresql+asyncpg://test:test@localhost/test",
            echo=False,
            pool_size=5,
            max_overflow=10,
        )

    @patch("tests.integration._compat.control_db.base.create_async_engine")
    def test_echo_flag_forwarded(self, mock_create: MagicMock) -> None:
        """echo parameter must be forwarded to create_async_engine."""
        mock_create.return_value = MagicMock(spec=AsyncEngine)

        get_async_engine("postgresql+asyncpg://test:test@localhost/test", echo=True)

        mock_create.assert_called_once_with(
            "postgresql+asyncpg://test:test@localhost/test",
            echo=True,
            pool_size=5,
            max_overflow=10,
        )


class TestGetAsyncSessionFactory:
    """Async session factory must produce async_sessionmaker instances."""

    @patch("tests.integration._compat.control_db.base.async_sessionmaker")
    def test_returns_session_factory(self, mock_sm: MagicMock) -> None:
        """get_async_session_factory should return an async_sessionmaker."""
        mock_engine = MagicMock(spec=AsyncEngine)
        mock_factory = MagicMock()
        mock_sm.return_value = mock_factory

        result = get_async_session_factory(mock_engine)

        assert result is mock_factory
        mock_sm.assert_called_once_with(
            mock_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )


class TestGetSyncEngine:
    """Sync engine factory for Alembic migrations."""

    @patch("tests.integration._compat.control_db.base.create_engine")
    def test_returns_sync_engine(self, mock_create: MagicMock) -> None:
        """get_sync_engine should call create_engine and return result."""
        mock_engine = MagicMock(spec=Engine)
        mock_create.return_value = mock_engine

        result = get_sync_engine("postgresql+psycopg://test:test@localhost/test")

        assert result is mock_engine
        mock_create.assert_called_once_with(
            "postgresql+psycopg://test:test@localhost/test",
            echo=False,
        )

    @patch("tests.integration._compat.control_db.base.create_engine")
    def test_echo_flag_forwarded(self, mock_create: MagicMock) -> None:
        """echo parameter must be forwarded to create_engine."""
        mock_create.return_value = MagicMock(spec=Engine)

        get_sync_engine("postgresql+psycopg://test:test@localhost/test", echo=True)

        mock_create.assert_called_once_with(
            "postgresql+psycopg://test:test@localhost/test",
            echo=True,
        )
