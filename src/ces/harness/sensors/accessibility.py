"""Accessibility sensor pack.

CES is a CLI tool, not a web application. Accessibility checks for HTML/UI
files are informational only. Returns pass with explanatory details.
"""

from __future__ import annotations

from ces.harness.models.sensor_result import SensorFinding
from ces.harness.sensors._file_reader import filter_by_extension
from ces.harness.sensors.base import BaseSensor

_UI_EXTENSIONS = (".html", ".htm", ".jsx", ".tsx", ".vue", ".svelte")


class AccessibilitySensor(BaseSensor):
    """Accessibility sensor pack — informational for CLI tools.

    Sensor ID: a11y_check
    Sensor Pack: accessibility
    """

    def __init__(self) -> None:
        super().__init__(sensor_id="a11y_check", sensor_pack="accessibility")

    async def _execute(self, context: dict) -> tuple[bool, float, str]:
        affected_files: list[str] = context.get("affected_files", [])

        if not affected_files:
            self._mark_skipped("No files in scope")
            return (True, 1.0, "No files in scope for accessibility check")

        ui_files = filter_by_extension(affected_files, _UI_EXTENSIONS)
        if ui_files:
            self._findings.append(
                SensorFinding(
                    category="a11y_informational",
                    severity="info",
                    location="",
                    message=f"Found {len(ui_files)} UI file(s) -- accessibility review recommended",
                    suggestion="Run a11y audit tool (e.g., axe-core) on UI files",
                )
            )
            return (
                True,
                0.8,
                f"Found {len(ui_files)} UI file(s) — accessibility checks are informational only for this CLI project",
            )

        self._mark_skipped("No HTML/UI files in scope")
        return (
            True,
            1.0,
            "No HTML/UI files in scope; accessibility checks not applicable for CLI tool",
        )
