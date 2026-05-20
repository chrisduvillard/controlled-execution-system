"""Semantic review artifact orchestration service."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ces.review.artifacts import SemanticReviewArtifactStore
from ces.review.diff_index import build_diff_index, resolve_git_root
from ces.review.intent_coverage import build_intent_coverage
from ces.review.models import (
    AgentProvenance,
    DiffIndex,
    IntentCoverageMap,
    ReviewArtifactBundle,
    ReviewGenerationOptions,
    ReviewMetadata,
    ReviewPath,
    RiskMap,
    VerificationSummary,
)
from ces.review.provenance import load_agent_provenance, load_build_context
from ces.review.renderer import render_intent_coverage, render_review_brief, render_review_path
from ces.review.risk import build_review_path, build_risk_map
from ces.review.verification import load_verification_summary, verification_evidence_fingerprint


class SemanticReviewService:
    """Generate deterministic, local-first semantic review artifacts."""

    def generate(
        self,
        repo_root: Path,
        *,
        base_ref: str | None = None,
        head_ref: str | None = None,
        build_id: str | None = None,
        output_dir: Path | None = None,
        options: ReviewGenerationOptions | None = None,
    ) -> ReviewArtifactBundle:
        """Generate and persist a complete semantic review artifact bundle."""

        opts = options or ReviewGenerationOptions()
        if output_dir is not None:
            raise ValueError(
                "Custom semantic review output directories are not supported; artifacts are stored under .ces/reviews."
            )
        root = resolve_git_root(repo_root)
        diff_index = build_diff_index(
            root, base_ref=base_ref, head_ref=head_ref, include_untracked=opts.include_untracked
        )
        requested_build_id = build_id or opts.from_build
        build_context = None
        if requested_build_id:
            build_context = load_build_context(root, requested_build_id)
            if build_context is None:
                raise ValueError(f"No CES builder metadata matched build id: {requested_build_id}")
        effective_objective = opts.objective or _build_context_objective(build_context)
        extra_requirement_texts = _build_context_requirements(build_context)
        verification = load_verification_summary(root)
        risk_map = build_risk_map(diff_index, verification)
        review_path = build_review_path(risk_map)
        intent = build_intent_coverage(
            root,
            diff_index,
            verification,
            objective=effective_objective,
            deferred_scope=opts.deferred_scope,
            extra_requirement_texts=extra_requirement_texts,
        )
        provenance = load_agent_provenance(root, build_id=requested_build_id)
        metadata = ReviewMetadata(
            review_id=_review_id(diff_index),
            created_at=datetime.now(timezone.utc),
            repo_root=root.name or str(root),
            base_ref=diff_index.base_ref,
            head_ref=diff_index.head_ref,
            diff_fingerprint=diff_index.diff_fingerprint,
            verification_fingerprint=verification_evidence_fingerprint(root),
            ces_build_id=requested_build_id,
            build_id=requested_build_id,
            include_untracked=opts.include_untracked,
            generation_options={
                "include_untracked": opts.include_untracked,
                "objective": opts.objective,
                "effective_objective": effective_objective,
                "deferred_scope": list(opts.deferred_scope),
                "from_build": opts.from_build,
            },
        )
        store = SemanticReviewArtifactStore(root)
        bundle_dir = store.reviews_dir / metadata.review_id
        metadata = metadata.model_copy(update={"artifact_paths": store.artifact_paths_for(metadata)})
        bundle = ReviewArtifactBundle(
            metadata=metadata,
            root_path=bundle_dir,
            review_brief_path=bundle_dir / "review-brief.md",
            diff_index=diff_index,
            risk_map=risk_map,
            intent_coverage=intent,
            review_path=review_path,
            verification_summary=verification,
            agent_provenance=provenance,
        )
        review_brief = render_review_brief(bundle)
        return store.write_bundle(
            bundle,
            review_brief=review_brief,
            intent_coverage_markdown=render_intent_coverage(intent) + "\n",
            review_path_markdown=render_review_path(review_path),
        )

    def latest(self, repo_root: Path) -> ReviewArtifactBundle:
        """Load the latest semantic review bundle for a repository."""

        return SemanticReviewArtifactStore(repo_root).load_bundle()


def _review_id(diff_index: DiffIndex) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    return f"{stamp}-{diff_index.diff_fingerprint[:8]}"


def _build_context_objective(build_context: dict[str, object] | None) -> str | None:
    if not build_context:
        return None
    objective = build_context.get("objective")
    return objective if isinstance(objective, str) and objective.strip() else None


def _build_context_requirements(build_context: dict[str, object] | None) -> tuple[str, ...]:
    if not build_context:
        return ()
    texts = build_context.get("requirement_texts")
    if not isinstance(texts, tuple | list):
        return ()
    return tuple(str(item) for item in texts if str(item).strip())


__all__ = [
    "AgentProvenance",
    "DiffIndex",
    "IntentCoverageMap",
    "ReviewArtifactBundle",
    "ReviewGenerationOptions",
    "ReviewMetadata",
    "ReviewPath",
    "RiskMap",
    "SemanticReviewService",
    "VerificationSummary",
]
