"""Cascade invalidation result model.

Frozen dataclass representing the result of a cascade invalidation
propagation through the dependency graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ces.shared.enums import InvalidationSeverity


@dataclass(frozen=True)
class CascadeResult:
    """Result of cascade invalidation propagation.

    Attributes:
        affected_manifests: Manifest IDs invalidated by the cascade.
        affected_reviews: Review IDs invalidated by the cascade.
        affected_merges: Merge IDs invalidated by the cascade.
        affected_releases: Release IDs invalidated by the cascade.
        severity: Overall severity of the invalidation cascade.
        cascade_depth: Maximum BFS depth reached during propagation.
        truncated: True if max depth was hit and propagation was cut short.
    """

    affected_manifests: tuple[str, ...] = field(default_factory=tuple)
    affected_reviews: tuple[str, ...] = field(default_factory=tuple)
    affected_merges: tuple[str, ...] = field(default_factory=tuple)
    affected_releases: tuple[str, ...] = field(default_factory=tuple)
    severity: InvalidationSeverity = InvalidationSeverity.LOW
    cascade_depth: int = 0
    truncated: bool = False
