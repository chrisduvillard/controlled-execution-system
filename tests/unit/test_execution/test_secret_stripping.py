"""Tests for runtime secret stripping (EXEC-03).

Tests verify:
- strip_secret_env removes keys matching secret patterns (case-insensitive)
- strip_secret_env removes values matching known API key prefixes
- Combined key+value stripping in build_allowed_env
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ces.execution.secrets import build_allowed_env, strip_secret_env


class TestStripSecretsKeyPatterns:
    """Test strip_secret_env removes entries with secret-like key names."""

    def test_strips_key_containing_secret(self) -> None:
        """Removes keys containing 'SECRET' (case-insensitive)."""
        env = {"MY_SECRET": "value", "SAFE_VAR": "ok"}
        result = strip_secret_env(env)
        assert "MY_SECRET" not in result
        assert result == {"SAFE_VAR": "ok"}

    def test_strips_key_containing_key(self) -> None:
        """Removes keys containing 'KEY'."""
        env = {"API_KEY_MAIN": "value", "SAFE_VAR": "ok"}
        result = strip_secret_env(env)
        assert "API_KEY_MAIN" not in result
        assert result == {"SAFE_VAR": "ok"}

    def test_strips_key_containing_token(self) -> None:
        """Removes keys containing 'TOKEN'."""
        env = {"AUTH_TOKEN": "value", "SAFE_VAR": "ok"}
        result = strip_secret_env(env)
        assert "AUTH_TOKEN" not in result
        assert result == {"SAFE_VAR": "ok"}

    def test_strips_key_containing_password(self) -> None:
        """Removes keys containing 'PASSWORD'."""
        env = {"DB_PASSWORD": "value", "SAFE_VAR": "ok"}
        result = strip_secret_env(env)
        assert "DB_PASSWORD" not in result
        assert result == {"SAFE_VAR": "ok"}

    def test_strips_key_containing_credential(self) -> None:
        """Removes keys containing 'CREDENTIAL'."""
        env = {"CLOUD_CREDENTIAL": "value", "SAFE_VAR": "ok"}
        result = strip_secret_env(env)
        assert "CLOUD_CREDENTIAL" not in result
        assert result == {"SAFE_VAR": "ok"}

    def test_strips_key_containing_api_key(self) -> None:
        """Removes keys containing 'API_KEY'."""
        env = {"OPENAI_API_KEY": "value", "SAFE_VAR": "ok"}
        result = strip_secret_env(env)
        assert "OPENAI_API_KEY" not in result
        assert result == {"SAFE_VAR": "ok"}

    def test_strips_key_case_insensitive(self) -> None:
        """Key matching is case-insensitive."""
        env = {"my_secret": "value", "My_Token": "value", "SAFE_VAR": "ok"}
        result = strip_secret_env(env)
        assert "my_secret" not in result
        assert "My_Token" not in result
        assert result == {"SAFE_VAR": "ok"}


class TestStripSecretsValuePatterns:
    """Test strip_secret_env removes entries with secret-like values."""

    @pytest.mark.parametrize(
        "prefix",
        ["sk-", "pk-", "ghp_", "ghs_", "AKIA", "xoxb-", "xoxp-"],
    )
    def test_strips_value_with_known_prefix(self, prefix: str) -> None:
        """Removes values starting with known API key prefixes."""
        env = {"SAFE_NAME": f"{prefix}abc123def456", "SAFE_VAR": "ok"}
        result = strip_secret_env(env)
        assert "SAFE_NAME" not in result
        assert result == {"SAFE_VAR": "ok"}

    def test_keeps_values_without_secret_prefix(self) -> None:
        """Keeps values that don't start with known secret prefixes."""
        env = {"PATH": "/usr/bin", "HOME": "/root", "LANG": "en_US.UTF-8"}
        result = strip_secret_env(env)
        assert result == env


class TestBuildEnvWithSecretStripping:
    """Test that build_allowed_env applies secret stripping to allowlisted vars."""

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
        """build_allowed_env strips secret-like vars even when allowlisted."""
        result = build_allowed_env(allowlist=["PATH", "API_KEY", "SAFE_VAR", "DB_TOKEN"])
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
        """build_allowed_env strips vars with secret-like values even when key is safe."""
        result = build_allowed_env(allowlist=["CUSTOM_VAR"])
        assert "CUSTOM_VAR" not in result
        assert result == {}
