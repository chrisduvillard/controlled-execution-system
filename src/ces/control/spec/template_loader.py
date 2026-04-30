"""Deterministic lookup of spec templates. No LLM."""

from __future__ import annotations

from pathlib import Path

import yaml

from ces.shared.base import CESBaseModel


class TemplateSidecar(CESBaseModel):
    name: str
    version: int
    required_sections: tuple[str, ...]
    story_header_pattern: str
    required_story_fields: tuple[str, ...]
    optional_story_fields: tuple[str, ...] = ()
    signal_fields: tuple[str, ...] = ()


BUNDLED_DIR = Path(__file__).parent / "templates"


class TemplateLoader:
    """Loads spec templates with user-override precedence.

    Lookup order:
      1. <project_root>/.ces/templates/spec/<name>.md + .yaml
      2. <bundled>/templates/<name>.md + .yaml

    Raises FileNotFoundError if neither exists.
    """

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    def _candidates(self, name: str, ext: str) -> list[Path]:
        return [
            self._project_root / ".ces" / "templates" / "spec" / f"{name}.{ext}",
            BUNDLED_DIR / f"{name}.{ext}",
        ]

    def _resolve(self, name: str, ext: str) -> Path:
        candidates = self._candidates(name, ext)
        for cand in candidates:
            if cand.is_file():
                return cand
        msg = f"Template {name!r} not found (looked in {[str(c) for c in candidates]})"
        raise FileNotFoundError(msg)

    def load(self, name: str) -> TemplateSidecar:
        path = self._resolve(name, "yaml")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return TemplateSidecar.model_validate(data, strict=False)

    def load_markdown(self, name: str) -> str:
        path = self._resolve(name, "md")
        return path.read_text(encoding="utf-8")
