"""Tests for shared secret redaction helpers."""

from __future__ import annotations

from ces.execution import secrets as execution_secrets
from ces.shared import secrets as shared_secrets


def test_execution_secret_scrubbers_reexport_shared_implementation() -> None:
    assert execution_secrets.scrub_secrets_from_text is shared_secrets.scrub_secrets_from_text
    assert execution_secrets.scrub_secrets_recursive is shared_secrets.scrub_secrets_recursive


def test_shared_secret_scrubber_redacts_nested_runtime_evidence() -> None:
    token = "ghp" + "_" + "syntheticsecretvalue"
    payload = {
        "stdout": f"runtime printed {token}",
        "metadata": {"env": "OPENAI_API_KEY=sk-synthetic-value"},
        "safe": ("kept", 7),
    }

    scrubbed = shared_secrets.scrub_secrets_recursive(payload)

    assert token not in str(scrubbed)
    assert "sk-synthetic-value" not in str(scrubbed)
    assert scrubbed["stdout"] == "runtime printed <REDACTED>"
    assert scrubbed["metadata"]["env"] == "OPENAI_API_KEY=<REDACTED>"
    assert scrubbed["safe"] == ("kept", 7)


def test_shared_secret_scrubber_redacts_public_audit_token_matrix() -> None:
    github_fine_grained = "github" + "_pat_" + "A" * 30
    gitlab = "glpat-" + "B" * 24
    slack = "xoxc-" + "1234567890" + "-abcdef"
    slack_config = "xoxe-" + "1234567890" + "-abcdef"
    jwt = "eyJ" + ("a" * 12) + "." + ("b" * 12) + "." + ("c" * 12)
    dsn_password = "pass" + "w0rd"
    dsn = "postgres://user:" + dsn_password + "@example.invalid/db"
    begin_private_key = "-----" + "BEGIN " + "PRIVATE KEY" + "-----"
    end_private_key = "-----" + "END " + "PRIVATE KEY" + "-----"
    key_block = f"{begin_private_key}\nMIIEvsyntheticfixture\n{end_private_key}"
    google_service_account = (
        '{"type": "service_account", "private_key_id": "abc123", '
        f'"private_key": "{begin_private_key}\\nMIIEvfixture\\n{end_private_key}\\n"}}'
    )

    text = (
        f"{github_fine_grained}\n{gitlab}\n{slack}\n{slack_config}\n{jwt}\n{dsn}\n{key_block}\n{google_service_account}"
    )

    scrubbed = shared_secrets.scrub_secrets_from_text(text)

    for secret in (
        github_fine_grained,
        gitlab,
        slack,
        slack_config,
        jwt,
        dsn_password,
        "MIIEvsyntheticfixture",
        "abc123",
    ):
        assert secret not in scrubbed
    assert "postgres://user:<REDACTED>@example.invalid/db" in scrubbed
    assert scrubbed.count("<REDACTED>") >= 7
