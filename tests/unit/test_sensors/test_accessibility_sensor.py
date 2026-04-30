"""Tests for AccessibilitySensor real implementation."""

from __future__ import annotations

import pytest

from ces.harness.sensors.accessibility import AccessibilitySensor


@pytest.fixture
def sensor():
    return AccessibilitySensor()


class TestAccessibilitySensor:
    """AccessibilitySensor — informational for CLI tools."""

    @pytest.mark.asyncio
    async def test_empty_context_passes(self, sensor):
        result = await sensor.run({})
        assert result.passed is True
        assert result.score == 1.0

    @pytest.mark.asyncio
    async def test_python_files_only_passes(self, sensor):
        result = await sensor.run({"affected_files": ["src/main.py", "tests/test.py"]})
        assert result.passed is True
        assert result.score == 1.0
        assert "not applicable" in result.details.lower()

    @pytest.mark.asyncio
    async def test_html_files_informational(self, sensor):
        result = await sensor.run({"affected_files": ["index.html", "app.jsx"]})
        assert result.passed is True
        assert result.score == 0.8
        assert "informational" in result.details.lower()

    @pytest.mark.asyncio
    async def test_mixed_files_with_html(self, sensor):
        result = await sensor.run({"affected_files": ["main.py", "page.tsx"]})
        assert result.passed is True
        assert result.score == 0.8
