# Design — `ces spec` Planning-Authoring Layer

> Historical design record. CES is currently shipped as a local builder-first CLI. Any references below to server surfaces or older control-plane wording should be read as design-time context rather than the active implementation contract.

**Date:** 2026-04-21
**Status:** Design approved, pending implementation planning
**Author:** Chris Duvillard (brainstorming session with Claude via `superpowers:brainstorming`)
**Scope target:** v0.2.x minor release
**Implementation planning:** To be produced by `superpowers:writing-plans` after this design is approved.

---

## 1. Context

CES today has a **governance on-ramp** (`ces build` asks 3–4 questions, produces a manifest) but no **planning on-ramp** — nothing that helps a user produce a PRD, epic, or story document that CES can then govern. Teams arriving at CES typically already have planning artifacts (Notion doc, Jira epic, handwritten PRD, Slack-thread-summary) and need a bridge from those artifacts into the CES manifest workflow. Teams starting greenfield need a guided path to produce such an artifact without leaving the tool.

This design adds a new `ces spec` command group that:

1. Produces a canonical planning document (authored from scratch OR imported from an existing doc).
2. Decomposes it deterministically into per-story manifest stubs.
3. Feeds those stubs into the existing `ces build` / `ces classify` workflow without bypassing any existing governance step.

**Success criterion:** a user who arrives with a 500-word PRD in Notion can, in under 5 minutes, produce a CES-governed manifest stub per story in that PRD, without running any LLM during the CES control-plane parsing step.

## 2. Decisions locked during brainstorming

| Axis | Choice | Rationale |
|---|---|---|
| Position in pipeline | **(A) Standalone `ces spec` command in front of `ces build`** | Users often already have a PRD; a pre-CES authoring layer composes cleanly and doesn't force an interview when a doc exists. |
| Work-unit granularity | **(B) 1:many — spec → multiple stories → multiple manifests** | Matches how engineering teams actually work (one PRD, many PRs). Keeps CES's manifest model flat. |
| Methodology | **(C) Opinionated default template + pluggable template loader** | Sharp out-of-box UX via one well-designed PRD template; teams can drop custom templates into `.ces/templates/spec/`. |
| LLM role | **(C+D) Deterministic spine + optional LLM polish during *authoring*; LLM-assisted section mapping during *import*; fully deterministic during *consumption* by CES** | Honors CLAUDE.md's LLM-05 rule (no LLM in control plane). Works offline / without API keys. |
| Scope for v1 | **Approach 3 — full first-class feature** | Ship the complete mental model (author / import / validate / decompose / tree / build --from-spec) in one release. |

## 3. Architecture & Command Surface

### 3.1 Commands

One top-level Typer subcommand group (`ces spec`) plus one enhancement to the existing `ces build`:

```
ces spec author [--template <name>] [--polish]      # interactive interview → spec.md
ces spec import <path> [--no-llm]                   # existing doc → spec.md
ces spec validate <spec>                             # deterministic completeness check
ces spec decompose <spec> [--force]                  # spec.md → N manifest stubs
ces spec reconcile <spec>                            # after post-decompose edits
ces spec tree [<spec>]                               # hierarchy + roll-up status
ces build --from-spec <spec> [--story <id>]          # batched build from decomposed spec
```

### 3.2 Three-plane placement

Respects the LLM-05 rule in `CLAUDE.md` ("All control plane operations must be deterministic — no LLM calls in the control plane"):

| Command | Plane | LLM? | Why |
|---|---|---|---|
| `spec author` | Harness | Optional (`--polish`) | Authoring is QA/UX, not governance |
| `spec import` | Harness | Optional (default on, `--no-llm` to disable) | Fuzzy parsing of messy docs lives here |
| `spec validate` | **Control** | Never | Deterministic gate — signals must parse cleanly |
| `spec decompose` | **Control** | Never | Emits manifest stubs that enter the ledger |
| `spec reconcile` | **Control** | Never | Deterministic diff of spec vs. existing manifests |
| `spec tree` | **Control** | Never | Reads state.db + specs, pure view |
| `build --from-spec` | Existing | Unchanged | Adds a batch loop on top of current build |

### 3.3 File layout in the user's repo

