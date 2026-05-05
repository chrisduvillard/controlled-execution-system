"""Packaging contract tests for public PyPI artifacts."""

from __future__ import annotations

import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_sdist_excludes_internal_workflow_and_test_material() -> None:
    pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    excludes = set(pyproject["tool"]["hatch"]["build"]["exclude"])

    assert "/.hermes" in excludes
    assert "/.github" in excludes
    assert "/.gitleaks.toml" in excludes
    assert "/.mcp.json" in excludes
    assert "/tests" in excludes
    assert "/scripts" in excludes
    assert "/docs/plans" in excludes


def test_public_version_surfaces_are_consistent() -> None:
    pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]

    assert version == "0.1.11"
    assert (_REPO_ROOT / "src" / "ces" / "__init__.py").read_text(encoding="utf-8").count(version) == 1
    assert f"controlled-execution-system=={version}" in (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert f"## [{version}]" in (_REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
