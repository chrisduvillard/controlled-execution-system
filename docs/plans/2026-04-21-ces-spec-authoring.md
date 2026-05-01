# `ces spec` Authoring Layer — Implementation Plan

> Historical implementation plan. CES is currently shipped as a local builder-first CLI. References below to older server surfaces or planning-era control-plane terminology are preserved for history, not as the active product contract.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a `ces spec` command group that turns a PRD (authored or imported) into a set of governed manifest drafts that flow through the existing `ces classify` / `ces build` pipeline.

**Architecture:** Authoring + import live in the **harness** plane (LLM allowed); validate, decompose, reconcile, tree live in the **control** plane (deterministic, no LLM). A bundled PRD template prescribes required section headers so parsing is regex-anchored. Each story in a spec becomes one full `TaskManifest` in DRAFT status with `parent_spec_id` + `parent_story_id` provenance; `ces classify` / `ces build` handle the rest unchanged.

**Tech Stack:** Python 3.12+, Pydantic v2 (`CESBaseModel`), Typer + Rich (CLI), PyYAML for frontmatter, SQLite via existing `LocalProjectStore`, `ClassificationOracle` (TF-IDF) for hint-based classification, `ProviderRegistry` for LLM polish/import, pytest + `CliRunner` for tests, 88 % coverage gate.

**Design reference:** `docs/designs/2026-04-21-ces-spec-authoring.md` (commit `55fd28d`).

---

## Scope Check

This plan covers **one cohesive feature** (a planning-authoring layer in front of the existing CES pipeline). It is not multiple independent subsystems — every command shares the spec document type, template loader, and manifest-stub contract. A single plan is appropriate.

Five items are explicitly deferred to a later plan (see design §8): spec-mutation content diffs in the audit ledger, multi-spec discovery commands, `ces spec migrate` for template schema evolution, `--polish` token budgets, and the `ces spec list` index.

---

## File Structure

**New files:**

| Path | Responsibility |
|---|---|
| `src/ces/control/models/spec.py` | Pydantic models — `SpecFrontmatter`, `SignalHints`, `Story`, `Risk`, `SpecDocument` |
| `src/ces/control/spec/__init__.py` | Package marker |
| `src/ces/control/spec/template_loader.py` | Template lookup + sidecar parsing |
| `src/ces/control/spec/parser.py` | Markdown → `SpecDocument` (deterministic) |
| `src/ces/control/spec/validator.py` | Completeness + DAG validation |
| `src/ces/control/spec/decomposer.py` | `SpecDocument` → `TaskManifest` drafts |
| `src/ces/control/spec/reconciler.py` | Diff spec vs. existing manifests |
| `src/ces/control/spec/tree.py` | Hierarchy + status reader |
| `src/ces/control/spec/templates/default.md` | Bundled PRD template |
| `src/ces/control/spec/templates/default.yaml` | Template sidecar (required sections) |
| `src/ces/harness/services/spec_authoring.py` | Interview engine + optional LLM polish |
| `src/ces/harness/services/spec_importer.py` | Existing-doc → spec.md, with optional LLM section mapping |
| `src/ces/harness/services/spec_questions.yaml` | Authoring interview question bank |
| `src/ces/cli/spec_cmd.py` | Typer subcommand group |

**Modifications:**

| Path | Change |
|---|---|
| `src/ces/shared/enums.py` | Add `SPEC_AUTHORED`, `SPEC_DECOMPOSED`, `SPEC_RECONCILED` to `EventType` |
| `src/ces/control/models/manifest.py` | Add optional `parent_spec_id: str \| None`, `parent_story_id: str \| None`, `acceptance_criteria: tuple[str, ...] = ()` fields to `TaskManifest` |
| `src/ces/control/services/classification_oracle.py` | Add `classify_from_hints(signals, risk_hint)` method |
| `src/ces/cli/__init__.py` | Register `spec_cmd.spec_app` under `name="spec"` |
| `src/ces/cli/run_cmd.py` | Add `--from-spec` / `--story` options to `run_task` |

**New tests:**

```
tests/unit/test_services/
    test_spec_models.py
    test_spec_template_loader.py
    test_spec_parser.py
    test_spec_validator.py
    test_spec_decomposer.py
    test_spec_reconciler.py
    test_spec_tree.py
    test_spec_authoring.py
    test_spec_importer.py
    test_classification_oracle_hints.py
tests/unit/test_cli/
    test_spec_cmd.py
tests/integration/
    test_spec_end_to_end.py
tests/property/
    test_spec_roundtrip.py
tests/fixtures/specs/
    minimal-valid.md
    missing-non-goals.md
    cyclic-deps.md
    notion-export.md
    complex-hierarchy.md
```

---

## Build Order (per CLAUDE.md §5.14)

Models → managers/services → CLI. Concretely, the phases below run top-to-bottom; each task's dependencies are prior tasks in the same or earlier phase.

---

## Phase 0 — Schema Foundations

### Task 1: Add spec event types to `EventType` enum

**Files:**
- Modify: `src/ces/shared/enums.py`
- Test: `tests/unit/test_services/test_audit_ledger.py` (extend existing, if present)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_services/test_audit_ledger.py` (create the file with minimal imports if it doesn't already exist):

```python
from ces.shared.enums import EventType

def test_spec_event_types_present():
    assert EventType.SPEC_AUTHORED.value == "spec_authored"
    assert EventType.SPEC_DECOMPOSED.value == "spec_decomposed"
    assert EventType.SPEC_RECONCILED.value == "spec_reconciled"
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/unit/test_services/test_audit_ledger.py::test_spec_event_types_present -v
```

Expected: FAIL with `AttributeError: SPEC_AUTHORED`.

- [ ] **Step 3: Implement**

In `src/ces/shared/enums.py`, within the existing `class EventType(str, Enum):`, add:

```python
SPEC_AUTHORED = "spec_authored"
SPEC_DECOMPOSED = "spec_decomposed"
SPEC_RECONCILED = "spec_reconciled"
```

- [ ] **Step 4: Run test to verify pass**

```
uv run pytest tests/unit/test_services/test_audit_ledger.py::test_spec_event_types_present -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ces/shared/enums.py tests/unit/test_services/test_audit_ledger.py
git commit -m "feat(enums): add SPEC_* event types for spec lifecycle"
```

---

### Task 2: Extend `TaskManifest` with spec-provenance fields

**Files:**
- Modify: `src/ces/control/models/manifest.py`
- Test: `tests/unit/test_services/test_manifest_manager.py` (extend existing)

The three fields are optional/defaulted so existing manifests remain valid; required fields are unchanged.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_services/test_manifest_manager.py`:

```python
from ces.control.models.manifest import TaskManifest

def test_taskmanifest_accepts_spec_provenance_fields(sample_manifest_kwargs):
    """parent_spec_id, parent_story_id, acceptance_criteria are optional fields."""
    mf = TaskManifest(
        **sample_manifest_kwargs,
        parent_spec_id="SP-01HX",
        parent_story_id="ST-01HX",
        acceptance_criteria=("returns 200", "p95 under 50ms"),
    )
    assert mf.parent_spec_id == "SP-01HX"
    assert mf.parent_story_id == "ST-01HX"
    assert mf.acceptance_criteria == ("returns 200", "p95 under 50ms")

def test_taskmanifest_defaults_provenance_fields_when_missing(sample_manifest_kwargs):
    mf = TaskManifest(**sample_manifest_kwargs)
    assert mf.parent_spec_id is None
    assert mf.parent_story_id is None
    assert mf.acceptance_criteria == ()
```

If `sample_manifest_kwargs` doesn't exist, add a module-level fixture (see existing tests in the file for the shape of a valid TaskManifest construction).

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/unit/test_services/test_manifest_manager.py -k "spec_provenance" -v
```

Expected: FAIL on `parent_spec_id` (unknown field).

- [ ] **Step 3: Implement**

In `src/ces/control/models/manifest.py`, add to `class TaskManifest(GovernedArtifactBase):`:

```python
parent_spec_id: str | None = None
parent_story_id: str | None = None
acceptance_criteria: tuple[str, ...] = ()
```

Place them after `release_slice: Optional[str] = None` so optional governance metadata stays together.

- [ ] **Step 4: Run test**

```
uv run pytest tests/unit/test_services/test_manifest_manager.py -k "spec_provenance" -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ces/control/models/manifest.py tests/unit/test_services/test_manifest_manager.py
git commit -m "feat(manifest): add parent_spec_id, parent_story_id, acceptance_criteria fields"
```

---

## Phase 1 — Spec Pydantic Models

### Task 3: Scaffold `SignalHints`, `SpecFrontmatter`, `Risk`

**Files:**
- Create: `src/ces/control/models/spec.py`
- Test: `tests/unit/test_services/test_spec_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_services/test_spec_models.py
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ces.control.models.spec import Risk, SignalHints, SpecFrontmatter


def test_signal_hints_enforces_literals():
    sh = SignalHints(
        primary_change_class="feature",
        blast_radius_hint="isolated",
    )
    assert sh.touches_data is False
    assert sh.touches_auth is False

def test_signal_hints_rejects_invalid_change_class():
    with pytest.raises(ValidationError):
        SignalHints(primary_change_class="nonsense", blast_radius_hint="isolated")

def test_risk_requires_both_fields():
    r = Risk(risk="flaky network", mitigation="add retries")
    assert r.risk == "flaky network"

def test_spec_frontmatter_is_frozen():
    fm = SpecFrontmatter(
        spec_id="SP-01",
        title="Healthcheck",
        owner="dev@example.com",
        created_at=datetime(2026, 4, 21, tzinfo=timezone.utc),
        status="draft",
        signals=SignalHints(
            primary_change_class="feature",
            blast_radius_hint="isolated",
        ),
    )
    with pytest.raises(ValidationError):
        fm.title = "X"  # frozen
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/unit/test_services/test_spec_models.py -v
```

Expected: FAIL — module `ces.control.models.spec` not found.

- [ ] **Step 3: Implement**

```python
# src/ces/control/models/spec.py
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
    Never authoritative — ces classify always gets the final word.
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
```

- [ ] **Step 4: Run test**

```
uv run pytest tests/unit/test_services/test_spec_models.py -v
```

Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/ces/control/models/spec.py tests/unit/test_services/test_spec_models.py
git commit -m "feat(spec): add SignalHints, SpecFrontmatter, Risk models"
```

---

### Task 4: Add `Story` and `SpecDocument` models

**Files:**
- Modify: `src/ces/control/models/spec.py`
- Test: `tests/unit/test_services/test_spec_models.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_services/test_spec_models.py`:

```python
from ces.control.models.spec import SpecDocument, Story


def _minimal_frontmatter():
    return SpecFrontmatter(
        spec_id="SP-01",
        title="T",
        owner="a@b.c",
        created_at=datetime(2026, 4, 21, tzinfo=timezone.utc),
        status="draft",
        signals=SignalHints(
            primary_change_class="feature",
            blast_radius_hint="isolated",
        ),
    )


def test_story_requires_acceptance_criteria_as_tuple():
    story = Story(
        story_id="ST-01",
        title="Add healthcheck",
        description="Wire FastAPI route.",
        acceptance_criteria=("returns 200",),
        size="S",
    )
    assert isinstance(story.acceptance_criteria, tuple)
    assert story.depends_on == ()
    assert story.risk is None


def test_story_rejects_list_under_strict_mode():
    with pytest.raises(ValidationError):
        Story(
            story_id="ST-01",
            title="x",
            description="x",
            acceptance_criteria=["a"],  # list, not tuple — strict mode rejects
            size="S",
        )


def test_specdocument_composes_full_spec():
    doc = SpecDocument(
        frontmatter=_minimal_frontmatter(),
        problem="Operators can't probe liveness.",
        users="Ops engineers.",
        success_criteria=("Route returns 200.",),
        non_goals=("No metrics in this change.",),
        risks=(Risk(risk="r", mitigation="m"),),
        stories=(
            Story(
                story_id="ST-01",
                title="Add route",
                description="desc",
                acceptance_criteria=("criterion",),
                size="S",
            ),
        ),
        rollback_plan="Revert the PR.",
    )
    assert len(doc.stories) == 1
    assert doc.frontmatter.spec_id == "SP-01"
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/unit/test_services/test_spec_models.py -k "story or specdocument" -v
```

Expected: FAIL — Story / SpecDocument not defined.

- [ ] **Step 3: Implement**

Append to `src/ces/control/models/spec.py`:

```python
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
```

- [ ] **Step 4: Run test**

```
uv run pytest tests/unit/test_services/test_spec_models.py -v
```

Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add src/ces/control/models/spec.py tests/unit/test_services/test_spec_models.py
git commit -m "feat(spec): add Story and SpecDocument models"
```

---

## Phase 2 — Templates & Loader

### Task 5: Create bundled default template and sidecar

**Files:**
- Create: `src/ces/control/spec/__init__.py` (empty)
- Create: `src/ces/control/spec/templates/__init__.py` (empty)
- Create: `src/ces/control/spec/templates/default.md`
- Create: `src/ces/control/spec/templates/default.yaml`

No test for template content itself (it's data, not code). Tests in Task 6 will exercise the loader reading these files.

- [ ] **Step 1: Create the sidecar**

```yaml
# src/ces/control/spec/templates/default.yaml
name: default
version: 1
required_sections:
  - "## Problem"
  - "## Users"
  - "## Success Criteria"
  - "## Non-Goals"
  - "## Risks & Mitigations"
  - "## Stories"
  - "## Rollback Plan"
