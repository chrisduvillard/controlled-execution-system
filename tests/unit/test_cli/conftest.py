"""Shared fixtures for CLI tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def ces_project(tmp_path: Path) -> Path:
    """Create a temporary directory with a .ces/ marker directory."""
    ces_dir = tmp_path / ".ces"
    ces_dir.mkdir()
    return tmp_path


@pytest.fixture()
def non_ces_dir(tmp_path: Path) -> Path:
    """Return a temporary directory without a .ces/ marker."""
    return tmp_path


@pytest.fixture()
def nested_ces_project(ces_project: Path) -> Path:
    """Create a nested subdirectory inside a CES project."""
    subdir = ces_project / "src" / "app" / "deep"
    subdir.mkdir(parents=True)
    return subdir