```
<user repo>/
├── docs/specs/                        # rendered spec docs (committed to VCS)
│   └── 2026-04-21-healthcheck.md
├── .ces/
│   ├── templates/spec/<name>.md        # optional user-provided template overrides
│   ├── templates/spec/<name>.yaml      # sidecar declaring required sections
│   ├── manifests/M-<ulid>.yaml         # existing path; now with spec linkage fields
│   └── state.db                        # existing SQLite; tracks spec ↔ manifest links
```

And in the CES distribution itself:

```
src/ces/templates/spec/default.md       # bundled canonical PRD template
src/ces/templates/spec/default.yaml     # bundled section-manifest declaration
```

### 3.4 New source files in CES

- `src/ces/cli/spec_cmd.py` — Typer subcommand group
- `src/ces/harness/services/spec_authoring.py` — interview engine + optional LLM polish
- `src/ces/harness/services/spec_importer.py` — import + LLM-assisted section identification
- `src/ces/control/spec/validator.py` — deterministic schema validation
- `src/ces/control/spec/decomposer.py` — deterministic story → manifest stub
- `src/ces/control/spec/reconciler.py` — deterministic diff + orphan detection
- `src/ces/control/spec/template_loader.py` — pluggable template lookup
- `src/ces/control/spec/tree.py` — hierarchy reader
- `src/ces/models/spec.py` — Pydantic models inheriting `CESBaseModel`
- `src/ces/templates/spec/default.md` + `src/ces/templates/spec/default.yaml` — bundled PRD template

### 3.5 Integration with existing modules

- **`ClassificationOracle`** (harness) is called during `decompose` via a new `classify_from_hints()` method to produce a *suggested* `RiskTier` / `BC` / `ChangeClass` for each manifest stub. The user can override via `ces classify M-<id>`. Classification remains authoritative on the manifest side.
- **`AuditLedger`** records three new event types: `SPEC_AUTHORED`, `SPEC_DECOMPOSED`, `SPEC_RECONCILED`. Content diffs of the spec file are tracked by git, not the audit ledger.
- **`ProviderRegistry`** handles LLM fallback for `author --polish` and `import`. No new provider logic required; if no provider resolves, the degraded deterministic paths take over.
- **`KillSwitch`** is checked before any LLM call during `author --polish` and `import`. If halted, the polish call is declined silently and the interview continues without enrichment.

## 4. Template & Schema

### 4.1 Canonical PRD template

The bundled template (`src/ces/templates/spec/default.md`) is markdown with **required section headers** and **YAML frontmatter**. The required section headers are what make deterministic parsing possible.

```markdown
---
spec_id: SP-01HXY...                      # auto-assigned ULID
title: Healthcheck endpoint
owner: duvillard.c@gmail.com
created_at: 2026-04-21T10:00:00Z
status: draft                             # draft | decomposed | complete
template: default
signals:
  primary_change_class: feature           # feature|bug|refactor|infra|doc
  blast_radius_hint: isolated             # isolated|module|system|cross-cutting
  touches_data: false
  touches_auth: false
  touches_billing: false
---

## Problem
<one-paragraph problem statement>

## Users
<who benefits, in what context>

## Success Criteria
- <measurable outcome 1>
- <measurable outcome 2>

## Non-Goals
- <explicitly out of scope>

## Risks & Mitigations
- **Risk:** <what could go wrong>
  **Mitigation:** <how we handle it>

## Stories

### Story: Add /healthcheck route
- **id:** ST-01HXY...                     # auto-assigned
- **size:** S                             # XS|S|M|L
- **risk:** C                             # A|B|C (hint, not binding)
- **depends_on:** []
- **description:** Wire FastAPI route returning 200/JSON.
- **acceptance:**
  - GET /healthcheck returns 200 with `{"status": "ok"}`
  - Response time <50ms p95

### Story: Add probe to docker-compose
- **id:** ST-01HXZ...
- **size:** XS
- **depends_on:** [ST-01HXY...]           # build ordering
- **description:** …
- **acceptance:** …

## Rollback Plan
<how to back out if this ships and breaks something>
```

### 4.2 Template sidecar (`default.yaml`)

A machine-readable declaration of what makes a template valid. `ces spec validate` reads this and confirms the rendered spec complies:

