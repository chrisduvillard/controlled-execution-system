"""Implementation of the ``ces baseline`` command.

Runs every sensor pack in ``ALL_SENSORS`` against the current
repository and persists the results as a day-0 snapshot under
``.ces/baseline/``. Subsequent runs write fresh snapshots and keep
``latest.json`` pointing at the most recent one so regression
comparisons later can diff against a known reference.

No LLM calls. Deterministic: only the sensors' own heuristics.

Exports:
    baseline: Typer command function for ``ces baseline``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rich.panel import Panel

from ces.cli._async import run_async
from ces.cli._output import console
from ces.harness.sensors import ALL_SENSORS

_EXCLUDED_DIRS = {".git", ".ces", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
_MAX_BASELINE_FILES = 500


def _discover_repo_files(project_root: Path) -> list[str]:
    files: list[str] = []
    for path in sorted(project_root.rglob("*")):
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(project_root)
        except ValueError:
            continue
        if any(part in _EXCLUDED_DIRS for part in relative.parts):
            continue
        files.append(relative.as_posix())
        if len(files) >= _MAX_BASELINE_FILES:
            break
    return files


def _serialize_sensor_result(result: object) -> dict[str, object]:
    """Convert a SensorResult into a JSON-safe dict."""
    return {
        "sensor_id": result.sensor_id,  # type: ignore[attr-defined]
        "sensor_pack": result.sensor_pack,  # type: ignore[attr-defined]
        "passed": bool(result.passed),  # type: ignore[attr-defined]
        "score": float(result.score),  # type: ignore[attr-defined]
        "details": str(result.details),  # type: ignore[attr-defined]
        "skipped": bool(getattr(result, "skipped", False)),
        "skip_reason": getattr(result, "skip_reason", None),
        "timestamp": result.timestamp.isoformat(),  # type: ignore[attr-defined]
    }


async def _run_all_sensors(project_root: Path) -> list[dict[str, object]]:
    """Instantiate and run every sensor in ALL_SENSORS, returning dicts."""
    context = {"project_root": str(project_root), "affected_files": _discover_repo_files(project_root)}
    entries: list[dict[str, object]] = []
    for sensor_cls in ALL_SENSORS:
        sensor = sensor_cls()
        result = await sensor.run(context)
        entries.append(_serialize_sensor_result(result))
    return entries


@run_async
async def baseline() -> None:
    """Capture a day-0 sensor snapshot for the current repository.

    Writes ``.ces/baseline/snapshot-<utc-iso>.json`` and updates
    ``.ces/baseline/latest.json`` to mirror it. Sensors that have no
    data to operate on (e.g., no coverage.json yet) self-skip and are
    recorded as such rather than treated as failures.
    """
    project_root = Path.cwd().resolve()
    entries = await _run_all_sensors(project_root)

    captured_at = datetime.now(timezone.utc)
    snapshot = {
        "project_root": str(project_root),
        "captured_at": captured_at.isoformat(),
        "sensors": entries,
    }

    baseline_dir = project_root / ".ces" / "baseline"
    baseline_dir.mkdir(parents=True, exist_ok=True)

    # Filename-safe timestamp with microseconds so rapid re-runs
    # (including test suites) produce distinct history entries.
    stamp = captured_at.strftime("%Y%m%dT%H%M%S") + f"{captured_at.microsecond:06d}Z"
    history_path = baseline_dir / f"snapshot-{stamp}.json"
    latest_path = baseline_dir / "latest.json"

    payload = json.dumps(snapshot, indent=2) + "\n"
    history_path.write_text(payload, encoding="utf-8")
    latest_path.write_text(payload, encoding="utf-8")

    skipped = sum(1 for e in entries if e["skipped"])
    passed = sum(1 for e in entries if e["passed"] and not e["skipped"])
    failed = len(entries) - skipped - passed

    console.print(
        Panel(
            f"Captured sensor snapshot for [bold]{project_root}[/bold]\n"
            f"  sensors:  {len(entries)}  (passed={passed} skipped={skipped} failed={failed})\n"
            f"  snapshot: {history_path}\n"
            f"  latest:   {latest_path}",
            title="[green]Baseline captured[/green]",
            border_style="green",
        )
    )
