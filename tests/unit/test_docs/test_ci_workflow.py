"""Verification for the CI workflow contract."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_ci_installs_explicit_local_ci_dependency_group() -> None:
    """CI should opt into the full local gate dependency group explicitly."""
    workflow_text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "uv sync --frozen --group ci" in workflow_text


def test_ci_pytest_step_treats_warnings_as_errors() -> None:
    """CI must fail on warnings so local strict verification matches automation."""
    repo_root = Path(__file__).resolve().parents[3]
    workflow_text = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    # Invariant for this test: CI must invoke pytest with -W error and with a
    # coverage gate. The gate value itself legitimately changes over the
    # lifecycle of the project, so don't couple the assertion to a specific
    # number here.
    assert "uv run pytest tests/" in workflow_text, "ci.yml must invoke pytest"
    assert "-W error" in workflow_text, "ci.yml must promote warnings to errors (-W error)"
    assert "--cov=ces" in workflow_text, "ci.yml must measure coverage of the ces package"
    assert "--cov-fail-under=" in workflow_text, "ci.yml must enforce a coverage gate"


def test_ci_builds_distribution_and_checks_package_metadata() -> None:
    """CI must verify the built distribution metadata before publication."""
    repo_root = Path(__file__).resolve().parents[3]
    workflow_text = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "uv build" in workflow_text
    assert "uvx twine check dist/*" in workflow_text


def test_ci_dependency_audit_exports_dependencies_without_editable_project() -> None:
    """Version-bump commits should audit dependencies before the new package exists on PyPI."""
    repo_root = Path(__file__).resolve().parents[3]
    workflow_text = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "uv export --frozen --group ci --format requirements-txt" in workflow_text
    assert "--no-emit-project" in workflow_text
    assert "uv run pip-audit --strict -r /tmp/ces-ci-requirements.txt" in workflow_text


def test_publish_workflow_runs_builder_first_smoke_before_pypi_publish() -> None:
    """PyPI publishing must gate on the documented builder-first smoke flow."""
    repo_root = Path(__file__).resolve().parents[3]
    workflow_text = (repo_root / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")

    assert "Run builder-first smoke tests" in workflow_text
    assert "tests/integration/test_freshcart_e2e.py" in workflow_text
    assert workflow_text.index("Run builder-first smoke tests") < workflow_text.index("- name: Publish to PyPI")
