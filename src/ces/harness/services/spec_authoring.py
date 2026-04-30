"""Deterministic interview spine for ces spec author.

LLM polish is optional and layered on top via the `polish_fn` hook; when None,
the interview degrades to pure Q&A with no LLM dependency.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from ces.control.models.spec import (
    Risk,
    SignalHints,
    SpecDocument,
    SpecFrontmatter,
    Story,
)

PromptFn = Callable[..., str]
PolishFn = Callable[[str, str], str] | None


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def _truthy(s: str) -> bool:
    return s.strip().lower() in {"y", "yes", "true", "1"}


def _read_bullets(prompt_fn: PromptFn, prompt: str) -> tuple[str, ...]:
    out: list[str] = []
    while True:
        line = prompt_fn(prompt)
        if not line.strip():
            return tuple(out)
        out.append(line.strip())


def _read_pairs(prompt_fn: PromptFn, prompt: str) -> tuple[Risk, ...]:
    out: list[Risk] = []
    while True:
        line = prompt_fn(prompt)
        if not line.strip():
            return tuple(out)
        risk, _, mitigation = line.partition("::")
        out.append(Risk(risk=risk.strip(), mitigation=mitigation.strip()))


class SpecAuthoringEngine:
    def __init__(
        self,
        project_root: Path,
        prompt_fn: PromptFn,
        polish_fn: PolishFn = None,
    ) -> None:
        self._project_root = project_root
        self._prompt = prompt_fn
        self._polish = polish_fn

    def run_interactive(self) -> SpecDocument:
        frontmatter = self._ask_frontmatter()
        sections = self._ask_sections()
        stories = self._ask_stories()
        return SpecDocument(
            frontmatter=frontmatter,
            problem=sections["problem"],
            users=sections["users"],
            success_criteria=sections["success_criteria"],
            non_goals=sections["non_goals"],
            risks=sections["risks"],
            stories=stories,
            rollback_plan=sections["rollback_plan"],
        )

    def _ask_frontmatter(self) -> SpecFrontmatter:
        title = self._prompt("Title for this spec (short imperative phrase)")
        owner = self._prompt("Owner email")
        signals = SignalHints(
            primary_change_class=self._prompt(
                "Primary change class",
                choices=["feature", "bug", "refactor", "infra", "doc"],
            ),
            blast_radius_hint=self._prompt(
                "Blast radius hint",
                choices=["isolated", "module", "system", "cross-cutting"],
            ),
            touches_data=_truthy(self._prompt("Touches data?")),
            touches_auth=_truthy(self._prompt("Touches auth?")),
            touches_billing=_truthy(self._prompt("Touches billing?")),
        )
        return SpecFrontmatter(
            spec_id=_new_id("SP"),
            title=title,
            owner=owner,
            created_at=datetime.now(tz=timezone.utc),
            status="draft",
            template="default",
            signals=signals,
        )

    def _ask_sections(self) -> dict[str, Any]:
        problem = self._maybe_polish("problem", self._prompt("Problem statement (one paragraph)"))
        users = self._maybe_polish("users", self._prompt("Who benefits, in what context?"))
        success_criteria = _read_bullets(self._prompt, "Success criterion (blank to finish)")
        non_goals = _read_bullets(self._prompt, "Non-goal (blank to finish)")
        risks = _read_pairs(self._prompt, "risk :: mitigation (blank to finish)")
        rollback_plan = self._maybe_polish("rollback_plan", self._prompt("Rollback plan (one paragraph)"))
        return {
            "problem": problem,
            "users": users,
            "success_criteria": success_criteria,
            "non_goals": non_goals,
            "risks": risks,
            "rollback_plan": rollback_plan,
        }

    def _ask_stories(self) -> tuple[Story, ...]:
        out: list[Story] = []
        while _truthy(self._prompt("Add a story?")):
            title = self._prompt("Story title")
            size = self._prompt("Size", choices=["XS", "S", "M", "L"])
            risk_raw = self._prompt("Risk hint", choices=["A", "B", "C", "skip"])
            risk = None if risk_raw == "skip" else risk_raw
            depends_on_raw = self._prompt("Depends on (story ids, comma-sep)")
            depends_on = tuple(p.strip() for p in depends_on_raw.split(",") if p.strip())
            description = self._maybe_polish("story.description", self._prompt("Description"))
            acceptance_criteria = _read_bullets(self._prompt, "Acceptance criterion (blank to finish)")
            out.append(
                Story(
                    story_id=_new_id("ST"),
                    title=title,
                    description=description,
                    acceptance_criteria=acceptance_criteria,
                    depends_on=depends_on,
                    size=size,
                    risk=risk,
                )
            )
        return tuple(out)

    def _maybe_polish(self, field: str, draft: str) -> str:
        if self._polish is None:
            return draft
        return self._polish(field, draft)


def render_markdown(doc: SpecDocument) -> str:
    """Serialize a SpecDocument back to canonical markdown.

    Must round-trip: `parse(render_markdown(doc)) == doc` modulo whitespace.
    """
    fm = doc.frontmatter
    fm_yaml = yaml.safe_dump(
        {
            "spec_id": fm.spec_id,
            "title": fm.title,
            "owner": fm.owner,
            "created_at": fm.created_at.isoformat(),
            "status": fm.status,
            "template": fm.template,
            "signals": fm.signals.model_dump(),
        },
        sort_keys=False,
    ).strip()

    parts: list[str] = [f"---\n{fm_yaml}\n---", ""]
    parts.append("## Problem")
    parts.append(doc.problem)
    parts.append("")
    parts.append("## Users")
    parts.append(doc.users)
    parts.append("")
    parts.append("## Success Criteria")
    for sc in doc.success_criteria:
        parts.append(f"- {sc}")
    parts.append("")
    parts.append("## Non-Goals")
    for ng in doc.non_goals:
        parts.append(f"- {ng}")
    parts.append("")
    parts.append("## Risks & Mitigations")
    for r in doc.risks:
        parts.append(f"- **Risk:** {r.risk}")
        parts.append(f"  **Mitigation:** {r.mitigation}")
    parts.append("")
    parts.append("## Stories")
    parts.append("")
    for story in doc.stories:
        parts.append(f"### Story: {story.title}")
        parts.append(f"- **id:** {story.story_id}")
        parts.append(f"- **size:** {story.size}")
        if story.risk:
            parts.append(f"- **risk:** {story.risk}")
        parts.append(f"- **depends_on:** [{', '.join(story.depends_on)}]")
        parts.append(f"- **description:** {story.description}")
        parts.append("- **acceptance:**")
        for ac in story.acceptance_criteria:
            parts.append(f"  - {ac}")
        parts.append("")
    parts.append("## Rollback Plan")
    parts.append(doc.rollback_plan)
    parts.append("")
    return "\n".join(parts)
