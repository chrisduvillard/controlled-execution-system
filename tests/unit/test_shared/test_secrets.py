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
