"""TEST-01: Docker sandbox integration tests with real containers.

Requires Docker daemon running. Tests verify actual container creation,
isolation properties (no network, read-only FS), and cleanup.
"""

from __future__ import annotations

import pytest

from ces.execution.sandbox import AgentSandbox, SandboxConfig


def _get_docker_module():
    """Import Docker SDK only for integration tests that actually run."""
    return pytest.importorskip("docker")


def _docker_available() -> bool:
    """Check if Docker daemon is reachable."""
    client = None
    try:
        docker_module = _get_docker_module()
        client = docker_module.from_env()
        client.ping()
        return True
    except Exception:
        return False
    finally:
        if client is not None:
            client.close()


pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def require_docker() -> None:
    if not _docker_available():
        pytest.skip("Docker daemon not available")


class TestDockerSandboxContainer:
    """Integration tests for AgentSandbox with real Docker containers."""

    def test_create_container_returns_container(self) -> None:
        """create_container() creates a real Docker container."""
        sandbox = AgentSandbox()
        try:
            container = sandbox.create_container("echo hello")
            assert container is not None
            assert container.id is not None
        finally:
            sandbox.destroy_container()

    def test_container_runs_command_and_exits(self) -> None:
        """Container runs a command and exits with status 0."""
        sandbox = AgentSandbox()
        try:
            container = sandbox.create_container("echo hello")
            result = container.wait(timeout=30)
            assert result["StatusCode"] == 0
            logs = container.logs().decode("utf-8").strip()
            assert "hello" in logs
        finally:
            sandbox.destroy_container()

    def test_container_has_no_network(self) -> None:
        """Container is created with network_mode='none'."""
        sandbox = AgentSandbox()
        try:
            container = sandbox.create_container("echo test")
            container.wait(timeout=30)
            attrs = container.attrs
            network_mode = attrs["HostConfig"]["NetworkMode"]
            assert network_mode == "none"
        finally:
            sandbox.destroy_container()

    def test_container_is_read_only(self) -> None:
        """Container root filesystem is read-only."""
        sandbox = AgentSandbox()
        try:
            container = sandbox.create_container("echo test")
            container.wait(timeout=30)
            attrs = container.attrs
            assert attrs["HostConfig"]["ReadonlyRootfs"] is True
        finally:
            sandbox.destroy_container()

    def test_container_has_memory_limit(self) -> None:
        """Container has the configured memory limit."""
        config = SandboxConfig(mem_limit="256m")
        sandbox = AgentSandbox(config=config)
        try:
            container = sandbox.create_container("echo test")
            container.wait(timeout=30)
            memory = container.attrs["HostConfig"]["Memory"]
            assert memory == 256 * 1024 * 1024  # 256MB in bytes
        finally:
            sandbox.destroy_container()

    def test_destroy_removes_container(self) -> None:
        """destroy_container() removes the container from Docker."""
        sandbox = AgentSandbox()
        container = sandbox.create_container("echo test")
        container.wait(timeout=30)
        container_id = container.id
        sandbox.destroy_container()

        docker_module = _get_docker_module()
        client = docker_module.from_env()
        with pytest.raises(docker_module.errors.NotFound):
            client.containers.get(container_id)


class TestDockerSandboxSecretStripping:
    """Tests for secret stripping (no Docker needed)."""

    def test_strip_secrets_filters_key_patterns(self) -> None:
        """Keys matching SECRET, KEY, TOKEN, PASSWORD, CREDENTIAL are removed."""
        env = {
            "AWS_SECRET_KEY": "mykey",
            "API_TOKEN": "tok",
            "DB_PASSWORD": "pass",
            "SAFE_VAR": "ok",
        }
        result = AgentSandbox._strip_secrets(env)
        assert result == {"SAFE_VAR": "ok"}

    def test_strip_secrets_filters_value_prefixes(self) -> None:
        """Values starting with sk-, ghp_, AKIA, etc. are removed."""
        env = {
            "VAR_A": "sk-1234567890",
            "VAR_B": "ghp_abcdefghij",
            "VAR_C": "AKIAIOSFODNN7EXAMPLE",
            "VAR_D": "safe_value",
        }
        result = AgentSandbox._strip_secrets(env)
        assert result == {"VAR_D": "safe_value"}

    def test_build_env_empty_without_allowlist(self) -> None:
        """_build_env() returns empty dict when no allowlist is given."""
        assert AgentSandbox._build_env() == {}
        assert AgentSandbox._build_env(None) == {}
        assert AgentSandbox._build_env([]) == {}
