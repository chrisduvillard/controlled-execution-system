"""Tests for AgentSandbox secret stripping (EXEC-03).

Tests verify:
- _strip_secrets removes keys matching secret patterns (case-insensitive)
- _strip_secrets removes values matching known API key prefixes
- Combined key+value stripping in _build_env
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ces.execution.sandbox import AgentSandbox


class TestStripSecretsKeyPatterns:
    """Test _strip_secrets removes entries with secret-like key names."""

    def test_strips_key_containing_secret(self) -> None:
        """Removes keys containing 'SECRET' (case-insensitive)."""
        env = {"MY_SECRET": "value", "SAFE_VAR": "ok"}
        result = AgentSandbox._strip_secrets(env)
        assert "MY_SECRET" not in result
        assert result == {"SAFE_VAR": "ok"}

    def test_strips_key_containing_key(self) -> None:
        """Removes keys containing 'KEY'."""
        env = {"API_KEY_MAIN": "value", "SAFE_VAR": "ok"}
        result = AgentSandbox._strip_secrets(env)
        assert "API_KEY_MAIN" not in result
        assert result == {"SAFE_VAR": "ok"}

    def test_strips_key_containing_token(self) -> None:
        """Removes keys containing 'TOKEN'."""
        env = {"AUTH_TOKEN": "value", "SAFE_VAR": "ok"}
        result = AgentSandbox._strip_secrets(env)
        assert "AUTH_TOKEN" not in result
        assert result == {"SAFE_VAR": "ok"}

    def test_strips_key_containing_password(self) -> None:
        """Removes keys containing 'PASSWORD'."""
        env = {"DB_PASSWORD": "value", "SAFE_VAR": "ok"}
        result = AgentSandbox._strip_secrets(env)
        assert "DB_PASSWORD" not in result
        assert result == {"SAFE_VAR": "ok"}

    def test_strips_key_containing_credential(self) -> None:
        """Removes keys containing 'CREDENTIAL'."""
        env = {"CLOUD_CREDENTIAL": "value", "SAFE_VAR": "ok"}
        result = AgentSandbox._strip_secrets(env)
        assert "CLOUD_CREDENTIAL" not in result
        assert result == {"SAFE_VAR": "ok"}

    def test_strips_key_containing_api_key(self) -> None:
        """Removes keys containing 'API_KEY'."""
        env = {"OPENAI_API_KEY": "value", "SAFE_VAR": "ok"}
        result = AgentSandbox._strip_secrets(env)
        assert "OPENAI_API_KEY" not in result
        assert result == {"SAFE_VAR": "ok"}

    def test_strips_key_case_insensitive(self) -> None:
        """Key matching is case-insensitive."""
        env = {"my_secret": "value", "My_Token": "value", "SAFE_VAR": "ok"}
        result = AgentSandbox._strip_secrets(env)
        assert "my_secret" not in result
        assert "My_Token" not in result
        assert result == {"SAFE_VAR": "ok"}


class TestStripSecretsValuePatterns:
    """Test _strip_secrets removes entries with secret-like values."""

    @pytest.mark.parametrize(
        "prefix",
        ["sk-", "pk-", "ghp_", "ghs_", "AKIA", "xoxb-", "xoxp-"],
    )
    def test_strips_value_with_known_prefix(self, prefix: str) -> None:
        """Removes values starting with known API key prefixes."""
        env = {"SAFE_NAME": f"{prefix}abc123def456", "SAFE_VAR": "ok"}
        result = AgentSandbox._strip_secrets(env)
        assert "SAFE_NAME" not in result
        assert result == {"SAFE_VAR": "ok"}

    def test_keeps_values_without_secret_prefix(self) -> None:
        """Keeps values that don't start with known secret prefixes."""
        env = {"PATH": "/usr/bin", "HOME": "/root", "LANG": "en_US.UTF-8"}
        result = AgentSandbox._strip_secrets(env)
        assert result == env


class TestBuildEnvWithSecretStripping:
    """Test that _build_env applies secret stripping to allowlisted vars."""

    @patch.dict(
        "os.environ",
        {
            "PATH": "/usr/bin",
            "API_KEY": "sk-12345",
            "SAFE_VAR": "hello",
            "DB_TOKEN": "mytoken",
        },
    )
    def test_build_env_strips_secrets_from_allowlisted(self) -> None:
        """_build_env strips secret-like vars even when allowlisted."""
        result = AgentSandbox._build_env(allowlist=["PATH", "API_KEY", "SAFE_VAR", "DB_TOKEN"])
        # API_KEY stripped by key pattern, DB_TOKEN stripped by key pattern
        assert "API_KEY" not in result
        assert "DB_TOKEN" not in result
        assert result == {"PATH": "/usr/bin", "SAFE_VAR": "hello"}

    @patch.dict(
        "os.environ",
        {
            "CUSTOM_VAR": "ghp_abc123",
        },
    )
    def test_build_env_strips_secret_values(self) -> None:
        """_build_env strips vars with secret-like values even when key is safe."""
        result = AgentSandbox._build_env(allowlist=["CUSTOM_VAR"])
        assert "CUSTOM_VAR" not in result
        assert result == {}
