"""SQLite schema setup and in-app migrations for local project state."""

from __future__ import annotations

import sqlite3

CURRENT_SCHEMA_VERSION = 1


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Create or migrate the local store schema in an open transaction."""
    _recover_interrupted_review_findings_migration(conn)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS project_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS manifests (
            manifest_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            description TEXT NOT NULL,
            risk_tier TEXT NOT NULL,
            behavior_confidence TEXT NOT NULL,
            change_class TEXT NOT NULL,
            status TEXT NOT NULL,
            workflow_state TEXT NOT NULL,
            content_hash TEXT,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            content TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_entries (
            entry_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            action_summary TEXT NOT NULL,
            decision TEXT NOT NULL,
            rationale TEXT NOT NULL,
            scope TEXT NOT NULL,
            metadata_extra TEXT,
            prev_hash TEXT NOT NULL,
            entry_hash TEXT
        );
        CREATE TRIGGER IF NOT EXISTS audit_entries_no_update
            BEFORE UPDATE ON audit_entries
            BEGIN
                SELECT RAISE(ABORT, 'audit_entries are append-only');
            END;
        CREATE TRIGGER IF NOT EXISTS audit_entries_no_delete
            BEFORE DELETE ON audit_entries
            BEGIN
                SELECT RAISE(ABORT, 'audit_entries are append-only');
            END;
        CREATE TABLE IF NOT EXISTS runtime_executions (
            manifest_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            runtime_name TEXT NOT NULL,
            runtime_version TEXT NOT NULL,
            reported_model TEXT,
            invocation_ref TEXT NOT NULL,
            exit_code INTEGER NOT NULL,
            stdout TEXT NOT NULL,
            stderr TEXT NOT NULL,
            duration_seconds REAL NOT NULL,
            transcript_path TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS evidence_packets (
            manifest_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            packet_id TEXT NOT NULL,
            summary TEXT NOT NULL,
            challenge TEXT NOT NULL,
            triage_color TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS approvals (
            manifest_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            rationale TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS builder_briefs (
            brief_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            request TEXT NOT NULL,
            project_mode TEXT NOT NULL,
            constraints TEXT NOT NULL,
            acceptance_criteria TEXT NOT NULL,
            must_not_break TEXT NOT NULL,
            open_questions TEXT NOT NULL,
            source_of_truth TEXT NOT NULL,
            critical_flows TEXT NOT NULL,
            manifest_id TEXT,
            evidence_packet_id TEXT,
            prl_draft_path TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS builder_sessions (
            session_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            brief_id TEXT,
            request TEXT NOT NULL,
            project_mode TEXT NOT NULL,
            stage TEXT NOT NULL,
            next_action TEXT NOT NULL,
            last_action TEXT NOT NULL,
            recovery_reason TEXT,
            last_error TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            manifest_id TEXT,
            runtime_manifest_id TEXT,
            evidence_packet_id TEXT,
            approval_manifest_id TEXT,
            source_of_truth TEXT NOT NULL,
            critical_flows TEXT NOT NULL,
            brownfield_review_state TEXT,
            brownfield_entry_ids TEXT,
            brownfield_reviewed_count INTEGER NOT NULL DEFAULT 0,
            brownfield_remaining_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS legacy_behaviors (
            entry_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            system TEXT NOT NULL,
            behavior_description TEXT NOT NULL,
            inferred_by TEXT NOT NULL,
            inferred_at TEXT NOT NULL,
            confidence REAL NOT NULL,
            disposition TEXT,
            reviewed_by TEXT,
            reviewed_at TEXT,
            promoted_to_prl_id TEXT,
            discarded INTEGER NOT NULL DEFAULT 0,
            source_manifest_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS prl_items (
            prl_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            statement TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS review_findings (
            id INTEGER PRIMARY KEY,
            finding_id TEXT NOT NULL,
            manifest_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            reviewer_role TEXT NOT NULL,
            severity TEXT NOT NULL,
            category TEXT NOT NULL,
            file_path TEXT,
            line_number INTEGER,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            recommendation TEXT NOT NULL,
            confidence REAL NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_review_findings_manifest
            ON review_findings (manifest_id);
        CREATE TABLE IF NOT EXISTS review_aggregates (
            manifest_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            critical_count INTEGER NOT NULL DEFAULT 0,
            high_count INTEGER NOT NULL DEFAULT 0,
            disagreements TEXT NOT NULL DEFAULT '[]',
            unanimous_zero_findings INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS harness_changes (
            change_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            component_type TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            manifest_json TEXT NOT NULL,
            manifest_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_harness_changes_project_status
            ON harness_changes (project_id, status, updated_at);
        CREATE TABLE IF NOT EXISTS harness_change_verdicts (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            change_id TEXT NOT NULL,
            verdict TEXT NOT NULL,
            verdict_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(change_id) REFERENCES harness_changes(change_id)
        );
        CREATE INDEX IF NOT EXISTS idx_harness_change_verdicts_change
            ON harness_change_verdicts (project_id, change_id, created_at);
        CREATE TABLE IF NOT EXISTS harness_memory_lessons (
            lesson_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            lesson_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (project_id, lesson_id)
        );
        CREATE INDEX IF NOT EXISTS idx_harness_memory_lessons_project_status
            ON harness_memory_lessons (project_id, status, updated_at);
        """
    )
    _migrate_review_findings_to_synthetic_pk(conn)
    _migrate_builder_sessions_brownfield_columns(conn)
    conn.execute(
        "INSERT OR IGNORE INTO schema_meta(key, value) VALUES('schema_version', ?)",
        (str(CURRENT_SCHEMA_VERSION),),
    )


