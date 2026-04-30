"""Tests for `ces build --from-spec` preview mode."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from ces.cli import app

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "specs"


def _patch_services(overrides):
    @asynccontextmanager
    async def fake(*args, **kwargs):
        yield overrides

    return fake


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _mock_manifest(
    manifest_id: str,
    story_id: str,
    spec_id: str = "SP-01HXY",
    description: str = "Add route",
    depends_on: tuple[str, ...] = (),
) -> MagicMock:
    mf = MagicMock()
    mf.manifest_id = manifest_id
    mf.parent_spec_id = spec_id
    mf.parent_story_id = story_id
    mf.description = description
    mf.acceptance_criteria = ("works",)
    deps = []
    for dep_id in depends_on:
        dep = MagicMock()
        dep.artifact_id = dep_id
        deps.append(dep)
    mf.dependencies = tuple(deps)
    return mf


def test_build_from_spec_prints_manifests_in_topological_order(runner, tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text((FIXTURES / "minimal-valid.md").read_text(encoding="utf-8"))

    mf = _mock_manifest("M-01", "ST-01HXY")
    manager = MagicMock()
    manager.list_by_spec = AsyncMock(return_value=[mf])

    with patch(
        "ces.cli.run_cmd.get_services",
        new=_patch_services({"manifest_manager": manager}),
    ):
        result = runner.invoke(app, ["build", "--from-spec", str(spec)])
    assert result.exit_code == 0, result.stdout
    assert "ST-01HXY" in result.stdout
    assert "M-01" in result.stdout


def test_build_from_spec_honors_topological_dependencies(runner, tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text((FIXTURES / "minimal-valid.md").read_text(encoding="utf-8"))

    # Three manifests with a chain: A independent, B depends on A, C depends on B.
    mf_a = _mock_manifest("M-A", "ST-A", description="A")
    mf_b = _mock_manifest("M-B", "ST-B", description="B", depends_on=("M-A",))
    mf_c = _mock_manifest("M-C", "ST-C", description="C", depends_on=("M-B",))

    manager = MagicMock()
    # Intentionally return them in wrong order.
    manager.list_by_spec = AsyncMock(return_value=[mf_c, mf_a, mf_b])

    with patch(
        "ces.cli.run_cmd.get_services",
        new=_patch_services({"manifest_manager": manager}),
    ):
        result = runner.invoke(app, ["build", "--from-spec", str(spec)])
    assert result.exit_code == 0, result.stdout
    # In the output, A must appear before B, B before C.
    pos_a = result.stdout.index("ST-A")
    pos_b = result.stdout.index("ST-B")
    pos_c = result.stdout.index("ST-C")
    assert pos_a < pos_b < pos_c


def test_build_from_spec_filters_by_story(runner, tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text((FIXTURES / "minimal-valid.md").read_text(encoding="utf-8"))

    mf_a = _mock_manifest("M-A", "ST-A", description="A")
    mf_b = _mock_manifest("M-B", "ST-B", description="B", depends_on=("M-A",))

    manager = MagicMock()
    manager.list_by_spec = AsyncMock(return_value=[mf_a, mf_b])

    with patch(
        "ces.cli.run_cmd.get_services",
        new=_patch_services({"manifest_manager": manager}),
    ):
        result = runner.invoke(app, ["build", "--from-spec", str(spec), "--story", "ST-B"])
    assert result.exit_code == 0, result.stdout
    assert "ST-B" in result.stdout
    # ST-A should NOT appear because we filtered to ST-B only.
    assert "ST-A" not in result.stdout
