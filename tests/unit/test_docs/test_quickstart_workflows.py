"""Quickstart workflow documentation contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_quickstart_documents_greenfield_and_brownfield_e2e_flows() -> None:
    quickstart = (ROOT / "docs" / "Quickstart.md").read_text(encoding="utf-8")

    assert "Greenfield flow (idea → build → verify → proof)" in quickstart
    assert (
        'ces build --from-scratch "Create a small task tracker app with add/list/complete tasks, tests, and a README"'
        in quickstart
    )
    assert "ces verify" in quickstart
    assert "ces proof" in quickstart

    assert "Brownfield flow (existing repo → bounded change)" in quickstart
    assert "ces mri" in quickstart
    assert "ces next" in quickstart
    assert 'ces build "Add invoice notes to CSV exports"' in quickstart


def test_readme_beginner_paths_and_quality_gates_are_explicit() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "### 1. Install CES" in readme
    assert "## Greenfield project: create a new project from scratch" in readme
    assert "## Brownfield project: apply CES to an existing project" in readme
    assert "## Quality gates: how to know it worked" in readme
    assert "Do not approve because the agent says it is done" in readme
    assert "--accept-runtime-side-effects" in readme


def test_scenario_matrix_and_friction_log_exist() -> None:
    matrix = (ROOT / "docs" / "scenario-matrix.md").read_text(encoding="utf-8")
    friction = (ROOT / "docs" / "friction-log.md").read_text(encoding="utf-8")

    assert "Greenfield scenarios" in matrix
    assert "Brownfield scenarios" in matrix
    assert "Agent-quality scenarios" in matrix
    assert "FL-007" in friction
    assert "FL-008" in friction
