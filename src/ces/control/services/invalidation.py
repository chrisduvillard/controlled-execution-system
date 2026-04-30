"""Hash-based dependency invalidation tracker (INVAL-01, D-14).

Detects when upstream truth artifacts have changed since a manifest was
created by comparing SHA-256 content hashes. Uses canonical JSON
serialization for deterministic hashing (T-05-02 mitigation).

This is a pure-function service with no database dependency. It takes
data in and returns results. The database integration (querying actual
manifests and artifacts) happens in Plan 08 where the ManifestManager
orchestrates invalidation checks.

Exports:
    InvalidationResult: Frozen dataclass with validity status and mismatch details.
    InvalidationTracker: Static methods for hash computation and validity checking.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ces.shared.crypto import sha256_hash


@dataclass(frozen=True)
class InvalidationResult:
    """Result of checking a manifest's truth artifact dependencies.

    Frozen to prevent accidental mutation of validation results.

    Attributes:
        manifest_id: The manifest that was checked.
        is_valid: True if all truth artifact hashes match.
        mismatched_artifacts: List of artifact IDs with hash mismatches or missing.
        details: Mapping of artifact_id -> (expected_hash, actual_hash).
                 actual_hash is "MISSING" if the artifact no longer exists.
    """

    manifest_id: str
    is_valid: bool
    mismatched_artifacts: list[str] = field(default_factory=list)
    details: dict[str, tuple[str, str]] = field(default_factory=dict)


class InvalidationTracker:
    """Tracks truth artifact dependencies and detects invalidation (INVAL-01).

    Uses SHA-256 content addressing (D-14) to detect when upstream truth
    artifacts have changed since a manifest was created.

    All methods are static — this is a stateless service. State management
    (querying DB for manifests and artifacts) is the caller's responsibility.
    """

    @staticmethod
    def compute_artifact_hash(content: dict) -> str:  # type: ignore[type-arg]
        """Compute SHA-256 hash of truth artifact content for dependency tracking.

        Delegates to the shared crypto module's sha256_hash which uses
        canonical JSON serialization (T-05-02 mitigation: deterministic input).

        Args:
            content: Truth artifact content as a dictionary.

        Returns:
            64-character lowercase hex SHA-256 hash.
        """
        return sha256_hash(content)

    @staticmethod
    def check_manifest_validity(
        manifest_id: str,
        truth_artifact_hashes: dict[str, str],
        current_artifacts: dict[str, dict],  # type: ignore[type-arg]
    ) -> InvalidationResult:
        """Check if a manifest's truth artifact references are still valid.

        Compares stored hashes against current artifact content hashes.
        An artifact is considered mismatched if:
        - Its current content produces a different SHA-256 hash, or
        - It no longer exists (marked as "MISSING")

        Args:
            manifest_id: ID of the manifest being validated.
            truth_artifact_hashes: Mapping of artifact_id -> expected hash
                (stored at manifest creation time).
            current_artifacts: Mapping of artifact_id -> current content dict.

        Returns:
            InvalidationResult with validity status and mismatch details.
        """
        mismatched: list[str] = []
        details: dict[str, tuple[str, str]] = {}

        for artifact_id, expected_hash in truth_artifact_hashes.items():
            if artifact_id not in current_artifacts:
                mismatched.append(artifact_id)
                details[artifact_id] = (expected_hash, "MISSING")
                continue

            actual_hash = sha256_hash(current_artifacts[artifact_id])
            if actual_hash != expected_hash:
                mismatched.append(artifact_id)
                details[artifact_id] = (expected_hash, actual_hash)

        return InvalidationResult(
            manifest_id=manifest_id,
            is_valid=len(mismatched) == 0,
            mismatched_artifacts=mismatched,
            details=details,
        )

    @staticmethod
    def find_affected_manifests(
        changed_artifact_id: str,
        manifests: dict[str, dict[str, str]],
    ) -> list[str]:
        """Find all manifests that reference the changed truth artifact.

        Returns a list of manifest IDs that need re-validation because
        they depend on the artifact that has changed.

        Args:
            changed_artifact_id: ID of the truth artifact that changed.
            manifests: Mapping of manifest_id -> {artifact_id: hash}.

        Returns:
            List of manifest IDs that reference the changed artifact.
        """
        return [
            manifest_id for manifest_id, artifact_hashes in manifests.items() if changed_artifact_id in artifact_hashes
        ]
