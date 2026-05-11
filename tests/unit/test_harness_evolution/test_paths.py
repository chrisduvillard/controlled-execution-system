"""Tests for deterministic harness substrate paths."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ces.harness_evolution.paths import HarnessPaths, create_harness_layout, expected_layout


def test_expected_layout_is_under_local_ces_harness(tmp_path: Path) -> None:
    paths = HarnessPaths.for_project(tmp_path)

    assert paths.root == tmp_path / ".ces" / "harness"
    assert paths.index == paths.root / "index.json"
    assert all(path.is_relative_to(paths.root) for path in expected_layout(tmp_path))


def test_create_harness_layout_creates_expected_dirs_and_index_only(tmp_path: Path) -> None:
    paths = create_harness_layout(tmp_path)

    expected_dirs = {
        "prompts",
        "tool_descriptions",
        "tool_policies",
        "middleware",
        "skills",
        "subagents",
        "memory",
        "runtime_profiles",
        "change_manifests",
        "analysis",
        "verdicts",
    }
    assert {path.name for path in paths.component_dirs} == expected_dirs
    assert paths.index.is_file()
    for directory in paths.component_dirs:
        assert directory.is_dir()
    data = json.loads(paths.index.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["schema"] == "ces.harness.index.v1"


def test_create_harness_layout_rejects_ces_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".ces").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        create_harness_layout(tmp_path)

    assert not (outside / "harness").exists()


def test_create_harness_layout_rejects_harness_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    ces_dir = tmp_path / ".ces"
    ces_dir.mkdir()
    (ces_dir / "harness").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        create_harness_layout(tmp_path)

    assert not (outside / "index.json").exists()


def test_create_harness_layout_rejects_component_symlink_escape(tmp_path: Path) -> None:
    paths = HarnessPaths.for_project(tmp_path)
    paths.root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    paths.change_manifests.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        create_harness_layout(tmp_path)

    assert not (outside / "hchg-any.json").exists()
