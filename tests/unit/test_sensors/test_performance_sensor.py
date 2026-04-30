"""Tests for PerformanceSensor real implementation."""

from __future__ import annotations

import pytest

from ces.harness.sensors.performance import PerformanceSensor


@pytest.fixture
def sensor():
    return PerformanceSensor()


class TestPerformanceSensorNoScope:
    """PerformanceSensor with no files in scope."""

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
        """A .py file in affected_files but absent on disk yields read_file_safe=None and continues."""
        result = await sensor.run(
            {
                "affected_files": ["does_not_exist.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is True


class TestPerformanceSensorNestedLoops:
    """PerformanceSensor nested loop detection."""

    @pytest.mark.asyncio
    async def test_nested_for_loop_warned(self, sensor, tmp_path):
        (tmp_path / "algo.py").write_text(
            "def slow():\n    for i in range(n):\n        for j in range(n):\n            pass\n",
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["algo.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is True  # Warnings, not failures
        assert result.score < 1.0
        assert "nested for-loop" in result.details

    @pytest.mark.asyncio
    async def test_single_loop_passes(self, sensor, tmp_path):
        (tmp_path / "ok.py").write_text(
            "def fast():\n    for i in range(10):\n        print(i)\n",
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["ok.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is True
        assert result.score == 1.0


class TestPerformanceSensorSyncInAsync:
    """PerformanceSensor sync-in-async detection."""

    @pytest.mark.asyncio
    async def test_time_sleep_in_async_warned(self, sensor, tmp_path):
        (tmp_path / "srv.py").write_text(
            "import time\nasync def handler():\n    time.sleep(1)\n",
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["srv.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is True
        assert result.score < 1.0
        assert "sync call" in result.details.lower()

    @pytest.mark.asyncio
    async def test_sync_http_in_async_warned(self, sensor, tmp_path):
        """A blocking HTTP call (requests.get) inside an async function is flagged (line 150)."""
        (tmp_path / "client.py").write_text(
            "import requests\nasync def fetch():\n    requests.get('https://x')\n",
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["client.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is True
        assert result.score < 1.0
        assert "sync http" in result.details.lower()

    @pytest.mark.asyncio
    async def test_bare_open_in_async_warned(self, sensor, tmp_path):
        """A bare-name sync call (open()) inside an async function is flagged (line 155)."""
        (tmp_path / "io_async.py").write_text(
            "async def loader():\n    open('/tmp/x').read()\n",
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["io_async.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is True
        assert result.score < 1.0
        assert "open()" in result.details

    @pytest.mark.asyncio
    async def test_async_without_sync_calls_passes(self, sensor, tmp_path):
        (tmp_path / "clean.py").write_text(
            "import asyncio\nasync def handler():\n    await asyncio.sleep(1)\n",
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["clean.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is True
        assert result.score == 1.0


class TestPerformanceSensorGlobal:
    """PerformanceSensor global keyword detection."""

    @pytest.mark.asyncio
    async def test_global_keyword_warned(self, sensor, tmp_path):
        (tmp_path / "state.py").write_text(
            "counter = 0\ndef inc():\n    global counter\n    counter += 1\n",
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["state.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is True
        assert result.score < 1.0
        assert "global" in result.details

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
        assert result.score == 1.0
