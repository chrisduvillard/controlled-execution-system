"""Guide pack models (D-12, D-13) -- task-specific context assembly.

GuidePackBudget defines token budgets with section quotas.
GuidePackContents holds the assembled context sections.
GuidePackResult is the final output, including oversized detection.
"""

from __future__ import annotations

from ces.shared.base import CESBaseModel


class GuidePackBudget(CESBaseModel):
    """Token budget for guide pack assembly (D-12).

    Default quotas: 40% truth artifacts, 30% vault notes, 30% harness context.
    Harness context gets the remainder after integer division to avoid
    rounding loss.

    Frozen CESBaseModel: budgets are immutable once set.
    """

    total_budget_tokens: int
    truth_artifact_quota: float = 0.40
    vault_notes_quota: float = 0.30
    harness_context_quota: float = 0.30

    @property
    def truth_artifact_tokens(self) -> int:
        """Token allocation for truth artifacts."""
        return int(self.total_budget_tokens * self.truth_artifact_quota)

    @property
    def vault_notes_tokens(self) -> int:
        """Token allocation for vault notes."""
        return int(self.total_budget_tokens * self.vault_notes_quota)

    @property
    def harness_context_tokens(self) -> int:
        """Token allocation for harness context (gets remainder)."""
        return self.total_budget_tokens - self.truth_artifact_tokens - self.vault_notes_tokens


class GuidePackContents(CESBaseModel):
    """Assembled guide pack content sections.

    Frozen CESBaseModel: contents are immutable once assembled.
    """

    truth_artifacts: str
    vault_notes: str
    harness_context: str
    total_tokens_used: int


class GuidePackResult(CESBaseModel):
    """Result of guide pack assembly (D-13).

    When the task exceeds the context budget, success=False and
    oversized=True. The guide pack builder does NOT split inline --
    it signals back to the manifest manager for re-decomposition.

    Frozen CESBaseModel: results are immutable.
    """

    success: bool
    contents: GuidePackContents | None = None
    oversized: bool = False
    oversized_reason: str = ""
    total_tokens_used: int = 0
    budget: GuidePackBudget
