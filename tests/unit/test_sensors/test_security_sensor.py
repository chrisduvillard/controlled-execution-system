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
        aws_key = "AK" + "IA" + "IOSYNTHETIC" + "EXAMPLE"
        (tmp_path / "config.py").write_text(f'AWS_KEY = "{aws_key}"\n', encoding="utf-8")
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
        key_header = "-----" + "BEGIN RSA " + "PRIVATE KEY" + "-----"
        (tmp_path / "key.py").write_text(f"{key_header}\nMIIE...\n", encoding="utf-8")
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
        assignment = "password" + ' = "fixture-password"\n'
        (tmp_path / "app.py").write_text(assignment, encoding="utf-8")
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
        github_token = "ghp" + "_" + "SYNTHETIC" + "EXAMPLEVALUE1234567890ABCDEFG"
        token_assignment = "TOKEN" + f' = "{github_token}"\n'
        (tmp_path / "ci.py").write_text(
            token_assignment,
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
    @pytest.mark.parametrize(
        ("label", "secret", "expected"),
        [
            ("github_pat", "github" + "_pat_" + "A" * 30, "GitHub token"),
            ("gitlab", "glpat-" + "B" * 24, "GitLab token"),
            ("slack", "xoxc-" + "1234567890" + "-abcdef", "Slack token"),
            ("slack_config", "xoxe-" + "1234567890" + "-abcdef", "Slack token"),
            ("jwt", "eyJ" + ("a" * 12) + "." + ("b" * 12) + "." + ("c" * 12), "JWT"),
            ("dsn", "postgres://user:" + "pass" + "w0rd@example.invalid/db", "Credential-bearing URL"),
        ],
    )
    async def test_public_audit_token_matrix_detected(self, sensor, tmp_path, label, secret, expected):
        (tmp_path / "tokens.py").write_text(f"{label} = {secret!r}\n", encoding="utf-8")
        result = await sensor.run(
            {
                "affected_files": ["tokens.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert expected in result.details

    @pytest.mark.asyncio
    async def test_google_service_account_json_detected(self, sensor, tmp_path):
        begin_private_key = "-----" + "BEGIN " + "PRIVATE KEY" + "-----"
        end_private_key = "-----" + "END " + "PRIVATE KEY" + "-----"
        (tmp_path / "credentials.json").write_text(
            (
                '{"type": "service_account", "private_key_id": "abc123", '
                f'"private_key": "{begin_private_key}\\nMIIEvfixture\\n{end_private_key}\\n"}}'
            ),
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["credentials.json"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "Sensitive file" in result.details
        assert "Google service account JSON" in result.details

    @pytest.mark.asyncio
    async def test_large_scannable_file_reports_security_gap(self, sensor, tmp_path):
        (tmp_path / "large.log").write_text("x" * 1_048_577, encoding="utf-8")
        result = await sensor.run(
            {
                "affected_files": ["large.log"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "Large file skipped by security scan" in result.details

    @pytest.mark.asyncio
    async def test_score_decreases_with_more_findings(self, sensor, tmp_path):
        password_assignment = "password" + ' = "secret"\n'
        api_key_assignment = "api_key" + ' = "fixture_api_key_value"\n'
        (tmp_path / "bad.py").write_text(
            password_assignment + api_key_assignment,
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
