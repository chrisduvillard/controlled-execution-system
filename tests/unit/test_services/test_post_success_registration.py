"""Tests for post-success sensor registration."""

from __future__ import annotations

import pytest

from ces.cli._factory import get_services


@pytest.mark.asyncio
async def test_factory_registers_post_success_state_sensor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ces_dir = tmp_path / ".ces"
    ces_dir.mkdir()
    (ces_dir / "config.yaml").write_text("project_id: registration-test\n", encoding="utf-8")

    async with get_services(project_root=tmp_path) as services:
        orchestrator = services["sensor_orchestrator"]
        assert "post_success_state" in orchestrator._sensors
