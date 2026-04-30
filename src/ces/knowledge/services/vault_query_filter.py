"""Vault query filter enforcing VAULT-06 informational-only constraint.

VAULT-06: The Knowledge Vault must NEVER answer requirement, policy,
or risk-acceptance questions. This filter is applied to every query
result before returning to the caller.

Full implementation in Task 2 -- this provides the core function
signature needed by KnowledgeVaultService.
"""

from __future__ import annotations

import re

from ces.control.models.knowledge_vault import VaultNote
from ces.shared.enums import VaultCategory

# Keywords that indicate policy-adjacent content
POLICY_ADJACENT_KEYWORDS = frozenset(
    {
        "requirement",
        "policy",
        "regulation",
        "compliance",
        "risk acceptance",
        "must",
        "shall",
        "mandatory",
        "approved by",
        "sign-off",
        "authorization",
    }
)

# Categories more likely to contain policy-adjacent content
POLICY_ADJACENT_CATEGORIES = frozenset(
    {
        VaultCategory.DECISIONS,
    }
)


def _is_policy_adjacent(note: VaultNote) -> bool:
    """Check if a note contains policy-adjacent content.

    For policy-adjacent categories (DECISIONS), applies stricter keyword
    matching: any single keyword match triggers filtering.

    For other categories, applies looser check: only filters if 2+
    policy keywords appear. This prevents over-filtering notes in
    discovery/domain/calibration categories (research Pitfall 4).

    Args:
        note: The VaultNote to check.

    Returns:
        True if the note is policy-adjacent and should be filtered.
    """
    content_lower = note.content.lower()
    matched_count = 0

    for keyword in POLICY_ADJACENT_KEYWORDS:
        # Use word boundary matching to avoid false positives
        # e.g., "requirements.txt" should not match "requirement"
        pattern = rf"\b{re.escape(keyword)}\b"
        if re.search(pattern, content_lower):
            matched_count += 1

    if note.category in POLICY_ADJACENT_CATEGORIES:
        # Stricter: any single keyword match
        return matched_count >= 1
    else:
        # Looser: need 2+ keyword matches
        return matched_count >= 2


def filter_informational_only(notes: list[VaultNote]) -> list[VaultNote]:
    """Filter notes to enforce VAULT-06 informational-only constraint.

    Hard enforcement: removes notes that contain policy-adjacent content.
    Applied to every query result before returning to the caller.

    VAULT-06: The Knowledge Vault must NEVER answer requirement, policy,
    or risk-acceptance questions.

    Args:
        notes: List of VaultNote instances to filter.

    Returns:
        Filtered list with policy-adjacent notes removed.
    """
    return [note for note in notes if not _is_policy_adjacent(note)]