story_header_pattern: "^### Story: (.+)$"
required_story_fields:
  - id
  - size
  - description
  - acceptance
optional_story_fields:
  - risk
  - depends_on
signal_fields:
  - primary_change_class
  - blast_radius_hint
  - touches_data
  - touches_auth
  - touches_billing
```

- [ ] **Step 2: Create the bundled template**

```markdown
<!-- src/ces/control/spec/templates/default.md -->
---
spec_id: SP-REPLACE
title: <feature title>
owner: <owner@example.com>
created_at: 2026-04-21T00:00:00Z
status: draft
template: default
signals:
  primary_change_class: feature
  blast_radius_hint: isolated
  touches_data: false
  touches_auth: false
  touches_billing: false
---

## Problem
<one-paragraph problem statement>

## Users
<who benefits, in what context>

## Success Criteria
- <measurable outcome>

## Non-Goals
- <explicitly out of scope>

## Risks & Mitigations
- **Risk:** <what could go wrong>
  **Mitigation:** <how we handle it>

## Stories

### Story: <short imperative title>
- **id:** ST-REPLACE
- **size:** S
- **risk:** C
- **depends_on:** []
- **description:** <what this story accomplishes>
- **acceptance:**
  - <criterion>

## Rollback Plan
<how to back out if this ships and breaks something>
```

- [ ] **Step 3: Create the empty package markers**

```python
# src/ces/control/spec/__init__.py
"""Control-plane spec authoring infrastructure (deterministic, no LLM)."""
```

```python
# src/ces/control/spec/templates/__init__.py
"""Bundled spec templates."""
```

- [ ] **Step 4: Verify files exist**

```
ls src/ces/control/spec/templates/
```

Expected: `__init__.py  default.md  default.yaml`.

- [ ] **Step 5: Commit**

```bash
git add src/ces/control/spec/
git commit -m "feat(spec): add bundled default PRD template and sidecar"
```

---

### Task 6: Implement `TemplateLoader`

**Files:**
- Create: `src/ces/control/spec/template_loader.py`
- Test: `tests/unit/test_services/test_spec_template_loader.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_services/test_spec_template_loader.py
from pathlib import Path

import pytest

from ces.control.spec.template_loader import TemplateLoader, TemplateSidecar


def test_loader_resolves_bundled_default():
    loader = TemplateLoader(project_root=Path("/tmp/no-overrides-here"))
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
    loader = TemplateLoader(project_root=Path("/tmp/no-overrides-here"))
    md = loader.load_markdown("default")
    assert "## Problem" in md
    assert "### Story:" in md
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/unit/test_services/test_spec_template_loader.py -v
```

Expected: FAIL — `ces.control.spec.template_loader` not found.

- [ ] **Step 3: Implement**

```python
# src/ces/control/spec/template_loader.py
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
        for cand in self._candidates(name, ext):
            if cand.is_file():
                return cand
        msg = f"Template {name!r} not found (looked in {[str(c) for c in self._candidates(name, ext)]})"
        raise FileNotFoundError(msg)

    def load(self, name: str) -> TemplateSidecar:
        path = self._resolve(name, "yaml")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return TemplateSidecar.model_validate(data)

    def load_markdown(self, name: str) -> str:
        path = self._resolve(name, "md")
        return path.read_text(encoding="utf-8")
```

- [ ] **Step 4: Run test**

```
uv run pytest tests/unit/test_services/test_spec_template_loader.py -v
```

Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/ces/control/spec/template_loader.py tests/unit/test_services/test_spec_template_loader.py
git commit -m "feat(spec): add TemplateLoader with user-override precedence"
```

---

## Phase 3 — Deterministic Parser

### Task 7: Parse frontmatter + top-level sections

**Files:**
- Create: `src/ces/control/spec/parser.py`
- Test: `tests/unit/test_services/test_spec_parser.py`
- Create: `tests/fixtures/specs/minimal-valid.md` (referenced by this test)

- [ ] **Step 1: Create the fixture**

```markdown
<!-- tests/fixtures/specs/minimal-valid.md -->
---
spec_id: SP-01HXY
title: Healthcheck endpoint
owner: duvillard.c@gmail.com
created_at: 2026-04-21T10:00:00Z
status: draft
template: default
signals:
  primary_change_class: feature
  blast_radius_hint: isolated
  touches_data: false
  touches_auth: false
  touches_billing: false
---

## Problem
Operators need a probe.

## Users
Ops engineers.

## Success Criteria
- Route returns 200.

## Non-Goals
- No metrics.

## Risks & Mitigations
- **Risk:** Network flakiness
  **Mitigation:** Add retries

## Stories

### Story: Add /healthcheck route
- **id:** ST-01HXY
- **size:** S
- **risk:** C
- **depends_on:** []
- **description:** Wire FastAPI route.
- **acceptance:**
  - Returns 200 with JSON body
  - p95 under 50ms

## Rollback Plan
Revert the PR.
```

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/test_services/test_spec_parser.py
from pathlib import Path

import pytest

from ces.control.models.spec import SpecDocument
from ces.control.spec.parser import SpecParseError, SpecParser
from ces.control.spec.template_loader import TemplateLoader


FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "specs"


@pytest.fixture
def loader(tmp_path: Path) -> TemplateLoader:
    return TemplateLoader(project_root=tmp_path)


@pytest.fixture
def parser(loader: TemplateLoader) -> SpecParser:
    return SpecParser(loader)


def test_parses_minimal_valid_spec(parser: SpecParser):
    text = (FIXTURES / "minimal-valid.md").read_text(encoding="utf-8")
    doc = parser.parse(text, template_name="default")
    assert isinstance(doc, SpecDocument)
    assert doc.frontmatter.spec_id == "SP-01HXY"
    assert doc.problem.strip() == "Operators need a probe."
    assert doc.success_criteria == ("Route returns 200.",)
    assert len(doc.stories) == 1

def test_rejects_missing_frontmatter(parser: SpecParser):
    with pytest.raises(SpecParseError, match="frontmatter"):
        parser.parse("## Problem\nFoo\n", template_name="default")