```yaml
# src/ces/templates/spec/default.yaml
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

### 4.3 Pydantic models (`src/ces/models/spec.py`)

All inherit `CESBaseModel` (frozen, strict; tuples not lists — per CES conventions in `CLAUDE.md`):

```python
class SignalHints(CESBaseModel):
    primary_change_class: Literal["feature", "bug", "refactor", "infra", "doc"]
    blast_radius_hint: Literal["isolated", "module", "system", "cross-cutting"]
    touches_data: bool = False
    touches_auth: bool = False
    touches_billing: bool = False

class SpecFrontmatter(CESBaseModel):
    spec_id: str                           # SP-<ulid>
    title: str
    owner: str
    created_at: datetime
    status: Literal["draft", "decomposed", "complete"]
    template: str = "default"
    signals: SignalHints

class Story(CESBaseModel):
    story_id: str                          # ST-<ulid>
    title: str
    description: str
    acceptance_criteria: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    size: Literal["XS", "S", "M", "L"]
    risk: Literal["A", "B", "C"] | None = None

class Risk(CESBaseModel):
    risk: str
    mitigation: str

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

### 4.4 Story → manifest stub mapping

`ces spec decompose <spec>` walks `SpecDocument.stories` and emits one manifest stub per story, written to `.ces/manifests/M-<ulid>-<slug>.yaml`.

