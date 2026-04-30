"""Tests for the hash-based invalidation tracker (INVAL-01, D-14).

Validates:
- InvalidationResult dataclass structure
- check_manifest_validity with matching hashes (valid)
- check_manifest_validity with mismatched hashes (invalid)
- check_manifest_validity with missing artifacts
- check_manifest_validity with empty dependencies (trivially valid)
- find_affected_manifests returns correct manifest IDs
- compute_artifact_hash produces consistent SHA-256 hashes
"""

from __future__ import annotations

import pytest

from ces.control.services.invalidation import InvalidationResult, InvalidationTracker
from ces.shared.crypto import sha256_hash

# ---------------------------------------------------------------------------
# InvalidationResult structure tests
# ---------------------------------------------------------------------------


class TestInvalidationResult:
    """Tests for the InvalidationResult dataclass."""

    def test_valid_result(self) -> None:
        result = InvalidationResult(
            manifest_id="manifest-001",
            is_valid=True,
        )
        assert result.manifest_id == "manifest-001"
        assert result.is_valid is True
        assert result.mismatched_artifacts == []
        assert result.details == {}

    def test_invalid_result_with_details(self) -> None:
        result = InvalidationResult(
            manifest_id="manifest-002",
            is_valid=False,
            mismatched_artifacts=["artifact-a"],
            details={"artifact-a": ("hash-old", "hash-new")},
        )
        assert result.is_valid is False
        assert result.mismatched_artifacts == ["artifact-a"]
        assert result.details["artifact-a"] == ("hash-old", "hash-new")

    def test_result_is_frozen(self) -> None:
        result = InvalidationResult(manifest_id="m", is_valid=True)
        with pytest.raises(AttributeError):
            result.is_valid = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# compute_artifact_hash tests
# ---------------------------------------------------------------------------


class TestComputeArtifactHash:
    """Tests for InvalidationTracker.compute_artifact_hash."""

    def test_consistent_hash_for_same_content(self) -> None:
        content = {"name": "test-artifact", "version": 1}
        hash1 = InvalidationTracker.compute_artifact_hash(content)
        hash2 = InvalidationTracker.compute_artifact_hash(content)
        assert hash1 == hash2

    def test_different_hash_for_different_content(self) -> None:
        content_a = {"name": "test-artifact", "version": 1}
        content_b = {"name": "test-artifact", "version": 2}
        hash_a = InvalidationTracker.compute_artifact_hash(content_a)
        hash_b = InvalidationTracker.compute_artifact_hash(content_b)
        assert hash_a != hash_b

    def test_hash_is_64_char_hex(self) -> None:
        content = {"key": "value"}
        result = InvalidationTracker.compute_artifact_hash(content)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_hash_matches_sha256_hash(self) -> None:
        """compute_artifact_hash should delegate to sha256_hash from crypto module."""
        content = {"name": "artifact", "data": [1, 2, 3]}
        assert InvalidationTracker.compute_artifact_hash(content) == sha256_hash(content)


# ---------------------------------------------------------------------------
# check_manifest_validity tests
# ---------------------------------------------------------------------------


