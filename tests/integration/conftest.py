"""Integration test fixtures for CES compatibility tests.

Most CES integration coverage is local-first. This fixture module supports the
smaller compatibility subset that still exercises PostgreSQL-backed repository
and migration paths with testcontainers.

On Windows with Docker Desktop, set DOCKER_HOST=npipe:////./pipe/docker_engine
if the Docker daemon is not auto-detected.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator, Generator

import pytest
import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from testcontainers.postgres import PostgresContainer


def _ensure_windows_docker_desktop_env() -> None:
    """Make Docker Desktop discoverable for Windows integration test runs."""
    if sys.platform != "win32":
        return

    docker_bin = Path(r"C:\Program Files\Docker\Docker\resources\bin")
    if docker_bin.exists():
        path_entries = os.environ.get("PATH", "").split(os.pathsep)
        docker_bin_str = str(docker_bin)
        if docker_bin_str not in path_entries:
            os.environ["PATH"] = os.pathsep.join([docker_bin_str, *path_entries])

    os.environ.setdefault("DOCKER_HOST", "npipe:////./pipe/docker_engine")


_ensure_windows_docker_desktop_env()


def _wait_for_postgres(db_url: str, attempts: int = 20, delay_seconds: float = 1.0) -> None:
    """Wait for the testcontainer PostgreSQL instance to accept connections."""
    last_error: OperationalError | None = None

    for _ in range(attempts):
        engine = create_engine(db_url)
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except OperationalError as exc:
            last_error = exc
            time.sleep(delay_seconds)
        finally:
            engine.dispose()

    if last_error is not None:
        raise last_error


@pytest.fixture()
def ces_project(tmp_path: Path) -> Path:
    """Return a tmp_path project root bootstrapped for local CES.

    Writes the current local-first `.ces/config.yaml` shape so
    ``get_services()`` resolves to the SQLite LocalProjectStore branch. The
    ``state.db`` file is created on first ManifestManager save.
    """
    ces_dir = tmp_path / ".ces"
    ces_dir.mkdir()
    config = {
        "project_name": "spec-e2e",
        "project_id": "proj-spec-e2e",
        "preferred_runtime": None,
    }
    with open(ces_dir / "config.yaml", "w") as f:
        yaml.safe_dump(config, f)
    return tmp_path


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    """Spin up PostgreSQL 17 container for integration tests."""
    postgres_module = pytest.importorskip("testcontainers.postgres")
    with postgres_module.PostgresContainer("postgres:17") as pg:
        yield pg


@pytest.fixture(scope="session")
def db_url(postgres_container: PostgresContainer) -> str:
    """Sync database URL using psycopg driver."""
    url = postgres_container.get_connection_url()
    # testcontainers may return psycopg2 driver; replace with psycopg
    return url.replace("psycopg2", "psycopg").replace("postgresql://", "postgresql+psycopg://")


@pytest.fixture(scope="session")
def async_db_url(postgres_container: PostgresContainer) -> str:
    """Async database URL using asyncpg driver."""
    url = postgres_container.get_connection_url()
    return (
        url.replace("psycopg2", "asyncpg")
        .replace("postgresql://", "postgresql+asyncpg://")
        .replace("postgresql+psycopg://", "postgresql+asyncpg://")
    )


@pytest.fixture(scope="session")
def _run_migrations(db_url: str) -> Generator[None, None, None]:
    """Run Alembic migrations against the test database.

    Creates schemas and all tables. Runs once per test session.
    Cleans up CES_DATABASE_SYNC_URL env var after migrations to prevent
    leakage into unit tests (T-10-01).
    """
    from alembic import command
    from alembic.config import Config

    _wait_for_postgres(db_url)

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    # Import env.py needs the URL override
    import os

    os.environ["CES_DATABASE_SYNC_URL"] = db_url
    try:
        command.upgrade(alembic_cfg, "head")
        yield
    finally:
        # Clean up env var to prevent leakage into unit tests (T-10-01)
        os.environ.pop("CES_DATABASE_SYNC_URL", None)


@pytest.fixture(scope="session")
def sync_engine(db_url: str, _run_migrations: None):  # type: ignore[no-untyped-def]
    """Create a sync SQLAlchemy engine for direct SQL testing."""
    engine = create_engine(db_url)
    yield engine
    engine.dispose()


@pytest.fixture()
async def async_session(async_db_url: str, _run_migrations: None) -> AsyncGenerator[AsyncSession, None]:
    """Create an async session for repository testing.

    Each test gets its own session that is rolled back after the test
    to maintain test isolation.
    """
    engine = create_async_engine(async_db_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()
