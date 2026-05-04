"""Tests for project type detection."""

from __future__ import annotations

import json
from pathlib import Path


def test_detects_python_cli_from_pyproject_scripts(tmp_path: Path) -> None:
    from ces.verification.project_detector import detect_project_type

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\n[project.scripts]\ndemo='demo.cli:app'\n",
        encoding="utf-8",
    )

    assert detect_project_type(tmp_path) == "python-cli"


def test_detects_python_package_from_pyproject_without_scripts(tmp_path: Path) -> None:
    from ces.verification.project_detector import detect_project_type

    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    assert detect_project_type(tmp_path) == "python-package"


def test_detects_vite_react_app(tmp_path: Path) -> None:
    from ces.verification.project_detector import detect_project_type

    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"@vitejs/plugin-react": "latest", "react": "latest"}}),
        encoding="utf-8",
    )

    assert detect_project_type(tmp_path) == "vite-react-app"
