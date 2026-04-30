"""Import an existing PRD and map its sections to the canonical template.

LLM section mapping is optional (injected via section_mapper_fn). With no
mapper, the importer does exact-match only -- good enough when the input
already uses canonical headers, useful as a fallback elsewhere.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from ces.control.spec.template_loader import TemplateLoader
from ces.shared.base import CESBaseModel

SectionMapperFn = Callable[[str, tuple[str, ...]], dict[str, str]] | None


class SectionMapping(CESBaseModel):
    # canonical header -> source header
    found: dict[str, str]
    missing: tuple[str, ...]


class ImportResult(CESBaseModel):
    mapping: SectionMapping
    rewritten_text: str  # source text with headers rewritten to canonical form


class SpecImporter:
    def __init__(
        self,
        project_root: Path,
        section_mapper_fn: SectionMapperFn,
        template_name: str = "default",
    ) -> None:
        self._loader = TemplateLoader(project_root)
        self._mapper = section_mapper_fn
        self._template_name = template_name

    def map_sections(self, source_text: str) -> SectionMapping:
        sidecar = self._loader.load(self._template_name)
        required = sidecar.required_sections
        found: dict[str, str] = {h: h for h in required if h in source_text}
        if self._mapper is not None:
            supplementary = self._mapper(source_text, required)
            for canonical, source_header in supplementary.items():
                if canonical in required and source_header in source_text:
                    found.setdefault(canonical, source_header)
        missing = tuple(h for h in required if h not in found)
        return SectionMapping(found=found, missing=missing)

    def rewrite_headers(self, source_text: str, mapping: SectionMapping) -> str:
        out = source_text
        for canonical, source_header in mapping.found.items():
            if canonical == source_header:
                continue
            pattern = re.compile(r"^" + re.escape(source_header) + r"$", re.MULTILINE)
            out = pattern.sub(canonical, out)
        return out

    def import_text(self, source_text: str) -> ImportResult:
        mapping = self.map_sections(source_text)
        rewritten = self.rewrite_headers(source_text, mapping)
        return ImportResult(mapping=mapping, rewritten_text=rewritten)
