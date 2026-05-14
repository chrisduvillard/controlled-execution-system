"""Packaging contract tests for public PyPI artifacts."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_sdist_excludes_internal_workflow_and_test_material() -> None:
    pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    excludes = set(pyproject["tool"]["hatch"]["build"]["exclude"])

    assert "/.hermes" in excludes
    assert "/.hypothesis" in excludes
    assert "/.github" in excludes
    assert "/.gitleaks.toml" in excludes
    assert "/.mcp.json" in excludes
    assert "/examples/voice-to-text-mvp" in excludes
    assert "/examples/auralis" in excludes
    assert "/runtime-transcripts" in excludes
    assert "**/__pycache__" in excludes
    assert "**/*.pyc" in excludes
    assert "**/env.sh" in excludes
    assert "**/state.db" in excludes
    assert "/tests" in excludes
    assert "/scripts" in excludes
    assert "/docs/plans" in excludes


def test_every_integration_test_file_is_marked_integration() -> None:
    integration_files = sorted((_REPO_ROOT / "tests" / "integration").glob("test_*.py"))

    assert integration_files
    for path in integration_files:
        text = path.read_text(encoding="utf-8")
        assert "pytestmark = pytest.mark.integration" in text, (
            f"{path.relative_to(_REPO_ROOT)} must set pytestmark = pytest.mark.integration"
        )


def test_gitleaks_allowlist_regexes_compile() -> None:
    config = tomllib.loads((_REPO_ROOT / ".gitleaks.toml").read_text(encoding="utf-8"))

    for pattern in config["allowlist"]["regexes"]:
        re.compile(pattern)


def test_publish_workflow_runs_release_preflight_quality_gates() -> None:
    publish_workflow = (_REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")

    assert "uv sync --frozen --group ci" in publish_workflow
    assert "uv run ruff check src/ tests/" in publish_workflow
    assert "uv run ruff format --check src/ tests/" in publish_workflow
    assert "uv run mypy src/ces/ --ignore-missing-imports" in publish_workflow
    assert "uv run pip-audit --strict -r /tmp/ces-publish-requirements.txt" in publish_workflow


def test_public_version_surfaces_are_consistent() -> None:
    pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]

    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    lockfile = (_REPO_ROOT / "uv.lock").read_text(encoding="utf-8")

    assert version == "0.1.21"
    assert (_REPO_ROOT / "src" / "ces" / "__init__.py").read_text(encoding="utf-8").count(version) == 1
    assert f"controlled-execution-system=={version}" in readme
    assert f"v{version}" in readme
    assert f"## [{version}]" in (_REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f'name = "controlled-execution-system"\nversion = "{version}"' in lockfile
