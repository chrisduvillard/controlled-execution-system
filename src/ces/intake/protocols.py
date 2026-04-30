"""Protocols for intake interview engine dependencies.

Defines duck-typed interfaces for:
- VaultPreCheckProtocol: vault integration for pre-checking answers
- AuditLedgerProtocol: audit ledger event logging

Using Protocol enables dependency injection without concrete imports,
keeping the intake domain decoupled from vault and audit implementations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ces.control.models.knowledge_vault import VaultNote
    from ces.shared.enums import ActorType, EventType


@runtime_checkable
class VaultPreCheckProtocol(Protocol):
    """Protocol for vault pre-check integration.

    Any object implementing this protocol can be used to check the
    knowledge vault for existing verified answers to intake questions.
    This avoids re-asking questions whose answers are already known.
    """

    async def find_verified_answer(self, *, category: str, question_text: str) -> VaultNote | None:
        """Check vault for existing verified answer to a question.

        Args:
            category: The assumption category (e.g., "block", "flag", "proceed").
            question_text: The question text to search for.

        Returns:
            A VaultNote if a verified answer exists, None otherwise.
        """
        ...


@runtime_checkable
class AuditLedgerProtocol(Protocol):
    """Protocol for audit ledger dependency injection.

    Any object implementing this protocol can be used to log
    intake events to the audit ledger. Matches the signature
    of AuditLedgerService.append_event().
    """

    async def append_event(
        self,
        event_type: EventType,
        actor: str,
        actor_type: ActorType,
        action_summary: str,
        **kwargs: object,
    ) -> object:
        """Append an event to the audit ledger.

        Args:
            event_type: The governance event type.
            actor: Identifier of the actor performing the action.
            actor_type: Whether actor is human, agent, or control_plane.
            action_summary: Human-readable description of what happened.
            **kwargs: Additional event metadata.

        Returns:
            The appended audit entry.
        """
        ...
