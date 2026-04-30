"""Read-only view of a spec's stories joined with manifest workflow state.

Consumed by ``ces spec tree`` to render a hierarchy of:

    Spec (SP-...)
    +-- Story ST-A (manifest M-...) [queued]
    +-- Story ST-B (not decomposed)

The join is performed in-process against ``ManifestManager.list_by_spec``.
Control-plane, deterministic, no LLM -- per LLM-05.
"""

from __future__ import annotations

from ces.control.models.spec import SpecDocument
from ces.control.services.manifest_manager import ManifestManager
from ces.shared.base import CESBaseModel


class SpecTreeNode(CESBaseModel):
    """One node in the rendered spec tree -- one per story in the spec.

    ``manifest_id`` / ``status_label`` are populated when the story has been
    decomposed into a manifest. Otherwise ``manifest_id`` is ``None`` and
    ``status_label`` is the sentinel ``"not decomposed"``.
    """

    story_id: str
    story_title: str
    manifest_id: str | None
    status_label: str
    blocked_by: tuple[str, ...]


class SpecTree:
    """Project a spec's stories onto manifest workflow state.

    Pure view layer: does not mutate manifests or the spec document.
    """

    def __init__(self, manifest_manager: ManifestManager) -> None:
        self._manager = manifest_manager

    async def render(self, doc: SpecDocument) -> tuple[SpecTreeNode, ...]:
        """Return one ``SpecTreeNode`` per story in spec declaration order.

        Performs a single ``list_by_spec`` round-trip and indexes the
        result by ``parent_story_id`` -- O(stories + manifests), no N+1.
        """
        manifests = await self._manager.list_by_spec(doc.frontmatter.spec_id)
        # If a story has multiple manifests (shouldn't happen -- validator +
        # reconciler prevent duplicates -- but be explicit): dict comprehension
        # keeps the last.
        manifest_by_story = {m.parent_story_id: m for m in manifests if m.parent_story_id is not None}
        nodes: list[SpecTreeNode] = []
        for story in doc.stories:
            mf = manifest_by_story.get(story.story_id)
            if mf is None:
                nodes.append(
                    SpecTreeNode(
                        story_id=story.story_id,
                        story_title=story.title,
                        manifest_id=None,
                        status_label="not decomposed",
                        blocked_by=story.depends_on,
                    )
                )
            else:
                nodes.append(
                    SpecTreeNode(
                        story_id=story.story_id,
                        story_title=story.title,
                        manifest_id=mf.manifest_id,
                        status_label=mf.workflow_state.value,
                        blocked_by=story.depends_on,
                    )
                )
        return tuple(nodes)
