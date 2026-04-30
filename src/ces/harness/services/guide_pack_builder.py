"""Guide pack builder service (GUIDE-01 to GUIDE-04, D-12, D-13).

Assembles task-specific context from truth artifacts, vault notes, and
harness profiles within a configurable token budget. Enforces section
quotas (40% truth / 30% vault / 30% harness) and handles oversized
context through summarization or by signaling decomposition.

Key behaviors:
- Character-based token estimation (chars_per_token=4 default, per research A1)
- 60% default budget (D-12)
- Section quotas: 40/30/30 with harness getting remainder (Pitfall 4)
- Truncation adds "[TRUNCATED]" marker for full disclosure (T-03-21)
- Oversized tasks return for decomposition, never split inline (D-13, GUIDE-04)
- Budget enforcement prevents unbounded context injection (T-03-20)

Threat mitigations:
- T-03-20: Budget enforcement prevents unbounded context injection
- T-03-21: Truncation adds explicit "[TRUNCATED]" marker for transparency
- T-03-22: Returns OversizedResult for decomposition per D-13
- T-03-23: All results are frozen CESBaseModel instances
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ces.harness.models.guide_pack import (
    GuidePackBudget,
    GuidePackContents,
    GuidePackResult,
)

if TYPE_CHECKING:
    from ces.control.services.kill_switch import KillSwitchProtocol
    from ces.harness.protocols import SummarizerProtocol


class GuidePackBuilder:
    """Assembles task-specific context within a configurable token budget.

    GUIDE-01: Assembles context from truth artifacts, vault notes, harness profiles.
    GUIDE-02: Enforces budget with section quotas (D-12).
    GUIDE-03: Truncates oversized sections with disclosure.
    GUIDE-04: Returns oversized result for decomposition, never splits inline (D-13).

    Args:
        default_budget_percent: Default fraction of context window for guide pack.
            Defaults to 0.60 per D-12.
        chars_per_token: Characters per token for estimation. Defaults to 4
            per research A1 (character-based proxy).
        kill_switch: Optional kill switch protocol for blocking assembly.
        audit_ledger: Optional audit ledger for logging assembly results.
        summarizer: Optional summarizer protocol for reducing oversized context.
    """

    def __init__(
        self,
        default_budget_percent: float = 0.60,
        chars_per_token: int = 4,
        kill_switch: KillSwitchProtocol | None = None,
        audit_ledger: object | None = None,
        summarizer: SummarizerProtocol | None = None,
    ) -> None:
        self._default_budget_percent = default_budget_percent
        self._chars_per_token = chars_per_token
        self._kill_switch = kill_switch
        self._audit_ledger = audit_ledger
        self._summarizer = summarizer

    # ---- Token estimation (research A1) ----

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count from text length using character-based proxy.

        Args:
            text: The text to estimate tokens for.

        Returns:
            Estimated token count (len(text) // chars_per_token).
            Returns 0 for empty string.
        """
        if not text:
            return 0
        return len(text) // self._chars_per_token

    # ---- Budget creation (D-12) ----

    def create_budget(
        self,
        context_window_tokens: int,
        budget_percent: float | None = None,
    ) -> GuidePackBudget:
        """Create a guide pack budget from a context window size.

        Args:
            context_window_tokens: Total context window in tokens.
            budget_percent: Override for default budget percentage.
                Uses self._default_budget_percent if None.

        Returns:
            GuidePackBudget with total budget and default 40/30/30 quotas.
        """
        pct = budget_percent if budget_percent is not None else self._default_budget_percent
        total = int(context_window_tokens * pct)
        return GuidePackBudget(total_budget_tokens=total)

    # ---- Truncation (GUIDE-03, T-03-21) ----

    def truncate_to_budget(
        self,
        text: str,
        max_tokens: int,
    ) -> tuple[str, bool]:
        """Truncate text to fit within a token budget.

        If text fits within max_tokens, returns it unchanged.
        Otherwise, truncates to max_tokens worth of characters and
        adds a "[TRUNCATED]" marker for full disclosure (T-03-21).

        Args:
            text: The text to potentially truncate.
            max_tokens: Maximum tokens allowed.

        Returns:
            Tuple of (text, was_truncated):
                - text: Original or truncated text with marker.
                - was_truncated: True if truncation occurred.
        """
        if self.estimate_tokens(text) <= max_tokens:
            return text, False

        max_chars = max_tokens * self._chars_per_token
        truncated = text[:max_chars] + "\n[TRUNCATED]"
        return truncated, True

    # ---- Assembly (GUIDE-01, GUIDE-02, GUIDE-03, GUIDE-04) ----

    async def assemble(
        self,
        truth_artifacts: str,
        vault_notes: str,
        harness_context: str,
        budget: GuidePackBudget,
    ) -> GuidePackResult:
        """Assemble task-specific context within budget constraints.

        Steps:
        1. Check kill switch (blocks if halted).
        2. Truncate each section to its quota if oversized.
        3. If total fits budget, return success with contents.
        4. If total exceeds budget and summarizer available, attempt
           summarization of the largest section.
        5. If still over budget, return oversized result for
           decomposition (D-13, GUIDE-04). Never splits inline.

        Args:
            truth_artifacts: Truth artifact text content.
            vault_notes: Vault notes text content.
            harness_context: Harness context text content.
            budget: Token budget with section quotas.

        Returns:
            GuidePackResult with success/oversized status and contents.

        Raises:
            RuntimeError: If kill switch is active for task_issuance.
        """
        # Step 1: Check kill switch
        self._check_kill_switch()

        # Step 2: Truncate each section to its quota
        truth_text, truth_truncated = self.truncate_to_budget(truth_artifacts, budget.truth_artifact_tokens)
        vault_text, vault_truncated = self.truncate_to_budget(vault_notes, budget.vault_notes_tokens)
        harness_text, harness_truncated = self.truncate_to_budget(harness_context, budget.harness_context_tokens)

        any_truncated = truth_truncated or vault_truncated or harness_truncated

        # Step 3: Compute total after truncation
        total_tokens = (
            self.estimate_tokens(truth_text) + self.estimate_tokens(vault_text) + self.estimate_tokens(harness_text)
        )

        # Step 4: Check if total fits budget
        if total_tokens <= budget.total_budget_tokens:
            result = GuidePackResult(
                success=True,
                contents=GuidePackContents(
                    truth_artifacts=truth_text,
                    vault_notes=vault_text,
                    harness_context=harness_text,
                    total_tokens_used=total_tokens,
                ),
                total_tokens_used=total_tokens,
                budget=budget,
            )
            await self._log_assembly("success", total_tokens, budget)
            return result

        # Step 5: Attempt summarization if summarizer available
        if self._summarizer is not None:
            # Find largest section and summarize it
            sections = [
                ("truth", truth_text, self.estimate_tokens(truth_text)),
                ("vault", vault_text, self.estimate_tokens(vault_text)),
                ("harness", harness_text, self.estimate_tokens(harness_text)),
            ]
            sections.sort(key=lambda s: s[2], reverse=True)
            largest_name, largest_text, largest_tokens = sections[0]

            # Summarize the largest section to fit the remaining budget
            other_tokens = total_tokens - largest_tokens
            max_summary_tokens = budget.total_budget_tokens - other_tokens
            if max_summary_tokens > 0:
                summarized = await self._summarizer.summarize(largest_text, max_summary_tokens)

                # Replace the largest section
                if largest_name == "truth":
                    truth_text = summarized
                elif largest_name == "vault":
                    vault_text = summarized
                else:
                    harness_text = summarized

                # Recompute total
                total_tokens = (
                    self.estimate_tokens(truth_text)
                    + self.estimate_tokens(vault_text)
                    + self.estimate_tokens(harness_text)
                )

                if total_tokens <= budget.total_budget_tokens:
                    result = GuidePackResult(
                        success=True,
                        contents=GuidePackContents(
                            truth_artifacts=truth_text,
                            vault_notes=vault_text,
                            harness_context=harness_text,
                            total_tokens_used=total_tokens,
                        ),
                        total_tokens_used=total_tokens,
                        budget=budget,
                    )
                    await self._log_assembly("success_after_summarization", total_tokens, budget)
                    return result

        # Step 6: Still oversized -> return for decomposition (D-13, GUIDE-04)
        result = GuidePackResult(
            success=False,
            contents=None,
            oversized=True,
            oversized_reason=(
                "Task context exceeds budget even after summarization. Task should be decomposed into smaller units."
            ),
            total_tokens_used=total_tokens,
            budget=budget,
        )
        await self._log_assembly("oversized", total_tokens, budget)
        return result

    # ---- Internal helpers ----

    def _check_kill_switch(self) -> None:
        """Check kill switch before assembly operations.

        Raises:
            RuntimeError: If kill switch is halted for task_issuance.
        """
        if self._kill_switch is not None:
            if self._kill_switch.is_halted("task_issuance"):  # type: ignore[union-attr]
                msg = "Kill switch is active for task_issuance -- guide pack assembly blocked"
                raise RuntimeError(msg)

    async def _log_assembly(
        self,
        outcome: str,
        total_tokens: int,
        budget: GuidePackBudget,
    ) -> None:
        """Log assembly result to audit ledger.

        Args:
            outcome: Assembly outcome description.
            total_tokens: Total tokens used.
            budget: Budget that was applied.
        """
        if self._audit_ledger is not None:
            from ces.shared.enums import ActorType, EventType

            await self._audit_ledger.append_event(  # type: ignore[attr-defined]
                event_type=EventType.DELEGATION,
                actor="guide_pack_builder",
                actor_type=ActorType.CONTROL_PLANE,
                action_summary=(f"Guide pack assembly: {outcome}. Tokens: {total_tokens}/{budget.total_budget_tokens}"),
                decision=outcome,
                rationale=(f"Budget: {budget.total_budget_tokens} tokens, Used: {total_tokens} tokens"),
            )
