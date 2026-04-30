"""Deterministic markdown -> SpecDocument parser. No LLM, no fuzzy matching."""

from __future__ import annotations

import re
from typing import Any

import yaml

from ces.control.models.spec import (
    Risk,
    SignalHints,
    SpecDocument,
    SpecFrontmatter,
    Story,
)
from ces.control.spec.template_loader import TemplateLoader, TemplateSidecar


class SpecParseError(ValueError):
    """Raised when a spec file can't be parsed into a SpecDocument."""


_FRONTMATTER_RE = re.compile(r"^---\n(?P<body>.*?)\n---\n(?P<rest>.*)$", re.DOTALL)
_SECTION_HEADER_RE = re.compile(r"^## (.+)$", re.MULTILINE)


class SpecParser:
    def __init__(self, template_loader: TemplateLoader) -> None:
        self._loader = template_loader

    def parse(self, text: str, template_name: str = "default") -> SpecDocument:
        sidecar = self._loader.load(template_name)
        frontmatter, body = self._split_frontmatter(text)
        sections = self._split_sections(body)
        self._require_sections(sections, sidecar)
        stories = self._parse_stories(sections["## Stories"], sidecar)
        risks = self._parse_risks(sections["## Risks & Mitigations"])
        success = self._parse_bullets(sections["## Success Criteria"])
        non_goals = self._parse_bullets(sections["## Non-Goals"])
        return SpecDocument(
            frontmatter=frontmatter,
            problem=sections["## Problem"].strip(),
            users=sections["## Users"].strip(),
            success_criteria=success,
            non_goals=non_goals,
            risks=risks,
            stories=stories,
            rollback_plan=sections["## Rollback Plan"].strip(),
        )

    def _split_frontmatter(self, text: str) -> tuple[SpecFrontmatter, str]:
        m = _FRONTMATTER_RE.match(text)
        if not m:
            raise SpecParseError("spec is missing YAML frontmatter delimited by '---' markers")
        try:
            data: dict[str, Any] = yaml.safe_load(m["body"]) or {}
        except yaml.YAMLError as exc:
            raise SpecParseError(f"frontmatter is not valid YAML: {exc}") from exc
        signals = SignalHints.model_validate(data.pop("signals", {}), strict=False)
        fm = SpecFrontmatter.model_validate({**data, "signals": signals}, strict=False)
        return fm, m["rest"]

    def _split_sections(self, body: str) -> dict[str, str]:
        sections: dict[str, str] = {}
        matches = list(_SECTION_HEADER_RE.finditer(body))
        for i, m in enumerate(matches):
            header = "## " + m.group(1).strip()
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
            sections[header] = body[start:end]
        return sections

    def _require_sections(self, sections: dict[str, str], sidecar: TemplateSidecar) -> None:
        missing = [s for s in sidecar.required_sections if s not in sections]
        if missing:
            raise SpecParseError(f"missing required sections: {missing}")

    def _parse_bullets(self, text: str) -> tuple[str, ...]:
        return tuple(
            line.lstrip().removeprefix("- ").strip() for line in text.splitlines() if line.lstrip().startswith("- ")
        )

    def _parse_risks(self, text: str) -> tuple[Risk, ...]:
        out: list[Risk] = []
        current_risk: str | None = None
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("- **Risk:**"):
                current_risk = s.removeprefix("- **Risk:**").strip()
            elif s.startswith("**Mitigation:**") and current_risk is not None:
                mitigation = s.removeprefix("**Mitigation:**").strip()
                out.append(Risk(risk=current_risk, mitigation=mitigation))
                current_risk = None
        return tuple(out)

    def _parse_stories(self, text: str, sidecar: TemplateSidecar) -> tuple[Story, ...]:
        header_re = re.compile(sidecar.story_header_pattern, re.MULTILINE)
        blocks = self._split_by_regex(text, header_re)
        stories: list[Story] = []
        for title, block in blocks:
            stories.append(self._parse_single_story(title, block))
        return tuple(stories)

    def _split_by_regex(self, text: str, pattern: re.Pattern[str]) -> list[tuple[str, str]]:
        matches = list(pattern.finditer(text))
        out: list[tuple[str, str]] = []
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            out.append((m.group(1).strip(), text[start:end]))
        return out

    def _parse_single_story(self, title: str, block: str) -> Story:
        fields = self._parse_story_fields(block)
        for required in ("id", "size", "description"):
            if required not in fields:
                raise SpecParseError(f"story {title!r} missing required field {required!r}")
        return Story(
            story_id=fields["id"],
            title=title,
            description=fields["description"],
            acceptance_criteria=tuple(fields["acceptance"]),
            depends_on=tuple(fields.get("depends_on", ())),
            size=fields["size"],
            risk=fields.get("risk"),
        )

    def _parse_story_fields(self, block: str) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        in_acceptance = False
        acceptance: list[str] = []
        for line in block.splitlines():
            s = line.rstrip()
            if not s.strip():
                in_acceptance = False
                continue
            if s.strip().startswith("- **acceptance:**"):
                in_acceptance = True
                continue
            if in_acceptance and s.lstrip().startswith("- "):
                acceptance.append(s.lstrip()[2:].strip())
                continue
            in_acceptance = False
            m = re.match(r"\s*- \*\*(?P<key>[a-z_]+):\*\*\s*(?P<val>.*)$", s)
            if m:
                key = m["key"]
                val = m["val"].strip()
                if key == "depends_on":
                    val = [v.strip() for v in val.strip("[]").split(",") if v.strip()]
                if key == "risk" and val == "":
                    continue
                fields[key] = val
        fields["acceptance"] = acceptance
        return fields
