"""Release workflow guardrail tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def _workflow(name: str) -> dict[str, Any]:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _step_names(workflow_name: str) -> list[str]:
    workflow = _workflow(workflow_name)
    job = next(iter(workflow["jobs"].values()))
    return [step.get("name", "") for step in job["steps"]]


def test_ci_workflow_declares_read_only_default_permissions() -> None:
    workflow = _workflow("ci.yml")

    assert workflow["permissions"] == {"contents": "read"}


def test_publish_workflow_uses_trusted_publishing_minimum_permissions() -> None:
    workflow = _workflow("publish.yml")
    permissions = workflow["jobs"]["publish"]["permissions"]

    assert permissions == {"id-token": "write", "contents": "read"}


def test_testpypi_workflow_uses_trusted_publishing_minimum_permissions() -> None:
    workflow = _workflow("publish-testpypi.yml")
    permissions = workflow["jobs"]["publish-testpypi"]["permissions"]

    assert permissions == {"id-token": "write", "contents": "read"}


def test_publish_workflow_validates_tag_ancestry_and_full_ci_parity() -> None:
    text = (WORKFLOWS / "publish.yml").read_text(encoding="utf-8")

    assert "fetch-depth: 0" in text
    assert 'git merge-base --is-ancestor "${GITHUB_SHA}" origin/master' in text
    assert 'uv run pytest tests/ -m "not integration" --cov=ces --cov-fail-under=90' in text
    assert "Run full release test suite before publishing" in _step_names("publish.yml")


def test_testpypi_workflow_validates_master_ancestry_and_full_ci_parity() -> None:
    text = (WORKFLOWS / "publish-testpypi.yml").read_text(encoding="utf-8")

    assert "fetch-depth: 0" in text
    assert 'git merge-base --is-ancestor "${GITHUB_SHA}" origin/master' in text
    assert 'uv run pytest tests/ -m "not integration" --cov=ces --cov-fail-under=90' in text
    assert "Run full release test suite before TestPyPI publishing" in _step_names("publish-testpypi.yml")


def test_distribution_build_steps_clean_and_assert_exact_artifact_set() -> None:
    for workflow_name in ("ci.yml", "publish.yml", "publish-testpypi.yml"):
        text = (WORKFLOWS / workflow_name).read_text(encoding="utf-8")
        assert "Remove stale distributions" in text
        assert "rm -rf dist" in text
        assert "Assert distribution artifact set" in text
        assert "controlled_execution_system-${project_version}-py3-none-any.whl" in text
        assert "controlled_execution_system-${project_version}.tar.gz" in text
        assert "find dist -maxdepth 1 -type f ! -name .gitignore | wc -l" in text


def test_publish_workflows_upload_checked_distribution_artifacts() -> None:
    publish = (WORKFLOWS / "publish.yml").read_text(encoding="utf-8")
    testpypi = (WORKFLOWS / "publish-testpypi.yml").read_text(encoding="utf-8")

    assert "actions/upload-artifact@v7" in publish
    assert "actions/upload-artifact@v4" not in publish
    assert "controlled-execution-system-${{ github.ref_name }}-dist" in publish
    assert "actions/upload-artifact@v7" in testpypi
    assert "actions/upload-artifact@v4" not in testpypi
    assert "controlled-execution-system-${{ inputs.package-version }}-testpypi-dist" in testpypi


def test_generated_github_ci_template_uses_node24_action_majors() -> None:
    template = (ROOT / "src" / "ces" / "cli" / "templates" / "ci" / "github.yml").read_text(encoding="utf-8")

    assert "actions/checkout@v6" in template
    assert "actions/setup-python@v6" in template
    assert "astral-sh/setup-uv@v7" in template
    assert "actions/upload-artifact@v7" in template
    assert "actions/upload-artifact@v4" not in template


def test_release_runbook_uses_pip_for_published_index_smoke_tests() -> None:
    release_doc = (ROOT / "docs" / "RELEASE.md").read_text(encoding="utf-8")

    smoke_python = "/tmp/ces-testpypi-smoke/bin/python"  # noqa: S108 - docs contract only
    assert f"{smoke_python} -m pip install --no-cache-dir" in release_doc
    assert "--index-url https://test.pypi.org/simple/" in release_doc
    assert "--extra-index-url https://pypi.org/simple/" in release_doc
    assert "uv pip install" not in release_doc
    assert "uv's resolver can report false `No matching distribution`" in release_doc
