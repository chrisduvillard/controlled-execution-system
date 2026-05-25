"""Builder evidence boundary contracts."""

from __future__ import annotations

from types import SimpleNamespace

from ces.cli._builder_evidence import workspace_scope_violations
from ces.execution.workspace_delta import WorkspaceDelta


def test_workspace_scope_violations_ignore_ces_local_state() -> None:
    manifest = SimpleNamespace(affected_files=("src/app.py",), forbidden_files=())
    delta = WorkspaceDelta(
        modified_files=(".ces/state.db", "src/app.py"),
        created_files=(".ces/latest-verification.json",),
    )

    assert workspace_scope_violations(manifest, delta) == ()


def test_workspace_scope_violations_ignore_ces_evidence_artifacts() -> None:
    manifest = SimpleNamespace(affected_files=("src/app.py",), forbidden_files=())
    delta = WorkspaceDelta(
        modified_files=("src/app.py",),
        created_files=(".ces/artifacts/test_pass.txt", ".ces/artifacts/coverage/parserlib.cover"),
    )

    assert workspace_scope_violations(manifest, delta) == ()


def test_workspace_scope_violations_report_out_of_scope_product_edits() -> None:
    manifest = SimpleNamespace(affected_files=("src/app.py",), forbidden_files=())
    delta = WorkspaceDelta(modified_files=("src/app.py", "tests/test_app.py"))

    assert workspace_scope_violations(manifest, delta) == ("tests/test_app.py",)


def test_workspace_scope_violations_allows_semantic_cli_api_source_edits() -> None:
    manifest = SimpleNamespace(affected_files=("CLI/API",), forbidden_files=())
    delta = WorkspaceDelta(modified_files=("parserlib.py", "tests/test_parserlib.py"))

    assert workspace_scope_violations(manifest, delta) == ("tests/test_parserlib.py",)


def test_workspace_scope_violations_report_governance_state_tampering() -> None:
    manifest = SimpleNamespace(affected_files=("src/app.py",), forbidden_files=())
    delta = WorkspaceDelta(
        modified_files=(".ces/config.yaml", ".ces/keys/audit_hmac_secret", ".ces/verification-profile.json")
    )

    assert workspace_scope_violations(manifest, delta) == (
        ".ces/config.yaml",
        ".ces/keys/audit_hmac_secret",
        ".ces/verification-profile.json",
    )


def test_workspace_scope_violations_forbidden_files_override_state_exemptions() -> None:
    manifest = SimpleNamespace(affected_files=("src/app.py",), forbidden_files=(".ces/state.db",))
    delta = WorkspaceDelta(modified_files=(".ces/state.db", "src/app.py"))

    assert workspace_scope_violations(manifest, delta) == (".ces/state.db",)


def test_workspace_scope_violations_forbidden_files_override_artifact_exemptions() -> None:
    manifest = SimpleNamespace(affected_files=("src/app.py",), forbidden_files=(".ces/artifacts/*",))
    delta = WorkspaceDelta(modified_files=(".ces/artifacts/test_pass.txt", "src/app.py"))

    assert workspace_scope_violations(manifest, delta) == (".ces/artifacts/test_pass.txt",)


def test_workspace_scope_violations_semantic_scope_rejects_parent_traversal() -> None:
    manifest = SimpleNamespace(affected_files=("CLI/API",), forbidden_files=("src/secret.py",))
    delta = WorkspaceDelta(modified_files=("src/../src/secret.py", "parserlib.py"))

    assert workspace_scope_violations(manifest, delta) == ("src/../src/secret.py",)


def test_workspace_scope_violations_normalizes_forbidden_windows_patterns() -> None:
    manifest = SimpleNamespace(affected_files=("CLI/API",), forbidden_files=(r"src\secret.py",))
    delta = WorkspaceDelta(modified_files=("src/secret.py", "parserlib.py"))

    assert workspace_scope_violations(manifest, delta) == ("src/secret.py",)


def test_workspace_scope_violations_semantic_scope_rejects_unsafe_paths_without_forbidden_match() -> None:
    manifest = SimpleNamespace(affected_files=("CLI/API",), forbidden_files=())
    delta = WorkspaceDelta(
        modified_files=(
            "../outside.py",
            "/abs/outside.py",
            "C:/tmp/outside.py",
            ".ces/artifacts/../state.db",
            "parserlib.py",
        )
    )

    assert workspace_scope_violations(manifest, delta) == (
        "../outside.py",
        ".ces/artifacts/../state.db",
        "/abs/outside.py",
        "C:/tmp/outside.py",
    )
