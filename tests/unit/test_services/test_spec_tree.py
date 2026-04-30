"""Unit tests for SpecTree: read-only join of spec stories x manifest status."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from ces.control.models.spec import (
    Risk,
    SignalHints,
    SpecDocument,
    SpecFrontmatter,
    Story,
)
from ces.control.spec.tree import SpecTree, SpecTreeNode
from ces.shared.enums import WorkflowState


def _sample_doc() -> SpecDocument:
    return SpecDocument(
        frontmatter=SpecFrontmatter(
            spec_id="SP-TREE",
            title="Tree test",
            owner="a@b.c",
            created_at=datetime(2026, 4, 21, tzinfo=timezone.utc),
            status="draft",
            signals=SignalHints(
                primary_change_class="feature",
                blast_radius_hint="isolated",
            ),
        ),
        problem="p",
        users="u",
        success_criteria=("s",),
        non_goals=("n",),
        risks=(Risk(risk="r", mitigation="m"),),
        stories=(
            Story(
                story_id="ST-A",
                title="Add A",
                description="desc",
                acceptance_criteria=("works",),
                size="S",
            ),
        ),
        rollback_plan="rb",
    )


@pytest.mark.asyncio
async def test_tree_renders_node_per_story_with_manifest_status() -> None:
    """Each story becomes a node carrying its matching manifest's workflow state."""
    doc = _sample_doc()
    # Build a mock manifest that matches the story.
    mf = MagicMock()
    mf.manifest_id = "M-ABC"
    mf.parent_spec_id = "SP-TREE"
    mf.parent_story_id = "ST-A"
    mf.workflow_state = WorkflowState.QUEUED

    manager = MagicMock()
    manager.list_by_spec = AsyncMock(return_value=[mf])

    tree = SpecTree(manager)
    nodes = await tree.render(doc)
    assert len(nodes) == 1
    node: SpecTreeNode = nodes[0]
    assert node.story_id == "ST-A"
    assert node.manifest_id == "M-ABC"
    assert node.status_label == "queued"
    # list_by_spec must be called with the spec id.
    manager.list_by_spec.assert_awaited_once_with("SP-TREE")


@pytest.mark.asyncio
async def test_tree_marks_undecomposed_story_as_not_decomposed() -> None:
    """Stories with no matching manifest surface a ``not decomposed`` label."""
    doc = _sample_doc()
    manager = MagicMock()
    manager.list_by_spec = AsyncMock(return_value=[])

    tree = SpecTree(manager)
    nodes = await tree.render(doc)
    assert nodes[0].manifest_id is None
    assert nodes[0].status_label == "not decomposed"
