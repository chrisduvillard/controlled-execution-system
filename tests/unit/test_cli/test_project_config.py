"""Tests for typed `.ces/config.yaml` loading."""

from __future__ import annotations

from pathlib import Path

from ces.cli._context import get_project_config
from ces.cli._project_config import ProjectConfig, load_project_config_dict


def test_load_project_config_dict_validates_through_typed_model(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """project_id: proj-local
project_name: Local Project
preferred_runtime: codex
execution_mode: local
version: 0.1.0
created_at: '2026-01-01T00:00:00+00:00'
""",
        encoding="utf-8",
    )

    config = load_project_config_dict(config_path)

    assert config == {
        "project_id": "proj-local",
        "project_name": "Local Project",
        "preferred_runtime": "codex",
        "execution_mode": "local",
        "version": "0.1.0",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    assert ProjectConfig.from_mapping(config).execution_mode == "local"


def test_get_project_config_preserves_server_mode_for_rejection(ces_project: Path) -> None:
    (ces_project / ".ces" / "config.yaml").write_text(
        "project_id: proj-local\nexecution_mode: server\n",
        encoding="utf-8",
    )

    assert get_project_config(start=ces_project)["execution_mode"] == "server"
