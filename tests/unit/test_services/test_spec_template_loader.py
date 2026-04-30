from pathlib import Path

import pytest

from ces.control.spec.template_loader import TemplateLoader, TemplateSidecar


def test_loader_resolves_bundled_default():
    loader = TemplateLoader(project_root=Path("no-overrides-here"))
    sidecar = loader.load("default")
    assert isinstance(sidecar, TemplateSidecar)
    assert sidecar.name == "default"
    assert "## Problem" in sidecar.required_sections
    assert sidecar.story_header_pattern == "^### Story: (.+)$"


def test_loader_prefers_user_override(tmp_path: Path):
    override_dir = tmp_path / ".ces" / "templates" / "spec"
    override_dir.mkdir(parents=True)
    (override_dir / "my-epic.md").write_text("---\ntemplate: my-epic\n---\n")
    (override_dir / "my-epic.yaml").write_text(
        "name: my-epic\nversion: 1\nrequired_sections: ['## Goal']\n"
        "story_header_pattern: '^### S: (.+)$'\n"
        "required_story_fields: []\noptional_story_fields: []\nsignal_fields: []\n",
    )
    loader = TemplateLoader(project_root=tmp_path)
    sidecar = loader.load("my-epic")
    assert sidecar.name == "my-epic"
    assert sidecar.required_sections == ("## Goal",)


def test_loader_raises_on_missing_template(tmp_path: Path):
    loader = TemplateLoader(project_root=tmp_path)
    with pytest.raises(FileNotFoundError, match="nonexistent"):
        loader.load("nonexistent")


def test_loader_returns_markdown_text():
    loader = TemplateLoader(project_root=Path("no-overrides-here"))
    md = loader.load_markdown("default")
    assert "## Problem" in md
    assert "### Story:" in md
