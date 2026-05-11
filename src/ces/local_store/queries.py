"""Project-scoped SELECT helpers for the local SQLite store."""

from __future__ import annotations

import sqlite3
from typing import Any


def fetch_builder_brief(conn: sqlite3.Connection, project_id: str, brief_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM builder_briefs WHERE brief_id = ? AND project_id = ?",
        (brief_id, project_id),
    ).fetchone()


def fetch_latest_builder_brief(conn: sqlite3.Connection, project_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM builder_briefs WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    ).fetchone()


def fetch_builder_session(conn: sqlite3.Connection, project_id: str, session_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM builder_sessions WHERE session_id = ? AND project_id = ?",
        (session_id, project_id),
    ).fetchone()


def fetch_latest_builder_session(conn: sqlite3.Connection, project_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM builder_sessions WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    ).fetchone()


def fetch_manifest(conn: sqlite3.Connection, project_id: str, manifest_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM manifests WHERE manifest_id = ? AND project_id = ?",
        (manifest_id, project_id),
    ).fetchone()


def fetch_active_manifests(conn: sqlite3.Connection, project_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT * FROM manifests
        WHERE project_id = ?
          AND workflow_state NOT IN ('merged', 'deployed', 'expired', 'rejected')
        ORDER BY created_at DESC
        """,
        (project_id,),
    ).fetchall()


def fetch_all_manifests(conn: sqlite3.Connection, project_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM manifests WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,),
    ).fetchall()


def fetch_runtime_execution(conn: sqlite3.Connection, project_id: str, manifest_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM runtime_executions WHERE manifest_id = ? AND project_id = ?",
        (manifest_id, project_id),
    ).fetchone()


def fetch_evidence_by_manifest(conn: sqlite3.Connection, project_id: str, manifest_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM evidence_packets WHERE manifest_id = ? AND project_id = ?",
        (manifest_id, project_id),
    ).fetchone()


def fetch_evidence_by_packet(conn: sqlite3.Connection, project_id: str, packet_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM evidence_packets WHERE packet_id = ? AND project_id = ?",
        (packet_id, project_id),
    ).fetchone()


def fetch_latest_evidence_packet(conn: sqlite3.Connection, project_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM evidence_packets WHERE project_id = ? ORDER BY created_at DESC, packet_id DESC LIMIT 1",
        (project_id,),
    ).fetchone()


def fetch_approval(conn: sqlite3.Connection, project_id: str, manifest_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM approvals WHERE manifest_id = ? AND project_id = ?",
        (manifest_id, project_id),
    ).fetchone()


def fetch_pending_legacy_behaviors(conn: sqlite3.Connection, project_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT * FROM legacy_behaviors
        WHERE project_id = ? AND disposition IS NULL AND discarded = 0
        ORDER BY created_at DESC
        """,
        (project_id,),
    ).fetchall()


def fetch_legacy_behaviors_by_system(conn: sqlite3.Connection, project_id: str, system: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT * FROM legacy_behaviors
        WHERE system = ? AND project_id = ?
        ORDER BY created_at DESC
        """,
        (system, project_id),
    ).fetchall()


def fetch_legacy_behavior(conn: sqlite3.Connection, project_id: str, entry_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM legacy_behaviors WHERE entry_id = ? AND project_id = ?",
        (entry_id, project_id),
    ).fetchone()


def fetch_promoted_prl_items(conn: sqlite3.Connection, project_id: str, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT content FROM prl_items
        WHERE project_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (project_id, limit),
    ).fetchall()


def fetch_audit(conn: sqlite3.Connection, query: str, params: tuple[Any, ...]) -> list[sqlite3.Row]:
    return conn.execute(query, params).fetchall()
