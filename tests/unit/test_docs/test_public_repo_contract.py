"""Public repository contract checks for GitHub and release docs."""

from __future__ import annotations

import shutil
import subprocess
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


def test_hermes_local_state_is_ignored_and_not_tracked() -> None:
    """Hermes agent scratch state should never become part of the public repo contract."""
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert ".hermes/" in gitignore

    git = shutil.which("git")
    assert git is not None
    tracked = subprocess.check_output(  # noqa: S603 - fixed git executable and literal args only
        [git, "ls-files", ".hermes", ".hermes/**"],
        cwd=ROOT,
        text=True,
    ).splitlines()
    assert tracked == []


def test_secret_docs_use_file_backed_audit_hmac_as_local_default() -> None:
    """Public secret docs should not tell local operators to use env-first dev defaults."""
    production = (ROOT / "docs" / "Production_Deployment_Guide.md").read_text(encoding="utf-8")
    secrets = (ROOT / "docs" / "Secrets_Management.md").read_text(encoding="utf-8")
    combined = f"{production}\n{secrets}"

    assert ".ces/keys/audit.hmac" in production
    assert ".ces/keys/audit.hmac" in secrets
    assert "ces init" in secrets
    assert "CES_AUDIT_HMAC_SECRET` | Optional override" in production
    assert "managed/CI environments" in secrets
    assert "will not overwrite an existing `.ces/` directory" in secrets
    assert "dev default" not in combined.lower()
    assert "export CES_AUDIT_HMAC_SECRET=<unique-local-value>" not in secrets


def test_getting_started_gate_reference_includes_required_scope_argument() -> None:
    """Getting Started command table should match the shipped Typer gate signature."""
    getting_started = (ROOT / "docs" / "Getting_Started.md").read_text(encoding="utf-8")

    assert "| `ces gate <phase> <scope>` | Evaluate phase gate |" in getting_started
    assert "| `ces gate <phase>` |" not in getting_started


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


def test_quickstart_distinguishes_preflight_from_runtime_auth_probe() -> None:
    quickstart = (ROOT / "docs" / "Quickstart.md").read_text(encoding="utf-8")

    assert "ces doctor --runtime-safety" in quickstart
    assert "ces doctor --verify-runtime --runtime all" in quickstart
    assert "may contact the runtime provider" in quickstart
    assert "Bare `ces doctor` is a preflight check" in quickstart


def test_install_docs_show_explicit_python_for_python_311_hosts() -> None:
    """Install docs should give operators a direct recovery path from Python 3.11 hosts."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    quickstart = (ROOT / "docs" / "Quickstart.md").read_text(encoding="utf-8")

    for doc in (readme, quickstart):
        assert "Python 3.11" in doc
        assert "uv tool install --python 3.13 controlled-execution-system" in doc
        assert "No matching distribution" in doc


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


def test_public_docs_surface_launch_trust_and_boundaries() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    quickstart = (ROOT / "docs" / "Quickstart.md").read_text(encoding="utf-8")

    assert "Why trust this release?" in readme
    assert "dogfood gauntlet" in readme
    assert "not a hosted control plane" in readme
    assert "not a substitute for the runtime's own credentials" in readme
    assert "Before you start" in quickstart
    assert "does not ship one" in quickstart
    assert "Keep `.ces/`" in quickstart
    assert "untracked unless you intentionally share" in quickstart


def test_project_version_surfaces_are_launch_consistent() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    init_py = (ROOT / "src" / "ces" / "__init__.py").read_text(encoding="utf-8")

    assert project["requires-python"] == ">=3.12,<3.14"
    assert f"controlled-execution-system=={project['version']}" in readme
    assert f"v{project['version']}" in readme
    assert f"## [{project['version']}]" in changelog
    assert f'__version__ = "{project["version"]}"' in init_py


def test_public_docs_do_not_overclaim_runtime_or_audit_boundaries() -> None:
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    getting_started = (ROOT / "docs" / "Getting_Started.md").read_text(encoding="utf-8")
    db_ops = (ROOT / "docs" / "Database_Operations.md").read_text(encoding="utf-8")

    assert "Codex runs under its disclosed local sandbox mode" in getting_started
    assert "rather than manifest tool allowlist enforcement" in getting_started
    assert "not as an operating-system process killer" in security
    assert "degraded_model_diversity" in security
    assert "public `ces audit --verify-integrity` command" in db_ops
    assert "ces audit --verify-integrity" not in db_ops.replace("public `ces audit --verify-integrity` command", "")


def test_freshcart_operating_model_example_is_archived_not_active_public_contract() -> None:
    active_stub = (ROOT / "docs" / "FreshCart_Worked_Example.md").read_text(encoding="utf-8")
    archived = ROOT / "docs" / "historical" / "FreshCart_Worked_Example.md"

    assert archived.is_file()
    assert "historical operating-model archive" in active_stub
    assert "not the current shipped CES product contract" in active_stub
    assert "not a sandbox" in active_stub
    assert "local control, evidence, review, and recovery layer" in active_stub
    assert "historical/FreshCart_Worked_Example.md" in active_stub

    active_stub_lower = active_stub.lower()
    for overclaim in (
        "Auto-merge",
        "Auto-deploy",
        "auto-merge",
        "auto-deploy",
        "auto-rollback",
        "canary observation",
        "Adversarial Review Triad",
        "Approval Triage Agent",
        "Deploy Controller",
        "deploy-controller",
        "Zero human intervention",
    ):
        assert overclaim not in active_stub
        assert overclaim.lower() not in active_stub_lower
