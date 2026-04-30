"""Deterministic spec -> TaskManifest expansion. No LLM.

Turns a parsed ``SpecDocument`` into a tuple of draft ``TaskManifest``
instances — one per ``Story``. Dependencies between stories are resolved
into ``ManifestDependency`` edges using the freshly-minted manifest IDs
(so the invalidation graph can follow story dependencies).

LLM-05 compliant: classification is performed via
``ClassificationOracle.classify_from_hints`` on the spec's ``SignalHints``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from ces.control.models.manifest import ManifestDependency, TaskManifest
from ces.control.models.oracle_result import OracleClassificationResult
from ces.control.models.spec import SpecDocument, Story
from ces.control.services.classification_oracle import ClassificationOracle
from ces.control.spec.template_loader import TemplateLoader
from ces.shared.base import CESBaseModel
from ces.shared.enums import ArtifactStatus, WorkflowState


class DecomposeResult(CESBaseModel):
    """Result of ``SpecDecomposer.decompose()``.

    Wraps the produced manifests in a frozen tuple to match the CES
    ``CESBaseModel`` convention.
    """

    manifests: tuple[TaskManifest, ...]


_DEFAULT_TOKEN_BUDGET = 100_000
# ManifestDependency.artifact_type is typed `str`; no ArtifactType enum exists
# today. Use a named constant so the single call site is easy to find if an
# enum is introduced later.
_STORY_DEP_ARTIFACT_TYPE = "spec_story"
# Placeholder content hash for inter-story dependencies. The real content hash
# is computed by the persistence layer when both sides exist; decomposition
# operates on transient drafts, so a stable synthetic value is correct here.
_STORY_DEP_PLACEHOLDER_HASH = "0" * 64


def _new_manifest_id() -> str:
    """Generate a fresh manifest ID with the ``M-`` prefix."""
    return f"M-{uuid.uuid4().hex[:12].upper()}"


class SpecDecomposer:
    """Expand a ``SpecDocument`` into draft ``TaskManifest`` instances.

    One manifest per story. Cross-story ``depends_on`` edges are mapped to
    ``ManifestDependency`` records keyed by the target story's freshly
    minted manifest_id.
    """

    def __init__(
        self,
        template_loader: TemplateLoader,
        oracle: ClassificationOracle | None = None,
    ) -> None:
        # _loader is reserved for template-specific decompose rules in a later phase.
        self._loader = template_loader
        self._oracle = oracle or ClassificationOracle()

    def decompose(self, doc: SpecDocument) -> DecomposeResult:
        story_to_manifest_id: dict[str, str] = {s.story_id: _new_manifest_id() for s in doc.stories}
        manifests = tuple(
            self._story_to_manifest(
                story=s,
                spec=doc,
                manifest_id=story_to_manifest_id[s.story_id],
                id_lookup=story_to_manifest_id,
            )
            for s in doc.stories
        )
        return DecomposeResult(manifests=manifests)

    def _story_to_manifest(
        self,
        story: Story,
        spec: SpecDocument,
        manifest_id: str,
        id_lookup: dict[str, str],
    ) -> TaskManifest:
        oracle_result: OracleClassificationResult = self._oracle.classify_from_hints(
            signals=spec.frontmatter.signals,
            risk_hint=story.risk,
        )
        rule = oracle_result.matched_rule
        if rule is None:
            msg = "classify_from_hints returned no matched rule"
            raise RuntimeError(msg)
        created = datetime.now(tz=timezone.utc)
        return TaskManifest(
            version=1,
            status=ArtifactStatus.DRAFT,
            owner=spec.frontmatter.owner,
            created_at=created,
            last_confirmed=created,
            manifest_id=manifest_id,
            description=f"{story.title}\n\n{story.description}",
            risk_tier=rule.risk_tier,
            behavior_confidence=rule.behavior_confidence,
            change_class=rule.change_class,
            affected_files=(),
            token_budget=_DEFAULT_TOKEN_BUDGET,
            dependencies=tuple(
                ManifestDependency(
                    artifact_id=id_lookup[dep],
                    artifact_type=_STORY_DEP_ARTIFACT_TYPE,
                    content_hash=_STORY_DEP_PLACEHOLDER_HASH,
                )
                for dep in story.depends_on
                if dep in id_lookup
            ),
            expires_at=created + TaskManifest.default_ttl(rule.risk_tier),
            workflow_state=WorkflowState.QUEUED,
            parent_spec_id=spec.frontmatter.spec_id,
            parent_story_id=story.story_id,
            acceptance_criteria=story.acceptance_criteria,
        )
