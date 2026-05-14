"""Tests for workspace before/after delta capture."""

from __future__ import annotations

from ces.execution.workspace_delta import WorkspaceSnapshot


def test_workspace_delta_reports_only_files_changed_after_snapshot(tmp_path) -> None:
    preexisting = tmp_path / "preexisting.py"
    preexisting.write_text("before\n", encoding="utf-8")
    snapshot = WorkspaceSnapshot.capture(tmp_path)

    preexisting.write_text("after\n", encoding="utf-8")
    (tmp_path / "created.py").write_text("new\n", encoding="utf-8")

    delta = snapshot.diff(WorkspaceSnapshot.capture(tmp_path))

    assert delta.modified_files == ("preexisting.py",)
    assert delta.created_files == ("created.py",)
    assert delta.deleted_files == ()


def test_workspace_delta_tracks_ces_governance_files_but_ignores_runtime_outputs(tmp_path) -> None:
    snapshot = WorkspaceSnapshot.capture(tmp_path)
    (tmp_path / ".ces" / "state.db").parent.mkdir()
    (tmp_path / ".ces" / "state.db").write_text("state", encoding="utf-8")
    (tmp_path / ".ces" / "runtime-transcripts").mkdir()
    (tmp_path / ".ces" / "runtime-transcripts" / "run.jsonl").write_text("transcript", encoding="utf-8")
    (tmp_path / ".ces" / "state.db-shm").write_text("sqlite shared memory", encoding="utf-8")
    (tmp_path / ".git" / "index").parent.mkdir()
    (tmp_path / ".git" / "index").write_text("git", encoding="utf-8")

    delta = snapshot.diff(WorkspaceSnapshot.capture(tmp_path))

    assert delta.created_files == (".ces/state.db",)
