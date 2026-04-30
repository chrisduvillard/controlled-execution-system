"""Unit tests for CascadeInvalidationEngine (INVAL-02, INVAL-03, INVAL-04).

Tests BFS-based cascade invalidation propagation with:
- Single-level and multi-level cascades
- Circular dependency handling (visited set)
- Max depth circuit breaker (truncation)
- Three severity levels based on downstream entity state
- Audit logging integration
- Empty dependency graph edge case
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ces.control.models.cascade_result import CascadeResult
from ces.control.services.cascade_invalidation import CascadeInvalidationEngine
from ces.shared.enums import InvalidationSeverity

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> CascadeInvalidationEngine:
    """Create a CascadeInvalidationEngine without audit ledger."""
    return CascadeInvalidationEngine(audit_ledger=None)


@pytest.fixture
def engine_with_audit() -> tuple[CascadeInvalidationEngine, AsyncMock]:
    """Create a CascadeInvalidationEngine with a mock audit ledger."""
    mock_ledger = AsyncMock()
    mock_ledger.record_invalidation = AsyncMock()
    engine = CascadeInvalidationEngine(audit_ledger=mock_ledger)
    return engine, mock_ledger


# ---------------------------------------------------------------------------
# CascadeResult model tests
# ---------------------------------------------------------------------------


class TestCascadeResult:
    """Tests for the CascadeResult frozen dataclass."""

    def test_cascade_result_is_frozen(self) -> None:
        """CascadeResult is a frozen dataclass -- attributes cannot be modified."""
        result = CascadeResult(
            affected_manifests=("M1",),
            affected_reviews=("R1",),
            affected_merges=("MG1",),
            affected_releases=("RL1",),
            severity=InvalidationSeverity.HIGH,
            cascade_depth=2,
        )
        with pytest.raises(AttributeError):
            result.cascade_depth = 5  # type: ignore[misc]

    def test_cascade_result_fields(self) -> None:
        """CascadeResult has all required fields with correct types."""
        result = CascadeResult(
            affected_manifests=("M1", "M2"),
            affected_reviews=("R1",),
            affected_merges=(),
            affected_releases=("RL1",),
            severity=InvalidationSeverity.MEDIUM,
            cascade_depth=3,
            truncated=True,
        )
        assert result.affected_manifests == ("M1", "M2")
        assert result.affected_reviews == ("R1",)
        assert result.affected_merges == ()
        assert result.affected_releases == ("RL1",)
        assert result.severity == InvalidationSeverity.MEDIUM
        assert result.cascade_depth == 3
        assert result.truncated is True

    def test_cascade_result_defaults(self) -> None:
        """CascadeResult defaults to empty lists, LOW severity, depth 0."""
        result = CascadeResult()
        assert result.affected_manifests == ()
        assert result.affected_reviews == ()
        assert result.affected_merges == ()
        assert result.affected_releases == ()
        assert result.severity == InvalidationSeverity.LOW
        assert result.cascade_depth == 0
        assert result.truncated is False


# ---------------------------------------------------------------------------
# Single-level cascade tests
# ---------------------------------------------------------------------------


class TestSingleLevelCascade:
    """Tests for single-level cascade propagation."""

    def test_single_artifact_affects_two_manifests(self, engine: CascadeInvalidationEngine) -> None:
        """Single-level cascade: artifact change affects 2 manifests."""
        # Dependency graph: artifact-A -> manifest:M1, manifest:M2
        dependency_graph: dict[str, list[str]] = {
            "artifact-A": ["manifest:M1", "manifest:M2"],
        }
        entity_states: dict[str, str] = {
            "manifest:M1": "queued",
            "manifest:M2": "draft",
        }
        result = engine.propagate(
            changed_artifact_id="artifact-A",
            artifact_type="truth_artifact",
            dependency_graph=dependency_graph,
            entity_states=entity_states,
        )
        assert isinstance(result, CascadeResult)
        assert sorted(result.affected_manifests) == ["M1", "M2"]
        assert result.cascade_depth >= 1

    def test_single_artifact_affects_reviews(self, engine: CascadeInvalidationEngine) -> None:
        """Single-level cascade: artifact change affects reviews directly."""
        dependency_graph: dict[str, list[str]] = {
            "artifact-A": ["review:R1", "review:R2"],
        }
        entity_states: dict[str, str] = {
            "review:R1": "pending",
            "review:R2": "pending",
        }
        result = engine.propagate(
            changed_artifact_id="artifact-A",
            artifact_type="truth_artifact",
            dependency_graph=dependency_graph,
            entity_states=entity_states,
        )
        assert sorted(result.affected_reviews) == ["R1", "R2"]


# ---------------------------------------------------------------------------
# Multi-level cascade tests
# ---------------------------------------------------------------------------


class TestMultiLevelCascade:
    """Tests for multi-level cascade propagation."""

    def test_artifact_to_manifest_to_review(self, engine: CascadeInvalidationEngine) -> None:
        """Multi-level: artifact A -> manifest M1 -> review R1."""
        dependency_graph: dict[str, list[str]] = {
            "artifact-A": ["manifest:M1"],
            "manifest:M1": ["review:R1"],
        }
        entity_states: dict[str, str] = {
            "manifest:M1": "in_flight",
            "review:R1": "pending",
        }
        result = engine.propagate(
            changed_artifact_id="artifact-A",
            artifact_type="truth_artifact",
            dependency_graph=dependency_graph,
            entity_states=entity_states,
        )
        assert "M1" in result.affected_manifests
        assert "R1" in result.affected_reviews
        assert result.cascade_depth >= 2

    def test_deep_cascade_chain(self, engine: CascadeInvalidationEngine) -> None:
        """Multi-level: artifact -> manifest -> review -> merge -> release."""
        dependency_graph: dict[str, list[str]] = {
            "artifact-A": ["manifest:M1"],
            "manifest:M1": ["review:R1"],
            "review:R1": ["merge:MG1"],
            "merge:MG1": ["release:RL1"],
        }
        entity_states: dict[str, str] = {
            "manifest:M1": "queued",
            "review:R1": "pending",
            "merge:MG1": "queued",
            "release:RL1": "draft",
        }
        result = engine.propagate(
            changed_artifact_id="artifact-A",
            artifact_type="truth_artifact",
            dependency_graph=dependency_graph,
            entity_states=entity_states,
        )
        assert "M1" in result.affected_manifests
        assert "R1" in result.affected_reviews
        assert "MG1" in result.affected_merges
        assert "RL1" in result.affected_releases
        assert result.cascade_depth >= 4


# ---------------------------------------------------------------------------
# Circular dependency tests
# ---------------------------------------------------------------------------


class TestCircularDependency:
    """Tests for circular dependency handling."""

    def test_circular_dependency_terminates(self, engine: CascadeInvalidationEngine) -> None:
        """Circular dependency (A -> B -> A) terminates without infinite loop."""
        dependency_graph: dict[str, list[str]] = {
            "artifact-A": ["manifest:M1"],
            "manifest:M1": ["artifact-A"],  # Circular reference back
        }
        entity_states: dict[str, str] = {
            "manifest:M1": "queued",
        }
        # Must not hang or raise -- visited set prevents re-processing
        result = engine.propagate(
            changed_artifact_id="artifact-A",
            artifact_type="truth_artifact",
            dependency_graph=dependency_graph,
            entity_states=entity_states,
        )
        assert isinstance(result, CascadeResult)
        assert "M1" in result.affected_manifests

    def test_indirect_circular_dependency(self, engine: CascadeInvalidationEngine) -> None:
        """Indirect circular: A -> B -> C -> A terminates correctly."""
        dependency_graph: dict[str, list[str]] = {
            "artifact-A": ["manifest:M1"],
            "manifest:M1": ["review:R1"],
            "review:R1": ["artifact-A"],  # Back to start
        }
        entity_states: dict[str, str] = {
            "manifest:M1": "queued",
            "review:R1": "pending",
        }
        result = engine.propagate(
            changed_artifact_id="artifact-A",
            artifact_type="truth_artifact",
            dependency_graph=dependency_graph,
            entity_states=entity_states,
        )
        assert "M1" in result.affected_manifests
        assert "R1" in result.affected_reviews


# ---------------------------------------------------------------------------
# Max depth tests
# ---------------------------------------------------------------------------


class TestMaxDepth:
    """Tests for max cascade depth enforcement."""

    def test_max_depth_enforced(self) -> None:
        """Chains deeper than max_depth are truncated with warning."""
        engine = CascadeInvalidationEngine(audit_ledger=None, max_depth=3)
        # Build a chain of depth 5
        dependency_graph: dict[str, list[str]] = {
            "artifact-A": ["manifest:M1"],
            "manifest:M1": ["review:R1"],
            "review:R1": ["merge:MG1"],
            "merge:MG1": ["release:RL1"],
            "release:RL1": ["manifest:M2"],
        }
        entity_states: dict[str, str] = {
            "manifest:M1": "queued",
            "review:R1": "pending",
            "merge:MG1": "queued",
            "release:RL1": "draft",
            "manifest:M2": "draft",
        }
        result = engine.propagate(
            changed_artifact_id="artifact-A",
            artifact_type="truth_artifact",
            dependency_graph=dependency_graph,
            entity_states=entity_states,
        )
        assert result.truncated is True
        assert result.cascade_depth <= 3

    def test_default_max_depth_is_ten(self) -> None:
        """Default max cascade depth is 10."""
        engine = CascadeInvalidationEngine(audit_ledger=None)
        # Build a chain of depth 11
        dependency_graph: dict[str, list[str]] = {}
        entity_states: dict[str, str] = {}
        prev = "artifact-A"
        for i in range(11):
            node = f"manifest:M{i}"
            dependency_graph[prev] = [node]
            entity_states[node] = "draft"
            prev = node

        result = engine.propagate(
            changed_artifact_id="artifact-A",
            artifact_type="truth_artifact",
            dependency_graph=dependency_graph,
            entity_states=entity_states,
        )
        assert result.truncated is True
        assert result.cascade_depth <= 10


# ---------------------------------------------------------------------------
# Severity level tests
# ---------------------------------------------------------------------------


class TestSeverityLevels:
    """Tests for severity determination based on entity states."""

    def test_severity_high_when_in_flight(self, engine: CascadeInvalidationEngine) -> None:
        """Severity is HIGH when any downstream entity is in_flight."""
        dependency_graph: dict[str, list[str]] = {
            "artifact-A": ["manifest:M1"],
        }
        entity_states: dict[str, str] = {
            "manifest:M1": "in_flight",
        }
        result = engine.propagate(
            changed_artifact_id="artifact-A",
            artifact_type="truth_artifact",
            dependency_graph=dependency_graph,
            entity_states=entity_states,
        )
        assert result.severity == InvalidationSeverity.HIGH

    def test_severity_high_when_under_review(self, engine: CascadeInvalidationEngine) -> None:
        """Severity is HIGH when any downstream entity is under_review."""
        dependency_graph: dict[str, list[str]] = {
            "artifact-A": ["manifest:M1"],
        }
        entity_states: dict[str, str] = {
            "manifest:M1": "under_review",
        }
        result = engine.propagate(
            changed_artifact_id="artifact-A",
            artifact_type="truth_artifact",
            dependency_graph=dependency_graph,
            entity_states=entity_states,
        )
        assert result.severity == InvalidationSeverity.HIGH

    def test_severity_medium_when_queued(self, engine: CascadeInvalidationEngine) -> None:
        """Severity is MEDIUM when downstream entities are in queued state."""
        dependency_graph: dict[str, list[str]] = {
            "artifact-A": ["manifest:M1"],
        }
        entity_states: dict[str, str] = {
            "manifest:M1": "queued",
        }
        result = engine.propagate(
            changed_artifact_id="artifact-A",
            artifact_type="truth_artifact",
            dependency_graph=dependency_graph,
            entity_states=entity_states,
        )
        assert result.severity == InvalidationSeverity.MEDIUM

    def test_severity_low_when_draft(self, engine: CascadeInvalidationEngine) -> None:
        """Severity is LOW when downstream entities are in draft/pending state."""
        dependency_graph: dict[str, list[str]] = {
            "artifact-A": ["manifest:M1"],
        }
        entity_states: dict[str, str] = {
            "manifest:M1": "draft",
        }
        result = engine.propagate(
            changed_artifact_id="artifact-A",
            artifact_type="truth_artifact",
            dependency_graph=dependency_graph,
            entity_states=entity_states,
        )
        assert result.severity == InvalidationSeverity.LOW

    def test_severity_uses_worst_case(self, engine: CascadeInvalidationEngine) -> None:
        """When multiple entities have different states, severity is worst case."""
        dependency_graph: dict[str, list[str]] = {
            "artifact-A": ["manifest:M1", "manifest:M2", "manifest:M3"],
        }
        entity_states: dict[str, str] = {
            "manifest:M1": "draft",  # LOW
            "manifest:M2": "queued",  # MEDIUM
            "manifest:M3": "in_flight",  # HIGH
        }
        result = engine.propagate(
            changed_artifact_id="artifact-A",
            artifact_type="truth_artifact",
            dependency_graph=dependency_graph,
            entity_states=entity_states,
        )
        assert result.severity == InvalidationSeverity.HIGH


# ---------------------------------------------------------------------------
# Empty dependency graph tests
# ---------------------------------------------------------------------------


class TestEmptyGraph:
    """Tests for edge case of empty dependency graph."""

    def test_empty_graph_returns_empty_result(self, engine: CascadeInvalidationEngine) -> None:
        """Empty dependency graph returns empty CascadeResult with depth 0."""
        result = engine.propagate(
            changed_artifact_id="artifact-A",
            artifact_type="truth_artifact",
            dependency_graph={},
            entity_states={},
        )
        assert result.affected_manifests == ()
        assert result.affected_reviews == ()
        assert result.affected_merges == ()
        assert result.affected_releases == ()
        assert result.cascade_depth == 0
        assert result.truncated is False

    def test_artifact_not_in_graph(self, engine: CascadeInvalidationEngine) -> None:
        """Artifact not in graph returns empty CascadeResult."""
        dependency_graph: dict[str, list[str]] = {
            "artifact-B": ["manifest:M1"],
        }
        result = engine.propagate(
            changed_artifact_id="artifact-A",
            artifact_type="truth_artifact",
            dependency_graph=dependency_graph,
            entity_states={},
        )
        assert result.affected_manifests == ()
        assert result.cascade_depth == 0


# ---------------------------------------------------------------------------
# Audit logging tests
# ---------------------------------------------------------------------------


class TestAuditLogging:
    """Tests for audit ledger integration."""

    @pytest.mark.asyncio
    async def test_audit_logging_called(
        self,
        engine_with_audit: tuple[CascadeInvalidationEngine, AsyncMock],
    ) -> None:
        """Audit logging called for cascade when audit_ledger provided."""
        engine, mock_ledger = engine_with_audit
        dependency_graph: dict[str, list[str]] = {
            "artifact-A": ["manifest:M1", "review:R1"],
        }
        entity_states: dict[str, str] = {
            "manifest:M1": "queued",
            "review:R1": "pending",
        }
        result = engine.propagate(
            changed_artifact_id="artifact-A",
            artifact_type="truth_artifact",
            dependency_graph=dependency_graph,
            entity_states=entity_states,
        )
        # Log cascade via async method
        await engine.log_cascade(
            result=result,
            changed_artifact_id="artifact-A",
            artifact_type="truth_artifact",
        )
        mock_ledger.record_invalidation.assert_called_once()
        call_kwargs = mock_ledger.record_invalidation.call_args
        assert call_kwargs.kwargs["artifact_id"] == "artifact-A"
        assert call_kwargs.kwargs["severity"] == result.severity

    @pytest.mark.asyncio
    async def test_audit_logging_skipped_without_ledger(
        self,
        engine: CascadeInvalidationEngine,
    ) -> None:
        """Audit logging is a no-op when audit_ledger is None."""
        result = CascadeResult(
            affected_manifests=("M1",),
            severity=InvalidationSeverity.LOW,
            cascade_depth=1,
        )
        # Should not raise
        await engine.log_cascade(
            result=result,
            changed_artifact_id="artifact-A",
            artifact_type="truth_artifact",
        )

    def test_engine_works_without_audit_ledger(self, engine: CascadeInvalidationEngine) -> None:
        """Engine works correctly without audit_ledger (audit_ledger=None)."""
        dependency_graph: dict[str, list[str]] = {
            "artifact-A": ["manifest:M1"],
        }
        entity_states: dict[str, str] = {
            "manifest:M1": "queued",
        }
        # Should not raise -- audit_ledger is optional
        result = engine.propagate(
            changed_artifact_id="artifact-A",
            artifact_type="truth_artifact",
            dependency_graph=dependency_graph,
            entity_states=entity_states,
        )
        assert "M1" in result.affected_manifests


# ---------------------------------------------------------------------------
# determine_severity static method tests
# ---------------------------------------------------------------------------


class TestDetermineSeverity:
    """Tests for the static determine_severity method."""

    def test_determine_severity_high_in_flight(self) -> None:
        """HIGH when any entity state is in_flight."""
        states = {"manifest:M1": "in_flight", "manifest:M2": "draft"}
        affected_ids = ["manifest:M1", "manifest:M2"]
        severity = CascadeInvalidationEngine.determine_severity(states, affected_ids)
        assert severity == InvalidationSeverity.HIGH

    def test_determine_severity_high_under_review(self) -> None:
        """HIGH when any entity state is under_review."""
        states = {"review:R1": "under_review"}
        affected_ids = ["review:R1"]
        severity = CascadeInvalidationEngine.determine_severity(states, affected_ids)
        assert severity == InvalidationSeverity.HIGH

    def test_determine_severity_medium_queued(self) -> None:
        """MEDIUM when highest entity state is queued."""
        states = {"manifest:M1": "queued", "manifest:M2": "draft"}
        affected_ids = ["manifest:M1", "manifest:M2"]
        severity = CascadeInvalidationEngine.determine_severity(states, affected_ids)
        assert severity == InvalidationSeverity.MEDIUM

    def test_determine_severity_low_draft(self) -> None:
        """LOW when all entities are in draft/pending state."""
        states = {"manifest:M1": "draft", "review:R1": "pending"}
        affected_ids = ["manifest:M1", "review:R1"]
        severity = CascadeInvalidationEngine.determine_severity(states, affected_ids)
        assert severity == InvalidationSeverity.LOW

    def test_determine_severity_empty_states(self) -> None:
        """LOW when no entity states are provided (nothing affected)."""
        severity = CascadeInvalidationEngine.determine_severity({}, [])
        assert severity == InvalidationSeverity.LOW

    def test_determine_severity_defaults_to_all_keys_when_affected_ids_none(self) -> None:
        """With no affected_ids argument, the function inspects every entity_state key."""
        states = {"manifest:M1": "in_flight"}
        severity = CascadeInvalidationEngine.determine_severity(states)  # affected_ids defaults to None
        assert severity == InvalidationSeverity.HIGH

    def test_classify_entity_unknown_prefix_is_silently_ignored(self) -> None:
        """A node_id without a recognized prefix exits without mutating the affected dict."""
        affected: dict[str, list[str]] = {"manifests": [], "reviews": [], "merges": [], "releases": []}
        CascadeInvalidationEngine._classify_entity("unknown:X1", affected)
        assert all(v == [] for v in affected.values())
