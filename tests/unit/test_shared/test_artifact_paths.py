"""Tests for shared project artifact path validation."""

from __future__ import annotations

from pathlib import Path


def test_project_artifact_exists_accepts_real_project_local_file(tmp_path: Path) -> None:
    from ces.shared.artifact_paths import project_artifact_exists, resolve_project_artifact_path

    report_path = tmp_path / ".ces" / "artifacts" / "coverage.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("{}\n", encoding="utf-8")

    assert project_artifact_exists(tmp_path, ".ces/artifacts/coverage.json") is True
    assert resolve_project_artifact_path(tmp_path, ".ces/artifacts/coverage.json") == report_path.resolve()


def test_project_artifact_exists_rejects_absolute_traversal_and_windows_paths(tmp_path: Path) -> None:
    from ces.shared.artifact_paths import project_artifact_exists, resolve_project_artifact_path

    outside_path = tmp_path.parent / "outside-report.json"
    outside_path.write_text("{}\n", encoding="utf-8")

    invalid_paths = (
        str(outside_path),
        "../outside-report.json",
        "./outside-report.json",
        "reports/./coverage.json",
        "reports//coverage.json",
        "reports/.",
        r"reports\\..\\outside-report.json",
        r"C:\\Temp\\coverage.json",
        "C:/Temp/coverage.json",
        "C:Temp/coverage.json",
    )

    for artifact_path in invalid_paths:
        assert project_artifact_exists(tmp_path, artifact_path) is False
        assert resolve_project_artifact_path(tmp_path, artifact_path) is None


def test_project_artifact_exists_rejects_symlink_escapes(tmp_path: Path) -> None:
    from ces.shared.artifact_paths import project_artifact_exists, resolve_project_artifact_path

    outside_path = tmp_path.parent / "outside-report.json"
    outside_path.write_text("{}\n", encoding="utf-8")
    symlink_path = tmp_path / "coverage.json"
    symlink_path.symlink_to(outside_path)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    nested_symlink = tmp_path / "linked-reports"
    nested_symlink.symlink_to(reports_dir, target_is_directory=True)
    (reports_dir / "coverage.json").write_text("{}\n", encoding="utf-8")

    assert project_artifact_exists(tmp_path, "coverage.json") is False
    assert resolve_project_artifact_path(tmp_path, "coverage.json") is None
    assert project_artifact_exists(tmp_path, "linked-reports/coverage.json") is False
    assert resolve_project_artifact_path(tmp_path, "linked-reports/coverage.json") is None
