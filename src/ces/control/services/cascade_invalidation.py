"""Cascade invalidation engine for truth artifact dependency propagation.

Implements BFS-based cascade invalidation (INVAL-02, INVAL-03, INVAL-04).
When an upstream truth artifact changes, propagates through the dependency
graph to find all downstream entities (manifests, reviews, merges, releases)
that need invalidation.

Key properties:
- BFS with visited set prevents circular dependency loops (T-02-05)
- Max cascade depth circuit breaker prevents resource exhaustion (T-02-06)
- Three severity levels based on downstream entity state (INVAL-03)
- Audit ledger integration for every cascade event (INVAL-04, T-02-07)

Entity type detection uses prefix convention in dependency graph node IDs:
    manifest:M1, review:R1, merge:MG1, release:RL1

Exports:
    CascadeInvalidationEngine: BFS cascade propagation service.
"""

from __future__ import annotations

import logging
from collections import deque

from ces.control.models.cascade_result import CascadeResult
from ces.shared.enums import InvalidationSeverity

logger = logging.getLogger(__name__)

# Entity type prefixes used to classify nodes in the dependency graph.
_ENTITY_PREFIXES = {
    "manifest:": "manifests",
    "review:": "reviews",
    "merge:": "merges",
    "release:": "releases",
}

# States that map to HIGH severity -- active work in progress.
_HIGH_SEVERITY_STATES = frozenset({"in_flight", "under_review"})

# States that map to MEDIUM severity -- queued but not yet active.
_MEDIUM_SEVERITY_STATES = frozenset({"queued"})


