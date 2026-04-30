"""Protocols for knowledge vault operations.

Defines VaultQueryProtocol and InvalidationTriggerProtocol as
runtime-checkable interfaces for vault consumers.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ces.control.models.knowledge_vault import VaultNote
from ces.shared.enums import VaultCategory, VaultTrustLevel


@runtime_checkable
class VaultQueryProtocol(Protocol):
    """Protocol for querying the knowledge vault."""

    async def query(
        self,
        category: VaultCategory | None = None,
        tags: list[str] | None = None,
        trust_level: VaultTrustLevel | None = None,
        limit: int = 10,
    ) -> list[VaultNote]: ...

    async def find_verified_answer(
        self,
        *,
        category: str,
        question_text: str,
    ) -> VaultNote | None: ...


@runtime_checkable
class InvalidationTriggerProtocol(Protocol):
    """Protocol for triggering vault invalidation from external events."""

    async def trigger_invalidation(
        self,
        *,
        trigger_source: str,
        affected_artifact_ids: list[str],
    ) -> list[str]: ...
