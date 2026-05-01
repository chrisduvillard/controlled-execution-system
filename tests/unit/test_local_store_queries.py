"""Focused tests for local-store SELECT helpers."""

from __future__ import annotations

from pathlib import Path

from ces.local_store import LocalProjectStore
from ces.local_store.queries import fetch_latest_builder_brief, fetch_manifest


def test_fetch_latest_builder_brief_is_project_scoped(tmp_path: Path) -> None:
    db_path = tmp_path / ".ces" / "state.db"
    store_a = LocalProjectStore(db_path, project_id="proj-a")
    store_b = LocalProjectStore(db_path, project_id="proj-b")
    store_a.save_builder_brief(
        request="Project A request",
        project_mode="greenfield",
        constraints=[],
        acceptance_criteria=[],
        must_not_break=[],
        open_questions={},
    )
    store_b.save_builder_brief(
        request="Project B request",
        project_mode="brownfield",
        constraints=[],
        acceptance_criteria=[],
        must_not_break=[],
        open_questions={},
    )

    with store_a._connect() as conn:
        row = fetch_latest_builder_brief(conn, "proj-a")

    assert row is not None
    assert row["request"] == "Project A request"
    store_a.close()
    store_b.close()


def test_fetch_manifest_filters_by_project(tmp_path: Path) -> None:
    db_path = tmp_path / ".ces" / "state.db"
    store_a = LocalProjectStore(db_path, project_id="proj-a")
    store_b = LocalProjectStore(db_path, project_id="proj-b")

    with store_a._connect() as conn:
        conn.execute(
            """
            INSERT INTO manifests(
                manifest_id, project_id, description, risk_tier,
                behavior_confidence, change_class, status, workflow_state,
                expires_at, created_at, updated_at, content
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "M-shared",
                "proj-a",
                "Project A",
                "B",
                "BC2",
                "class_2",
                "draft",
                "in_flight",
                "2026-01-01T01:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                "{}",
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO manifests(
                manifest_id, project_id, description, risk_tier,
                behavior_confidence, change_class, status, workflow_state,
                expires_at, created_at, updated_at, content
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "M-other",
                "proj-b",
                "Project B",
                "C",
                "BC1",
                "class_3",
                "draft",
                "in_flight",
                "2026-01-01T01:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                "{}",
            ),
        )

    with store_b._connect() as conn:
        assert fetch_manifest(conn, "proj-b", "M-shared") is None
        row = fetch_manifest(conn, "proj-b", "M-other")

    assert row is not None
    assert row["description"] == "Project B"
    store_a.close()
    store_b.close()
