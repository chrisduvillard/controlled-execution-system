"""LLM-backed review executor implementing ReviewExecutorProtocol.

Takes a ReviewAssignment and code diff, dispatches an LLM call with
role-specific prompts, and parses structured findings from the response.

This is the core piece that closes the review pipeline gap -- it turns
reviewer assignments into actual code review findings via LLM providers.

Implements:
    - ReviewExecutorProtocol (harness/protocols.py)
    - Chain of custody tracking (LLM-04)
    - Kill switch enforcement before LLM calls
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import TYPE_CHECKING

from ces.harness.models.review_assignment import ReviewAssignment, ReviewerRole
from ces.harness.models.review_finding import (
    ReviewFinding,
    ReviewFindingSeverity,
    ReviewResult,
)
from ces.harness.prompts.review_prompts import build_review_prompt
from ces.harness.services.diff_extractor import DiffContext

if TYPE_CHECKING:
    from ces.control.services.kill_switch import KillSwitchProtocol
    from ces.execution.providers.protocol import (
        ChainOfCustodyTracker,
    )
    from ces.execution.providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)

# Activity class for kill switch checks on review operations
_REVIEW_ACTIVITY_CLASS = "task_issuance"

# Regex to extract JSON from markdown code blocks
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL)

# Valid severity values for input validation
_VALID_SEVERITIES = frozenset(s.value for s in ReviewFindingSeverity)


class LLMReviewExecutor:
    """Executes code reviews by dispatching LLM calls with role-specific prompts.

    Satisfies ``ReviewExecutorProtocol`` from ``ces.harness.protocols``.

    Args:
        provider_registry: Registry for resolving model IDs to LLM providers.
        kill_switch: Optional kill switch for blocking execution.
        chain_tracker: Optional chain of custody tracker for audit trail.
    """

    def __init__(
        self,
        provider_registry: ProviderRegistry,
        kill_switch: KillSwitchProtocol | None = None,
        chain_tracker: ChainOfCustodyTracker | None = None,
    ) -> None:
        self._provider_registry = provider_registry
        self._kill_switch = kill_switch
        self._chain_tracker = chain_tracker

    # ---- Kill switch guard ----

    def _check_kill_switch(self) -> None:
        """Check kill switch before LLM calls.

        Raises:
            RuntimeError: If kill switch is active for review activity.
        """
        if self._kill_switch is not None and self._kill_switch.is_halted(
            _REVIEW_ACTIVITY_CLASS,
        ):
            msg = "Kill switch is active for review operations"
            raise RuntimeError(msg)

    # ---- ReviewExecutorProtocol implementation ----

    async def execute_review(
        self,
        assignment: ReviewAssignment,
        evidence: dict,  # type: ignore[type-arg]
    ) -> dict:  # type: ignore[type-arg]
        """Execute a review for the given assignment (protocol method).

        Delegates to ``execute_code_review`` after extracting diff context
        from the evidence dict.

        Args:
            assignment: The review role and model assignment.
            evidence: Evidence data containing ``diff_context`` and
                ``manifest_context`` keys.

        Returns:
            Review findings as a dictionary.
        """
        diff_context = evidence.get("diff_context")
        manifest_context = evidence.get("manifest_context", {})

        if diff_context is None:
            # No diff to review -- return empty result
            return {"findings": [], "summary": "No diff context provided."}

        result = await self.execute_code_review(
            assignment=assignment,
            diff_context=diff_context,
            manifest_context=manifest_context,
        )
        return result.model_dump()

    # ---- Primary code review method ----

    async def execute_code_review(
        self,
        assignment: ReviewAssignment,
        diff_context: DiffContext,
        manifest_context: dict[str, str],
    ) -> ReviewResult:
        """Execute an LLM-backed code review for the given assignment.

        Args:
            assignment: Review role and model assignment.
            diff_context: Structured diff with code changes to review.
            manifest_context: Task governance context.

        Returns:
            ReviewResult with structured findings and metadata.

        Raises:
            RuntimeError: If kill switch is active.
            KeyError: If no provider registered for the assignment's model.
        """
        self._check_kill_switch()

        provider = self._provider_registry.get_provider(assignment.model_id)
        messages = build_review_prompt(
            role=assignment.role,
            diff_context=diff_context,
            manifest_context=manifest_context,
        )

        start_time = time.monotonic()
        response = await provider.generate(
            model_id=assignment.model_id,
            messages=messages,
            max_tokens=4096,
            temperature=0.0,
        )
        duration = time.monotonic() - start_time

        # Record chain of custody
        if self._chain_tracker is not None:
            self._chain_tracker.record_call(
                response=response,
                step="code_review",
                agent_role=f"reviewer_{assignment.role.value}",
            )

        # Parse findings from LLM response
        findings = _parse_findings(response.content, assignment.role)

        return ReviewResult(
            assignment=assignment,
            findings=tuple(findings),
            summary=_summarize_findings(findings),
            review_duration_seconds=duration,
            model_version=response.model_version,
            tokens_used=response.input_tokens + response.output_tokens,
        )


# ---------------------------------------------------------------------------
# Response parsing helpers
# ---------------------------------------------------------------------------


def _parse_findings(
    content: str,
    role: ReviewerRole,
) -> list[ReviewFinding]:
    """Parse structured findings from LLM response content.

    Tries three strategies in order:
    1. Direct JSON parse of the entire content
    2. Extract JSON from markdown code blocks
    3. Fallback: wrap raw text as a single INFO finding

    Args:
        content: Raw LLM response text.
        role: Reviewer role to attach to each finding.

    Returns:
        List of ReviewFinding objects.
    """

    # Strategy 1: try direct JSON parse
    findings = _try_parse_json(content, role)
    if findings is not None:
        return findings

    # Strategy 2: extract from markdown code blocks
    match = _JSON_BLOCK_RE.search(content)
    if match:
        findings = _try_parse_json(match.group(1).strip(), role)
        if findings is not None:
            return findings

    # Strategy 3: find first [ and last ] — handles LLM preamble text
    bracket_start = content.find("[")
    bracket_end = content.rfind("]")
    if bracket_start != -1 and bracket_end > bracket_start:
        findings = _try_parse_json(content[bracket_start : bracket_end + 1], role)
        if findings is not None:
            return findings

    # Strategy 4: fallback -- wrap raw text as INFO finding
    logger.warning("Could not parse review findings as JSON; using fallback")
    return [
        ReviewFinding(
            finding_id=str(uuid.uuid4()),
            reviewer_role=role,
            severity=ReviewFindingSeverity.INFO,
            category="unparsed_review",
            title="Review output (unparsed)",
            description=content[:2000],
            recommendation="Manually review the raw output above.",
            confidence=0.3,
        ),
    ]


def _try_parse_json(
    text: str,
    role: ReviewerRole,
) -> list[ReviewFinding] | None:
    """Attempt to parse JSON text into ReviewFinding list.

    Returns None if parsing fails rather than raising.
    """

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, list):
        return None

    findings: list[ReviewFinding] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            severity_str = str(item.get("severity", "info")).lower()
            if severity_str not in _VALID_SEVERITIES:
                severity_str = "info"

            findings.append(
                ReviewFinding(
                    finding_id=item.get("finding_id", str(uuid.uuid4())),
                    reviewer_role=role,
                    severity=ReviewFindingSeverity(severity_str),
                    category=str(item.get("category", "general")),
                    file_path=item.get("file_path"),
                    line_number=item.get("line_number"),
                    title=str(item.get("title", "Untitled finding")),
                    description=str(item.get("description", "")),
                    recommendation=str(item.get("recommendation", "")),
                    confidence=float(item.get("confidence", 0.5)),
                ),
            )
        except (TypeError, ValueError, KeyError) as exc:
            logger.debug("Skipping malformed finding: %s", exc)
            continue

    return findings


def _summarize_findings(findings: list[ReviewFinding]) -> str:
    """Generate a brief summary of review findings.

    Args:
        findings: List of findings to summarize.

    Returns:
        Human-readable summary string.
    """
    if not findings:
        return "No issues found."

    counts: dict[str, int] = {}
    for f in findings:
        counts[f.severity.value] = counts.get(f.severity.value, 0) + 1

    parts = []
    for sev in ("critical", "high", "medium", "low", "info"):
        count = counts.get(sev, 0)
        if count > 0:
            parts.append(f"{count} {sev}")

    return f"Found {len(findings)} issue(s): {', '.join(parts)}."