class CascadeInvalidationEngine:
    """BFS-based cascade invalidation engine (INVAL-02).

    Propagates truth artifact changes through a dependency graph to
    identify all downstream entities that need invalidation.

    The audit_ledger parameter is optional. When None, cascade propagation
    still works but audit events are not recorded. This supports unit
    testing without requiring a full audit infrastructure.

    Args:
        audit_ledger: Optional audit ledger implementing record_invalidation.
        max_depth: Maximum BFS depth before truncation (default 10, T-02-06).
    """

    def __init__(
        self,
        audit_ledger: object = None,
        max_depth: int = 10,
    ) -> None:
        self._audit_ledger = audit_ledger
        self._max_depth = max_depth

    def propagate(
        self,
        changed_artifact_id: str,
        artifact_type: str,
        dependency_graph: dict[str, list[str]],
        entity_states: dict[str, str],
    ) -> CascadeResult:
        """Propagate a truth artifact change through the dependency graph.

        Uses BFS traversal starting from the changed artifact. Maintains a
        visited set to prevent circular dependency loops (T-02-05). Enforces
        max cascade depth to prevent resource exhaustion (T-02-06).

        Entity types are classified by node ID prefix:
        - "manifest:X" -> affected_manifests
        - "review:X" -> affected_reviews
        - "merge:X" -> affected_merges
        - "release:X" -> affected_releases

        Args:
            changed_artifact_id: ID of the truth artifact that changed.
            artifact_type: Type of the changed artifact (e.g., "truth_artifact").
            dependency_graph: Adjacency list mapping node IDs to downstream nodes.
            entity_states: Mapping of node IDs to their current workflow state.

        Returns:
            CascadeResult with all affected entities, severity, and depth info.
        """
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque()  # (node_id, depth)
        affected: dict[str, list[str]] = {
            "manifests": [],
            "reviews": [],
            "merges": [],
            "releases": [],
        }
        max_depth_reached = 0
        truncated = False

        # Seed BFS with the changed artifact itself at depth 0.
        visited.add(changed_artifact_id)
        queue.append((changed_artifact_id, 0))

        while queue:
            node_id, depth = queue.popleft()

            # Get downstream dependencies for this node.
            neighbors = dependency_graph.get(node_id, [])

            for neighbor in neighbors:
                if neighbor in visited:
                    continue

                visited.add(neighbor)
                neighbor_depth = depth + 1

                # Check max depth circuit breaker (T-02-06).
                if neighbor_depth > self._max_depth:
                    truncated = True
                    logger.warning(
                        "Cascade depth %d exceeds max_depth %d for node %s; truncating propagation",
                        neighbor_depth,
                        self._max_depth,
                        neighbor,
                    )
                    continue

                max_depth_reached = max(max_depth_reached, neighbor_depth)

                # Classify the neighbor by entity type prefix.
                self._classify_entity(neighbor, affected)

                # Continue BFS from this neighbor.
                queue.append((neighbor, neighbor_depth))

        # Collect all affected node IDs (with prefix) for severity calculation.
        all_affected_ids: list[str] = []
        for prefix, category in _ENTITY_PREFIXES.items():
            for entity_id in affected[category]:
                all_affected_ids.append(f"{prefix}{entity_id}")

        severity = self.determine_severity(entity_states, all_affected_ids)

        return CascadeResult(
            affected_manifests=tuple(affected["manifests"]),
            affected_reviews=tuple(affected["reviews"]),
            affected_merges=tuple(affected["merges"]),
            affected_releases=tuple(affected["releases"]),
            severity=severity,
            cascade_depth=max_depth_reached,
            truncated=truncated,
        )

    @staticmethod
    def _classify_entity(
        node_id: str,
        affected: dict[str, list[str]],
    ) -> None:
        """Classify a node ID into the appropriate affected entity list.

        Uses the prefix convention (e.g., "manifest:M1" -> manifests["M1"]).
        Nodes without a recognized prefix are silently ignored.

        Args:
            node_id: The dependency graph node ID with type prefix.
            affected: Mutable dict of affected entity lists to populate.
        """
        for prefix, category in _ENTITY_PREFIXES.items():
            if node_id.startswith(prefix):
                entity_id = node_id[len(prefix) :]
                affected[category].append(entity_id)
                return

    @staticmethod
    def determine_severity(
        entity_states: dict[str, str],
        affected_ids: list[str] | None = None,
    ) -> InvalidationSeverity:
        """Determine the overall severity of the cascade (INVAL-03).

        Severity is based on the worst-case downstream entity state:
        - HIGH: Any affected entity is in_flight or under_review.
        - MEDIUM: Any affected entity is in queued state.
        - LOW: All affected entities are in draft/pending or unknown state.

        Args:
            entity_states: Mapping of node IDs to workflow state strings.
            affected_ids: List of affected node IDs to check. If None,
                         checks all IDs in entity_states.

        Returns:
            The worst-case InvalidationSeverity.
        """
        if affected_ids is None:
            ids_to_check = list(entity_states.keys())
        else:
            ids_to_check = affected_ids

        if not ids_to_check:
            return InvalidationSeverity.LOW

        has_medium = False

        for entity_id in ids_to_check:
            state = entity_states.get(entity_id, "")
            if state in _HIGH_SEVERITY_STATES:
                return InvalidationSeverity.HIGH
            if state in _MEDIUM_SEVERITY_STATES:
                has_medium = True

        return InvalidationSeverity.MEDIUM if has_medium else InvalidationSeverity.LOW

    async def log_cascade(
        self,
        result: CascadeResult,
        changed_artifact_id: str,
        artifact_type: str,
    ) -> None:
        """Log the cascade invalidation to the audit ledger (INVAL-04, T-02-07).

        Records one audit event per cascade with all affected entities and
        severity. No-op if audit_ledger is None.

        Args:
            result: The CascadeResult from propagation.
            changed_artifact_id: ID of the artifact that triggered the cascade.
            artifact_type: Type of the changed artifact.
        """
        if self._audit_ledger is None:
            return

        all_affected = (
            result.affected_manifests + result.affected_reviews + result.affected_merges + result.affected_releases
        )

        rationale = (
            f"Cascade invalidation triggered by {artifact_type} "
            f"'{changed_artifact_id}' change. "
            f"Depth: {result.cascade_depth}, "
            f"Truncated: {result.truncated}, "
            f"Affected: {len(all_affected)} entities "
            f"({len(result.affected_manifests)} manifests, "
            f"{len(result.affected_reviews)} reviews, "
            f"{len(result.affected_merges)} merges, "
            f"{len(result.affected_releases)} releases)"
        )

        await self._audit_ledger.record_invalidation(  # type: ignore[union-attr]
            artifact_id=changed_artifact_id,
            affected_manifests=result.affected_manifests,
            severity=result.severity,
            rationale=rationale,
        )
