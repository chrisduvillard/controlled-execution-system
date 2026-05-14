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
