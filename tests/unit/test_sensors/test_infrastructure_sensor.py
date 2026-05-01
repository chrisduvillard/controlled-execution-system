"""Tests for InfrastructureSensor real implementation."""

from __future__ import annotations

import pytest

from ces.harness.sensors.infrastructure import InfrastructureSensor


@pytest.fixture
def sensor():
    return InfrastructureSensor()


class TestInfrastructureSensorNoScope:
    """InfrastructureSensor with no infrastructure files in scope."""

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
    async def test_missing_infrastructure_file_is_skipped(self, sensor, tmp_path):
        """A listed infrastructure file absent on disk yields no findings."""
        result = await sensor.run(
            {
                "affected_files": [".github/workflows/ci.yml"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is True


class TestInfrastructureSensorConfigFiles:
    """InfrastructureSensor repository configuration linting."""

    @pytest.mark.asyncio
    async def test_clean_workflow_passes(self, sensor, tmp_path):
        workflow = tmp_path / ".github" / "workflows"
        workflow.mkdir(parents=True)
        (workflow / "ci.yml").write_text(
            "jobs:\n"
            "  test:\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "      - uses: actions/setup-python@v5\n"
            "        with:\n"
            "          python-version: '3.12'\n",
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": [".github/workflows/ci.yml"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_floating_action_ref_flagged(self, sensor, tmp_path):
        workflow = tmp_path / ".github" / "workflows"
        workflow.mkdir(parents=True)
        (workflow / "ci.yml").write_text("steps:\n  - uses: actions/checkout@main\n", encoding="utf-8")
        result = await sensor.run(
            {
                "affected_files": [".github/workflows/ci.yml"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "floating ref" in result.details

    @pytest.mark.asyncio
    async def test_unpinned_python_version_flagged(self, sensor, tmp_path):
        workflow = tmp_path / ".github" / "workflows"
        workflow.mkdir(parents=True)
        (workflow / "ci.yml").write_text("with:\n  python-version: '3'\n", encoding="utf-8")
        result = await sensor.run(
            {
                "affected_files": [".github/workflows/ci.yml"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "Python version" in result.details

    @pytest.mark.asyncio
    async def test_pyproject_without_project_metadata_flagged(self, sensor, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")
        result = await sensor.run(
            {
                "affected_files": ["pyproject.toml"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "[project]" in result.details

    @pytest.mark.asyncio
    async def test_lockfile_without_package_entries_flagged(self, sensor, tmp_path):
        (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
        result = await sensor.run(
            {
                "affected_files": ["uv.lock"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "package entries" in result.details
