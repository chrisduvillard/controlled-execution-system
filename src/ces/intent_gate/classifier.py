"""Deterministic classifier for Intent Gate preflight decisions."""

from __future__ import annotations

from collections.abc import Sequence

from ces.intent_gate.models import IntentGatePreflight, IntentQuestion, SpecificationLedger

_HIGH_RISK_TERMS = (
    "auth",
    "authentication",
    "authorization",
    "credential",
    "token",
    "secret",
    "permission",
    "payment",
    "billing",
    "database",
    "production",
    "delete",
    "drop",
    "migration",
    "schema",
    "security",
    "encrypt",
)

_LOW_RISK_WORDING_TERMS = (
    "readme",
    "docs",
    "documentation",
    "wording",
    "copy",
    "typo",
    "lint",
    "format",
    "formatting",
)


def classify_intent(
    request: str,
    constraints: Sequence[str],
    acceptance_criteria: Sequence[str],
    must_not_break: Sequence[str],
    project_mode: str,
    non_interactive: bool,
) -> IntentGatePreflight:
    """Classify a user request into a deterministic Intent Gate preflight."""

    request_text = " ".join(request.split())
    request_lower = request_text.lower()
    constraints_tuple = tuple(constraints)
    acceptance_tuple = tuple(acceptance_criteria)
    must_not_break_tuple = tuple(must_not_break)

    if _has_acceptance_criteria(acceptance_tuple):
        ledger = _base_ledger(
            request=request_text,
            constraints=constraints_tuple,
            acceptance_criteria=acceptance_tuple,
            must_not_break=must_not_break_tuple,
            project_mode=project_mode,
            assumptions=(),
            decisions=("Explicit acceptance criteria provided; proceed within stated boundaries.",),
            verification_plan=acceptance_tuple,
        )
        return IntentGatePreflight(
            decision="proceed",
            ledger=ledger,
            safe_next_step="Inspect the relevant files, make the smallest change satisfying the acceptance criteria, then verify.",
        )

    if _is_high_risk(request_lower):
        question = IntentQuestion(
            question="What acceptance criteria and failure mode boundaries should govern this high-risk change?",
            why_it_matters="Auth, data, deletion, production, and security changes can cause material harm without explicit success and failure boundaries.",
            default_if_unanswered="Do not proceed with implementation.",
        )
        ledger = _base_ledger(
            request=request_text,
            constraints=constraints_tuple,
            acceptance_criteria=(),
            must_not_break=must_not_break_tuple,
            project_mode=project_mode,
            assumptions=(),
            open_questions=(question,),
            decisions=("High-risk request lacks acceptance criteria; clarification is required.",),
            verification_plan=("Wait for explicit acceptance criteria and failure mode constraints.",),
            risks=("Material behavior, data, security, or production impact is possible without clear boundaries.",),
        )
        return IntentGatePreflight(
            decision="blocked" if non_interactive else "ask",
            ledger=ledger,
            safe_next_step="Request clarification before making changes; non-interactive runs must stop until clarified.",
        )

    if _is_low_risk_wording_task(request_lower):
        ledger = _base_ledger(
            request=request_text,
            constraints=constraints_tuple,
            acceptance_criteria=(),
            must_not_break=must_not_break_tuple,
            project_mode=project_mode,
            assumptions=("Assume a conservative minimal-change docs/lint/format/readme edit is acceptable.",),
            decisions=("Proceed under a minimal-change assumption for a low-risk wording or formatting task.",),
            verification_plan=("Inspect the diff to confirm only the requested wording or formatting changed.",),
            risks=("Minor wording drift if the ambiguous phrasing is interpreted too broadly.",),
        )
        return IntentGatePreflight(
            decision="assume_and_proceed",
            ledger=ledger,
            safe_next_step="Inspect the relevant text first, then make the smallest wording or formatting-only change.",
        )

    ledger = _base_ledger(
        request=request_text,
        constraints=constraints_tuple,
        acceptance_criteria=(),
        must_not_break=must_not_break_tuple,
        project_mode=project_mode,
        assumptions=("Assume inspect-first execution: gather local context before changing behavior or files.",),
        decisions=("Proceed only after inspecting context and keeping changes narrow.",),
        verification_plan=("Run the smallest relevant verification available after implementation.",),
        risks=("Ambiguity may require revisiting assumptions if inspection reveals material uncertainty.",),
    )
    return IntentGatePreflight(
        decision="assume_and_proceed",
        ledger=ledger,
        safe_next_step="Inspect project context first; proceed only with the smallest reversible next change.",
    )


def _base_ledger(
    *,
    request: str,
    constraints: tuple[str, ...],
    acceptance_criteria: tuple[str, ...],
    must_not_break: tuple[str, ...],
    project_mode: str,
    assumptions: tuple[str, ...],
    decisions: tuple[str, ...],
    verification_plan: tuple[str, ...],
    risks: tuple[str, ...] = (),
    open_questions: tuple[IntentQuestion, ...] = (),
) -> SpecificationLedger:
    scoped_constraints = constraints + tuple(f"Must not break: {item}" for item in must_not_break)
    return SpecificationLedger(
        goal=request,
        deliverable="Completed request within the classified intent boundary.",
        audience="Project maintainers and requestor.",
        scope=("Classify and execute only the requested work.",),
        non_goals=("No unrelated changes or broad refactors.",),
        constraints=scoped_constraints or ("Keep changes narrow and reversible.",),
        inputs=(request, f"Project mode: {project_mode}"),
        tool_permissions=(
            "Inspect repository context.",
            "Edit files only if needed for the requested change.",
            "Run focused verification commands.",
        ),
        assumptions=assumptions,
        open_questions=open_questions,
        decisions=decisions,
        acceptance_criteria=acceptance_criteria,
        verification_plan=verification_plan,
        risks=risks,
    )


def _has_acceptance_criteria(acceptance_criteria: Sequence[str]) -> bool:
    return any(item.strip() for item in acceptance_criteria)


def _is_high_risk(request_lower: str) -> bool:
    return any(term in request_lower for term in _HIGH_RISK_TERMS)


def _is_low_risk_wording_task(request_lower: str) -> bool:
    return any(term in request_lower for term in _LOW_RISK_WORDING_TERMS)
