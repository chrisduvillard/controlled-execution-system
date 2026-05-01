"""Scenario-harness regressions for the builder-first CES loop."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.builder_scenarios import (
    BROWNFIELD_RETRY_SCENARIO,
    GREENFIELD_SCENARIO,
    BuilderScenarioHarness,
    materialize_builder_fixture,
)


@pytest.fixture(autouse=True)
def _reset_json_mode():
    from ces.cli._output import set_json_mode

    set_json_mode(False)
    yield
    set_json_mode(False)


def test_materialize_fixture_copies_brownfield_repo_template(tmp_path: Path) -> None:
    target = tmp_path / "repo"

    materialize_builder_fixture("brownfield-billing", target)

    assert (target / "billing_export.py").is_file()
    assert (target / "README.md").is_file()
    assert "export" in (target / "README.md").read_text(encoding="utf-8").lower()


def test_greenfield_scenario_exercises_full_builder_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    harness = BuilderScenarioHarness(tmp_path=tmp_path, monkeypatch=monkeypatch)

    result = harness.run(GREENFIELD_SCENARIO)

    assert result.build.exit_code == 0, f"stdout={result.build.stdout}"
    assert "Build Review Complete" in result.build.stdout
    assert result.explain.exit_code == 0, f"stdout={result.explain.stdout}"
    assert "Start a new task with `ces build`" in result.explain.stdout
    assert result.status.exit_code == 0, f"stdout={result.status.stdout}"
    assert "Start a new task with `ces build`" in result.status.stdout
    assert result.continue_.exit_code == 0
    assert "already completed" in result.continue_.stdout.lower()


def test_brownfield_retry_scenario_exercises_retry_loop_without_replaying_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = BuilderScenarioHarness(tmp_path=tmp_path, monkeypatch=monkeypatch)

    result = harness.run(BROWNFIELD_RETRY_SCENARIO)

    assert result.build.exit_code != 0
    assert "exited with code 1" in result.build.stdout
    assert result.explain.exit_code == 0, f"stdout={result.explain.stdout}"
    assert "Retry the last runtime execution with `ces continue`." in result.explain.stdout
    assert result.status.exit_code == 0, f"stdout={result.status.stdout}"
    assert "Retry the last runtime execution with `ces continue`." in result.status.stdout
    assert result.continue_.exit_code == 0, f"stdout={result.continue_.stdout}"
    assert "Build Review Complete" in result.continue_.stdout
    assert result.final_explain is not None
    assert "Start a new task with `ces build`" in result.final_explain.stdout
    assert result.final_status is not None
    assert "Start a new task with `ces build`" in result.final_status.stdout
    assert result.runtime_retry_preserved_review_count
