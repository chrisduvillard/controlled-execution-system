"""Deterministic structural validation of a parsed SpecDocument. No LLM."""

from __future__ import annotations

from ces.control.models.spec import SpecDocument, Story
from ces.control.spec.template_loader import TemplateLoader, TemplateSidecar


class SpecValidationError(ValueError):
    """Raised when a SpecDocument fails structural validation."""


class SpecValidator:
    def __init__(self, template_loader: TemplateLoader) -> None:
        self._loader = template_loader

    def validate(self, doc: SpecDocument, template_name: str = "default") -> None:
        sidecar = self._loader.load(template_name)
        self._check_story_fields(doc.stories, sidecar)
        self._check_depends_on_references(doc.stories)
        self._check_dependency_graph_acyclic(doc.stories)

    def _check_story_fields(self, stories: tuple[Story, ...], sidecar: TemplateSidecar) -> None:
        # Pydantic already enforces the required fields on Story via the model.
        # This hook is for template-specific checks beyond the canonical Story shape.
        for story in stories:
            if not story.acceptance_criteria:
                raise SpecValidationError(f"story {story.story_id} has no acceptance criteria")

    def _check_depends_on_references(self, stories: tuple[Story, ...]) -> None:
        known = {s.story_id for s in stories}
        for story in stories:
            for ref in story.depends_on:
                if ref not in known:
                    raise SpecValidationError(f"story {story.story_id} depends on unknown story {ref}")

    def _check_dependency_graph_acyclic(self, stories: tuple[Story, ...]) -> None:
        graph = {s.story_id: set(s.depends_on) for s in stories}
        visited: set[str] = set()
        stack: set[str] = set()

        def visit(node: str, path: list[str]) -> None:
            if node in stack:
                cycle = [*path[path.index(node) :], node]
                raise SpecValidationError(f"dependency cycle: {' -> '.join(cycle)}")
            if node in visited:
                return
            stack.add(node)
            path.append(node)
            for nxt in graph[node]:
                visit(nxt, path)
            stack.discard(node)
            path.pop()
            visited.add(node)

        for node in graph:
            visit(node, [])
