"""Tests for SecuritySensor real implementation."""

from __future__ import annotations

import pytest

from ces.harness.sensors.security import SecuritySensor


@pytest.fixture
def sensor():
    return SecuritySensor()


class TestSecuritySensorNoScope:
    """SecuritySensor with no files in scope."""

    @pytest.mark.asyncio
    async def test_empty_context_passes(self, sensor):
        result = await sensor.run({})
        assert result.passed is True
        assert result.score == 1.0

    @pytest.mark.asyncio
    async def test_no_affected_files_passes(self, sensor):
        result = await sensor.run({"affected_files": []})
        assert result.passed is True


class TestSecuritySensorPathChecks:
    """SecuritySensor path-based secret detection."""

    @pytest.mark.asyncio
    async def test_env_file_flagged(self, sensor):
        result = await sensor.run({"affected_files": [".env"]})
        assert result.passed is False
        assert "Sensitive file" in result.details

    @pytest.mark.asyncio
    async def test_pem_file_flagged(self, sensor):
        result = await sensor.run({"affected_files": ["certs/server.pem"]})
        assert result.passed is False
        assert "Private key/cert" in result.details

    @pytest.mark.asyncio
    async def test_credentials_json_flagged(self, sensor):
        result = await sensor.run({"affected_files": ["credentials.json"]})
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_normal_files_pass(self, sensor):
        result = await sensor.run({"affected_files": ["src/main.py", "README.md"]})
        assert result.passed is True


class TestSecuritySensorContentChecks:
    """SecuritySensor content-based secret detection."""

    @pytest.mark.asyncio
    async def test_aws_key_detected(self, sensor, tmp_path):
        (tmp_path / "config.py").write_text('AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n', encoding="utf-8")
        result = await sensor.run(
            {
                "affected_files": ["config.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "AWS access key" in result.details

    @pytest.mark.asyncio
    async def test_private_key_header_detected(self, sensor, tmp_path):
        (tmp_path / "key.py").write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n", encoding="utf-8")
        result = await sensor.run(
            {
                "affected_files": ["key.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "Private key header" in result.details

    @pytest.mark.asyncio
    async def test_password_assignment_detected(self, sensor, tmp_path):
        (tmp_path / "app.py").write_text('password = "supersecret123"\n', encoding="utf-8")
        result = await sensor.run(
            {
                "affected_files": ["app.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "Password assignment" in result.details

    @pytest.mark.asyncio
    async def test_clean_file_passes(self, sensor, tmp_path):
        (tmp_path / "clean.py").write_text('x = 42\nprint("hello world")\n', encoding="utf-8")
        result = await sensor.run(
            {
                "affected_files": ["clean.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is True
        assert result.score == 1.0

    @pytest.mark.asyncio
    async def test_missing_file_skipped_gracefully(self, sensor, tmp_path):
        result = await sensor.run(
            {
                "affected_files": ["nonexistent.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_github_token_detected(self, sensor, tmp_path):
        (tmp_path / "ci.py").write_text(
            'TOKEN = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklm"\n',
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["ci.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "GitHub token" in result.details

    @pytest.mark.asyncio
    async def test_score_decreases_with_more_findings(self, sensor, tmp_path):
        (tmp_path / "bad.py").write_text(
            'password = "secret"\napi_key = "long_enough_key_value"\n',
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["bad.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert result.score < 1.0