def _recover_interrupted_review_findings_migration(conn: sqlite3.Connection) -> None:
    # Defensive recovery: if initialize() was interrupted mid-migration, a temp
    # review_findings_new table can strand. Reconcile based on which side of
    # the rename completed before running CREATE-IF-NOT-EXISTS.
    has_temp = bool(
        conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='review_findings_new'").fetchone()
    )
    if not has_temp:
        return
    has_main = bool(
        conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='review_findings'").fetchone()
    )
    if has_main:
        conn.execute("DROP TABLE review_findings_new")
    else:
        conn.execute("ALTER TABLE review_findings_new RENAME TO review_findings")


def _migrate_review_findings_to_synthetic_pk(conn: sqlite3.Connection) -> None:
    # review_findings should have a synthetic INTEGER PK, not a uniqueness
    # constraint on finding_id. Earlier schemas used finding_id alone or
    # (manifest_id, finding_id), which collided when reviewers reused labels.
    existing_columns = [row["name"] for row in conn.execute("PRAGMA table_info(review_findings)").fetchall()]
    if not existing_columns or "id" in existing_columns:
        return
    conn.execute(
        """
        CREATE TABLE review_findings_new (
            id INTEGER PRIMARY KEY,
            finding_id TEXT NOT NULL,
            manifest_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            reviewer_role TEXT NOT NULL,
            severity TEXT NOT NULL,
            category TEXT NOT NULL,
            file_path TEXT,
            line_number INTEGER,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            recommendation TEXT NOT NULL,
            confidence REAL NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO review_findings_new (
            finding_id, manifest_id, project_id, reviewer_role,
            severity, category, file_path, line_number, title,
            description, recommendation, confidence, created_at
        )
        SELECT
            finding_id, manifest_id, project_id, reviewer_role,
            severity, category, file_path, line_number, title,
            description, recommendation, confidence, created_at
        FROM review_findings
        """
    )
    conn.execute("DROP TABLE review_findings")
    conn.execute("ALTER TABLE review_findings_new RENAME TO review_findings")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_review_findings_manifest ON review_findings (manifest_id)")


def _migrate_builder_sessions_brownfield_columns(conn: sqlite3.Connection) -> None:
    builder_session_columns = {row["name"] for row in conn.execute("PRAGMA table_info(builder_sessions)").fetchall()}
    if "brownfield_review_state" not in builder_session_columns:
        conn.execute("ALTER TABLE builder_sessions ADD COLUMN brownfield_review_state TEXT")
    if "brownfield_entry_ids" not in builder_session_columns:
        conn.execute("ALTER TABLE builder_sessions ADD COLUMN brownfield_entry_ids TEXT")
    if "brownfield_reviewed_count" not in builder_session_columns:
        conn.execute("ALTER TABLE builder_sessions ADD COLUMN brownfield_reviewed_count INTEGER NOT NULL DEFAULT 0")
    if "brownfield_remaining_count" not in builder_session_columns:
        conn.execute("ALTER TABLE builder_sessions ADD COLUMN brownfield_remaining_count INTEGER NOT NULL DEFAULT 0")
