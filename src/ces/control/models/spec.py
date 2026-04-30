"""Pydantic models for the ces spec authoring layer.

All models inherit CESBaseModel (strict, frozen). Tuples are used for collections
to preserve the CES convention (see CLAUDE.md).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from ces.shared.base import CESBaseModel


class SignalHints(CESBaseModel):
    """Classification hints derived from the spec frontmatter.

    Consumed by ClassificationOracle.classify_from_hints() during decompose.
    Never authoritative -- ces classify always gets the final word.
    """

    primary_change_class: Literal["feature", "bug", "refactor", "infra", "doc"]
    blast_radius_hint: Literal["isolated", "module", "system", "cross-cutting"]
    touches_data: bool = False
    touches_auth: bool = False
    touches_billing: bool = False


class SpecFrontmatter(CESBaseModel):
    spec_id: str
    title: str
    owner: str
    created_at: datetime
    status: Literal["draft", "decomposed", "complete"]
    template: str = "default"
    signals: SignalHints


class Risk(CESBaseModel):
    risk: str
    mitigation: str


class Story(CESBaseModel):
    story_id: str
    title: str
    description: str
    acceptance_criteria: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    size: Literal["XS", "S", "M", "L"]
    risk: Literal["A", "B", "C"] | None = None


class SpecDocument(CESBaseModel):
    frontmatter: SpecFrontmatter
    problem: str
    users: str
    success_criteria: tuple[str, ...]
    non_goals: tuple[str, ...]
    risks: tuple[Risk, ...]
    stories: tuple[Story, ...]
    rollback_plan: str
