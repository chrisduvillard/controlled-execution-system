"""Tests for AgentSandbox Docker container management.

Tests verify:
- SandboxConfig is a frozen CESBaseModel with correct defaults
- AgentSandbox creates containers with proper isolation settings
- Container lifecycle (create/destroy) works correctly
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ces.execution.sandbox import AgentSandbox, SandboxConfig, scrub_secrets_from_text
from ces.shared.base import CESBaseModel


class TestSandboxConfig:
    """Test SandboxConfig frozen model with defaults."""

    def test_sandbox_config_is_ces_base_model(self) -> None:
        """SandboxConfig inherits from CESBaseModel."""
        assert issubclass(SandboxConfig, CESBaseModel)

    def test_sandbox_config_defaults(self) -> None:
        """SandboxConfig has correct default values."""
        config = SandboxConfig()
        assert config.image == "python:3.12-slim"
        assert config.mem_limit == "512m"
        assert config.network_mode == "none"
        assert config.read_only is True
        assert config.max_output_bytes == 1_048_576

    def test_sandbox_config_is_frozen(self) -> None:
        """SandboxConfig instances are immutable."""
        config = SandboxConfig()
        with pytest.raises(Exception):
            config.image = "other:latest"  # type: ignore[misc]

    def test_sandbox_config_custom_values(self) -> None:
        """SandboxConfig accepts custom values."""
        config = SandboxConfig(
            image="node:20-slim",
            mem_limit="1g",
            network_mode="bridge",
            read_only=False,
            max_output_bytes=2_097_152,
        )
        assert config.image == "node:20-slim"
        assert config.mem_limit == "1g"
        assert config.network_mode == "bridge"
        assert config.read_only is False
        assert config.max_output_bytes == 2_097_152


class TestAgentSandboxBuildEnv:
    """Test AgentSandbox._build_env() environment building."""

    def test_build_env_empty_when_no_allowlist(self) -> None:
        """_build_env returns empty dict when no allowlisted env vars provided."""
        result = AgentSandbox._build_env()
        assert result == {}

    def test_build_env_empty_when_allowlist_is_none(self) -> None:
        """_build_env returns empty dict when allowlist is None."""
        result = AgentSandbox._build_env(allowlist=None)
        assert result == {}

    def test_build_env_empty_when_allowlist_is_empty(self) -> None:
        """_build_env returns empty dict when allowlist is empty list."""
        result = AgentSandbox._build_env(allowlist=[])
        assert result == {}

    @patch.dict("os.environ", {"PATH": "/usr/bin", "HOME": "/root", "SECRET_KEY": "abc"})
    def test_build_env_returns_only_allowlisted_vars(self) -> None:
        """_build_env returns only PATH from host env when allowlist=["PATH"]."""
        result = AgentSandbox._build_env(allowlist=["PATH"])
        assert result == {"PATH": "/usr/bin"}
        assert "HOME" not in result
        assert "SECRET_KEY" not in result

    @patch.dict("os.environ", {"PATH": "/usr/bin", "HOME": "/root"})
    def test_build_env_skips_missing_vars(self) -> None:
        """_build_env skips vars not present in host env."""
        result = AgentSandbox._build_env(allowlist=["PATH", "NONEXISTENT"])
        assert result == {"PATH": "/usr/bin"}


class TestAgentSandboxCreateContainer:
    """Test AgentSandbox.create_container() Docker interaction."""

    @patch("ces.execution.sandbox.docker")
    def test_create_container_calls_docker_with_isolation(self, mock_docker: MagicMock) -> None:
        """create_container calls docker client.containers.run with proper isolation settings."""
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_client.containers.run.return_value = mock_container

        sandbox = AgentSandbox()
        result = sandbox.create_container("echo hello")

        mock_client.containers.run.assert_called_once_with(
            image="python:3.12-slim",
            command="echo hello",
            detach=True,
            network_mode="none",
            read_only=True,
            mem_limit="512m",
            environment={},
        )
        assert result is mock_container

    @patch("ces.execution.sandbox.docker")
    def test_create_container_with_custom_config(self, mock_docker: MagicMock) -> None:
        """create_container respects custom SandboxConfig values."""
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_client.containers.run.return_value = mock_container

        config = SandboxConfig(image="node:20-slim", mem_limit="1g")
        sandbox = AgentSandbox(config=config)
        sandbox.create_container("node script.js")

        mock_client.containers.run.assert_called_once_with(
            image="node:20-slim",
            command="node script.js",
            detach=True,
            network_mode="none",
            read_only=True,
            mem_limit="1g",
            environment={},
        )


class TestAgentSandboxDestroyContainer:
    """Test AgentSandbox.destroy_container() cleanup."""

    @patch("ces.execution.sandbox.docker")
    def test_destroy_container_calls_remove_force(self, mock_docker: MagicMock) -> None:
        """destroy_container calls container.remove(force=True)."""
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_client.containers.run.return_value = mock_container

        sandbox = AgentSandbox()
        sandbox.create_container("echo hello")
        sandbox.destroy_container()

        mock_container.remove.assert_called_once_with(force=True)

    @patch("ces.execution.sandbox.docker")
    def test_destroy_container_noop_when_no_container(self, mock_docker: MagicMock) -> None:
        """destroy_container does nothing when no container exists."""
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client

        sandbox = AgentSandbox()
        # Should not raise
        sandbox.destroy_container()

    @patch("ces.execution.sandbox.docker")
    def test_destroy_container_clears_reference(self, mock_docker: MagicMock) -> None:
        """destroy_container sets internal container reference to None."""
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_client.containers.run.return_value = mock_container

        sandbox = AgentSandbox()
        sandbox.create_container("echo hello")
        sandbox.destroy_container()
        # Second destroy should be a no-op
        sandbox.destroy_container()
        mock_container.remove.assert_called_once()


class TestScrubSecretsFromText:
    """0.1.2 extends ``_strip_secrets`` to free-form text persistence."""

    @pytest.mark.parametrize(
        "payload",
        [
            "sk-anthropic1234567890abcdef",
            "AKIAIOSFODNN7EXAMPLE",
            "ghp_1234567890abcdefABCDEF",
            "xoxb-1234567890-ABCDEF1234",
        ],
    )
    def test_known_prefix_tokens_are_redacted(self, payload: str) -> None:
        assert payload not in scrub_secrets_from_text(f"Token: {payload} end")

    def test_key_value_assignments_are_redacted(self) -> None:
        raw = "Loaded ANTHROPIC_API_KEY=sk-ant-abc-1 and GITHUB_TOKEN=ghp_xyz"
        scrubbed = scrub_secrets_from_text(raw)
        assert "sk-ant-abc-1" not in scrubbed
        assert "ghp_xyz" not in scrubbed
        # Key names remain (for audit context), value becomes placeholder
        assert "ANTHROPIC_API_KEY" in scrubbed
        assert "<REDACTED>" in scrubbed

    def test_non_secret_text_is_unchanged(self) -> None:
        raw = "Opened 3 files, 2 tests passed, coverage 91%."
        assert scrub_secrets_from_text(raw) == raw

    def test_empty_and_none_handled(self) -> None:
        assert scrub_secrets_from_text("") == ""
        assert scrub_secrets_from_text("just plain text") == "just plain text"

    def test_json_embedded_secret_is_redacted(self) -> None:
        raw = '{"env": {"OPENAI_API_KEY": "sk-openai-abcdef"}}'
        scrubbed = scrub_secrets_from_text(raw)
        assert "sk-openai-abcdef" not in scrubbed
        assert "<REDACTED>" in scrubbed


def test_sandbox_init_raises_runtime_error_when_docker_unavailable(monkeypatch) -> None:
    """AgentSandbox() raises RuntimeError with an install hint when the docker module
    is not importable (lean install without [docker] extras)."""
    from ces.execution import sandbox as sandbox_mod

    monkeypatch.setattr(sandbox_mod, "docker", None)
    with pytest.raises(RuntimeError, match=r"\[docker\]"):
        AgentSandbox()