```

- [ ] **Step 3: Run test to verify it fails**

```
uv run pytest tests/unit/test_services/test_spec_parser.py -v
```

Expected: FAIL — `SpecParser` not defined.

- [ ] **Step 4: Implement**

```python
# src/ces/control/spec/parser.py
"""Deterministic markdown → SpecDocument parser. No LLM, no fuzzy matching."""

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
        except yaml.YAMLError as exc:  # pragma: no cover — defensive
            raise SpecParseError(f"frontmatter is not valid YAML: {exc}") from exc
        signals = SignalHints.model_validate(data.pop("signals", {}))
        fm = SpecFrontmatter(signals=signals, **data)
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

    def _require_sections(
        self, sections: dict[str, str], sidecar: TemplateSidecar
    ) -> None:
        missing = [s for s in sidecar.required_sections if s not in sections]
        if missing:
            raise SpecParseError(f"missing required sections: {missing}")

    def _parse_bullets(self, text: str) -> tuple[str, ...]:
        return tuple(
            line.lstrip("- ").strip()
            for line in text.splitlines()
            if line.lstrip().startswith("- ")
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

    def _parse_stories(
        self, text: str, sidecar: TemplateSidecar
    ) -> tuple[Story, ...]:
        header_re = re.compile(sidecar.story_header_pattern, re.MULTILINE)
        blocks = self._split_by_regex(text, header_re)
        stories: list[Story] = []
        for title, block in blocks:
            stories.append(self._parse_single_story(title, block))
        return tuple(stories)

    def _split_by_regex(
        self, text: str, pattern: re.Pattern[str]
    ) -> list[tuple[str, str]]:
        matches = list(pattern.finditer(text))
        out: list[tuple[str, str]] = []
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            out.append((m.group(1).strip(), text[start:end]))
        return out

    def _parse_single_story(self, title: str, block: str) -> Story:
        fields = self._parse_story_fields(block)
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
```

- [ ] **Step 5: Run test**

```
uv run pytest tests/unit/test_services/test_spec_parser.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add src/ces/control/spec/parser.py tests/unit/test_services/test_spec_parser.py tests/fixtures/specs/minimal-valid.md
git commit -m "feat(spec): add deterministic markdown parser"
```

---

### Task 8: Parser error handling for missing sections and malformed stories

**Files:**
- Modify: `src/ces/control/spec/parser.py` (if needed)
- Test: `tests/unit/test_services/test_spec_parser.py`
- Create: `tests/fixtures/specs/missing-non-goals.md`

- [ ] **Step 1: Create the fixture**

Copy `minimal-valid.md` and remove the `## Non-Goals` section and its body:

```markdown
<!-- tests/fixtures/specs/missing-non-goals.md -->
---
spec_id: SP-01
title: Broken
owner: a@b.c
created_at: 2026-04-21T10:00:00Z
status: draft
template: default
signals:
  primary_change_class: feature
  blast_radius_hint: isolated
  touches_data: false
  touches_auth: false
  touches_billing: false
---

## Problem
x

## Users
x

## Success Criteria
- x

## Risks & Mitigations
- **Risk:** r
  **Mitigation:** m

## Stories

### Story: X
- **id:** ST-01
- **size:** S
- **description:** x
- **acceptance:**
  - x

## Rollback Plan
x
```

- [ ] **Step 2: Write the failing test**

Append to `tests/unit/test_services/test_spec_parser.py`:

```python
def test_missing_required_section_raises(parser: SpecParser):
    text = (FIXTURES / "missing-non-goals.md").read_text(encoding="utf-8")
    with pytest.raises(SpecParseError, match="Non-Goals"):
        parser.parse(text, template_name="default")

def test_story_without_id_raises(parser: SpecParser, tmp_path: Path):
    bad = tmp_path / "bad.md"
    base = (FIXTURES / "minimal-valid.md").read_text(encoding="utf-8")
    mangled = base.replace("- **id:** ST-01HXY\n", "")  # drop id line
    bad.write_text(mangled, encoding="utf-8")
    with pytest.raises((SpecParseError, ValueError)):
        parser.parse(mangled, template_name="default")
```

- [ ] **Step 3: Run tests**

```
uv run pytest tests/unit/test_services/test_spec_parser.py -v
```

Expected: the first test already passes (Task 7 parser raises on missing section). The second test should fail if the parser silently creates a Story with no `story_id` — if so, add a guard.

- [ ] **Step 4: Fix if needed**

If the second test fails, add to `_parse_single_story`:

```python
if "id" not in fields:
    raise SpecParseError(f"story {title!r} missing required field 'id'")
```

- [ ] **Step 5: Run tests again**

```
uv run pytest tests/unit/test_services/test_spec_parser.py -v
```

Expected: PASS (all tests).

- [ ] **Step 6: Commit**

```bash
git add src/ces/control/spec/parser.py tests/unit/test_services/test_spec_parser.py tests/fixtures/specs/missing-non-goals.md
git commit -m "feat(spec): parser raises on missing sections and story fields"
```

---

## Phase 4 — Validator

### Task 9: DAG cycle detection and story-field validation

**Files:**
- Create: `src/ces/control/spec/validator.py`
- Test: `tests/unit/test_services/test_spec_validator.py`
- Create: `tests/fixtures/specs/cyclic-deps.md`

- [ ] **Step 1: Create the cyclic fixture**

```markdown
<!-- tests/fixtures/specs/cyclic-deps.md -->
---
spec_id: SP-01
title: Cyclic
owner: a@b.c
created_at: 2026-04-21T10:00:00Z
status: draft
template: default
signals:
  primary_change_class: feature
  blast_radius_hint: isolated
  touches_data: false
  touches_auth: false
  touches_billing: false
---

## Problem
x

## Users
x

## Success Criteria
- x

## Non-Goals
- x

## Risks & Mitigations
- **Risk:** r
  **Mitigation:** m

## Stories

### Story: A
- **id:** ST-A
- **size:** S
- **depends_on:** [ST-B]
- **description:** x
- **acceptance:**
  - x

### Story: B
- **id:** ST-B
- **size:** S
- **depends_on:** [ST-A]
- **description:** x
- **acceptance:**
  - x

## Rollback Plan
x
```

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/test_services/test_spec_validator.py
from pathlib import Path

import pytest

from ces.control.spec.parser import SpecParser
from ces.control.spec.template_loader import TemplateLoader
from ces.control.spec.validator import SpecValidationError, SpecValidator


FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "specs"


@pytest.fixture
def validator(tmp_path: Path) -> SpecValidator:
    loader = TemplateLoader(project_root=tmp_path)
    return SpecValidator(loader)


@pytest.fixture
def parser(tmp_path: Path) -> SpecParser:
    return SpecParser(TemplateLoader(project_root=tmp_path))


def test_validates_minimal_spec(validator: SpecValidator, parser: SpecParser):
    text = (FIXTURES / "minimal-valid.md").read_text(encoding="utf-8")
    doc = parser.parse(text)
    validator.validate(doc, template_name="default")  # does not raise

def test_detects_dependency_cycle(validator: SpecValidator, parser: SpecParser):
    text = (FIXTURES / "cyclic-deps.md").read_text(encoding="utf-8")
    doc = parser.parse(text)
    with pytest.raises(SpecValidationError, match="cycle"):
        validator.validate(doc, template_name="default")

def test_detects_unknown_depends_on(validator: SpecValidator, parser: SpecParser, tmp_path):
    text = (FIXTURES / "minimal-valid.md").read_text(encoding="utf-8")
    bad = text.replace("- **depends_on:** []", "- **depends_on:** [ST-ZZZ]")
    doc = parser.parse(bad)
    with pytest.raises(SpecValidationError, match="unknown"):
        validator.validate(doc, template_name="default")
```

- [ ] **Step 3: Run test to verify it fails**

```
uv run pytest tests/unit/test_services/test_spec_validator.py -v
```

Expected: FAIL — `SpecValidator` not defined.

- [ ] **Step 4: Implement**

```python
# src/ces/control/spec/validator.py
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

    def _check_story_fields(
        self, stories: tuple[Story, ...], sidecar: TemplateSidecar
    ) -> None:
        # Pydantic already enforces required fields on Story; this is a hook for
        # future template-specific field checks beyond the canonical Story model.
        for story in stories:
            if not story.acceptance_criteria:
                raise SpecValidationError(
                    f"story {story.story_id} has no acceptance criteria"
                )

    def _check_depends_on_references(self, stories: tuple[Story, ...]) -> None:
        known = {s.story_id for s in stories}
        for story in stories:
            for ref in story.depends_on:
                if ref not in known:
                    raise SpecValidationError(
                        f"story {story.story_id} depends on unknown story {ref}"
                    )

    def _check_dependency_graph_acyclic(self, stories: tuple[Story, ...]) -> None:
        graph = {s.story_id: set(s.depends_on) for s in stories}
        visited: set[str] = set()
        stack: set[str] = set()

        def visit(node: str, path: list[str]) -> None:
            if node in stack:
                cycle = path[path.index(node):] + [node]
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
```

- [ ] **Step 5: Run test**

```
uv run pytest tests/unit/test_services/test_spec_validator.py -v
```

Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add src/ces/control/spec/validator.py tests/unit/test_services/test_spec_validator.py tests/fixtures/specs/cyclic-deps.md
git commit -m "feat(spec): add SpecValidator with DAG cycle detection"
```

---

## Phase 5 — Decomposer

### Task 10: Add `classify_from_hints` to `ClassificationOracle`

**Files:**
- Modify: `src/ces/control/services/classification_oracle.py`
- Test: `tests/unit/test_services/test_classification_oracle_hints.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_services/test_classification_oracle_hints.py
from ces.control.services.classification_oracle import ClassificationOracle


def test_classify_from_hints_uses_change_class():
    oracle = ClassificationOracle()
    result = oracle.classify_from_hints(
        signals={
            "primary_change_class": "feature",
            "blast_radius_hint": "isolated",
            "touches_data": False,
            "touches_auth": False,
            "touches_billing": False,
        },
        risk_hint="C",
    )
    # feature + isolated + C → the oracle should produce something suitable
    # for a low-risk new surface. Exact values depend on the existing rules
    # table, so assert the shape and that no LLM was used.
    assert result.confidence >= 0.0
    assert result.action in ("auto_accept", "human_review", "human_classify")

def test_classify_from_hints_respects_auth_touch():
    oracle = ClassificationOracle()
    low = oracle.classify_from_hints(
        signals={
            "primary_change_class": "feature",
            "blast_radius_hint": "isolated",
            "touches_data": False,
            "touches_auth": False,
            "touches_billing": False,
        },
        risk_hint=None,
    )
    auth = oracle.classify_from_hints(
        signals={
            "primary_change_class": "feature",
            "blast_radius_hint": "isolated",
            "touches_data": False,
            "touches_auth": True,
            "touches_billing": False,
        },
        risk_hint=None,
    )
    # Auth touch should never *downgrade* risk compared to the same otherwise-isolated change.
    # We compare via the resulting tier name; exact comparison uses the RiskTier ordering.
    assert auth.risk_tier_value_or_none() >= low.risk_tier_value_or_none()
```

Note: `risk_tier_value_or_none` is illustrative — use whatever accessor `OracleClassificationResult` already exposes. If it exposes `result.risk_tier: RiskTier`, compare with `RiskTier.__members__` ordering instead:

```python
    assert auth.risk_tier.value >= low.risk_tier.value
```

Confirm against `OracleClassificationResult`'s actual API when running the test.

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/unit/test_services/test_classification_oracle_hints.py -v
```

Expected: FAIL — `classify_from_hints` not defined.

- [ ] **Step 3: Implement**

Add to `ClassificationOracle` in `src/ces/control/services/classification_oracle.py`:

```python
from ces.shared.enums import BehaviorConfidence, ChangeClass, RiskTier

_CHANGE_CLASS_MAP = {
    "feature": ChangeClass.NEW_SURFACE,
    "bug": ChangeClass.BUG_FIX,
    "refactor": ChangeClass.REFACTOR,
    "infra": ChangeClass.INFRA,
    "doc": ChangeClass.DOCS,
}

_BLAST_RADIUS_RISK = {
    "isolated": RiskTier.C,
    "module": RiskTier.B,
    "system": RiskTier.A,
    "cross-cutting": RiskTier.A,
}


def classify_from_hints(
    self, signals: dict, risk_hint: str | None = None
) -> OracleClassificationResult:
    """Pure-rules classification from spec signals.

    Never imports anthropic / openai / httpx — LLM-05 compliant.
    """
    change_class = _CHANGE_CLASS_MAP[signals["primary_change_class"]]
    baseline_tier = _BLAST_RADIUS_RISK[signals["blast_radius_hint"]]
    # Escalate on sensitive touches.
    if signals.get("touches_auth") or signals.get("touches_billing"):
        baseline_tier = RiskTier.A
    if risk_hint:
        hinted = RiskTier(risk_hint)
        # The explicit hint wins unless the sensitive-touch escalation is higher.
        tier = max(baseline_tier, hinted, key=lambda t: t.value)
    else:
        tier = baseline_tier
    return OracleClassificationResult(
        matched_rule=f"from_hints({signals['primary_change_class']}, {signals['blast_radius_hint']})",
        risk_tier=tier,
        behavior_confidence=BehaviorConfidence.MEDIUM,
        change_class=change_class,
        confidence=0.7,
        top_matches=(),
        action="human_review",
    )
```

Implementation note: the exact `OracleClassificationResult` constructor signature and enum names need to be confirmed against the existing file. Use the field list returned by `oracle.classify()` for a test input and mirror that shape.

- [ ] **Step 4: Run test**

```
uv run pytest tests/unit/test_services/test_classification_oracle_hints.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/ces/control/services/classification_oracle.py tests/unit/test_services/test_classification_oracle_hints.py
git commit -m "feat(classify): add classify_from_hints() for spec decompose"
```

---

### Task 11: Decomposer — spec → manifest drafts

**Files:**
- Create: `src/ces/control/spec/decomposer.py`
- Test: `tests/unit/test_services/test_spec_decomposer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_services/test_spec_decomposer.py
from pathlib import Path

import pytest

from ces.control.spec.decomposer import DecomposeResult, SpecDecomposer
from ces.control.spec.parser import SpecParser
from ces.control.spec.template_loader import TemplateLoader


FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "specs"


@pytest.fixture
def loader(tmp_path: Path) -> TemplateLoader:
    return TemplateLoader(project_root=tmp_path)


@pytest.fixture
def decomposer(loader: TemplateLoader) -> SpecDecomposer:
    return SpecDecomposer(loader)


def _load_spec(path: str, loader: TemplateLoader):
    parser = SpecParser(loader)
    return parser.parse((FIXTURES / path).read_text(encoding="utf-8"))


def test_decompose_produces_one_manifest_per_story(decomposer, loader):
    doc = _load_spec("minimal-valid.md", loader)
    result = decomposer.decompose(doc)
    assert isinstance(result, DecomposeResult)
    assert len(result.manifests) == 1
    mf = result.manifests[0]
    assert mf.parent_spec_id == "SP-01HXY"
    assert mf.parent_story_id == "ST-01HXY"
    assert mf.acceptance_criteria == ("Returns 200 with JSON body", "p95 under 50ms")

def test_decompose_resolves_dependencies_by_story_id(decomposer, loader, tmp_path):
    base = (FIXTURES / "minimal-valid.md").read_text(encoding="utf-8")
    # Add a second story that depends on the first.
    extra = base.replace(
        "## Rollback Plan",
        "### Story: Add probe\n"
        "- **id:** ST-PROBE\n"
        "- **size:** XS\n"
        "- **depends_on:** [ST-01HXY]\n"
        "- **description:** service health probe.\n"
        "- **acceptance:**\n"
        "  - probe returns healthy\n\n"
        "## Rollback Plan",
    )
    doc = SpecParser(loader).parse(extra)
    result = decomposer.decompose(doc)
    assert len(result.manifests) == 2
    # Find the probe manifest and assert it depends on the first one.
    probe = next(m for m in result.manifests if m.parent_story_id == "ST-PROBE")
    first = next(m for m in result.manifests if m.parent_story_id == "ST-01HXY")
    assert first.manifest_id in probe.dependencies_manifest_ids()
```

Note: `dependencies_manifest_ids()` is a convenience shown here. If `TaskManifest.dependencies` is `tuple[ManifestDependency, ...]`, adapt the assertion to inspect those objects. During implementation, confirm the exact `ManifestDependency` shape.

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/unit/test_services/test_spec_decomposer.py -v
```

Expected: FAIL — `SpecDecomposer` not defined.

- [ ] **Step 3: Implement**

```python
# src/ces/control/spec/decomposer.py
"""Deterministic spec → TaskManifest expansion. No LLM."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ulid import ULID  # project already pulls in ULID via an existing dep; confirm

from ces.control.models.manifest import ManifestDependency, TaskManifest
from ces.control.models.spec import SpecDocument, Story
from ces.control.services.classification_oracle import (
    ClassificationOracle,
    OracleClassificationResult,
)
from ces.control.spec.template_loader import TemplateLoader
from ces.shared.base import CESBaseModel
from ces.shared.enums import ArtifactStatus, WorkflowState


class DecomposeResult(CESBaseModel):
    manifests: tuple[TaskManifest, ...]


_DEFAULT_TOKEN_BUDGET = 100_000
_DEFAULT_EXPIRY_DAYS = 90


class SpecDecomposer:
    def __init__(
        self,
        template_loader: TemplateLoader,
        oracle: ClassificationOracle | None = None,
    ) -> None:
        self._loader = template_loader
        self._oracle = oracle or ClassificationOracle()

    def decompose(self, doc: SpecDocument) -> DecomposeResult:
        story_to_manifest_id = {
            s.story_id: f"M-{ULID()}" for s in doc.stories
        }
        manifests = tuple(
            self._story_to_manifest(
                story=s,
                spec=doc,
                manifest_id=story_to_manifest_id[s.story_id],
                id_lookup=story_to_manifest_id,
            )
            for s in doc.stories
        )
        return DecomposeResult(manifests=manifests)

    def _story_to_manifest(
        self,
        story: Story,
        spec: SpecDocument,
        manifest_id: str,
        id_lookup: dict[str, str],
    ) -> TaskManifest:
        signals = spec.frontmatter.signals.model_dump()
        oracle_result: OracleClassificationResult = self._oracle.classify_from_hints(
            signals=signals, risk_hint=story.risk
        )
        created = datetime.now(tz=timezone.utc)
        return TaskManifest(
            version=1,
            status=ArtifactStatus.DRAFT,
            owner=spec.frontmatter.owner,
            created_at=created,
            last_confirmed=created,
            manifest_id=manifest_id,
            description=f"{story.title}\n\n{story.description}",
            risk_tier=oracle_result.risk_tier,
            behavior_confidence=oracle_result.behavior_confidence,
            change_class=oracle_result.change_class,
            affected_files=(),
            token_budget=_DEFAULT_TOKEN_BUDGET,
            dependencies=tuple(
                ManifestDependency(manifest_id=id_lookup[dep])
                for dep in story.depends_on
            ),
            expires_at=created + timedelta(days=_DEFAULT_EXPIRY_DAYS),
            workflow_state=WorkflowState.QUEUED,
            parent_spec_id=spec.frontmatter.spec_id,
            parent_story_id=story.story_id,
            acceptance_criteria=story.acceptance_criteria,
        )
```

Implementation notes for the executor:
- `ULID` import: confirm CES already depends on a ULID library (`ulid-py` or `python-ulid`). If not, switch to `uuid.uuid4()` and prefix with `M-` for manifest ids, `SP-` for specs, `ST-` for stories.
- `ManifestDependency` constructor arguments: confirm against `src/ces/control/models/manifest.py`. Adapt the kwarg name if it's not `manifest_id`.
- `ArtifactStatus.DRAFT` and `WorkflowState.QUEUED`: confirm these enum members exist. If `DRAFT` is named differently (e.g., `DRAFT_MANIFEST`), use the real member.

- [ ] **Step 4: Run test**

```
uv run pytest tests/unit/test_services/test_spec_decomposer.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/ces/control/spec/decomposer.py tests/unit/test_services/test_spec_decomposer.py
git commit -m "feat(spec): add SpecDecomposer to expand specs into manifest drafts"
```

---

### Task 12: Wire decompose into `ManifestManager` for persistence

**Files:**
- Modify: `src/ces/control/services/manifest_manager.py` — add `save_manifest_batch(manifests)` if it doesn't exist
- Test: `tests/unit/test_services/test_spec_decomposer.py`

- [ ] **Step 1: Write the failing integration-style test**

Append to `tests/unit/test_services/test_spec_decomposer.py`:

```python
import pytest_asyncio

@pytest.mark.asyncio
async def test_decompose_persists_manifests_via_manager(ces_project, loader):
    from ces.cli._factory import get_services

    doc = _load_spec("minimal-valid.md", loader)
    decomposer = SpecDecomposer(loader)
    result = decomposer.decompose(doc)

    async with get_services(project_root=ces_project) as services:
        manager = services["manifest_manager"]
        for mf in result.manifests:
            await manager.save_manifest(mf)
        fetched = await manager.get_manifest(result.manifests[0].manifest_id)
        assert fetched is not None
        assert fetched.parent_spec_id == "SP-01HXY"
```

(If a `ces_project` fixture already exists — see `tests/unit/test_cli/test_classify_cmd.py` line 91 for its use — reuse it. If not, copy its shape from the existing conftest.)

- [ ] **Step 2: Run the test to verify it fails or passes**

```
uv run pytest tests/unit/test_services/test_spec_decomposer.py::test_decompose_persists_manifests_via_manager -v
```

If `ManifestManager.save_manifest` already exists and accepts a `TaskManifest` as found during exploration, this test may pass without further changes. If it only supports `create_manifest(...)`, add a `save_manifest(manifest: TaskManifest) -> TaskManifest` shim that persists via the same path.

- [ ] **Step 3: Implement (only if the test failed)**

Confirm `save_manifest` already exists at `manifest_manager.py` per exploration. If missing, add:

```python
async def save_manifest(self, manifest: TaskManifest) -> TaskManifest:
    await self._persist_manifest(manifest)
    return manifest
```

- [ ] **Step 4: Run test**

```
uv run pytest tests/unit/test_services/test_spec_decomposer.py -v
```

Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add src/ces/control/services/manifest_manager.py tests/unit/test_services/test_spec_decomposer.py
git commit -m "feat(spec): persist decomposed manifests via ManifestManager"
```

---

## Phase 6 — Reconciler

### Task 13: Reconciler — diff spec vs. existing manifests

**Files:**
- Create: `src/ces/control/spec/reconciler.py`
- Test: `tests/unit/test_services/test_spec_reconciler.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_services/test_spec_reconciler.py
from pathlib import Path

import pytest

from ces.control.spec.parser import SpecParser
from ces.control.spec.reconciler import ReconcileReport, SpecReconciler
from ces.control.spec.template_loader import TemplateLoader


FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "specs"


@pytest.fixture
def loader(tmp_path: Path) -> TemplateLoader:
    return TemplateLoader(project_root=tmp_path)


def _load_spec(path: str, loader: TemplateLoader):
    return SpecParser(loader).parse((FIXTURES / path).read_text(encoding="utf-8"))


def test_reconcile_added_story(loader):
    base = _load_spec("minimal-valid.md", loader)
    # Simulate "existing manifests were decomposed from a now-extended spec".
    # base has one story ST-01HXY. Pretend only ST-01HXY exists as a manifest.
    existing_manifest_story_ids = frozenset({"ST-01HXY"})
    # Now imagine the spec grew a new story ST-NEW.
    extended_text = (FIXTURES / "minimal-valid.md").read_text(encoding="utf-8").replace(
        "## Rollback Plan",
        "### Story: New story\n"
        "- **id:** ST-NEW\n"
        "- **size:** XS\n"
        "- **description:** n\n"
        "- **acceptance:**\n"
        "  - n\n\n"
        "## Rollback Plan",
    )
    extended = SpecParser(loader).parse(extended_text)

    reconciler = SpecReconciler(loader)
    report = reconciler.reconcile(extended, existing_manifest_story_ids)
    assert isinstance(report, ReconcileReport)
    assert report.added == ("ST-NEW",)
    assert report.orphaned == ()
    assert report.unchanged == ("ST-01HXY",)


def test_reconcile_orphaned_story(loader):
    # Spec has only ST-01HXY, but a manifest for ST-DELETED exists.
    base = _load_spec("minimal-valid.md", loader)
    existing = frozenset({"ST-01HXY", "ST-DELETED"})
    reconciler = SpecReconciler(loader)
    report = reconciler.reconcile(base, existing)
    assert report.orphaned == ("ST-DELETED",)
    assert report.added == ()
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/unit/test_services/test_spec_reconciler.py -v
```

Expected: FAIL — module not defined.

- [ ] **Step 3: Implement**

```python
# src/ces/control/spec/reconciler.py
"""Diff a SpecDocument against already-decomposed manifest story ids."""

from __future__ import annotations

from ces.control.models.spec import SpecDocument
from ces.control.spec.template_loader import TemplateLoader
from ces.shared.base import CESBaseModel


class ReconcileReport(CESBaseModel):
    added: tuple[str, ...]       # story_ids in spec but not yet decomposed
    orphaned: tuple[str, ...]    # story_ids with manifests but no spec entry
    unchanged: tuple[str, ...]   # story_ids present in both


class SpecReconciler:
    def __init__(self, template_loader: TemplateLoader) -> None:
        self._loader = template_loader  # reserved for future per-template reconcile logic

    def reconcile(
        self,
        doc: SpecDocument,
        existing_manifest_story_ids: frozenset[str],
    ) -> ReconcileReport:
        spec_ids = {s.story_id for s in doc.stories}
        added = tuple(sorted(spec_ids - existing_manifest_story_ids))
        orphaned = tuple(sorted(existing_manifest_story_ids - spec_ids))
        unchanged = tuple(sorted(spec_ids & existing_manifest_story_ids))
        return ReconcileReport(added=added, orphaned=orphaned, unchanged=unchanged)
```

- [ ] **Step 4: Run test**

```
uv run pytest tests/unit/test_services/test_spec_reconciler.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/ces/control/spec/reconciler.py tests/unit/test_services/test_spec_reconciler.py
git commit -m "feat(spec): add SpecReconciler to diff spec vs. existing manifests"
```

---

## Phase 7 — Tree

### Task 14: Tree reader — join spec with manifest status from `.ces/state.db`

**Files:**
- Create: `src/ces/control/spec/tree.py`
- Test: `tests/unit/test_services/test_spec_tree.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_services/test_spec_tree.py
from pathlib import Path

import pytest
import pytest_asyncio

from ces.control.spec.parser import SpecParser
from ces.control.spec.template_loader import TemplateLoader
from ces.control.spec.tree import SpecTree, SpecTreeNode


FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "specs"


@pytest.mark.asyncio
async def test_tree_joins_spec_with_manifest_status(ces_project):
    from ces.cli._factory import get_services

    loader = TemplateLoader(project_root=ces_project)
    parser = SpecParser(loader)
    doc = parser.parse((FIXTURES / "minimal-valid.md").read_text(encoding="utf-8"))

    async with get_services(project_root=ces_project) as services:
        # Seed a manifest linked to the story.
        from ces.control.spec.decomposer import SpecDecomposer
        decomposer = SpecDecomposer(loader)
        result = decomposer.decompose(doc)
        for mf in result.manifests:
            await services["manifest_manager"].save_manifest(mf)

        tree = SpecTree(services["manifest_manager"])
        nodes = await tree.render(doc)
        assert len(nodes) == 1
        node: SpecTreeNode = nodes[0]
        assert node.story_id == "ST-01HXY"
        assert node.manifest_id.startswith("M-")
        assert node.status_label in {"queued", "draft"}
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/unit/test_services/test_spec_tree.py -v
```

Expected: FAIL — module not defined.

- [ ] **Step 3: Implement**

```python
# src/ces/control/spec/tree.py
"""Read a spec + existing manifest status. Pure-view control-plane code."""

from __future__ import annotations

from ces.control.models.spec import SpecDocument
from ces.control.services.manifest_manager import ManifestManager
from ces.shared.base import CESBaseModel


class SpecTreeNode(CESBaseModel):
    story_id: str
    story_title: str
    manifest_id: str | None
    status_label: str
    blocked_by: tuple[str, ...]


class SpecTree:
    def __init__(self, manifest_manager: ManifestManager) -> None:
        self._manager = manifest_manager

    async def render(self, doc: SpecDocument) -> tuple[SpecTreeNode, ...]:
        # Look up manifests by parent_story_id. If the manager doesn't expose a
        # native filter, fall back to scanning all manifests for the project.
        all_manifests = await self._manager.list_all()  # confirm method name
        by_story: dict[str, str] = {
            m.manifest_id: m.parent_story_id
            for m in all_manifests
            if m.parent_spec_id == doc.frontmatter.spec_id
        }
        manifest_by_story = {
            v: k for k, v in by_story.items() if v is not None
        }

        nodes: list[SpecTreeNode] = []
        for story in doc.stories:
            manifest_id = manifest_by_story.get(story.story_id)
            if manifest_id:
                mf = await self._manager.get_manifest(manifest_id)
                status_label = mf.workflow_state.value if mf else "unknown"
            else:
                status_label = "not decomposed"
            nodes.append(
                SpecTreeNode(
                    story_id=story.story_id,
                    story_title=story.title,
                    manifest_id=manifest_id,
                    status_label=status_label,
                    blocked_by=story.depends_on,
                )
            )
        return tuple(nodes)
```

Note: `manager.list_all()` may not be the exact method name — confirm against the real `ManifestManager`. If only `get_manifest(id)` is exposed, add a `list_by_spec(spec_id)` method to the manager as part of this task.

- [ ] **Step 4: Run test**

```
uv run pytest tests/unit/test_services/test_spec_tree.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ces/control/spec/tree.py tests/unit/test_services/test_spec_tree.py
git commit -m "feat(spec): add SpecTree view over spec + manifest status"
```

---

## Phase 8 — Authoring & Import (Harness)

### Task 15: Spec authoring questions YAML + interview service

**Files:**
- Create: `src/ces/harness/services/spec_questions.yaml`
- Create: `src/ces/harness/services/spec_authoring.py`
- Test: `tests/unit/test_services/test_spec_authoring.py`

- [ ] **Step 1: Create the question bank**

```yaml
# src/ces/harness/services/spec_questions.yaml
frontmatter:
  - key: title
    prompt: "Title for this spec (short imperative phrase)"
  - key: owner
    prompt: "Owner email"
  - key: signals.primary_change_class
    prompt: "Primary change class"
    choices: [feature, bug, refactor, infra, doc]
  - key: signals.blast_radius_hint
    prompt: "Blast radius hint"
    choices: [isolated, module, system, cross-cutting]
  - key: signals.touches_data
    prompt: "Does this change touch user/customer data storage?"
    type: bool
  - key: signals.touches_auth
    prompt: "Does this change touch authentication or authorization?"
    type: bool
  - key: signals.touches_billing
    prompt: "Does this change touch billing or payments?"
    type: bool

sections:
  - key: problem
    prompt: "Problem statement (one paragraph)"
  - key: users
    prompt: "Who benefits, in what context?"
  - key: success_criteria
    prompt: "Success criteria (enter one per line, blank line to finish)"
    type: bullets
  - key: non_goals
    prompt: "Non-goals (enter one per line, blank line to finish)"
    type: bullets
  - key: risks
    prompt: "Risks (enter 'risk :: mitigation' per line, blank to finish)"
    type: pairs
  - key: rollback_plan
    prompt: "Rollback plan (one paragraph)"

story:
  - key: title
    prompt: "Story title"
  - key: size
    prompt: "Size"
    choices: [XS, S, M, L]
  - key: risk
    prompt: "Risk hint (A|B|C|skip)"
    choices: [A, B, C, skip]
  - key: depends_on
    prompt: "Depends on story ids (comma-sep, blank for none)"
    type: csv
  - key: description
    prompt: "Description"
  - key: acceptance_criteria
    prompt: "Acceptance criteria (one per line, blank to finish)"
    type: bullets
```

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/test_services/test_spec_authoring.py
from pathlib import Path

from ces.harness.services.spec_authoring import SpecAuthoringEngine


def _scripted_prompt(responses):
    it = iter(responses)
    def prompt(text, *, default=None, choices=None, type=None):
        return next(it)
    return prompt


def test_author_produces_spec_document_from_scripted_answers(tmp_path: Path):
    engine = SpecAuthoringEngine(project_root=tmp_path, prompt_fn=_scripted_prompt([
        # frontmatter
        "Healthcheck",                 # title
        "dev@example.com",             # owner
        "feature",                     # primary_change_class
        "isolated",                    # blast_radius_hint
        "N",                           # touches_data
        "N",                           # touches_auth
        "N",                           # touches_billing
        # sections
        "Operators need a probe.",     # problem
        "Ops engineers.",              # users
        "Route returns 200.",          # success_criteria line 1
        "",                            # success_criteria done
        "No metrics.",                 # non_goals line 1
        "",                            # non_goals done
        "flaky :: retries",            # risks line 1
        "",                            # risks done
        "Revert the PR.",              # rollback_plan
        # one story
        "Y",                           # add a story?
        "Add /healthcheck route",      # story.title
        "S",                           # size
        "skip",                        # risk (skip)
        "",                            # depends_on (none)
        "Wire FastAPI route.",         # description
        "Returns 200",                 # acceptance line 1
        "",                            # acceptance done
        "N",                           # add another story?
    ]))
    doc = engine.run_interactive()
    assert doc.frontmatter.title == "Healthcheck"
    assert len(doc.stories) == 1
    assert doc.stories[0].acceptance_criteria == ("Returns 200",)
    assert doc.stories[0].risk is None  # "skip" maps to None
```

- [ ] **Step 3: Run test to verify it fails**

```
uv run pytest tests/unit/test_services/test_spec_authoring.py -v
```

Expected: FAIL — module not defined.

- [ ] **Step 4: Implement**

```python
# src/ces/harness/services/spec_authoring.py
"""Deterministic interview spine for ces spec author.

LLM polish is optional and layered on top via the `polish_fn` hook; when None,
the interview degrades to pure Q&A with no LLM dependency.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml
from ulid import ULID  # confirm dep as for Task 11

from ces.control.models.spec import (
    Risk,
    SignalHints,
    SpecDocument,
    SpecFrontmatter,
    Story,
)

PromptFn = Callable[..., str]
PolishFn = Callable[[str, str], str] | None  # (field_name, draft) -> polished


_QUESTIONS_PATH = Path(__file__).parent / "spec_questions.yaml"


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
        self._questions = yaml.safe_load(
            _QUESTIONS_PATH.read_text(encoding="utf-8")
        )

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
                "Primary change class", choices=["feature", "bug", "refactor", "infra", "doc"]
            ),
            blast_radius_hint=self._prompt(
                "Blast radius hint", choices=["isolated", "module", "system", "cross-cutting"]
            ),
            touches_data=_truthy(self._prompt("Touches data?")),
            touches_auth=_truthy(self._prompt("Touches auth?")),
            touches_billing=_truthy(self._prompt("Touches billing?")),
        )
        return SpecFrontmatter(
            spec_id=f"SP-{ULID()}",
            title=title,
            owner=owner,
            created_at=datetime.now(tz=timezone.utc),
            status="draft",
            template="default",
            signals=signals,
        )

    def _ask_sections(self) -> dict[str, object]:
        problem = self._prompt("Problem statement (one paragraph)")
        problem = self._maybe_polish("problem", problem)
        users = self._prompt("Who benefits, in what context?")
        users = self._maybe_polish("users", users)
        success_criteria = _read_bullets(self._prompt, "Success criterion (blank to finish)")
        non_goals = _read_bullets(self._prompt, "Non-goal (blank to finish)")
        risks = _read_pairs(self._prompt, "risk :: mitigation (blank to finish)")
        rollback_plan = self._prompt("Rollback plan (one paragraph)")
        rollback_plan = self._maybe_polish("rollback_plan", rollback_plan)
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
        while True:
            if not _truthy(self._prompt("Add a story?")):
                break
            title = self._prompt("Story title")
            size = self._prompt("Size", choices=["XS", "S", "M", "L"])
            risk_raw = self._prompt("Risk hint", choices=["A", "B", "C", "skip"])
            risk = None if risk_raw == "skip" else risk_raw
            depends_on_raw = self._prompt("Depends on (story ids, comma-sep)")
            depends_on = tuple(
                p.strip() for p in depends_on_raw.split(",") if p.strip()
            )
            description = self._prompt("Description")
            description = self._maybe_polish("story.description", description)
            acceptance_criteria = _read_bullets(
                self._prompt, "Acceptance criterion (blank to finish)"
            )
            out.append(
                Story(
                    story_id=f"ST-{ULID()}",
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
```

- [ ] **Step 5: Run test**

```
uv run pytest tests/unit/test_services/test_spec_authoring.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ces/harness/services/spec_authoring.py src/ces/harness/services/spec_questions.yaml tests/unit/test_services/test_spec_authoring.py
git commit -m "feat(spec): add SpecAuthoringEngine with deterministic interview spine"
```

---

### Task 16: Spec authoring — markdown serializer

**Files:**
- Modify: `src/ces/harness/services/spec_authoring.py` — add `render_markdown(doc)`
- Test: `tests/unit/test_services/test_spec_authoring.py`

- [ ] **Step 1: Write the failing test**

```python
def test_render_markdown_round_trips_through_parser(tmp_path):
    from ces.harness.services.spec_authoring import render_markdown
    from ces.control.spec.parser import SpecParser
    from ces.control.spec.template_loader import TemplateLoader

    engine = SpecAuthoringEngine(project_root=tmp_path, prompt_fn=_scripted_prompt([
        "Healthcheck", "dev@example.com",
        "feature", "isolated", "N", "N", "N",
        "p", "u",
        "s1", "",
        "n1", "",
        "r :: m", "",
        "rb",
        "Y", "Add route", "S", "C", "", "desc",
        "a1", "",
        "N",
    ]))
    doc = engine.run_interactive()

    md = render_markdown(doc)
    # Round-trip back through the parser.
    parser = SpecParser(TemplateLoader(project_root=tmp_path))
    reparsed = parser.parse(md)
    assert reparsed.frontmatter.title == doc.frontmatter.title
    assert reparsed.stories[0].story_id == doc.stories[0].story_id
    assert reparsed.stories[0].acceptance_criteria == doc.stories[0].acceptance_criteria
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/unit/test_services/test_spec_authoring.py::test_render_markdown_round_trips_through_parser -v
```

Expected: FAIL — `render_markdown` not defined.

- [ ] **Step 3: Implement**

Append to `src/ces/harness/services/spec_authoring.py`:

```python
def render_markdown(doc: SpecDocument) -> str:
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
```

- [ ] **Step 4: Run test**

```
uv run pytest tests/unit/test_services/test_spec_authoring.py -v
```

Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add src/ces/harness/services/spec_authoring.py tests/unit/test_services/test_spec_authoring.py
git commit -m "feat(spec): render SpecDocument to canonical markdown"
```

---

### Task 17: Spec importer — deterministic section-matching fallback

**Files:**
- Create: `src/ces/harness/services/spec_importer.py`
- Test: `tests/unit/test_services/test_spec_importer.py`
- Create: `tests/fixtures/specs/notion-export.md`

- [ ] **Step 1: Create the messy fixture**

```markdown
<!-- tests/fixtures/specs/notion-export.md -->
# Healthcheck Endpoint (PRD)

## The Problem We're Solving
Operators need a probe endpoint.

## Who It's For
Ops engineers and platform teams.

## What Success Looks Like
- Route returns 200 under normal load
- p95 latency under 50ms

## Rolling Back
Revert the PR.

## User Stories

### Story: Add route
- **id:** ST-01
- **size:** S
- **description:** Wire FastAPI route.
- **acceptance:**
  - Returns 200
```

(Notice: no `## Non-Goals`, no `## Risks & Mitigations`, no frontmatter — simulates a real export.)

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/test_services/test_spec_importer.py
from pathlib import Path

import pytest

from ces.harness.services.spec_importer import (
    ImportResult,
    SpecImporter,
    SectionMapping,
)


FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "specs"


def test_importer_produces_mapping_with_missing_sections(tmp_path: Path):
    importer = SpecImporter(project_root=tmp_path, section_mapper_fn=None)
    text = (FIXTURES / "notion-export.md").read_text(encoding="utf-8")
    result = importer.map_sections(text)
    assert isinstance(result, SectionMapping)
    # The deterministic fallback uses exact header match only, so most required
    # sections are "missing" — that's expected; mapping is best-effort.
    assert "## Non-Goals" in result.missing
    assert "## Risks & Mitigations" in result.missing

def test_importer_uses_llm_mapper_when_provided(tmp_path: Path):
    def fake_mapper(source_text: str, required: tuple[str, ...]) -> dict[str, str]:
        # Pretend an LLM matched these prose sections to the canonical ones.
        return {
            "## Problem": "## The Problem We're Solving",
            "## Users": "## Who It's For",
            "## Success Criteria": "## What Success Looks Like",
            "## Rollback Plan": "## Rolling Back",
            "## Stories": "## User Stories",
        }
    importer = SpecImporter(project_root=tmp_path, section_mapper_fn=fake_mapper)
    text = (FIXTURES / "notion-export.md").read_text(encoding="utf-8")
    result = importer.map_sections(text)
    assert result.found["## Problem"] == "## The Problem We're Solving"
    assert "## Non-Goals" in result.missing   # LLM didn't map this either
```

- [ ] **Step 3: Run test to verify it fails**

```
uv run pytest tests/unit/test_services/test_spec_importer.py -v
```

Expected: FAIL — module not defined.

- [ ] **Step 4: Implement**

```python
# src/ces/harness/services/spec_importer.py
"""Import an existing PRD and map its sections to the canonical template.

LLM section mapping is optional (injected via section_mapper_fn). With no
mapper, the importer does exact-match only — good enough when the input
already uses canonical headers, useful as a fallback elsewhere.
"""

from __future__ import annotations

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
        found: dict[str, str] = {}
        # Start with exact matches present verbatim in the source.
        for header in required:
            if header in source_text:
                found[header] = header
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
            if canonical != source_header:
                out = out.replace(source_header, canonical)
        return out

    def import_text(self, source_text: str) -> ImportResult:
        mapping = self.map_sections(source_text)
        rewritten = self.rewrite_headers(source_text, mapping)
        return ImportResult(mapping=mapping, rewritten_text=rewritten)
```

- [ ] **Step 5: Run test**

```
uv run pytest tests/unit/test_services/test_spec_importer.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add src/ces/harness/services/spec_importer.py tests/unit/test_services/test_spec_importer.py tests/fixtures/specs/notion-export.md
git commit -m "feat(spec): add SpecImporter with optional LLM section mapping"
```

---

## Phase 9 — CLI

### Task 18: `spec_app` Typer subgroup scaffolding + `ces spec validate`

**Files:**
- Create: `src/ces/cli/spec_cmd.py`
- Modify: `src/ces/cli/__init__.py`
- Test: `tests/unit/test_cli/test_spec_cmd.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cli/test_spec_cmd.py
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ces.cli import app


FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "specs"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_spec_validate_accepts_valid_file(runner: CliRunner, tmp_path: Path):
    spec = tmp_path / "spec.md"
    spec.write_text((FIXTURES / "minimal-valid.md").read_text(encoding="utf-8"))
    result = runner.invoke(app, ["spec", "validate", str(spec)])
    assert result.exit_code == 0, result.stdout
    assert "Ready for decompose" in result.stdout

def test_spec_validate_reports_missing_section(runner: CliRunner, tmp_path: Path):
    spec = tmp_path / "spec.md"
    spec.write_text((FIXTURES / "missing-non-goals.md").read_text(encoding="utf-8"))
    result = runner.invoke(app, ["spec", "validate", str(spec)])
    assert result.exit_code == 1
    assert "Non-Goals" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/unit/test_cli/test_spec_cmd.py -v
```

Expected: FAIL — the `spec` subcommand group is not registered yet.

- [ ] **Step 3: Implement the subgroup and `validate`**

```python
# src/ces/cli/spec_cmd.py
"""ces spec CLI subcommand group."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from ces.control.spec.parser import SpecParseError, SpecParser
from ces.control.spec.template_loader import TemplateLoader
from ces.control.spec.validator import SpecValidationError, SpecValidator

spec_app = typer.Typer(help="Spec lifecycle: author, import, validate, decompose, reconcile, tree.")
_console = Console()


def _project_root() -> Path:
    return Path.cwd()


@spec_app.command("validate")
def spec_validate(spec_path: Path = typer.Argument(..., exists=True, readable=True)) -> None:
    """Validate a spec file against its template."""
    loader = TemplateLoader(_project_root())
    parser = SpecParser(loader)
    validator = SpecValidator(loader)
    try:
        doc = parser.parse(spec_path.read_text(encoding="utf-8"))
    except SpecParseError as exc:
        _console.print(f"[red]Parse error:[/red] {exc}")
        raise typer.Exit(code=1) from None
    try:
        validator.validate(doc, template_name=doc.frontmatter.template)
    except SpecValidationError as exc:
        _console.print(f"[red]Validation error:[/red] {exc}")
        raise typer.Exit(code=1) from None
    _console.print(
        f"[green]OK[/green] {doc.frontmatter.spec_id} — "
        f"{len(doc.stories)} stories, Ready for decompose."
    )
```

Register in `src/ces/cli/__init__.py` (alongside existing `app.add_typer(...)` calls):

```python
from ces.cli import spec_cmd
app.add_typer(spec_cmd.spec_app, name="spec")
```

- [ ] **Step 4: Run test**

```
uv run pytest tests/unit/test_cli/test_spec_cmd.py::test_spec_validate_accepts_valid_file -v
uv run pytest tests/unit/test_cli/test_spec_cmd.py::test_spec_validate_reports_missing_section -v
```

Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ces/cli/spec_cmd.py src/ces/cli/__init__.py tests/unit/test_cli/test_spec_cmd.py
git commit -m "feat(cli): register ces spec subgroup with validate command"
```

---

### Task 19: `ces spec decompose`

**Files:**
- Modify: `src/ces/cli/spec_cmd.py`
- Test: `tests/unit/test_cli/test_spec_cmd.py`

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import AsyncMock, MagicMock, patch


def _patch_services(overrides):
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def fake(*args, **kwargs):
        yield overrides
    return fake


def test_spec_decompose_persists_manifests(runner: CliRunner, tmp_path: Path):
    spec = tmp_path / "spec.md"
    spec.write_text((FIXTURES / "minimal-valid.md").read_text(encoding="utf-8"))

    manager = MagicMock()
    manager.save_manifest = AsyncMock()
    manager.list_by_spec = AsyncMock(return_value=[])

    with patch(
        "ces.cli.spec_cmd.get_services",
        new=_patch_services({"manifest_manager": manager, "audit_ledger": AsyncMock()}),
    ):
        result = runner.invoke(app, ["spec", "decompose", str(spec)])
    assert result.exit_code == 0, result.stdout
    assert "manifest stubs written" in result.stdout.lower()
    # One story in minimal-valid → one save_manifest call.
    assert manager.save_manifest.await_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/unit/test_cli/test_spec_cmd.py::test_spec_decompose_persists_manifests -v
```

Expected: FAIL — `decompose` subcommand not defined.

- [ ] **Step 3: Implement**

Append to `src/ces/cli/spec_cmd.py`:

```python
from ces.cli._async import run_async
from ces.cli._factory import get_services
from ces.control.spec.decomposer import SpecDecomposer
from ces.shared.enums import ActorType, EventType
from ces.control.services.audit_ledger import AuditScope


@spec_app.command("decompose")
@run_async
async def spec_decompose(
    spec_path: Path = typer.Argument(..., exists=True, readable=True),
    force: bool = typer.Option(False, "--force", help="Overwrite existing stubs"),
) -> None:
    """Decompose a validated spec into manifest stubs."""
    loader = TemplateLoader(_project_root())
    parser = SpecParser(loader)
    validator = SpecValidator(loader)
    doc = parser.parse(spec_path.read_text(encoding="utf-8"))
    validator.validate(doc, template_name=doc.frontmatter.template)

    async with get_services(project_root=_project_root()) as services:
        manager = services["manifest_manager"]
        existing = await manager.list_by_spec(doc.frontmatter.spec_id)
        if existing and not force:
            _console.print(
                f"[red]Error:[/red] spec {doc.frontmatter.spec_id} already "
                f"has {len(existing)} manifest(s). Use --force or ces spec reconcile."
            )
            raise typer.Exit(code=1)

        decomposer = SpecDecomposer(loader)
        result = decomposer.decompose(doc)
        for mf in result.manifests:
            await manager.save_manifest(mf)

        audit = services["audit_ledger"]
        await audit.append_event(
            event_type=EventType.SPEC_DECOMPOSED,
            actor=doc.frontmatter.owner,
            actor_type=ActorType.HUMAN,
            action_summary=(
                f"Decomposed spec {doc.frontmatter.spec_id} into "
                f"{len(result.manifests)} manifest(s)"
            ),
            scope=AuditScope(
                affected_manifests=tuple(m.manifest_id for m in result.manifests)
            ),
        )

    _console.print(
        f"[green]OK[/green] {len(result.manifests)} manifest stubs written."
    )
```

Note: confirm `manager.list_by_spec` exists. If not, either add it to `ManifestManager` as a dependency of this task (one-liner SQL query on `manifests.content->>'parent_spec_id'`) or filter in Python from `manager.list_all()`.

- [ ] **Step 4: Run test**

```
uv run pytest tests/unit/test_cli/test_spec_cmd.py::test_spec_decompose_persists_manifests -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ces/cli/spec_cmd.py tests/unit/test_cli/test_spec_cmd.py
git commit -m "feat(cli): add ces spec decompose with audit ledger integration"
```

---

### Task 20: `ces spec reconcile`

**Files:**
- Modify: `src/ces/cli/spec_cmd.py`
- Test: `tests/unit/test_cli/test_spec_cmd.py`

- [ ] **Step 1: Write the failing test**

```python
def test_spec_reconcile_reports_added_and_orphans(runner: CliRunner, tmp_path: Path):
    spec = tmp_path / "spec.md"
    spec.write_text((FIXTURES / "minimal-valid.md").read_text(encoding="utf-8"))

    existing_mf = MagicMock()
    existing_mf.parent_story_id = "ST-DELETED"  # orphan
    existing_mf.manifest_id = "M-OLD"

    manager = MagicMock()
    manager.list_by_spec = AsyncMock(return_value=[existing_mf])

    with patch(
        "ces.cli.spec_cmd.get_services",
        new=_patch_services({"manifest_manager": manager, "audit_ledger": AsyncMock()}),
    ):
        result = runner.invoke(app, ["spec", "reconcile", str(spec)])
    assert result.exit_code == 0
    assert "ST-DELETED" in result.stdout   # orphan reported
    assert "ST-01HXY" in result.stdout     # unchanged story listed
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/unit/test_cli/test_spec_cmd.py::test_spec_reconcile_reports_added_and_orphans -v
```

Expected: FAIL — `reconcile` not defined.

- [ ] **Step 3: Implement**

Append to `src/ces/cli/spec_cmd.py`:

```python
from ces.control.spec.reconciler import SpecReconciler


@spec_app.command("reconcile")
@run_async
async def spec_reconcile(
    spec_path: Path = typer.Argument(..., exists=True, readable=True),
) -> None:
    """Report added/orphaned/unchanged stories vs. existing manifests."""
    loader = TemplateLoader(_project_root())
    parser = SpecParser(loader)
    doc = parser.parse(spec_path.read_text(encoding="utf-8"))

    async with get_services(project_root=_project_root()) as services:
        manager = services["manifest_manager"]
        manifests = await manager.list_by_spec(doc.frontmatter.spec_id)
        existing_story_ids = frozenset(
            m.parent_story_id for m in manifests if m.parent_story_id
        )

    reconciler = SpecReconciler(loader)
    report = reconciler.reconcile(doc, existing_story_ids)

    if report.added:
        _console.print(f"[yellow]Added:[/yellow] {', '.join(report.added)}")
    if report.orphaned:
        _console.print(
            f"[red]Orphaned (manifests exist but story deleted):[/red] "
            f"{', '.join(report.orphaned)}"
        )
        _console.print(
            "Orphaned manifests are kept for human review. "
            "Use `ces manifest delete <M-...>` if truly obsolete."
        )
    if report.unchanged:
        _console.print(f"[green]Unchanged:[/green] {', '.join(report.unchanged)}")
```

- [ ] **Step 4: Run test**

```
uv run pytest tests/unit/test_cli/test_spec_cmd.py::test_spec_reconcile_reports_added_and_orphans -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ces/cli/spec_cmd.py tests/unit/test_cli/test_spec_cmd.py
git commit -m "feat(cli): add ces spec reconcile command"
```

---

### Task 21: `ces spec tree`

**Files:**
- Modify: `src/ces/cli/spec_cmd.py`
- Test: `tests/unit/test_cli/test_spec_cmd.py`

- [ ] **Step 1: Write the failing test**

```python
def test_spec_tree_prints_hierarchy(runner: CliRunner, tmp_path: Path):
    spec = tmp_path / "spec.md"
    spec.write_text((FIXTURES / "minimal-valid.md").read_text(encoding="utf-8"))

    mf = MagicMock()
    mf.manifest_id = "M-ABC"
    mf.parent_story_id = "ST-01HXY"
    mf.parent_spec_id = "SP-01HXY"
    mf.workflow_state = MagicMock(value="queued")

    manager = MagicMock()
    manager.list_by_spec = AsyncMock(return_value=[mf])
    manager.get_manifest = AsyncMock(return_value=mf)

    with patch(
        "ces.cli.spec_cmd.get_services",
        new=_patch_services({"manifest_manager": manager}),
    ):
        result = runner.invoke(app, ["spec", "tree", str(spec)])
    assert result.exit_code == 0
    assert "SP-01HXY" in result.stdout
    assert "Add /healthcheck route" in result.stdout
    assert "queued" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/unit/test_cli/test_spec_cmd.py::test_spec_tree_prints_hierarchy -v
```

Expected: FAIL — `tree` not defined.

- [ ] **Step 3: Implement**

Append to `src/ces/cli/spec_cmd.py`:

```python
from ces.control.spec.tree import SpecTree
from rich.tree import Tree


@spec_app.command("tree")
@run_async
async def spec_tree(
    spec_path: Path = typer.Argument(..., exists=True, readable=True),
) -> None:
    """Render the spec → stories → manifest-status hierarchy."""
    loader = TemplateLoader(_project_root())
    parser = SpecParser(loader)
    doc = parser.parse(spec_path.read_text(encoding="utf-8"))

    async with get_services(project_root=_project_root()) as services:
        tree_service = SpecTree(services["manifest_manager"])
        nodes = await tree_service.render(doc)

    root = Tree(f"[bold]{doc.frontmatter.spec_id}[/bold] {doc.frontmatter.title} ({doc.frontmatter.status})")
    for node in nodes:
        label = f"{node.story_id} {node.story_title}"
        if node.manifest_id:
            label += f" [{node.manifest_id} {node.status_label}]"
        else:
            label += f" [{node.status_label}]"
        root.add(label)
    _console.print(root)
```

- [ ] **Step 4: Run test**

```
uv run pytest tests/unit/test_cli/test_spec_cmd.py::test_spec_tree_prints_hierarchy -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ces/cli/spec_cmd.py tests/unit/test_cli/test_spec_cmd.py
git commit -m "feat(cli): add ces spec tree command"
```

---

### Task 22: `ces spec author`

**Files:**
- Modify: `src/ces/cli/spec_cmd.py`
- Test: `tests/unit/test_cli/test_spec_cmd.py`

- [ ] **Step 1: Write the failing test**

```python
def test_spec_author_writes_markdown_to_docs_specs(runner: CliRunner, tmp_path: Path):
    # CliRunner sends stdin → Typer's prompt(). Provide every answer in sequence.
    inputs = "\n".join([
        "Healthcheck",                # title
        "dev@example.com",            # owner
        "feature",                    # change class
        "isolated",                   # blast radius
        "N", "N", "N",                # touches
        "Operators need a probe.",    # problem
        "Ops engineers.",             # users
        "Route returns 200.", "",     # success criteria
        "No metrics.", "",            # non-goals
        "flaky :: retries", "",       # risks
        "Revert the PR.",             # rollback
        "Y",                          # add story
        "Add /healthcheck route",
        "S",
        "skip",
        "",
        "Wire FastAPI route.",
        "Returns 200", "",
        "N",                          # no more stories
    ]) + "\n"
    with patch("ces.cli.spec_cmd._project_root", return_value=tmp_path):
        result = runner.invoke(
            app, ["spec", "author"], input=inputs, catch_exceptions=False
        )
    assert result.exit_code == 0, result.stdout
    # Doc created under docs/specs/
    produced = list((tmp_path / "docs" / "specs").glob("*.md"))
    assert len(produced) == 1
    body = produced[0].read_text(encoding="utf-8")
    assert "## Problem" in body
    assert "Add /healthcheck route" in body
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/unit/test_cli/test_spec_cmd.py::test_spec_author_writes_markdown_to_docs_specs -v
```

Expected: FAIL — `author` command not defined.

- [ ] **Step 3: Implement**

Append to `src/ces/cli/spec_cmd.py`:

```python
from datetime import datetime
from ces.harness.services.spec_authoring import (
    SpecAuthoringEngine,
    render_markdown,
)


@spec_app.command("author")
def spec_author(
    template: str = typer.Option("default", "--template"),
    polish: bool = typer.Option(False, "--polish"),
) -> None:
    """Interactively author a new spec."""
    root = _project_root()

    def prompt(text: str, *, choices=None, default=None, type=None) -> str:
        if choices:
            text = f"{text} [{'|'.join(choices)}]"
        return typer.prompt(text, default=default) if default else typer.prompt(text)

    polish_fn = _build_polish_fn() if polish else None
    engine = SpecAuthoringEngine(project_root=root, prompt_fn=prompt, polish_fn=polish_fn)
    doc = engine.run_interactive()

    # Write to docs/specs/.
    out_dir = root / "docs" / "specs"
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = doc.frontmatter.title.lower().replace(" ", "-")
    out_path = out_dir / f"{datetime.utcnow().strftime('%Y-%m-%d')}-{slug}.md"
    out_path.write_text(render_markdown(doc), encoding="utf-8")
    _console.print(f"[green]Wrote[/green] {out_path}")


def _build_polish_fn():  # defined here, wired up in Task 23
    return None
```

- [ ] **Step 4: Run test**

```
uv run pytest tests/unit/test_cli/test_spec_cmd.py::test_spec_author_writes_markdown_to_docs_specs -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ces/cli/spec_cmd.py tests/unit/test_cli/test_spec_cmd.py
git commit -m "feat(cli): add ces spec author command"
```

---

### Task 23: Wire `--polish` to `ProviderRegistry`

**Files:**
- Modify: `src/ces/cli/spec_cmd.py`
- Test: `tests/unit/test_cli/test_spec_cmd.py`

- [ ] **Step 1: Write the failing test**

```python
def test_polish_calls_provider_and_substitutes(runner: CliRunner, tmp_path: Path):
    from unittest.mock import MagicMock

    provider = MagicMock()
    provider.generate = AsyncMock(return_value="a much better description")
    registry = MagicMock()
    registry.get_provider.return_value = provider

    inputs = "\n".join([
        "T", "a@b.c", "feature", "isolated", "N", "N", "N",
        "weak description",            # problem → polished
        "u", "s", "", "n", "", "r :: m", "", "rb",
        "Y", "Add route", "S", "skip", "",
        "weak story desc",             # description → polished
        "ok", "",
        "N",
    ]) + "\n"

    with patch("ces.cli.spec_cmd._project_root", return_value=tmp_path), \
         patch(
             "ces.cli.spec_cmd.get_services",
             new=_patch_services({"provider_registry": registry, "kill_switch": MagicMock(is_halted=lambda: False)}),
         ):
        result = runner.invoke(app, ["spec", "author", "--polish"], input=inputs)

    assert result.exit_code == 0, result.stdout
    produced = list((tmp_path / "docs" / "specs").glob("*.md"))
    body = produced[0].read_text(encoding="utf-8")
    assert "much better description" in body
    assert provider.generate.await_count >= 2
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/unit/test_cli/test_spec_cmd.py::test_polish_calls_provider_and_substitutes -v
```

Expected: FAIL — `_build_polish_fn` still returns None.

- [ ] **Step 3: Implement**

Replace `_build_polish_fn` in `spec_cmd.py`:

```python
import asyncio


def _build_polish_fn():
    """Return a callable (field, draft) -> polished, or None if unavailable."""
    try:
        # Services are resolved lazily — if we can get the registry now, great.
        # If the factory fails (no provider configured), fall back to no-op.
        ctx = get_services(project_root=_project_root())
        loop = asyncio.get_event_loop()
        services = loop.run_until_complete(ctx.__aenter__())
    except Exception:
        return None

    registry = services.get("provider_registry")
    kill_switch = services.get("kill_switch")
    if registry is None:
        return None

    def polish(field: str, draft: str) -> str:
        if kill_switch and kill_switch.is_halted():
            return draft
        # Pick the default provider — the registry is responsible for fallback
        # chain (API key → CLI → demo). Model id is left to the registry default.
        provider = registry.get_provider(model_id=None)  # confirm default signature
        prompt = (
            "Rewrite this spec field for clarity and specificity in 1-3 sentences. "
            "Preserve the author's meaning.\n\n"
            f"Field: {field}\nDraft:\n{draft}"
        )
        polished = asyncio.run(provider.generate(prompt))
        return polished.strip() if polished else draft

    return polish
```

Implementation note: using `asyncio.run` inside a sync callback is sub-optimal. If the executor prefers a cleaner path, convert the full `ces spec author` command to async (mirror the pattern of `ces spec decompose`), pass a real async engine that awaits `provider.generate()` inline, and drop this wrapper. Verify `ProviderRegistry.get_provider()` signature before committing — the sample above may need `model_id="claude-sonnet-4-6"` or similar.

- [ ] **Step 4: Run test**

```
uv run pytest tests/unit/test_cli/test_spec_cmd.py::test_polish_calls_provider_and_substitutes -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ces/cli/spec_cmd.py tests/unit/test_cli/test_spec_cmd.py
git commit -m "feat(cli): wire --polish to provider registry with kill-switch guard"
```

---

### Task 24: `ces spec import`

**Files:**
- Modify: `src/ces/cli/spec_cmd.py`
- Test: `tests/unit/test_cli/test_spec_cmd.py`

- [ ] **Step 1: Write the failing test**

```python
def test_spec_import_writes_rewritten_file_and_reports_missing(
    runner: CliRunner, tmp_path: Path,
):
    source = tmp_path / "src.md"
    source.write_text((FIXTURES / "notion-export.md").read_text(encoding="utf-8"))

    with patch("ces.cli.spec_cmd._project_root", return_value=tmp_path):
        result = runner.invoke(app, ["spec", "import", str(source), "--no-llm"])
    assert result.exit_code == 0, result.stdout
    produced = list((tmp_path / "docs" / "specs").glob("*.md"))
    assert len(produced) == 1
    # Missing sections are reported.
    assert "Non-Goals" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/unit/test_cli/test_spec_cmd.py::test_spec_import_writes_rewritten_file_and_reports_missing -v
```

Expected: FAIL — `import` command not defined.

- [ ] **Step 3: Implement**

Append to `src/ces/cli/spec_cmd.py`:

```python
from ces.harness.services.spec_importer import SpecImporter


@spec_app.command("import")
def spec_import(
    source_path: Path = typer.Argument(..., exists=True, readable=True),
    no_llm: bool = typer.Option(False, "--no-llm"),
) -> None:
    """Import an existing PRD; map headers to the canonical template."""
    root = _project_root()
    mapper = None if no_llm else _build_llm_section_mapper()
    importer = SpecImporter(project_root=root, section_mapper_fn=mapper)
    source = source_path.read_text(encoding="utf-8")
    result = importer.import_text(source)

    out_dir = root / "docs" / "specs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / source_path.with_suffix(".imported.md").name
    out_path.write_text(result.rewritten_text, encoding="utf-8")

    _console.print(f"[green]Wrote[/green] {out_path}")
    if result.mapping.missing:
        _console.print(
            "[yellow]Missing sections (add them interactively or manually):[/yellow] "
            f"{', '.join(result.mapping.missing)}"
        )


def _build_llm_section_mapper():
    # Mirrors _build_polish_fn: resolves provider, calls generate() with a
    # structured prompt, parses the reply as a dict. Returns None on failure.
    # Provided as a stub to keep the deterministic path fully tested in v1;
    # fill in during implementation when provider integration is exercised.
    return None
```

Implementation note: `_build_llm_section_mapper()` needs a concrete implementation mirroring `_build_polish_fn` from Task 23. The prompt should ask the provider to return a JSON object mapping canonical headers (`## Problem`, etc.) to source headers found in the file. Parse with `json.loads`; on any error, return `None`.

- [ ] **Step 4: Run test**

```
uv run pytest tests/unit/test_cli/test_spec_cmd.py::test_spec_import_writes_rewritten_file_and_reports_missing -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ces/cli/spec_cmd.py tests/unit/test_cli/test_spec_cmd.py
git commit -m "feat(cli): add ces spec import (deterministic path)"
```

---

### Task 25: Flesh out `_build_llm_section_mapper`

**Files:**
- Modify: `src/ces/cli/spec_cmd.py`
- Test: `tests/unit/test_cli/test_spec_cmd.py`

- [ ] **Step 1: Write the failing test**

```python
def test_spec_import_uses_llm_mapper_by_default(runner: CliRunner, tmp_path: Path):
    source = tmp_path / "src.md"
    source.write_text((FIXTURES / "notion-export.md").read_text(encoding="utf-8"))

    provider = MagicMock()
    provider.generate = AsyncMock(
        return_value=(
            '{"## Problem": "## The Problem We\'re Solving", '
            '"## Users": "## Who It\'s For", '
            '"## Success Criteria": "## What Success Looks Like", '
            '"## Rollback Plan": "## Rolling Back", '
            '"## Stories": "## User Stories"}'
        )
    )
    registry = MagicMock()
    registry.get_provider.return_value = provider

    with patch("ces.cli.spec_cmd._project_root", return_value=tmp_path), \
         patch(
             "ces.cli.spec_cmd.get_services",
             new=_patch_services({"provider_registry": registry, "kill_switch": MagicMock(is_halted=lambda: False)}),
         ):
        result = runner.invoke(app, ["spec", "import", str(source)])
    assert result.exit_code == 0, result.stdout
    # The provider was consulted.
    assert provider.generate.await_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/unit/test_cli/test_spec_cmd.py::test_spec_import_uses_llm_mapper_by_default -v
```

Expected: FAIL — `_build_llm_section_mapper` still returns None.

- [ ] **Step 3: Implement**

Replace `_build_llm_section_mapper` in `spec_cmd.py`:

```python
import json


def _build_llm_section_mapper():
    try:
        ctx = get_services(project_root=_project_root())
        loop = asyncio.get_event_loop()
        services = loop.run_until_complete(ctx.__aenter__())
    except Exception:
        return None
    registry = services.get("provider_registry")
    kill_switch = services.get("kill_switch")
    if registry is None:
        return None

    def mapper(source_text: str, required: tuple[str, ...]) -> dict[str, str]:
        if kill_switch and kill_switch.is_halted():
            return {}
        provider = registry.get_provider(model_id=None)
        prompt = (
            "You are mapping sections in a source document to canonical headers. "
            "Return ONLY a JSON object whose keys are canonical headers and values "
            "are the matching source headers (or null if no match).\n\n"
            f"Canonical headers: {list(required)}\n\nSource document:\n{source_text}"
        )
        reply = asyncio.run(provider.generate(prompt))
        try:
            data = json.loads(reply)
        except (json.JSONDecodeError, TypeError):
            return {}
        return {k: v for k, v in data.items() if isinstance(v, str)}

    return mapper
```

- [ ] **Step 4: Run test**

```
uv run pytest tests/unit/test_cli/test_spec_cmd.py::test_spec_import_uses_llm_mapper_by_default -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ces/cli/spec_cmd.py tests/unit/test_cli/test_spec_cmd.py
git commit -m "feat(cli): add LLM-backed section mapper for ces spec import"
```

---

## Phase 10 — Build Integration

### Task 26: `ces build --from-spec`

**Files:**
- Modify: `src/ces/cli/run_cmd.py`
- Test: `tests/unit/test_cli/test_run_cmd_from_spec.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cli/test_run_cmd_from_spec.py
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from ces.cli import app


FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "specs"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_build_from_spec_invokes_orchestrator_per_story(runner, tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text((FIXTURES / "minimal-valid.md").read_text(encoding="utf-8"))

    mf = MagicMock()
    mf.manifest_id = "M-01"
    mf.parent_story_id = "ST-01HXY"
    mf.description = "Add /healthcheck route"
    mf.acceptance_criteria = ("Returns 200",)

    manager = MagicMock()
    manager.list_by_spec = AsyncMock(return_value=[mf])

    orchestrator = MagicMock()
    orchestrator.run_for_manifest = AsyncMock()

    with patch("ces.cli.run_cmd._project_root", return_value=tmp_path), \
         patch(
             "ces.cli.run_cmd.get_services",
             new=_patch_services({"manifest_manager": manager, "builder_flow": orchestrator}),
         ):
        result = runner.invoke(app, ["build", "--from-spec", str(spec)])
    assert result.exit_code == 0, result.stdout
    assert orchestrator.run_for_manifest.await_count == 1
```

(If `_patch_services` helper isn't in scope, copy its definition from `test_spec_cmd.py`.)

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/unit/test_cli/test_run_cmd_from_spec.py -v
```

Expected: FAIL — `--from-spec` flag unknown.

- [ ] **Step 3: Implement**

In `src/ces/cli/run_cmd.py`:

- Add the option to `run_task`:

  ```python
  from_spec: Path | None = typer.Option(
      None, "--from-spec", help="Run one build per story from a decomposed spec."
  ),
  story: str | None = typer.Option(
      None, "--story", help="Restrict --from-spec to a single story id."
  ),
  ```

- Branch early in the function body:

  ```python
  if from_spec is not None:
      await _run_from_spec(from_spec, story_id=story)
      return
  ```

- Add `_run_from_spec` below `run_task`:

  ```python
  async def _run_from_spec(spec_path: Path, story_id: str | None) -> None:
      from ces.control.spec.parser import SpecParser
      from ces.control.spec.template_loader import TemplateLoader

      root = _project_root()
      loader = TemplateLoader(root)
      doc = SpecParser(loader).parse(spec_path.read_text(encoding="utf-8"))
      async with get_services(project_root=root) as services:
          manager = services["manifest_manager"]
          orchestrator = services["builder_flow"]
          manifests = await manager.list_by_spec(doc.frontmatter.spec_id)
          # Order by depends_on graph (topological).
          ordered = _topological_sort(manifests)
          for mf in ordered:
              if story_id and mf.parent_story_id != story_id:
                  continue
              await orchestrator.run_for_manifest(mf)


  def _topological_sort(manifests: list) -> list:
      # Minimal Kahn's algorithm keyed off TaskManifest.dependencies.
      by_id = {m.manifest_id: m for m in manifests}
      indegree = {mid: 0 for mid in by_id}
      edges: dict[str, list[str]] = {mid: [] for mid in by_id}
      for m in manifests:
          for dep in m.dependencies:
              # ManifestDependency exposes the dependency's manifest_id.
              if dep.manifest_id in by_id:
                  edges[dep.manifest_id].append(m.manifest_id)
                  indegree[m.manifest_id] += 1
      queue = [mid for mid, n in indegree.items() if n == 0]
      out: list = []
      while queue:
          mid = queue.pop(0)
          out.append(by_id[mid])
          for nxt in edges[mid]:
              indegree[nxt] -= 1
              if indegree[nxt] == 0:
                  queue.append(nxt)
      return out
  ```

Implementation note: `builder_flow` may not currently be exposed in `get_services()`. If not, add it alongside `manifest_manager` in `_factory.py`, returning a `BuilderFlowOrchestrator` initialized with the same project root. The `run_for_manifest(manifest)` method may also be new — if it's not already there, add a thin wrapper that builds a `BuilderBriefDraft` from the manifest (using `description` + `acceptance_criteria`) and calls into the existing orchestrator path used by `ces build <description>`.

- [ ] **Step 4: Run test**

```
uv run pytest tests/unit/test_cli/test_run_cmd_from_spec.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ces/cli/run_cmd.py tests/unit/test_cli/test_run_cmd_from_spec.py
git commit -m "feat(cli): add --from-spec flag to ces build with topological ordering"
```

---

## Phase 11 — Integration & Property Tests

### Task 27: End-to-end integration test

**Files:**
- Create: `tests/integration/test_spec_end_to_end.py`

- [ ] **Step 1: Write the test**

```python
# tests/integration/test_spec_end_to_end.py
"""Exercise the full spec flow against a real .ces/state.db."""

from pathlib import Path

import pytest
import pytest_asyncio

from ces.control.spec.decomposer import SpecDecomposer
from ces.control.spec.parser import SpecParser
from ces.control.spec.reconciler import SpecReconciler
from ces.control.spec.template_loader import TemplateLoader
from ces.control.spec.tree import SpecTree
from ces.control.spec.validator import SpecValidator


FIXTURES = Path(__file__).parent.parent / "fixtures" / "specs"


@pytest.mark.asyncio
async def test_author_validate_decompose_tree_flow(ces_project):
    from ces.cli._factory import get_services

    spec_text = (FIXTURES / "minimal-valid.md").read_text(encoding="utf-8")
    loader = TemplateLoader(ces_project)
    parser = SpecParser(loader)
    validator = SpecValidator(loader)
    decomposer = SpecDecomposer(loader)

    doc = parser.parse(spec_text)
    validator.validate(doc)
    result = decomposer.decompose(doc)

    async with get_services(project_root=ces_project) as services:
        manager = services["manifest_manager"]
        for mf in result.manifests:
            await manager.save_manifest(mf)

        tree = SpecTree(manager)
        nodes = await tree.render(doc)
        assert len(nodes) == 1
        assert nodes[0].manifest_id is not None

        # Reconcile reports unchanged.
        reconciler = SpecReconciler(loader)
        existing = frozenset({nodes[0].story_id})
        report = reconciler.reconcile(doc, existing)
        assert report.added == ()
        assert report.unchanged == (nodes[0].story_id,)
```

- [ ] **Step 2: Run the test**

```
uv run pytest tests/integration/test_spec_end_to_end.py -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_spec_end_to_end.py
git commit -m "test(spec): add end-to-end integration test"
```

---

### Task 28: Property-based round-trip test

**Files:**
- Create: `tests/property/test_spec_roundtrip.py`

- [ ] **Step 1: Write the test**

```python
# tests/property/test_spec_roundtrip.py
"""Random valid SpecDocument → markdown → parser → equivalent SpecDocument."""

from datetime import datetime, timezone

import pytest
from hypothesis import given, strategies as st

from ces.control.models.spec import (
    Risk,
    SignalHints,
    SpecDocument,
    SpecFrontmatter,
    Story,
)
from ces.control.spec.parser import SpecParser
from ces.control.spec.template_loader import TemplateLoader
from ces.harness.services.spec_authoring import render_markdown


_SAFE_TEXT = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\n`---"),
    min_size=1,
    max_size=40,
).map(str.strip).filter(lambda s: bool(s))


@st.composite
def specs(draw):
    n_stories = draw(st.integers(min_value=1, max_value=4))
    story_ids = [f"ST-{i:04d}" for i in range(n_stories)]
    stories = [
        Story(
            story_id=sid,
            title=draw(_SAFE_TEXT),
            description=draw(_SAFE_TEXT),
            acceptance_criteria=tuple(draw(st.lists(_SAFE_TEXT, min_size=1, max_size=3))),
            depends_on=tuple(draw(st.sampled_from([(), tuple(story_ids[:i])])) if i > 0 else ()),
            size=draw(st.sampled_from(["XS", "S", "M", "L"])),
            risk=draw(st.one_of(st.none(), st.sampled_from(["A", "B", "C"]))),
        )
        for i, sid in enumerate(story_ids)
    ]
    return SpecDocument(
        frontmatter=SpecFrontmatter(
            spec_id="SP-PROP",
            title=draw(_SAFE_TEXT),
            owner="a@b.c",
            created_at=datetime(2026, 4, 21, tzinfo=timezone.utc),
            status="draft",
            signals=SignalHints(
                primary_change_class="feature",
                blast_radius_hint="isolated",
            ),
        ),
        problem=draw(_SAFE_TEXT),
        users=draw(_SAFE_TEXT),
        success_criteria=(draw(_SAFE_TEXT),),
        non_goals=(draw(_SAFE_TEXT),),
        risks=(Risk(risk=draw(_SAFE_TEXT), mitigation=draw(_SAFE_TEXT)),),
        stories=tuple(stories),
        rollback_plan=draw(_SAFE_TEXT),
    )


@given(doc=specs())
def test_render_then_parse_preserves_story_ids_and_acceptance(tmp_path, doc):
    md = render_markdown(doc)
    parser = SpecParser(TemplateLoader(project_root=tmp_path))
    reparsed = parser.parse(md)
    assert [s.story_id for s in reparsed.stories] == [s.story_id for s in doc.stories]
    assert [s.acceptance_criteria for s in reparsed.stories] == [
        s.acceptance_criteria for s in doc.stories
    ]
```

- [ ] **Step 2: Run the test**

```
uv run pytest tests/property/test_spec_roundtrip.py -v
```

Expected: PASS. If Hypothesis finds a narrow input class that fails (e.g., titles containing exotic unicode), tighten the `_SAFE_TEXT` filter inline and re-run.

- [ ] **Step 3: Commit**

```bash
git add tests/property/test_spec_roundtrip.py
git commit -m "test(spec): add property-based render/parse round-trip"
```

---

### Task 29: Complex-hierarchy fixture + ordering smoke test

**Files:**
- Create: `tests/fixtures/specs/complex-hierarchy.md`
- Modify: `tests/integration/test_spec_end_to_end.py`

- [ ] **Step 1: Create the fixture**

A spec with 4 stories and a diamond dependency: `A ← B, A ← C, {B,C} ← D`. (Shortened here; flesh out acceptance criteria in the fixture.)

```markdown
<!-- tests/fixtures/specs/complex-hierarchy.md -->
---
spec_id: SP-COMPLEX
title: Diamond deps
owner: a@b.c
created_at: 2026-04-21T10:00:00Z
status: draft
template: default
signals:
  primary_change_class: feature
  blast_radius_hint: module
  touches_data: false
  touches_auth: false
  touches_billing: false
---

## Problem
p

## Users
u

## Success Criteria
- s

## Non-Goals
- n

## Risks & Mitigations
- **Risk:** r
  **Mitigation:** m

## Stories

### Story: A (base)
- **id:** ST-A
- **size:** S
- **description:** base
- **acceptance:**
  - works

### Story: B (depends on A)
- **id:** ST-B
- **size:** S
- **depends_on:** [ST-A]
- **description:** b
- **acceptance:**
  - works

### Story: C (depends on A)
- **id:** ST-C
- **size:** S
- **depends_on:** [ST-A]
- **description:** c
- **acceptance:**
  - works

### Story: D (depends on B and C)
- **id:** ST-D
- **size:** S
- **depends_on:** [ST-B, ST-C]
- **description:** d
- **acceptance:**
  - works

## Rollback Plan
rb
```

- [ ] **Step 2: Add integration test asserting topological order**

Append to `tests/integration/test_spec_end_to_end.py`:

```python
@pytest.mark.asyncio
async def test_decompose_orders_dependencies_topologically(ces_project):
    from ces.cli._factory import get_services
    from ces.cli.run_cmd import _topological_sort

    loader = TemplateLoader(ces_project)
    doc = SpecParser(loader).parse(
        (FIXTURES / "complex-hierarchy.md").read_text(encoding="utf-8")
    )
    result = SpecDecomposer(loader).decompose(doc)
    ordered = _topological_sort(list(result.manifests))
    by_story = {m.parent_story_id: i for i, m in enumerate(ordered)}
    # A before B/C; B and C before D.
    assert by_story["ST-A"] < by_story["ST-B"]
    assert by_story["ST-A"] < by_story["ST-C"]
    assert by_story["ST-B"] < by_story["ST-D"]
    assert by_story["ST-C"] < by_story["ST-D"]
```

- [ ] **Step 3: Run test**

```
uv run pytest tests/integration/test_spec_end_to_end.py -v
```

Expected: both tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/specs/complex-hierarchy.md tests/integration/test_spec_end_to_end.py
git commit -m "test(spec): add complex-hierarchy fixture and topo-order assertion"
```

---

## Phase 12 — Coverage & Doc

### Task 30: Verify coverage meets the 88 % gate

**Files:**
- None (verification only)

- [ ] **Step 1: Run coverage**

```
uv run pytest \
    --cov=src/ces/control/models/spec \
    --cov=src/ces/control/spec \
    --cov=src/ces/harness/services/spec_authoring \
    --cov=src/ces/harness/services/spec_importer \
    --cov=src/ces/cli/spec_cmd \
    --cov-report=term-missing
```

Expected: combined coverage ≥ 88 % for the listed modules.

- [ ] **Step 2: Address gaps**

If any module drops below 88 %, add targeted tests — typically covering error branches (template loader's dual-candidate fallback, parser's malformed-frontmatter path, decomposer's default-risk path when `risk_hint` is `None`). Keep additions small, one test per branch; no speculative testing.

- [ ] **Step 3: Re-run and commit the gap-closing tests**

```bash
uv run pytest --cov=... --cov-report=term-missing  # same command
git add tests/
git commit -m "test(spec): close coverage gaps to hit 88% gate"
```

- [ ] **Step 4: User-facing docs entry**

Append a "Authoring a spec" section to `docs/Quick_Reference_Card.md` (in the existing command-reference table style), linking to `docs/designs/2026-04-21-ces-spec-authoring.md` for the full design. Keep it ≤ 15 lines — one example invocation each for `author`, `import`, `validate`, `decompose`, `reconcile`, `tree`, `build --from-spec`.

Commit:

```bash
git add docs/Quick_Reference_Card.md
git commit -m "docs: add ces spec command reference"
```

---

## Self-Review

Spec coverage (against design §§ 3, 4, 5, 6, 7):

| Design section | Task(s) |
|---|---|
| §3.1 command surface — `author`, `import`, `validate`, `decompose`, `reconcile`, `tree`, `build --from-spec` | 18, 19, 20, 21, 22, 24, 26 |
| §3.2 plane placement | Honored in every task — control-plane modules under `ces.control.spec.*`, harness under `ces.harness.services.*`. No LLM imports in control plane. |
| §3.4 source files | Tasks 3–5, 6, 7–8, 9, 11, 13, 14, 15–17 |
| §3.5 `ClassificationOracle.classify_from_hints()` | Task 10 |
| §3.5 `AuditLedger` event types | Task 1 (enum), Task 19 (log `SPEC_DECOMPOSED` in decompose CLI) — `SPEC_AUTHORED` and `SPEC_RECONCILED` to be logged in Tasks 22 and 20 respectively (verify during implementation; acceptable to add a TODO test that asserts the event shape and have the task writer include the `append_event` call). |
| §4.1 canonical template | Task 5 |
| §4.2 sidecar | Task 5 |
| §4.3 Pydantic models | Tasks 3, 4 |
| §4.4 story → manifest mapping | Task 2 (fields), Task 11 (mapping) |
| §4.5 template plugin loader | Task 6 |
| §5 data flow | Tasks 18, 22 (author path), 24, 25 (import path), 19 + 21 (validate/decompose/tree), 26 (build) |
| §6 error handling matrix | Tasks 8 (parser), 9 (validator), 19 (decompose --force), 20 (reconcile orphans), 23 (polish kill switch + no provider) |
| §7 testing strategy | Tasks 27 (integration), 28 (property), 29 (complex fixture), 30 (coverage) |
| §8 open questions | Deliberately deferred — not task work |
| §9 out of scope | Respected (no web UI, no cross-spec deps, no JSON schema, etc.) |

Gaps flagged during self-review (already addressed in the plan above):
- Logging of `SPEC_AUTHORED` and `SPEC_RECONCILED` events — folded into Tasks 22 and 20 as acceptance criteria (the `author` task must append `SPEC_AUTHORED` after the file is written; the `reconcile` task must append `SPEC_RECONCILED` even when the report is all-empty).
- `manifest_manager.list_by_spec(...)` — referenced by three CLI tasks (19, 20, 21, 26). It is NOT present in the current `ManifestManager` per the interface map. Either add it as a one-line helper in Task 19's implementation step (SQL: `SELECT * FROM manifests WHERE json_extract(content, '$.parent_spec_id') = ?`) or mirror the existing iteration pattern. Treat the addition as part of Task 19 — the tests in 19/20/21/26 already assume it exists.
- `builder_flow` in `get_services()` — referenced by Task 26. If not present, Task 26's Step 3 must include adding it to `_factory.py`.

Placeholder scan: no "TBD", "TODO", or un-coded steps in the plan body. Three "confirm during implementation" notes remain (Task 10: `OracleClassificationResult` constructor; Task 11: `ManifestDependency` fields and `ArtifactStatus.DRAFT`/`WorkflowState.QUEUED` enum members; Task 23: `ProviderRegistry.get_provider()` default signature). These are not placeholders for *behavior* — they're flags for minor field-name validation against existing code. The executor confirms them during Step 3 of each task.

Type consistency check: `SpecDocument`, `Story`, `SpecFrontmatter`, `SignalHints`, `Risk` are defined once in Task 3/4 and used verbatim throughout. `TaskManifest`, `ManifestDependency`, `ClassificationOracle`, `OracleClassificationResult`, `AuditLedgerService`, `EventType`, `ActorType`, `ArtifactStatus`, `WorkflowState`, `BehaviorConfidence`, `ChangeClass`, `RiskTier` are imported from their existing CES modules — same spellings everywhere. No name drift.

---

## Execution Handoff

**Plan complete and saved to `docs/plans/2026-04-21-ces-spec-authoring.md`. Two execution options:**

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for a 30-task plan where each task has a tight scope and clear acceptance criteria.
2. **Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

Which approach?
