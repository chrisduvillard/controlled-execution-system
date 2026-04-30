"""Tests for ResilienceSensor real implementation."""

from __future__ import annotations

import pytest

from ces.harness.sensors.resilience import ResilienceSensor


@pytest.fixture
def sensor():
    return ResilienceSensor()


class TestResilienceSensorNoScope:
    """ResilienceSensor with no files in scope."""

    @pytest.mark.asyncio
    async def test_empty_context_passes(self, sensor):
        result = await sensor.run({})
        assert result.passed is True
        assert result.score == 1.0

    @pytest.mark.asyncio
    async def test_no_python_files_passes(self, sensor):
        result = await sensor.run({"affected_files": ["README.md"]})
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_missing_python_file_is_skipped(self, sensor, tmp_path):
        """A .py file in affected_files that does not exist on disk is silently skipped."""
        result = await sensor.run(
            {
                "affected_files": ["does_not_exist.py"],
                "project_root": str(tmp_path),
            }
        )
        # No content to scan -> no findings -> sensor passes.
        assert result.passed is True


class TestResilienceSensorBareExcept:
    """ResilienceSensor bare except detection."""

    @pytest.mark.asyncio
    async def test_bare_except_fails(self, sensor, tmp_path):
        (tmp_path / "handler.py").write_text(
            "def risky():\n    try:\n        do_stuff()\n    except:\n        pass\n",
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["handler.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "bare" in result.details.lower()

    @pytest.mark.asyncio
    async def test_specific_except_passes(self, sensor, tmp_path):
        (tmp_path / "safe.py").write_text(
            "def safe():\n    try:\n        do_stuff()\n    except ValueError:\n        pass\n",
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["safe.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is True
        assert result.score == 1.0


class TestResilienceSensorMissingTimeout:
    """ResilienceSensor HTTP timeout detection."""

    @pytest.mark.asyncio
    async def test_httpx_without_timeout_fails(self, sensor, tmp_path):
        (tmp_path / "client.py").write_text(
            "import httpx\ndef fetch():\n    httpx.get('http://example.com')\n",
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["client.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "timeout" in result.details.lower()

    @pytest.mark.asyncio
    async def test_httpx_with_timeout_passes(self, sensor, tmp_path):
        (tmp_path / "client.py").write_text(
            "import httpx\ndef fetch():\n    httpx.get('http://example.com', timeout=10)\n",
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["client.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_requests_without_timeout_fails(self, sensor, tmp_path):
        (tmp_path / "api.py").write_text(
            "import requests\ndef call():\n    requests.post('http://api.com/data')\n",
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["api.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "timeout" in result.details.lower()

    @pytest.mark.asyncio
    async def test_unparseable_file_skipped(self, sensor, tmp_path):
        (tmp_path / "bad.py").write_text("def broken(:\n", encoding="utf-8")
        result = await sensor.run(
            {
                "affected_files": ["bad.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is True
