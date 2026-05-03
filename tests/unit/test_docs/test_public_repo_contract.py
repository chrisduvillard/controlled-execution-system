"""Public repository contract checks for GitHub and release docs."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_readme_uses_local_first_contract_and_avoids_stale_numeric_badges() -> None:
    """README should describe the local public contract and avoid frozen counts."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "local runtime execution" in readme.lower() or "supported local runtime" in readme.lower()
    assert "Authorization: Bearer" not in readme
    assert "X-API-Key" not in readme
    assert "tests-3087" not in readme
    assert "coverage-91%25" not in readme
    assert "ces:completion" in readme
    assert "workspace delta" in readme.lower()


def test_security_docs_distinguish_codex_and_claude_runtime_boundaries() -> None:
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")

    assert "Claude runs with `--allowedTools`" in security
    assert "Codex runs under `--sandbox danger-full-access`" in security
    assert "not manifest-tool-allowlist-enforced" in security


def test_production_deployment_guide_uses_real_package_name() -> None:
    """Deployment docs should install the published package by its actual name."""
    guide = (ROOT / "docs" / "Production_Deployment_Guide.md").read_text(encoding="utf-8")

    assert "uv tool install controlled-execution-system" in guide
    assert "uv tool install ces" not in guide


def test_publish_workflow_keeps_strict_tests_and_cli_smoke() -> None:
    """Release publishing must keep warning-strict tests and wheel smoke coverage."""
    workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")

    assert "uv run pytest tests/unit/ -q -W error" in workflow
    assert "uv tool run --from" in workflow
    assert "ces --help" in workflow


def test_github_community_files_exist_for_public_repo() -> None:
    """Public GitHub repos need issue intake, PR guidance, and ownership metadata."""
    assert (ROOT / ".github" / "CODEOWNERS").is_file()
    assert (ROOT / ".github" / "pull_request_template.md").is_file()

    issue_templates = list((ROOT / ".github" / "ISSUE_TEMPLATE").glob("*"))
    assert issue_templates, "Expected at least one issue template"


def test_readme_documents_repo_self_dogfooding() -> None:
    """Public docs should explain how to bootstrap CES on the CES repo itself."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "ces dogfood" in readme
    assert ".ces/" in readme


def test_readme_pinned_install_example_matches_project_version() -> None:
    """README should not point users at an older pinned package release."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert f"controlled-execution-system=={project['version']}" in readme


def test_quickstart_treats_pypi_as_published() -> None:
    quickstart = (ROOT / "docs" / "Quickstart.md").read_text(encoding="utf-8")

    assert "once published" not in quickstart
    assert "uv tool install controlled-execution-system" in quickstart


def test_troubleshooting_uses_current_coverage_floor_and_runtime_guidance() -> None:
    troubleshooting = (ROOT / "docs" / "Troubleshooting.md").read_text(encoding="utf-8")

    assert "coverage below 90%" in troubleshooting
    assert "--cov-fail-under=90" in troubleshooting
    assert "install and authenticate `codex` so it is on `PATH`" in troubleshooting
    assert "Set `CODEX_HOME`" not in troubleshooting


def test_getting_started_links_existing_prd_target() -> None:
    getting_started = (ROOT / "docs" / "Getting_Started.md").read_text(encoding="utf-8")

    assert "(historical/PRD.md)" in getting_started
    assert (ROOT / "docs" / "historical" / "PRD.md").is_file()