class TestCheckManifestValidity:
    """Tests for InvalidationTracker.check_manifest_validity."""

    def test_all_hashes_match_is_valid(self) -> None:
        """Manifest is valid when all truth artifact hashes match current content."""
        artifact_content = {"name": "prl", "items": ["a", "b"]}
        expected_hash = sha256_hash(artifact_content)

        result = InvalidationTracker.check_manifest_validity(
            manifest_id="manifest-001",
            truth_artifact_hashes={"prl-001": expected_hash},
            current_artifacts={"prl-001": artifact_content},
        )
        assert result.is_valid is True
        assert result.mismatched_artifacts == []
        assert result.manifest_id == "manifest-001"

    def test_hash_mismatch_is_invalid(self) -> None:
        """Manifest is invalid when truth artifact content has changed."""
        original_content = {"name": "prl", "version": 1}
        updated_content = {"name": "prl", "version": 2}
        original_hash = sha256_hash(original_content)

        result = InvalidationTracker.check_manifest_validity(
            manifest_id="manifest-002",
            truth_artifact_hashes={"prl-001": original_hash},
            current_artifacts={"prl-001": updated_content},
        )
        assert result.is_valid is False
        assert "prl-001" in result.mismatched_artifacts
        assert result.details["prl-001"][0] == original_hash
        assert result.details["prl-001"][1] == sha256_hash(updated_content)

    def test_missing_artifact_is_invalid(self) -> None:
        """Manifest is invalid when a referenced artifact is missing."""
        result = InvalidationTracker.check_manifest_validity(
            manifest_id="manifest-003",
            truth_artifact_hashes={"prl-001": "somehash"},
            current_artifacts={},
        )
        assert result.is_valid is False
        assert "prl-001" in result.mismatched_artifacts
        assert result.details["prl-001"] == ("somehash", "MISSING")

    def test_empty_dependencies_is_valid(self) -> None:
        """Manifest with no truth artifact dependencies is always valid."""
        result = InvalidationTracker.check_manifest_validity(
            manifest_id="manifest-004",
            truth_artifact_hashes={},
            current_artifacts={},
        )
        assert result.is_valid is True
        assert result.mismatched_artifacts == []

    def test_multiple_artifacts_some_mismatched(self) -> None:
        """Multiple artifacts, only some have changed."""
        content_a = {"name": "artifact-a"}
        content_b_original = {"name": "artifact-b", "version": 1}
        content_b_updated = {"name": "artifact-b", "version": 2}

        result = InvalidationTracker.check_manifest_validity(
            manifest_id="manifest-005",
            truth_artifact_hashes={
                "art-a": sha256_hash(content_a),
                "art-b": sha256_hash(content_b_original),
            },
            current_artifacts={
                "art-a": content_a,
                "art-b": content_b_updated,
            },
        )
        assert result.is_valid is False
        assert "art-b" in result.mismatched_artifacts
        assert "art-a" not in result.mismatched_artifacts

    def test_multiple_artifacts_all_valid(self) -> None:
        """Multiple artifacts, all unchanged."""
        content_a = {"name": "a"}
        content_b = {"name": "b"}
        content_c = {"name": "c"}

        result = InvalidationTracker.check_manifest_validity(
            manifest_id="manifest-006",
            truth_artifact_hashes={
                "art-a": sha256_hash(content_a),
                "art-b": sha256_hash(content_b),
                "art-c": sha256_hash(content_c),
            },
            current_artifacts={
                "art-a": content_a,
                "art-b": content_b,
                "art-c": content_c,
            },
        )
        assert result.is_valid is True
        assert result.mismatched_artifacts == []


# ---------------------------------------------------------------------------
# find_affected_manifests tests
# ---------------------------------------------------------------------------


class TestFindAffectedManifests:
    """Tests for InvalidationTracker.find_affected_manifests."""

    def test_finds_manifests_referencing_artifact(self) -> None:
        manifests = {
            "m-001": {"prl-001": "hash1", "arch-001": "hash2"},
            "m-002": {"prl-001": "hash1"},
            "m-003": {"arch-001": "hash2"},
        }
        result = InvalidationTracker.find_affected_manifests("prl-001", manifests)
        assert sorted(result) == ["m-001", "m-002"]

    def test_no_manifests_reference_artifact(self) -> None:
        manifests = {
            "m-001": {"arch-001": "hash1"},
            "m-002": {"arch-002": "hash2"},
        }
        result = InvalidationTracker.find_affected_manifests("prl-999", manifests)
        assert result == []

    def test_all_manifests_reference_artifact(self) -> None:
        manifests = {
            "m-001": {"shared-001": "hash1"},
            "m-002": {"shared-001": "hash2"},
        }
        result = InvalidationTracker.find_affected_manifests("shared-001", manifests)
        assert sorted(result) == ["m-001", "m-002"]

    def test_empty_manifests_dict(self) -> None:
        result = InvalidationTracker.find_affected_manifests("art-001", {})
        assert result == []

    def test_single_manifest_single_artifact(self) -> None:
        manifests = {"m-001": {"art-001": "hash1"}}
        result = InvalidationTracker.find_affected_manifests("art-001", manifests)
        assert result == ["m-001"]
