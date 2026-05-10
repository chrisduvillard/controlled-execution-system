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


def test_ci_smokes_installed_wheel_public_contract() -> None:
    """CI should catch broken entrypoints and machine-readable JSON before release."""
    workflow_text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "Smoke built wheel public CLI contract" in workflow_text
    assert 'uv pip install --python "$smoke_venv/bin/python" "$wheel_path"' in workflow_text
    assert '"$smoke_venv/bin/ces" --help' in workflow_text
    assert '"$smoke_venv/bin/ces" --version' in workflow_text
    assert 'ces" --json doctor --project-root "$smoke_dir"' in workflow_text
    assert 'ces" --json scan --root "$smoke_dir"' in workflow_text
    assert 'scan_payload["modules"]' in workflow_text
    assert '"$smoke_venv/bin/ces" baseline' in workflow_text
    assert '"$smoke_venv/bin/ces" setup-ci --provider github' in workflow_text
    assert 'ces" --json scan --project-root "$smoke_dir"' in workflow_text
    assert 'payload["error"]["type"] == "usage_error"' in workflow_text
    assert 'ces" --json audit --limit nope' in workflow_text
    assert 'payload["error"]["type"] == "user_error"' in workflow_text


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


def test_publish_workflow_validates_tag_version_and_runs_real_installed_init_smoke() -> None:
    workflow_text = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")

    assert "Validate tag and package version agreement" in workflow_text
    assert 'test "$tag_name" = "v${project_version}"' in workflow_text
    assert 'grep -q "^## \\[${project_version}\\]" CHANGELOG.md' in workflow_text
    assert '"$smoke_venv/bin/ces" init publish-smoke' in workflow_text
    assert '"$smoke_venv/bin/ces" --version' in workflow_text
    assert "test -f .ces/config.yaml" in workflow_text
    assert 'ces" doctor --security' in workflow_text
    assert 'ces" --json doctor --project-root "$smoke_dir"' in workflow_text
    assert 'ces" --json scan --root "$smoke_dir"' in workflow_text
    assert 'scan_payload["modules"]' in workflow_text
    assert '"$smoke_venv/bin/ces" baseline' in workflow_text
    assert '"$smoke_venv/bin/ces" setup-ci --provider github' in workflow_text
    assert 'ces" --json scan --project-root "$smoke_dir"' in workflow_text
    assert 'payload["error"]["type"] == "usage_error"' in workflow_text
    assert 'ces" --json audit --limit nope' in workflow_text
    assert 'payload["error"]["type"] == "user_error"' in workflow_text
    assert "codex-cli publish-smoke" in workflow_text


def test_testpypi_workflow_is_manual_and_uses_test_repository() -> None:
    workflow_text = (ROOT / ".github" / "workflows" / "publish-testpypi.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch" in workflow_text
    assert "package-version" in workflow_text
    assert "environment: testpypi" in workflow_text
    assert "repository-url: https://test.pypi.org/legacy/" in workflow_text
    assert "Validate requested version and package metadata agreement" in workflow_text
    assert 'test "${{ inputs.package-version }}" = "$project_version"' in workflow_text


def test_testpypi_workflow_runs_release_smoke_before_upload() -> None:
    workflow_text = (ROOT / ".github" / "workflows" / "publish-testpypi.yml").read_text(encoding="utf-8")

    assert "Run builder-first smoke tests" in workflow_text
    assert "tests/integration/test_freshcart_e2e.py" in workflow_text
    assert "Smoke test installed CLI" in workflow_text
    assert 'ces" --json doctor --project-root "$smoke_dir"' in workflow_text
    assert 'ces" --json scan --root "$smoke_dir"' in workflow_text
    assert workflow_text.index("Smoke test installed CLI") < workflow_text.index("- name: Publish to TestPyPI")
