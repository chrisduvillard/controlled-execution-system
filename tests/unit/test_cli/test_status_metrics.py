"""Tests for the telemetry metrics panel in ces status command.

Tests:
1. _build_metrics_table({}) returns a table with title "Telemetry (Last Hour)" and 5 rows
2. _build_metrics_table({"task": {"record_count": 42}}) includes "42" in the output
3. _build_verbose_metrics_table returns table with "Telemetry Detail" title
4. _build_verbose_metrics_table with metric data includes values in output
5. _gather_status_data returns a telemetry_summary key for the local status view
6. show_status includes --verbose option
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture(autouse=True)
def _reset_json_mode():
    """Reset JSON mode before each test to avoid leaking state."""
    from ces.cli._output import set_json_mode

    set_json_mode(False)
    yield
    set_json_mode(False)


def _get_app():
    """Import app lazily to avoid import errors during collection."""
    from ces.cli import app

    return app


def _patch_services(mock_services: dict[str, Any]):
    """Return a patch that replaces get_services with a fake async context manager."""

    @asynccontextmanager
    async def _fake_get_services(*args: Any, **kwargs: Any):
        del args, kwargs
        yield mock_services

    return patch("ces.cli.status_cmd.get_services", new=_fake_get_services)


def _make_mock_services() -> dict[str, Any]:
    """Create mock services with the APIs used by ``ces status``."""
    mock_trust = AsyncMock()
    mock_manifest = AsyncMock()
    mock_manifest.get_active_manifests = AsyncMock(return_value=[])
    mock_audit = AsyncMock()
    mock_audit.query_by_time_range = AsyncMock(return_value=[])
    return {
        "trust_manager": mock_trust,
        "manifest_manager": mock_manifest,
        "audit_ledger": mock_audit,
    }


def _make_mock_summary() -> dict[str, dict]:
    """Create a mock telemetry summary for testing."""
    return {
        "task": {"record_count": 42, "total_tokens": 5000, "avg_wall_clock_seconds": 3.5},
        "agent": {"record_count": 10, "avg_error_rate": 0.05, "agent_agg": [], "agent_count": 0},
        "harness": {"record_count": 3, "avg_review_catch_rate": 0.8},
        "control_plane": {"record_count": 2, "max_approval_queue_depth": 5},
        "system": {"record_count": 1, "max_active_agents": 3},
    }


class TestBuildMetricsTable:
    """Tests for _build_metrics_table function."""

    def test_empty_summaries_returns_table_with_title(self) -> None:
        """_build_metrics_table({}) returns a table titled 'Telemetry (Last Hour)'."""
        from ces.cli.status_cmd import _build_metrics_table

        table = _build_metrics_table({})
        assert table.title == "Telemetry (Last Hour)"

    def test_empty_summaries_has_five_rows(self) -> None:
        """_build_metrics_table({}) has 5 rows (one per level, all zero values)."""
        from ces.cli.status_cmd import _build_metrics_table

        table = _build_metrics_table({})
        assert table.row_count == 5

    def test_task_record_count_in_output(self) -> None:
        """_build_metrics_table with task record_count=42 includes '42' in row data."""
        from ces.cli.status_cmd import _build_metrics_table

        summaries = _make_mock_summary()
        table = _build_metrics_table(summaries)
        # Table rows contain the rendered cell text
        # Check that 42 appears in the third column (Value) of the first row (task)
        found = False
        for row_idx in range(table.row_count):
            cells = [col._cells[row_idx] for col in table.columns]
            if "Task" in cells[0] and "42" in cells[2]:
                found = True
                break
        assert found, "Expected '42' in Task row value column"

    def test_has_three_columns(self) -> None:
        """_build_metrics_table has columns: Level, Key Metric, Value."""
        from ces.cli.status_cmd import _build_metrics_table

        table = _build_metrics_table({})
        column_headers = [col.header for col in table.columns]
        assert "Level" in column_headers
        assert "Key Metric" in column_headers
        assert "Value" in column_headers

    def test_float_formatting(self) -> None:
        """Float values are formatted with 2 decimal places."""
        from ces.cli.status_cmd import _build_metrics_table

        summaries = {"agent": {"avg_error_rate": 0.12345}}
        table = _build_metrics_table(summaries)
        # Find the Agent row
        for row_idx in range(table.row_count):
            cells = [col._cells[row_idx] for col in table.columns]
            if "Agent" in cells[0]:
                assert "0.12" in cells[2]
                break


class TestBuildVerboseMetricsTable:
    """Tests for _build_verbose_metrics_table function."""

    def test_returns_table_with_detail_title(self) -> None:
        """_build_verbose_metrics_table returns table with 'Telemetry Detail' in title."""
        from ces.cli.status_cmd import _build_verbose_metrics_table

        table = _build_verbose_metrics_table({})
        assert "Telemetry Detail" in table.title

    def test_includes_metric_values(self) -> None:
        """_build_verbose_metrics_table includes metric values in table rows."""
        from ces.cli.status_cmd import _build_verbose_metrics_table

        summaries = {"task": {"total_tokens": 1500, "avg_wall_clock_seconds": 12.5}}
        table = _build_verbose_metrics_table(summaries)
        # Check that values appear in the table
        all_cells = []
        for col in table.columns:
            for cell in col._cells:
                all_cells.append(str(cell))
        assert any("1500" in c for c in all_cells), f"Expected '1500' in cells: {all_cells}"
        assert any("12.5" in c for c in all_cells), f"Expected '12.5' in cells: {all_cells}"

    def test_has_three_columns(self) -> None:
        """_build_verbose_metrics_table has Level, Metric, Value columns."""
        from ces.cli.status_cmd import _build_verbose_metrics_table

        table = _build_verbose_metrics_table({})
        column_headers = [col.header for col in table.columns]
        assert "Level" in column_headers
        assert "Metric" in column_headers
        assert "Value" in column_headers


class TestGatherStatusDataTelemetry:
    """Tests for telemetry_summary in _gather_status_data."""

    @pytest.mark.asyncio
    async def test_local_status_view_returns_empty_telemetry_summary(self) -> None:
        """The local status view keeps telemetry_summary as an empty dict."""
        from ces.cli.status_cmd import _gather_status_data

        mock_services = _make_mock_services()
        data = await _gather_status_data(
            mock_services,
            project_id="test",
            project_config={},
        )

        assert "telemetry_summary" in data
        assert data["telemetry_summary"] == {}


class TestShowStatusVerboseOption:
    """Test that show_status has a --verbose option."""

    def test_verbose_option_exists(self) -> None:
        """show_status command accepts --verbose flag."""
        import inspect

        from ces.cli.status_cmd import show_status

        # Check the wrapped function's parameters
        # The run_async decorator wraps the function, check the original
        inner = show_status.__wrapped__ if hasattr(show_status, "__wrapped__") else show_status
        sig = inspect.signature(inner)
        param_names = list(sig.parameters.keys())
        assert "verbose" in param_names, f"Expected 'verbose' in params, got {param_names}"

    def test_status_with_verbose_flag(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces status --verbose runs without error."""
        monkeypatch.chdir(ces_project)
        mock_services = _make_mock_services()

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["status", "--verbose"])

        assert result.exit_code == 0, f"stdout={result.stdout}\nexc={result.exception}"
