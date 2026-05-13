"""Focused tests for local SQLite schema initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ces.local_store import LocalProjectStore
from ces.local_store.schema import CURRENT_SCHEMA_VERSION, initialize_schema


def test_initialize_schema_creates_schema_meta_with_current_version(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    with conn:
        initialize_schema(conn)

    row = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
    assert row is not None
    assert row["value"] == str(CURRENT_SCHEMA_VERSION)
    conn.close()


def test_local_project_store_initializes_schema_meta_for_new_databases(tmp_path: Path) -> None:
    store = LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj")

    with store._connect() as conn:
        row = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()

    assert row is not None
    assert row["value"] == str(CURRENT_SCHEMA_VERSION)
    store.close()


def test_initialize_schema_creates_harness_evolution_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    with conn:
        initialize_schema(conn)

    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'harness_change%'"
        ).fetchall()
    }
    assert tables == {"harness_changes", "harness_change_verdicts"}

    change_columns = {row["name"] for row in conn.execute("PRAGMA table_info(harness_changes)").fetchall()}
    assert {
        "change_id",
        "component_type",
        "title",
        "status",
        "manifest_json",
        "manifest_hash",
        "created_at",
        "updated_at",
    }.issubset(change_columns)

    verdict_columns = {row["name"] for row in conn.execute("PRAGMA table_info(harness_change_verdicts)").fetchall()}
    assert {"id", "change_id", "verdict", "verdict_json", "created_at"}.issubset(verdict_columns)
    conn.close()


def test_initialize_schema_is_idempotent_for_harness_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    with conn:
        initialize_schema(conn)
        initialize_schema(conn)

    assert conn.execute("SELECT COUNT(*) FROM harness_changes").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM harness_change_verdicts").fetchone()[0] == 0
    conn.close()