| Story field | Manifest stub field |
|---|---|
| `story_id` | `parent_story_id` (new manifest field) |
| Spec `spec_id` | `parent_spec_id` (new manifest field) |
| `title` + `description` | `description` on manifest (joined: `"<title>\n\n<description>"`) |
| `acceptance_criteria` | `acceptance_criteria` (tuple preserved) |
| `risk` | `proposed_tier` (non-binding; `ces classify` still authoritative) |
| Spec-level `signals.*` | seeded into manifest's classification context (consumed by `ClassificationOracle.classify_from_hints()`) |
| `depends_on` (story IDs) | `depends_on_manifests` (resolved during decompose by looking up peer stories' generated manifest IDs) |

Each stub enters the manifest workflow at the **`draft`** state. The user still runs `ces classify` and `ces build`; signals and risk hints are a *prior*, not a governance bypass.

> **Implementation note for writing-plans:** the exact manifest field names above (`description`, `proposed_tier`, `acceptance_criteria`, and the three new `parent_*` fields) need to be confirmed against the current `Manifest` Pydantic model in `src/ces/models/`. The mapping intent is what's load-bearing here; the field names are best-effort based on the conventions in `CLAUDE.md` and may shift by a word during implementation.

### 4.5 Template plugin loader

Lookup order — fail-loud if missing, never silently fall back:

1. `<repo>/.ces/templates/spec/<name>.md` + `.ces/templates/spec/<name>.yaml` (user override)
2. `src/ces/templates/spec/<name>.md` + `src/ces/templates/spec/<name>.yaml` (bundled)

Only `default` ships in v1. Custom templates require both the `.md` and a `.yaml` sidecar — users can copy the bundled pair as a starting point.

## 5. Data flow (two end-to-end walkthroughs)

### 5.1 Path 1: Author from scratch

```
$ ces spec author --template default --polish
> Title: Healthcheck endpoint
> Owner: [duvillard.c@gmail.com] (Enter)
> Primary change class: [feature|bug|refactor|infra|doc] feature
> Blast radius hint: [isolated|module|system|cross-cutting] isolated
> Touches data? [y/N] N
> Problem statement: (? for polish)
>   > we want a healthcheck
>   ? expanding...
>   > Operators need a programmatic probe to confirm the API service is running and
>   >  responsive. Without one, container orchestrators can't distinguish healthy
>   >  from hung pods, causing slow failover during incidents.
>   Accept polished version? [Y/n] Y
> Users: …
> Success criteria (one per line, blank to finish): …
> Stories: Add [y/N] y
>   Story title: Add /healthcheck route
>   Size: [XS|S|M|L] S
>   Description: …
>   Acceptance criteria: …
>   Depends on (story IDs, comma-sep): <blank>
> Add another story? [y/N] y
> …
✓ Wrote docs/specs/2026-04-21-healthcheck.md
✓ Spec SP-01HXY... created, 3 stories, status=draft
Next: ces spec validate docs/specs/2026-04-21-healthcheck.md
```

### 5.2 Path 2: Import existing doc

```
$ ces spec import ~/Downloads/healthcheck-prd.md
✓ Provider available: claude (CLI)
✓ LLM section mapping:
   - "## The Problem We're Solving"  →  ## Problem        [confident]
   - "## Who It's For"                →  ## Users          [confident]
   - "## What Success Looks Like"     →  ## Success Criteria [confident]
   - <no match>                       →  ## Non-Goals      [missing]
   - "## User Stories"                →  ## Stories        [confident]
   - "## Rolling Back"                →  ## Rollback Plan  [confident]
! Missing required section: Non-Goals
? Add Non-Goals now (interactive) or skip for manual edit? [interactive/skip] interactive
  > Non-goals: …
✓ Wrote docs/specs/2026-04-21-healthcheck.md
✓ Spec SP-01HXY... created, 3 stories, status=draft
```

### 5.3 Common tail (validate → decompose → tree → build)

```
$ ces spec validate docs/specs/2026-04-21-healthcheck.md
✓ Frontmatter complete
✓ All 5 required sections present
✓ 3 stories, all with required fields
✓ depends_on graph is acyclic
✓ Ready for decompose

$ ces spec decompose docs/specs/2026-04-21-healthcheck.md
✓ 3 manifest stubs written to .ces/manifests/
  M-01... (ST-01...) proposed_tier=C
  M-02... (ST-02...) proposed_tier=C
  M-03... (ST-03...) proposed_tier=C  depends_on_manifests=[M-02]
✓ Spec status: draft → decomposed

$ ces spec tree
SP-01HXY... Healthcheck endpoint (decomposed)
├── ST-01 Add /healthcheck route     [M-01 classified A]  ✓ approved
├── ST-02 Add probe to docker-compose [M-02 under_review] …
└── ST-03 Document operator runbook   [M-03 queued]       (blocked by M-02)

$ ces build --from-spec docs/specs/2026-04-21-healthcheck.md
# runs ces build on each manifest in topological order of depends_on_manifests
```

## 6. Error handling

| Failure mode | Detection | Response |
|---|---|---|
| Required section missing during validate | `TemplateLoader.verify_sections()` returns missing list | Exit 1; print missing sections with line hints |
| Story missing required field | Validator enumerates each story | Exit 1; point to story id + missing field |
| Cycle in `depends_on` graph | DAG walker during validate | Exit 1; print cycle path |
| LLM provider unavailable during `import` | `ProviderRegistry.resolve()` returns null | Fall back to interactive section mapping ("Which heading is your Problem section?") |
| LLM provider unavailable during `author --polish` | Same | Silent degradation — `?` becomes a no-op; user writes their own prose |
| `decompose` run twice | Check for existing `M-<ulid>` files carrying this `parent_spec_id` | Refuse with exit 1; require `--force` or `ces spec reconcile` |
| Spec edited after decompose (story added) | `ces spec validate` detects frontmatter `status=decomposed` but story count differs | Warn and suggest `ces spec reconcile` |
| Reconcile encounters orphaned manifest (story deleted from spec) | Reconciler scans existing manifests for missing parent stories | Warn loudly; never auto-delete manifests (they may be in-flight or merged); require human decision |
| Kill switch halted during author or import | `KillSwitch.is_halted()` checked before any LLM call | LLM call declined silently; interview / import continues in deterministic mode |
| Spec file edited manually to invalid state | `validate` catches it on next run | Same as any validation failure |

## 7. Testing strategy

Target coverage: **88%** (matches project gate per `CLAUDE.md`).

**Unit tests** (`tests/unit/spec/`):
- `test_template_loader.py` — lookup order, missing template, malformed sidecar
- `test_validator.py` — every error class in §6, parametrized
- `test_decomposer.py` — story → manifest stub mapping, DAG topological ordering, dependency resolution
- `test_reconciler.py` — added story, deleted story, edited story, no-op
- `test_spec_models.py` — Pydantic frozen/strict conformance, tuple invariants

**Integration tests** (`tests/integration/spec/`):
- Full author flow with a mock LLM provider (canned responses)
- Full import flow with fixture PRDs
- `decompose` → manifests land in `.ces/manifests/` and get picked up by existing `ces classify`
- `build --from-spec` honors `depends_on_manifests` ordering
- Re-decompose without `--force` fails; with `--force` succeeds
- `reconcile` detects and flags orphans

**Property-based tests** (`tests/property/`):
- `render(parse(spec_text)) == spec_text` modulo whitespace (round-trip)
- Random valid `SpecDocument` → decompose → `count(manifests) == len(stories)`
- Random DAG of stories → topological sort of decomposed manifests respects edges

**Fixtures** (`tests/fixtures/specs/`):
- `minimal-valid.md` — smallest passing spec (1 story, no deps)
- `missing-non-goals.md` — validation failure case
- `cyclic-deps.md` — cycle failure case
- `notion-export.md` — messy import source (non-standard headers)
- `complex-hierarchy.md` — 10 stories with multi-level deps

## 8. Open questions (deferred to writing-plans phase)

Five items are intentionally left open — they're sensitive to implementation detail and are easier to resolve once file-level tasks exist:

1. **Spec mutation auditing.** Proposal: audit ledger records `SPEC_AUTHORED`, `SPEC_DECOMPOSED`, `SPEC_RECONCILED` events only. Content diffs live in git. Alternative considered: full content snapshots in ledger. Rejected for storage/perf reasons.
2. **Multi-spec project discovery.** Proposal: ship v1 with only per-spec commands; add `ces spec list` / an index file when users ask for it. Deferred to avoid premature abstraction.
3. **Story-deletion orphan handling during reconcile.** Proposal: warn loudly, never auto-delete manifests. Manifest may be in-flight or merged; human must decide. The reconcile output lists orphans and suggests `ces manifest delete M-<id>` if appropriate.
4. **Template schema evolution.** Proposal: `template` field in frontmatter pins the template version (e.g., `default@v1`); validator uses the pinned version; `ces spec migrate <spec>` assists upgrades in later versions.
5. **`--polish` token budget.** Proposal: dry-run token estimate at `ces spec author --polish` startup; add `--max-tokens N` flag in 0.2.x if field-by-field LLM costs become a concern.

These become tasks in the implementation plan, not blockers for this design.

## 9. Out of scope (explicitly)

- Rich HTML or PDF rendering of specs.
- Real-time collaborative editing of spec documents.
- A web UI for the authoring interview. (CLI-only, consistent with rest of CES.)
- Cross-spec dependency management (e.g., Spec A's story depends on Spec B's story).
- Integration with external issue trackers (Jira, Linear). The import command accepts files; integrations are a separate feature.
- Migrating this feature to the FastAPI server surface. v1 is CLI-only.

## 10. Verification plan

This spec is verified in three stages:

1. **Design-phase self-review** (done inline before this file was committed): placeholder scan, internal consistency, scope check, ambiguity check. See §11.
2. **User review of this doc** — pending.
3. **Implementation-phase verification** — covered by the test strategy in §7 and the 88% coverage gate. Each task produced by `writing-plans` will include explicit acceptance criteria that map back to the error-handling matrix in §6 and the commands in §3.1.

## 11. Spec self-review checklist

Run against this document before asking the user to review:

- [x] **No placeholders.** No "TBD", "TODO", or unresolved sections. Every "<placeholder>" in the template is illustrative (appears inside a code fence showing template skeleton).
- [x] **Internal consistency.** Commands in §3.1 match plane placements in §3.2 match source files in §3.4 match test targets in §7. `spec reconcile` added to §3.1/§3.2 after initial Section 3 draft omitted it from the command list.
- [x] **Scope check.** §9 names explicit out-of-scope items. §8 lists 5 items deferred to implementation planning. All commands fit inside Approach 3.
- [x] **Ambiguity check.** `risk_hint` is explicitly non-binding (§4.4). `template` pinning is proposed in §8. Orphan handling is conservative (warn, never auto-delete) in §6 and §8.
- [x] **Cross-references to existing CES artifacts.** Refers to `ClassificationOracle`, `AuditLedger`, `ProviderRegistry`, `KillSwitch`, `CESBaseModel`, all verifiable against `src/ces/`.
- [x] **Honors `CLAUDE.md` constraints.** Python 3.12+ (unchanged). uv (unchanged). Pydantic models inherit `CESBaseModel`, use tuples. No LLM in control plane (§3.2). 88% coverage (§7).

---

**Next step:** User review. If approved, proceed to `superpowers:writing-plans` to produce the file-by-file implementation plan.
