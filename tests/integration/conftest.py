"""Integration test fixtures for local-first CES flows."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


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
