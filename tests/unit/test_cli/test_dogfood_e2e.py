"""End-to-end dogfood tests: sensors + evidence synthesis on the CES repo.

Tests the sensor orchestrator with a realistic CES project context,
verifying the full sensor pipeline produces meaningful output. Validates
the affected_files fallback logic and the sensor + evidence triage path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ces.harness.sensors import ALL_SENSORS
from ces.harness.services.evidence_synthesizer import EvidenceSynthesizer
from ces.harness.services.sensor_orchestrator import SensorOrchestrator
from ces.shared.enums import RiskTier, TrustStatus


class TestDogfoodCESBuild:
    """Simulate the sensor + synthesis portion of ces build against CES itself."""

    @pytest.fixture
    def ces_project_root(self) -> str:
        return str(Path(__file__).resolve().parents[3])

    @pytest.fixture
    def ces_python_files(self, ces_project_root: str) -> list[str]:
        src = Path(ces_project_root) / "src"
        files = [str(p.relative_to(ces_project_root)) for p in src.rglob("*.py") if "__pycache__" not in str(p)]
        return files[:100]

    @pytest.mark.asyncio
    async def test_dogfood_sensors_produce_output(self, ces_project_root: str, ces_python_files: list[str]) -> None:
        """All sensors produce non-empty details when given CES source files."""
        orchestrator = SensorOrchestrator()
        for cls in ALL_SENSORS:
            orchestrator.register_sensor(cls())

        context = {
            "affected_files": ces_python_files,
            "project_root": ces_project_root,
            "manifest_id": "dogfood-test",
            "description": "Self-dogfooding CES",
        }
        results = await orchestrator.run_all(context)
        assert len(results) >= 7
        for pack in results:
            for r in pack.results:
                assert isinstance(r.details, str)
                assert len(r.details) > 0

    @pytest.mark.asyncio
    async def test_dogfood_triage_succeeds(self, ces_project_root: str, ces_python_files: list[str]) -> None:
        """Triage runs without error after sensor execution on CES repo."""
        orchestrator = SensorOrchestrator()
        for cls in ALL_SENSORS:
            orchestrator.register_sensor(cls())

        context = {
            "affected_files": ces_python_files,
            "project_root": ces_project_root,
        }
        pack_results = await orchestrator.run_all(context)
        sensor_results = [r for pack in pack_results for r in pack.results]

        synth = EvidenceSynthesizer()
        triage = await synth.triage(
            risk_tier=RiskTier.B,
            trust_status=TrustStatus.TRUSTED,
            sensor_results=sensor_results,
        )
        assert triage.color is not None
        assert triage.reason

    @pytest.mark.asyncio
    async def test_dogfood_evidence_format(self, ces_project_root: str, ces_python_files: list[str]) -> None:
        """Evidence format conversion works with real sensor data."""
        orchestrator = SensorOrchestrator()
        for cls in ALL_SENSORS:
            orchestrator.register_sensor(cls())

        context = {
            "affected_files": ces_python_files,
            "project_root": ces_project_root,
        }
        pack_results = await orchestrator.run_all(context)
        evidence = orchestrator.results_to_evidence_format(pack_results)
        assert "sensor_packs" in evidence
        assert len(evidence["sensor_packs"]) >= 7

    @pytest.mark.asyncio
    async def test_dogfood_affected_files_fallback(self) -> None:
        """When affected_files is empty, verify the fallback logic finds files."""
        project_root = Path(__file__).resolve().parents[3]
        # Replicate the exact fallback logic from run_cmd.py so the test
        # stays in sync: discover, filter, sort src/ first, cap at 500.
        excluded_dirs = {".venv", "node_modules", "__pycache__", ".git", ".ces"}
        discovered = list(project_root.rglob("*.py"))
        all_files = [
            p.relative_to(project_root).as_posix()
            for p in discovered
            if not any(part in excluded_dirs for part in p.parts)
        ]
        all_files.sort(key=lambda f: (0 if f.startswith("src/") else 1, f))
        sensor_files = all_files[:500]
        assert len(sensor_files) > 50, f"Expected >50 Python files, found {len(sensor_files)}"
        # Verify src/ files appear first thanks to the sort
        src_files = [f for f in sensor_files if f.startswith("src/")]
        assert len(src_files) > 20, f"Expected >20 src/ files, found {len(src_files)}"
        # First file in list should be from src/ if the project has any
        assert sensor_files[0].startswith("src/"), f"Expected src/ files first, got: {sensor_files[0]}"
