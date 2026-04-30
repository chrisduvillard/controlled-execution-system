"""Tests for InfrastructureSensor real implementation."""

from __future__ import annotations

import pytest

from ces.harness.sensors.infrastructure import InfrastructureSensor


@pytest.fixture
def sensor():
    return InfrastructureSensor()


class TestInfrastructureSensorNoScope:
    """InfrastructureSensor with no infra files in scope."""

    @pytest.mark.asyncio
    async def test_empty_context_passes(self, sensor):
        result = await sensor.run({})
        assert result.passed is True
        assert result.score == 1.0

    @pytest.mark.asyncio
    async def test_no_infra_files_passes(self, sensor):
        result = await sensor.run({"affected_files": ["src/main.py"]})
        assert result.passed is True
        assert "No infrastructure files" in result.details

    @pytest.mark.asyncio
    async def test_missing_dockerfile_is_skipped(self, sensor, tmp_path):
        """A Dockerfile in affected_files but absent on disk yields no findings (line 59 continue)."""
        result = await sensor.run(
            {
                "affected_files": ["Dockerfile"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is True


class TestInfrastructureSensorDockerfile:
    """InfrastructureSensor Dockerfile linting."""

    @pytest.mark.asyncio
    async def test_clean_dockerfile_passes(self, sensor, tmp_path):
        (tmp_path / "Dockerfile").write_text(
            "FROM python:3.12-slim\n"
            "RUN pip install --no-cache-dir flask\n"
            "HEALTHCHECK CMD curl -f http://localhost/ || exit 1\n"
            "USER appuser\n"
            'CMD ["python", "app.py"]\n',
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["Dockerfile"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_latest_tag_flagged(self, sensor, tmp_path):
        (tmp_path / "Dockerfile").write_text(
            "FROM python:latest\nHEALTHCHECK CMD true\nUSER app\n",
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["Dockerfile"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert ":latest" in result.details

    @pytest.mark.asyncio
    async def test_missing_healthcheck_flagged(self, sensor, tmp_path):
        (tmp_path / "Dockerfile").write_text(
            'FROM python:3.12\nUSER app\nCMD ["python"]\n',
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["Dockerfile"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "HEALTHCHECK" in result.details

    @pytest.mark.asyncio
    async def test_no_user_instruction_flagged(self, sensor, tmp_path):
        (tmp_path / "Dockerfile").write_text(
            'FROM python:3.12\nHEALTHCHECK CMD true\nCMD ["python"]\n',
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["Dockerfile"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "USER" in result.details

    @pytest.mark.asyncio
    async def test_copy_all_flagged(self, sensor, tmp_path):
        (tmp_path / "Dockerfile").write_text(
            "FROM python:3.12\nCOPY . .\nHEALTHCHECK CMD true\nUSER app\n",
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["Dockerfile"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "COPY . ." in result.details

    @pytest.mark.asyncio
    async def test_pip_without_no_cache_flagged(self, sensor, tmp_path):
        (tmp_path / "Dockerfile").write_text(
            "FROM python:3.12\nRUN pip install flask\nHEALTHCHECK CMD true\nUSER app\n",
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["Dockerfile"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "no-cache-dir" in result.details

    @pytest.mark.asyncio
    async def test_apt_get_without_no_install_recommends_flagged(self, sensor, tmp_path):
        """apt-get install without --no-install-recommends triggers an issue (line 113)."""
        (tmp_path / "Dockerfile").write_text(
            "FROM debian:bullseye-slim\nRUN apt-get install -y curl\nHEALTHCHECK CMD true\nUSER app\n",
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["Dockerfile"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "no-install-recommends" in result.details

    @pytest.mark.asyncio
    async def test_multiple_issues_reduce_score(self, sensor, tmp_path):
        (tmp_path / "Dockerfile").write_text(
            'FROM python:latest\nRUN pip install flask\nCOPY . .\nCMD ["python"]\n',
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["Dockerfile"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert result.score < 0.6  # Multiple issues stack
