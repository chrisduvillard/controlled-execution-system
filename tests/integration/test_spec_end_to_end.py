"""Exercise the full spec flow against a real ManifestManager."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from ces.control.spec.decomposer import SpecDecomposer
from ces.control.spec.parser import SpecParser
from ces.control.spec.reconciler import SpecReconciler
from ces.control.spec.template_loader import TemplateLoader
from ces.control.spec.tree import SpecTree
from ces.control.spec.validator import SpecValidator
from ces.shared.enums import WorkflowState

FIXTURES = Path(__file__).parent.parent / "fixtures" / "specs"


@pytest.mark.asyncio
async def test_author_validate_decompose_tree_flow(ces_project: Path) -> None:
    """Parser -> validator -> decomposer -> persistence -> tree -> reconciler.

    Uses a real ManifestManager (not mocks) via get_services() in local mode.
    """
    from ces.cli._factory import get_services

    spec_text = (FIXTURES / "minimal-valid.md").read_text(encoding="utf-8")
    loader = TemplateLoader(ces_project)
    parser = SpecParser(loader)
    validator = SpecValidator(loader)
    decomposer = SpecDecomposer(loader)

    doc = parser.parse(spec_text)
    validator.validate(doc)
    result = decomposer.decompose(doc)

    # Change CWD to ces_project so get_services() picks up the right root.
    original_cwd = os.getcwd()
    os.chdir(ces_project)
    try:
        async with get_services() as services:
            manager = services["manifest_manager"]
            for mf in result.manifests:
                await manager.save_manifest(mf)

            tree = SpecTree(manager)
            nodes = await tree.render(doc)
            assert len(nodes) == 1
            assert nodes[0].manifest_id is not None

            reconciler = SpecReconciler(loader)
            existing = frozenset({nodes[0].story_id})
            report = reconciler.reconcile(doc, existing)
            assert report.added == ()
            assert report.unchanged == (nodes[0].story_id,)
    finally:
        os.chdir(original_cwd)


@pytest.mark.asyncio
async def test_decompose_orders_dependencies_topologically(ces_project: Path) -> None:
    """Decomposed manifests feed into Kahn's sort with correct dependency edges.

    Diamond hierarchy: A <- {B, C} <- D. After decompose -> topo sort:
    A must come before B and C; B and C must come before D.
    """
    from ces.cli.run_cmd import _topological_sort_manifests

    loader = TemplateLoader(ces_project)
    doc = SpecParser(loader).parse((FIXTURES / "complex-hierarchy.md").read_text(encoding="utf-8"))
    result = SpecDecomposer(loader).decompose(doc)
    ordered = _topological_sort_manifests(list(result.manifests))
    by_story = {m.parent_story_id: i for i, m in enumerate(ordered)}
    # A before B/C; B and C before D.
    assert by_story["ST-A"] < by_story["ST-B"]
    assert by_story["ST-A"] < by_story["ST-C"]
    assert by_story["ST-B"] < by_story["ST-D"]
    assert by_story["ST-C"] < by_story["ST-D"]


@pytest.mark.asyncio
async def test_list_by_spec_includes_terminal_manifests(ces_project: Path) -> None:
    """Regression: list_by_spec must return merged/deployed/rejected manifests.

    Previously the repository branch fell through to ``get_active()`` which
    filters out terminal workflow states. After a story's manifest reached
    ``WorkflowState.MERGED``, ``ces spec reconcile`` would misclassify that
    story as "added" instead of "unchanged", producing false positives on
    every run for a team actively shipping.

    This test persists a merged manifest (constructed in the terminal state
    from the start, since ManifestManager has no public workflow-transition
    API) and asserts ``list_by_spec`` still returns it via the repository
    path (we clear the in-memory cache to force the DB lookup).
    """
    from ces.cli._factory import get_services
    from ces.control.spec.decomposer import SpecDecomposer
    from ces.control.spec.parser import SpecParser
    from ces.control.spec.template_loader import TemplateLoader

    spec_text = (FIXTURES / "minimal-valid.md").read_text(encoding="utf-8")
    loader = TemplateLoader(ces_project)
    doc = SpecParser(loader).parse(spec_text)
    result = SpecDecomposer(loader).decompose(doc)
    assert len(result.manifests) == 1, "minimal-valid.md has exactly one story"

    original_cwd = os.getcwd()
    os.chdir(ces_project)
    try:
        async with get_services() as services:
            manager = services["manifest_manager"]

            # Save a manifest already in a terminal workflow state to
            # simulate a story that has shipped end-to-end.
            merged_manifest = result.manifests[0].model_copy(update={"workflow_state": WorkflowState.MERGED})
            await manager.save_manifest(merged_manifest)

            # Force the repository lookup path so we prove terminal manifests
            # survive the DB round-trip; otherwise the in-memory cache alone
            # would mask the bug.
            manager._manifests = []

            matches = await manager.list_by_spec(doc.frontmatter.spec_id)
            assert len(matches) == 1
            assert matches[0].manifest_id == merged_manifest.manifest_id
            assert matches[0].workflow_state == WorkflowState.MERGED
            assert matches[0].parent_spec_id == doc.frontmatter.spec_id
    finally:
        os.chdir(original_cwd)


@pytest.mark.asyncio
async def test_round_trip_preserves_spec_provenance_through_local_store(
    ces_project: Path,
) -> None:
    """Round-trip: decompose -> save_manifest -> list_by_spec preserves provenance.

    Closes the gap where the JSONB serialization of the three new provenance
    fields (``parent_spec_id``, ``parent_story_id``, ``acceptance_criteria``)
    was never exercised end-to-end through ``LocalProjectStore``. This test
    decomposes a real spec, persists each manifest via the real
    ``ManifestManager.save_manifest`` (which writes JSON to SQLite), clears
    the in-memory cache to force a DB read, then asserts every provenance
    field made it back intact.
    """
    from ces.cli._factory import get_services

    spec_text = (FIXTURES / "minimal-valid.md").read_text(encoding="utf-8")
    loader = TemplateLoader(ces_project)
    doc = SpecParser(loader).parse(spec_text)
    SpecValidator(loader).validate(doc)
    result = SpecDecomposer(loader).decompose(doc)
    saved = list(result.manifests)
    assert saved, "decomposer produced no manifests"

    original_cwd = os.getcwd()
    os.chdir(ces_project)
    try:
        async with get_services() as services:
            manager = services["manifest_manager"]
            for mf in saved:
                await manager.save_manifest(mf)

            # Force the repository path so we're testing SQLite round-trip,
            # not the in-memory list.
            manager._manifests = []

            retrieved = await manager.list_by_spec(doc.frontmatter.spec_id)

        assert len(retrieved) == len(saved), f"expected {len(saved)} manifests from list_by_spec, got {len(retrieved)}"
        by_id = {m.manifest_id: m for m in retrieved}
        for original in saved:
            got = by_id.get(original.manifest_id)
            assert got is not None, f"manifest {original.manifest_id} missing after round-trip"
            assert got.parent_spec_id == original.parent_spec_id
            assert got.parent_story_id == original.parent_story_id
            assert got.acceptance_criteria == original.acceptance_criteria
    finally:
        os.chdir(original_cwd)
