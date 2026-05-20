"""Safe filesystem persistence for semantic review bundles."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ces.execution.secrets import scrub_secrets_from_text, scrub_secrets_recursive
from ces.local_state_path import validate_ces_state_dir, validate_ces_state_path
from ces.review.models import (
    AgentProvenance,
    DiffIndex,
    IntentCoverageMap,
    ReviewArtifactBundle,
    ReviewMetadata,
    RiskMap,
    VerificationSummary,
)

_JSON_ARTIFACTS = {
    "metadata": "metadata.json",
    "diff_index": "diff-index.json",
    "risk_map": "risk-map.json",
    "intent_coverage": "intent-coverage.json",
    "agent_provenance": "agent-provenance.json",
    "verification_summary": "verification-summary.json",
}
_MARKDOWN_ARTIFACTS = {
    "review_brief": "review-brief.md",
    "intent_coverage_markdown": "intent-coverage.md",
    "review_path_markdown": "review-path.md",
}


class SemanticReviewArtifactStore:
    """Write and load `.ces/reviews/<review-id>/` bundles safely."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.ces_dir = self.project_root / ".ces"
        self.reviews_dir = self.ces_dir / "reviews"

    def prepare_bundle_dir(self, metadata: ReviewMetadata) -> Path:
        """Create the review bundle directory after symlink and boundary checks."""

        _validate_review_id(metadata.review_id)
        self._ensure_ces_dir()
        if self.reviews_dir.is_symlink():
            raise ValueError("Refusing to use symlinked .ces/reviews directory.")
        validate_ces_state_path(self.project_root, self.reviews_dir)
        self.reviews_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        bundle_dir = self._bundle_dir_for(metadata.review_id)
        bundle_dir.mkdir(mode=0o700, exist_ok=True)
        return bundle_dir

    def artifact_paths_for(self, metadata: ReviewMetadata) -> dict[str, str]:
        bundle_dir = self._bundle_dir_for(metadata.review_id)
        mapping = {**_JSON_ARTIFACTS, **_MARKDOWN_ARTIFACTS}
        return {key: str((bundle_dir / filename).relative_to(self.project_root)) for key, filename in mapping.items()}

    def write_bundle(
        self,
        bundle: ReviewArtifactBundle,
        *,
        review_brief: str,
        intent_coverage_markdown: str = "",
        review_path_markdown: str = "",
    ) -> ReviewArtifactBundle:
        """Persist all canonical semantic review artifacts atomically."""

        bundle_dir = self.prepare_bundle_dir(bundle.metadata)
        artifact_paths = {
            key: bundle_dir / filename for key, filename in {**_JSON_ARTIFACTS, **_MARKDOWN_ARTIFACTS}.items()
        }
        metadata = bundle.metadata.model_copy(update={"artifact_paths": self.artifact_paths_for(bundle.metadata)})
        bundle = bundle.model_copy(
            update={
                "metadata": metadata,
                "root_path": bundle_dir,
                "review_brief_path": artifact_paths["review_brief"],
                "artifact_paths": artifact_paths,
            }
        )
        self._write_json(artifact_paths["metadata"], metadata.model_dump(mode="json"))
        self._write_json(artifact_paths["diff_index"], bundle.diff_index.model_dump(mode="json"))
        self._write_json(artifact_paths["risk_map"], bundle.risk_map.model_dump(mode="json"))
        self._write_json(artifact_paths["intent_coverage"], bundle.intent_coverage.model_dump(mode="json"))
        self._write_json(artifact_paths["agent_provenance"], bundle.agent_provenance.model_dump(mode="json"))
        self._write_json(artifact_paths["verification_summary"], bundle.verification_summary.model_dump(mode="json"))
        self._write_text(artifact_paths["review_brief"], review_brief)
        self._write_text(artifact_paths["intent_coverage_markdown"], intent_coverage_markdown)
        self._write_text(artifact_paths["review_path_markdown"], review_path_markdown)
        return bundle

    def list_bundle_metadata(self) -> tuple[ReviewMetadata, ...]:
        if not self.reviews_dir.exists():
            return ()
        if self.reviews_dir.is_symlink():
            raise ValueError("Refusing to list symlinked .ces/reviews directory.")
        validate_ces_state_path(self.project_root, self.reviews_dir)
        entries: list[ReviewMetadata] = []
        for metadata_path in sorted(self.reviews_dir.glob("*/metadata.json")):
            if metadata_path.is_symlink() or metadata_path.parent.is_symlink():
                continue
            try:
                metadata = ReviewMetadata.model_validate_json(metadata_path.read_text(encoding="utf-8"))
                _validate_review_id(metadata.review_id)
                if metadata.review_id != metadata_path.parent.name:
                    continue
                self._bundle_dir_for(metadata.review_id)
                entries.append(metadata)
            except (OSError, ValueError):
                continue
        return tuple(sorted(entries, key=lambda item: (item.created_at, item.review_id), reverse=True))

    def latest_bundle_metadata(self) -> ReviewMetadata | None:
        items = self.list_bundle_metadata()
        return items[0] if items else None

    def load_bundle(self, review_id: str | None = None) -> ReviewArtifactBundle:
        metadata = self._resolve_metadata(review_id)
        bundle_dir = self._bundle_dir_for(metadata.review_id)
        if bundle_dir.is_symlink():
            raise ValueError("Refusing to read symlinked semantic review bundle directory.")
        diff_index = DiffIndex.model_validate_json(self._read_artifact(bundle_dir / "diff-index.json"))
        risk_map = RiskMap.model_validate_json(self._read_artifact(bundle_dir / "risk-map.json"))
        intent = IntentCoverageMap.model_validate_json(self._read_artifact(bundle_dir / "intent-coverage.json"))
        provenance = AgentProvenance.model_validate_json(self._read_artifact(bundle_dir / "agent-provenance.json"))
        verification = VerificationSummary.model_validate_json(
            self._read_artifact(bundle_dir / "verification-summary.json")
        )
        from ces.review.risk import build_review_path

        review_path = build_review_path(risk_map)
        artifact_paths = {
            key: bundle_dir / filename for key, filename in {**_JSON_ARTIFACTS, **_MARKDOWN_ARTIFACTS}.items()
        }
        return ReviewArtifactBundle(
            metadata=metadata,
            root_path=bundle_dir,
            review_brief_path=bundle_dir / "review-brief.md",
            diff_index=diff_index,
            risk_map=risk_map,
            intent_coverage=intent,
            review_path=review_path,
            verification_summary=verification,
            agent_provenance=provenance,
            artifact_paths=artifact_paths,
        )

    def review_brief_text(self, review_id: str | None = None) -> str:
        bundle = self.load_bundle(review_id)
        return self._read_artifact(bundle.review_brief_path)

    def is_stale(self, metadata: ReviewMetadata) -> bool:
        try:
            from ces.review.diff_index import build_diff_index
            from ces.review.verification import verification_evidence_fingerprint

            current = build_diff_index(
                self.project_root,
                base_ref=metadata.base_ref,
                head_ref=None if metadata.head_ref == "WORKTREE" else metadata.head_ref,
                include_untracked=metadata.include_untracked,
            )
        except (OSError, RuntimeError, ValueError):
            return True
        if current.diff_fingerprint != metadata.diff_fingerprint:
            return True
        if metadata.verification_fingerprint is None:
            return False
        return metadata.verification_fingerprint != verification_evidence_fingerprint(self.project_root)

    def _resolve_metadata(self, review_id: str | None) -> ReviewMetadata:
        metadata = self.latest_bundle_metadata() if review_id is None else None
        if review_id is not None:
            _validate_review_id(review_id)
            metadata_path = self._bundle_dir_for(review_id) / "metadata.json"
            metadata = ReviewMetadata.model_validate_json(self._read_artifact(metadata_path))
            if metadata.review_id != review_id:
                raise ValueError("Semantic review metadata ID does not match requested bundle.")
        if metadata is None:
            raise ValueError("No semantic review artifacts found. Run `ces review generate` first.")
        _validate_review_id(metadata.review_id)
        self._bundle_dir_for(metadata.review_id)
        return metadata

    def _ensure_ces_dir(self) -> None:
        if self.ces_dir.is_symlink():
            raise ValueError("Refusing to use symlinked .ces directory.")
        validate_ces_state_dir(self.project_root, self.ces_dir)
        self.ces_dir.mkdir(mode=0o700, exist_ok=True)
        validate_ces_state_dir(self.project_root, self.ces_dir)

    def _bundle_dir_for(self, review_id: str) -> Path:
        _validate_review_id(review_id)
        bundle_dir = self.reviews_dir / review_id
        if bundle_dir.is_symlink():
            raise ValueError("Refusing to use symlinked semantic review bundle directory.")
        validate_ces_state_path(self.project_root, bundle_dir)
        bundle_dir.resolve(strict=False).relative_to(self.reviews_dir.resolve(strict=False))
        return bundle_dir

    def _safe_artifact_path(self, path: Path) -> Path:
        if path.is_symlink():
            raise ValueError(f"Refusing to write semantic review artifact through symlink: {path.name}")
        validate_ces_state_path(self.project_root, path)
        resolved_parent = path.parent.resolve(strict=False)
        resolved_parent.relative_to(self.reviews_dir.resolve(strict=False))
        return path

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        self._write_text(path, json.dumps(scrub_secrets_recursive(payload), indent=2, sort_keys=True) + "\n")

    def _write_text(self, path: Path, content: str) -> None:
        safe_path = self._safe_artifact_path(path)
        safe_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=safe_path.parent, prefix=f".{safe_path.name}.", suffix=".tmp", delete=False
        ) as handle:
            tmp_name = handle.name
            handle.write(scrub_secrets_from_text(content))
        os.replace(tmp_name, safe_path)

    def _read_artifact(self, path: Path) -> str:
        if path.is_symlink():
            raise ValueError(f"Refusing to read symlinked semantic review artifact: {path.name}")
        validate_ces_state_path(self.project_root, path)
        resolved_path = path.resolve(strict=False)
        resolved_path.relative_to(self.reviews_dir.resolve(strict=False))
        return path.read_text(encoding="utf-8")


def _validate_review_id(review_id: str) -> None:
    if not review_id or any(part in review_id for part in ("/", "\\", "..")):
        raise ValueError("Invalid semantic review ID.")
