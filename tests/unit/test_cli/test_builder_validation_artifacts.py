"""Tests for exported builder validation artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.support.builder_scenarios import (
    BROWNFIELD_RETRY_SCENARIO,
    GREENFIELD_SCENARIO,
    BuilderScenarioHarness,
)
from tests.support.builder_validation import export_builder_validation_artifacts


@pytest.fixture(autouse=True)
def _reset_json_mode():
    from ces.cli._output import set_json_mode

    set_json_mode(False)
    yield
    set_json_mode(False)


def test_builder_validation_export_writes_markdown_and_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    greenfield_root = tmp_path / "greenfield"
    brownfield_root = tmp_path / "brownfield"
    output_dir = tmp_path / "artifacts"

    greenfield = BuilderScenarioHarness(
        tmp_path=greenfield_root,
        monkeypatch=monkeypatch,
    ).run(GREENFIELD_SCENARIO)
    brownfield = BuilderScenarioHarness(
        tmp_path=brownfield_root,
        monkeypatch=monkeypatch,
    ).run(BROWNFIELD_RETRY_SCENARIO)

    report = export_builder_validation_artifacts(
        output_dir=output_dir,
        milestone="v2.3",
        records=[
            (GREENFIELD_SCENARIO, greenfield),
            (BROWNFIELD_RETRY_SCENARIO, brownfield),
        ],
    )

    assert report.markdown_path.is_file()
    assert report.json_path.is_file()

    markdown = report.markdown_path.read_text(encoding="utf-8")
    assert "greenfield-habit-tracker" in markdown
    assert "brownfield-billing-retry" in markdown
    assert "Build a habit tracker" in markdown
    assert "Modernize billing exports" in markdown
    assert "approval" in markdown.lower()

    payload = json.loads(report.json_path.read_text(encoding="utf-8"))
    assert payload["milestone"] == "v2.3"
    assert len(payload["records"]) == 2
    assert payload["records"][0]["is_chain_complete"] is True
    assert payload["records"][1]["runtime_retry_preserved_review_count"] is True
