"""Diff a SpecDocument against already-decomposed manifest story ids."""

from __future__ import annotations

from ces.control.models.spec import SpecDocument
from ces.control.spec.template_loader import TemplateLoader
from ces.shared.base import CESBaseModel


class ReconcileReport(CESBaseModel):
    added: tuple[str, ...]  # story_ids in spec but not yet decomposed
    orphaned: tuple[str, ...]  # story_ids with manifests but no spec entry
    unchanged: tuple[str, ...]  # story_ids present in both


class SpecReconciler:
    """Diffs a parsed spec against the story ids of already-persisted manifests."""

    def __init__(self, template_loader: TemplateLoader) -> None:
        # Stored for future template-specific reconcile rules; unused today.
        self._loader = template_loader

    def reconcile(
        self,
        doc: SpecDocument,
        existing_manifest_story_ids: frozenset[str],
    ) -> ReconcileReport:
        spec_ids = {s.story_id for s in doc.stories}
        added = tuple(sorted(spec_ids - existing_manifest_story_ids))
        orphaned = tuple(sorted(existing_manifest_story_ids - spec_ids))
        unchanged = tuple(sorted(spec_ids & existing_manifest_story_ids))
        return ReconcileReport(added=added, orphaned=orphaned, unchanged=unchanged)
