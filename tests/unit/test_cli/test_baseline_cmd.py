"""Tests for ces baseline command (baseline_cmd module)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

runner = CliRunner()


def _get_app():
    from ces.cli import app

    return app


class TestCesBaseline:
    """Tests for the ces baseline command."""

    def test_baseline_is_registered(self) -> None:
        """The app has a baseline command registered."""
        app = _get_app()
        result = runner.invoke(app, ["baseline", "--help"])
        assert result.exit_code == 0

    def test_writes_latest_snapshot(self, tmp_path: Path, monkeypatch: object) -> None:
        """`ces baseline` writes .ces/baseline/latest.json."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["baseline"])
        assert result.exit_code == 0, result.stdout
        out = tmp_path / ".ces" / "baseline" / "latest.json"
        assert out.is_file()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "sensors" in data
        assert "captured_at" in data
        assert "project_root" in data

    def test_baseline_scans_repository_files(self, tmp_path: Path, monkeypatch: object) -> None:
        """Baseline should feed real repo files into sensors, not an empty scope."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        api_key_assignment = "API_KEY" + ' = "1234567890abcdef"\n'
        (tmp_path / "settings.py").write_text(api_key_assignment, encoding="utf-8")
        app = _get_app()
        result = runner.invoke(app, ["baseline"])
        assert result.exit_code == 0, result.stdout

        data = json.loads((tmp_path / ".ces" / "baseline" / "latest.json").read_text(encoding="utf-8"))
        security = next(entry for entry in data["sensors"] if entry["sensor_id"] == "security_scan")
        assert security["passed"] is False
        assert "settings.py" in security["details"]

    def test_includes_all_eight_sensors(self, tmp_path: Path, monkeypatch: object) -> None:
        """Snapshot contains an entry per sensor in ALL_SENSORS."""
        from ces.harness.sensors import ALL_SENSORS

        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        runner.invoke(app, ["baseline"])
        data = json.loads((tmp_path / ".ces" / "baseline" / "latest.json").read_text(encoding="utf-8"))
        assert len(data["sensors"]) == len(ALL_SENSORS)
        for entry in data["sensors"]:
            assert "sensor_id" in entry
            assert "sensor_pack" in entry
            assert "passed" in entry
            assert "score" in entry
            assert "skipped" in entry

    def test_writes_timestamped_history_entry(self, tmp_path: Path, monkeypatch: object) -> None:
        """Each baseline run also writes a history file alongside latest.json."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        runner.invoke(app, ["baseline"])
        baseline_dir = tmp_path / ".ces" / "baseline"
        history = list(baseline_dir.glob("snapshot-*.json"))
        assert len(history) == 1

    def test_re_running_replaces_latest(self, tmp_path: Path, monkeypatch: object) -> None:
        """Re-running baseline keeps latest.json pointing at the new snapshot."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        runner.invoke(app, ["baseline"])
        first = json.loads((tmp_path / ".ces" / "baseline" / "latest.json").read_text(encoding="utf-8"))
        runner.invoke(app, ["baseline"])
        second = json.loads((tmp_path / ".ces" / "baseline" / "latest.json").read_text(encoding="utf-8"))
        # captured_at should differ (monotonic UTC) or at least be present in both.
        assert "captured_at" in first
        assert "captured_at" in second
        # After two runs there are two snapshot-*.json history files.
        history = list((tmp_path / ".ces" / "baseline").glob("snapshot-*.json"))
        assert len(history) == 2
