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


def test_workspace_snapshot_skips_symlinks_to_outside_files(tmp_path) -> None:
    """Workspace deltas should not hash files that escape the project via symlink."""
    outside = tmp_path / "outside.txt"
    outside.write_text("outside secret-ish content\n", encoding="utf-8")
    (tmp_path / "inside.txt").write_text("inside\n", encoding="utf-8")
    (tmp_path / "linked-outside.txt").symlink_to(outside)

    snapshot = WorkspaceSnapshot.capture(tmp_path)

    assert "inside.txt" in snapshot.files
    assert "linked-outside.txt" not in snapshot.files


def test_workspace_snapshot_ignores_broken_symlink(tmp_path) -> None:
    """Broken symlinks in messy brownfield repos should not crash snapshotting."""
    (tmp_path / "broken.txt").symlink_to(tmp_path / "missing.txt")

    snapshot = WorkspaceSnapshot.capture(tmp_path)

    assert snapshot.files == {}
