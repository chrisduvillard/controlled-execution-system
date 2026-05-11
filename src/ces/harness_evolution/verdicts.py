"""File IO helpers for harness change verdict computation."""

from __future__ import annotations

import json
from pathlib import Path

from ces.harness_evolution.trajectory import TrajectoryReport


def read_trajectory_report(path: Path) -> TrajectoryReport:
    """Read a structured trajectory report JSON file."""

    return TrajectoryReport.model_validate(json.loads(path.read_text(encoding="utf-8")))
