"""Tests for DependencySensor real implementation."""

from __future__ import annotations

import pytest

from ces.harness.sensors.dependency import DependencySensor


@pytest.fixture
def sensor():
    return DependencySensor()


class TestDependencySensorNoScope:
    """DependencySensor with no dependency files in scope."""

    @pytest.mark.asyncio
    async def test_empty_context_passes(self, sensor):
        result = await sensor.run({})
        assert result.passed is True
        assert result.score == 1.0

    @pytest.mark.asyncio
    async def test_no_dep_files_passes(self, sensor):
        result = await sensor.run({"affected_files": ["src/main.py"]})
        assert result.passed is True
        assert "No dependency files" in result.details


class TestDependencySensorRequirementsTxt:
    """DependencySensor checks on requirements.txt."""

    @pytest.mark.asyncio
    async def test_all_pinned_passes(self, sensor, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask==2.3.0\nrequests>=2.28.0\n", encoding="utf-8")
        result = await sensor.run(
            {
                "affected_files": ["requirements.txt", "uv.lock"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is True
        assert result.score == 1.0

    @pytest.mark.asyncio
    async def test_unpinned_deps_fail(self, sensor, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask\nrequests\nnumpy\n", encoding="utf-8")
        result = await sensor.run(
            {
                "affected_files": ["requirements.txt"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "unpinned" in result.details

    @pytest.mark.asyncio
    async def test_comments_and_blanks_skipped(self, sensor, tmp_path):
        (tmp_path / "requirements.txt").write_text("# comment\n\nflask==2.0\n", encoding="utf-8")
        result = await sensor.run(
            {
                "affected_files": ["requirements.txt", "uv.lock"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_mixed_pinned_and_unpinned(self, sensor, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask==2.3.0\nrequests\n", encoding="utf-8")
        result = await sensor.run(
            {
                "affected_files": ["requirements.txt"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "1/2" in result.details


class TestDependencySensorPyprojectToml:
    """DependencySensor checks on pyproject.toml."""

    @pytest.mark.asyncio
    async def test_pinned_pyproject_passes(self, sensor, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\ndependencies = [\n  "flask>=2.3.0",\n  "requests>=2.28",\n]\n',
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["pyproject.toml", "uv.lock"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_unpinned_pyproject_fails(self, sensor, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\ndependencies = [\n  "flask",\n  "requests",\n]\n',
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["pyproject.toml"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False


class TestDependencySensorPyprojectSectionStyle:
    """The pyproject.toml parser walks [project.dependencies]-style sections."""

    @pytest.mark.asyncio
    async def test_section_style_pyproject_detects_unpinned_and_closes_section(self, sensor, tmp_path):
        """Section-style TOML with quoted deps is parsed; a following section closes the deps block."""
        (tmp_path / "pyproject.toml").write_text(
            '[project.dependencies]\n"flask"\n"requests==2.0"\n[other.section]\n"not-a-dep"\n',
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["pyproject.toml", "uv.lock"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        # Only the unpinned-dep finding should fire; lockfile drift is satisfied by uv.lock.
        assert "1/2" in result.details


class TestDependencySensorUnreadableFile:
    """Files listed in scope but missing on disk are skipped, not crashed on."""

    @pytest.mark.asyncio
    async def test_missing_dep_file_is_skipped(self, sensor, tmp_path):
        """affected_files names requirements.txt but the file is absent -> no crash, no parse."""
        result = await sensor.run(
            {
                "affected_files": ["requirements.txt"],
                "project_root": str(tmp_path),
            }
        )
        # Lockfile drift still fires (no lockfile in affected_files), but no
        # unpinned-dep finding is produced because the file could not be read.
        assert result.passed is False
        assert "lockfile" in result.details.lower()
        assert "unpinned" not in result.details.lower()


class TestDependencySensorLockfileDrift:
    """DependencySensor lockfile drift detection."""

    @pytest.mark.asyncio
    async def test_requirements_without_lockfile_warned(self, sensor, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask==2.0\n", encoding="utf-8")
        result = await sensor.run(
            {
                "affected_files": ["requirements.txt"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "lockfile" in result.details.lower()

    @pytest.mark.asyncio
    async def test_requirements_with_lockfile_passes(self, sensor, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask==2.0\n", encoding="utf-8")
        result = await sensor.run(
            {
                "affected_files": ["requirements.txt", "uv.lock"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is True
