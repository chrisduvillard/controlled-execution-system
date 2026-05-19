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


def test_workspace_scope_violations_report_out_of_scope_product_edits() -> None:
    manifest = SimpleNamespace(affected_files=("src/app.py",), forbidden_files=())
    delta = WorkspaceDelta(modified_files=("src/app.py", "tests/test_app.py"))

    assert workspace_scope_violations(manifest, delta) == ("tests/test_app.py",)


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
