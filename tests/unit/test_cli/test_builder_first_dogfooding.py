"""Builder-first dogfooding regressions for the default CES loop."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.builder_scenarios import (
    BROWNFIELD_RETRY_SCENARIO,
    GREENFIELD_SCENARIO,
    BuilderScenarioHarness,
)


@pytest.fixture(autouse=True)
def _reset_json_mode():
    from ces.cli._output import set_json_mode

    set_json_mode(False)
    yield
    set_json_mode(False)


class TestBuilderFirstDogfooding:
    def test_greenfield_builder_loop_guides_the_next_task_after_completion(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        harness = BuilderScenarioHarness(tmp_path=tmp_path, monkeypatch=monkeypatch)

        result = harness.run(GREENFIELD_SCENARIO)

        assert result.build.exit_code == 0, f"stdout={result.build.stdout}"
        assert "Build Review Complete" in result.build.stdout
        assert result.explain.exit_code == 0, f"stdout={result.explain.stdout}"
        assert "Build a habit tracker" in result.explain.stdout
        assert "Start a new task with `ces build`" in result.explain.stdout
        assert result.status.exit_code == 0, f"stdout={result.status.stdout}"
        assert "Build a habit tracker" in result.status.stdout
        assert "Start a new task with `ces build`" in result.status.stdout
        assert result.continue_.exit_code != 0
        assert "already completed" in result.continue_.stdout.lower()
        assert "Start a new task" in result.continue_.stdout

    def test_brownfield_builder_loop_retries_runtime_without_replaying_review(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        harness = BuilderScenarioHarness(tmp_path=tmp_path, monkeypatch=monkeypatch)

        result = harness.run(BROWNFIELD_RETRY_SCENARIO)

        assert result.build.exit_code != 0
        assert "exited with code 1" in result.build.stdout
        assert result.explain.exit_code == 0, f"stdout={result.explain.stdout}"
        assert "Modernize billing exports" in result.explain.stdout
        assert "Retry the last runtime execution with `ces continue`." in result.explain.stdout
        assert result.status.exit_code == 0, f"stdout={result.status.stdout}"
        assert "Modernize billing exports" in result.status.stdout
        assert "Retry the last runtime execution with `ces continue`." in result.status.stdout
        assert result.continue_.exit_code == 0, f"stdout={result.continue_.stdout}"
        assert "Build Review Complete" in result.continue_.stdout
        assert result.runtime_retry_preserved_review_count
        assert result.final_explain is not None
        assert result.final_explain.exit_code == 0, f"stdout={result.final_explain.stdout}"
        assert "Start a new task with `ces build`" in result.final_explain.stdout
        assert result.final_status is not None
        assert result.final_status.exit_code == 0, f"stdout={result.final_status.stdout}"
        assert "Start a new task with `ces build`" in result.final_status.stdout
