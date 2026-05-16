# CES Intake and Execution Contract Implementation Plan

> **For Hermes:** Use subagent-driven-development to implement this plan task-by-task. Keep the execution path test-driven. Do not expand CES into a broad spec-framework importer ecosystem.

**Goal:** Productize CES intake as the narrow bridge from raw prompts, local PRDs, and GitHub issues into governed execution contracts, while preserving CES's core identity as an execution-governance and proof layer.

**Architecture:** Reframe the existing `ces spec` lifecycle behind a simpler `ces intake` command family. Intake accepts exactly three source shapes: inline intent text, local `prd.md`/Markdown files, and GitHub issue numbers or URLs. Intake normalizes these inputs into one canonical artifact, the **Execution Contract**, then reuses the existing deterministic spec validation, decomposition, manifest creation, build, verification, proof, and approval pipeline. LLMs may assist only during optional authoring/import mapping; deterministic validation, manifest generation, runtime governance, evidence, proof, and approval remain authoritative.

**Tech Stack:** Python 3.12+, Typer + Rich, Pydantic v2 via `CESBaseModel`, existing `ces.control.spec` parser/validator/decomposer services, existing manifest manager and audit ledger services, optional `gh` CLI or GitHub API for GitHub issue ingestion, pytest + `CliRunner`, existing 88 percent coverage gate.

---

## Strategic Decision

The importer scope should be intentionally narrow.

I agree with limiting importers to:

- `ces intake "Add CSV invoice notes"`
- `ces intake docs/prd.md`
- `ces intake --from-github-issue 123`

Do **not** maintain importers for spec-kit, OpenSpec, BMAD, GSD, Kiro, Superpowers, or other external project formats.

Reason:

- External project formats are unstable and create maintenance drag.
- CES should not become a compatibility layer for upstream methodology tools.
- A good `prd.md` contract is enough. Users of those tools can export/copy their artifact into Markdown.
- GitHub issues are worth supporting because they are durable, common, operationally central, and represent real work intake rather than another methodology format.
- This protects CES's positioning: **bring any serious intent source, but CES only owns the execution contract and proof loop.**

The product stance should be:

```text
CES accepts plain human intent, PRDs, and GitHub issues.
CES does not chase every planning framework's internal file layout.
If another tool produces a PRD or issue, CES can ingest that stable boundary.
```

---

## Product Positioning

### Primary message

```text
Specs tell agents what to build. CES proves what they actually did.
```

### CLI promise

```text
ces intake  -> turn intent into an execution contract
ces build   -> run bounded local AI execution
ces verify  -> collect fresh evidence
ces proof   -> summarize whether approval is safe
ces approve -> record the human decision
```

### What CES is

- Local-first control plane for AI coding agents.
- Execution-contract compiler from intent/PRD/GitHub issue into governed manifests.
- Evidence and proof layer for generated code.
- Approval safety layer for human operators.

### What CES is not

- Not a spec-kit replacement.
- Not an OpenSpec compatibility layer.
- Not a BMAD/GSD methodology runner.
- Not a broad planning-doc factory.
- Not an LLM-dependent spec generator.

---

## Current Codebase Reality

The repo already contains the main building blocks:

- `src/ces/cli/spec_cmd.py`
  - `ces spec author`
  - `ces spec import`
  - `ces spec validate`
  - `ces spec decompose`
  - `ces spec reconcile`
  - `ces spec tree`

- `src/ces/control/models/spec.py`
  - `SpecFrontmatter`
  - `SignalHints`
  - `Risk`
  - `Story`
  - `SpecDocument`

- `src/ces/control/spec/`
  - template loading
  - parsing
  - validation
  - decomposition
  - reconciliation
  - tree rendering

- `src/ces/harness/services/spec_authoring.py`
  - interactive spec authoring
  - optional polish path

- `src/ces/harness/services/spec_importer.py`
  - existing document to canonical spec mapping

- `src/ces/cli/run_cmd.py`
  - `--from-spec`
  - `--story`

There is also an existing `src/ces/cli/intake_cmd.py`, but it currently means a phase-based Q&A interview:

```bash
ces intake <phase>
```

That conflicts with the product direction proposed here:

```bash
ces intake "Add CSV invoice notes"
ces intake docs/prd.md
ces intake --from-github-issue 123
```

So the plan must deliberately migrate or preserve the existing phase interview without breaking users.

Recommended compatibility path:

- Keep the old phase interview available as `ces intake interview <phase>`.
- Add a deprecation warning for `ces intake <phase>` only if it currently has users.
- Use the top-level `ces intake` for the new execution-contract flow.

---

## Target User Experience

### Inline intent

```bash
ces intake "Add CSV invoice notes"
```

Expected behavior:

- Treat the quoted text as raw intent.
- Create an execution contract draft.
- If the intent is too ambiguous, write the draft with explicit assumptions and gaps.
- Do not run code by default unless a later command explicitly builds.
- Print the next safe command.

Example output:

```text
Execution contract created: .ces/contracts/EC-20260516-csv-invoice-notes.yaml
Spec draft created: docs/specs/2026-05-16-csv-invoice-notes.md
Status: needs review
Next: ces intake review EC-20260516-csv-invoice-notes
Then: ces build --contract EC-20260516-csv-invoice-notes
```

### Local PRD file

```bash
ces intake docs/prd.md
```

Expected behavior:

- Read the Markdown file.
- Reject missing file, binary file, empty file, or unsupported extension with clear usage errors.
- Normalize into canonical Execution Contract.
- Preserve source path provenance.
- Do not mutate the source file.
- Produce a spec draft only under CES-controlled paths.

### GitHub issue

```bash
ces intake --from-github-issue 123
```

Expected behavior:

- Resolve the current repository remote.
- Fetch issue title/body/labels/comments only if explicitly supported.
- Default to title + body + labels, not full discussion sprawl.
- Store source provenance: repository, issue number, URL, fetched timestamp.
- Fail gracefully if `gh` is missing or unauthenticated.
- Never require GitHub support for local-only CES operation.

Alternative input forms to support later if cheap:

```bash
ces intake --from-github-issue https://github.com/org/repo/issues/123
ces intake --from-github-issue org/repo#123
```

Initial implementation can support only the number form against the current repo.

---

## Canonical Artifact: Execution Contract

The Execution Contract is the product center. It is not just a renamed spec. It is the bridge between human intent and governed execution.

### Contract fields

The first version should include:

```yaml
contract_id: EC-20260516-csv-invoice-notes
title: Add CSV invoice notes
status: draft
source:
  type: inline | prd_file | github_issue
  value: "Add CSV invoice notes" | docs/prd.md | github:org/repo#123
  fetched_at: null
owner: cli-user
created_at: "2026-05-16T...Z"
objective: "..."
acceptance_criteria:
  - "..."
non_goals:
  - "..."
affected_areas:
  - "..."
risks:
  - risk: "..."
    mitigation: "..."
behavior_delta:
  added:
    - "..."
  modified:
    - "..."
  removed:
    - "..."
  preserved:
    - "..."
  unknown_or_unverified:
    - "..."
required_evidence:
  tests:
    - "..."
  manual_checks:
    - "..."
  artifacts:
    - "..."
policy:
  worktree_required: false
  tdd_required: false
  dependency_review_required: false
  human_approval_required: true
approval:
  status: not_requested
  reason: null
links:
  spec_path: docs/specs/2026-05-16-csv-invoice-notes.md
  manifest_ids: []
```

### Why this artifact matters

The contract lets CES say:

```text
This is what was requested.
This is what is allowed.
This is what must be preserved.
This is the proof required before approval.
```

That is CES's moat.

---

## Importer Boundary

### Accepted sources

Support only:

- inline text
- local Markdown PRD file
- GitHub issue

### Rejected sources

Do not support dedicated adapters for:

- spec-kit
- OpenSpec
- BMAD
- GSD
- Kiro
- Superpowers
- Linear yet, unless explicitly prioritized later
- Notion yet
- Jira yet

### Recommended error copy

If a user asks for an unsupported source:

```text
CES does not maintain framework-specific importers. Export or copy the upstream artifact to a Markdown PRD, then run:

  ces intake docs/prd.md

Supported intake sources are inline text, local Markdown PRDs, and GitHub issues.
```

This keeps the product clean and prevents maintenance traps.

---

## Behavior Delta Model

Borrow the best part of OpenSpec, but make it CES-native.

Every non-trivial contract should classify expected behavior into:

- Added behavior
- Modified behavior
- Removed behavior
- Preserved behavior
- Unknown or unverified behavior

For brownfield work, `preserved` should be required before build unless the task is explicitly classified as tiny/low-risk.

### Example

For:

```bash
ces intake "Add CSV invoice notes"
```

A good contract should eventually say:

```yaml
behavior_delta:
  added:
    - "CSV exports include invoice notes when present."
  modified:
    - "Invoice export row generation includes one additional notes field."
  removed: []
  preserved:
    - "Existing CSV column order remains stable unless explicitly changed."
    - "Invoices without notes still export successfully."
    - "Existing import scripts remain compatible or the contract must say otherwise."
  unknown_or_unverified:
    - "Exact CSV schema is unknown until implementation files are inspected."
```

The proof card can then verify or challenge each claim.

---

## Risk-Adaptive Intake Depth

The first implementation should avoid heavy ceremony for every task.

### Tiny patch

Trigger:

- inline intent is small
- no auth/data/billing/security labels
- likely isolated change

Required fields:

- objective
- acceptance criteria
- affected area if known
- one required verification command or unknown placeholder

### Normal feature

Trigger:

- feature label
- PRD file
- multiple acceptance criteria
- new user-visible behavior

Required fields:

- objective
- acceptance criteria
- non-goals
- behavior delta
- risks
- required evidence

### Brownfield change

Trigger:

- existing code modification
- bugfix
- regression risk
- data/export/import behavior
- billing/auth/security labels

Required fields:

- all normal feature fields
- preserved behavior
- regression evidence
- rollback plan
- human approval required

### High-risk change

Trigger:

- auth
- payments/billing
- data migration
- destructive operations
- dependency changes
- security-sensitive code

Required fields:

- all brownfield fields
- worktree required
- dependency review required when dependency changes are requested
- explicit approval gate before execution if non-interactive
- proof card must mark approval unsafe if required evidence is missing

---

## CLI Shape

### Proposed top-level command

Use a Typer sub-app instead of a single function if possible:

```python
intake_app = typer.Typer(help="Turn intent, PRDs, or GitHub issues into execution contracts.")
```

Register:

```python
app.add_typer(intake_cmd.intake_app, name="intake")
```

### Commands

Support:

```bash
ces intake "Add CSV invoice notes"
ces intake docs/prd.md
ces intake --from-github-issue 123
ces intake review EC-...
ces intake show EC-...
ces intake validate EC-...
ces intake decompose EC-...
ces intake interview 1
```

For a cleaner first release, implement only:

```bash
ces intake "..."
ces intake docs/prd.md
ces intake --from-github-issue 123
ces intake show EC-...
ces intake validate EC-...
```

Then add `review` and `decompose` after the artifact model settles.

### Compatibility with current `ces intake <phase>`

Current behavior:

```bash
ces intake 1
```

Recommended migration:

```bash
ces intake interview 1
```

Short-term compatibility:

- If the single argument is an integer in `1..3`, route to old interview flow and print a deprecation notice.
- If the single argument is non-integer and an existing file, treat as PRD path.
- If the single argument is non-integer and not an existing file, treat as inline intent.

Deprecation copy:

```text
Note: `ces intake 1` is now `ces intake interview 1`. This compatibility alias will remain for one minor release.
```

---

## File Layout

### New files

Create:

```text
src/ces/control/models/execution_contract.py
src/ces/control/intake/__init__.py
src/ces/control/intake/source.py
src/ces/control/intake/normalizer.py
src/ces/control/intake/validator.py
src/ces/control/intake/repository.py
src/ces/harness/services/github_issue_importer.py
src/ces/cli/intake_contract_cmd.py
```

Tests:

```text
tests/unit/test_services/test_execution_contract_models.py
tests/unit/test_services/test_intake_source.py
tests/unit/test_services/test_intake_normalizer.py
tests/unit/test_services/test_intake_validator.py
tests/unit/test_services/test_intake_repository.py
tests/unit/test_services/test_github_issue_importer.py
tests/unit/test_cli/test_intake_contract_cmd.py
tests/integration/test_intake_to_contract.py
tests/integration/test_intake_contract_to_spec.py
```

Fixtures:

```text
tests/fixtures/intake/prd-minimal.md
tests/fixtures/intake/prd-with-risks.md
tests/fixtures/intake/github-issue-export.json
```

### Modified files

Modify:

```text
src/ces/cli/__init__.py
src/ces/cli/intake_cmd.py
src/ces/control/models/spec.py
src/ces/control/spec/decomposer.py
src/ces/control/spec/templates/default.md
src/ces/control/spec/templates/default.yaml
src/ces/harness/services/spec_importer.py
src/ces/cli/spec_cmd.py
README.md
docs/designs/2026-04-21-ces-spec-authoring.md, or create a successor design doc
```

Potentially modify:

```text
src/ces/control/models/manifest.py
src/ces/cli/run_cmd.py
src/ces/cli/report_cmd.py
src/ces/cli/verify_cmd.py
src/ces/cli/approve_cmd.py
```

Only modify the latter group if the first release connects contracts directly to proof/approval gates.

---

## Implementation Phases

## Phase 0: Lock the product contract

### Task 0.1: Add a short design doc

**Objective:** Record the strategic boundary so future contributors do not add fragile external importers.

**Files:**

- Create: `docs/designs/2026-05-16-ces-intake-execution-contract.md`

**Content requirements:**

- CES intake accepts inline text, local Markdown PRDs, and GitHub issues only.
- Framework-specific importers are explicitly out of scope.
- Execution Contract is the canonical intake output.
- LLM assistance is optional and never authoritative after intake.
- Deterministic validation, evidence, proof, and approval remain the trust boundary.

**Verification:**

```bash
uv run pytest tests/unit/test_docs/test_package_contract.py -v
```

If docs tests do not cover design docs, run the repository's existing docs/package contract tests and ensure no packaging assertions fail.

---

## Phase 1: Add Execution Contract models

### Task 1.1: Create source provenance model

**Objective:** Represent where the intake came from without coupling to external frameworks.

**Files:**

- Create: `src/ces/control/models/execution_contract.py`
- Create or update: `tests/unit/test_services/test_execution_contract_models.py`

**Model sketch:**

```python
from __future__ import annotations

from datetime import datetime
from typing import Literal

from ces.shared.base import CESBaseModel

class ContractSource(CESBaseModel):
    type: Literal["inline", "prd_file", "github_issue"]
    value: str
    fetched_at: datetime | None = None
    url: str | None = None
```

**Tests:**

- Accepts `inline` source.
- Accepts `prd_file` source.
- Accepts `github_issue` source with `url` and `fetched_at`.
- Rejects unsupported source types like `speckit`, `openspec`, `bmad`, `gsd`.

**Command:**

```bash
uv run pytest tests/unit/test_services/test_execution_contract_models.py -v
```

---

### Task 1.2: Create behavior delta model

**Objective:** Add CES-native behavior delta semantics.

**Files:**

- Modify: `src/ces/control/models/execution_contract.py`
- Modify: `tests/unit/test_services/test_execution_contract_models.py`

**Model sketch:**

```python
class BehaviorDelta(CESBaseModel):
    added: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    preserved: tuple[str, ...] = ()
    unknown_or_unverified: tuple[str, ...] = ()
```

**Tests:**

- Defaults all buckets to empty tuples.
- Preserves tuple immutability.
- Serializes cleanly via `model_dump()`.

---

### Task 1.3: Create required evidence and policy models

**Objective:** Encode proof requirements before execution.

**Files:**

- Modify: `src/ces/control/models/execution_contract.py`
- Modify: `tests/unit/test_services/test_execution_contract_models.py`

**Model sketch:**

```python
class RequiredEvidence(CESBaseModel):
    tests: tuple[str, ...] = ()
    manual_checks: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()

class ContractPolicy(CESBaseModel):
    worktree_required: bool = False
    tdd_required: bool = False
    dependency_review_required: bool = False
    human_approval_required: bool = True
```

**Tests:**

- Defaults are conservative.
- Human approval defaults to true.
- No mutable list defaults.

---

### Task 1.4: Create ExecutionContract aggregate

**Objective:** Define the canonical intake artifact.

**Files:**

- Modify: `src/ces/control/models/execution_contract.py`
- Modify: `tests/unit/test_services/test_execution_contract_models.py`

**Model sketch:**

```python
class ContractLinks(CESBaseModel):
    spec_path: str | None = None
    manifest_ids: tuple[str, ...] = ()

class ExecutionContract(CESBaseModel):
    contract_id: str
    title: str
    status: Literal["draft", "reviewed", "decomposed", "in_progress", "complete", "rejected"] = "draft"
    source: ContractSource
    owner: str
    created_at: datetime
    objective: str
    acceptance_criteria: tuple[str, ...] = ()
    non_goals: tuple[str, ...] = ()
    affected_areas: tuple[str, ...] = ()
    risks: tuple[Risk, ...] = ()
    behavior_delta: BehaviorDelta = BehaviorDelta()
    required_evidence: RequiredEvidence = RequiredEvidence()
    policy: ContractPolicy = ContractPolicy()
    links: ContractLinks = ContractLinks()
```

If Pydantic or the project style dislikes model instances as defaults, use `Field(default_factory=...)` according to existing conventions.

**Tests:**

- Creates minimal valid contract.
- Rejects empty title/objective if existing validators support that convention.
- Rejects unsupported statuses.
- Round-trips through JSON/YAML serialization.

---

## Phase 2: Add local contract repository

### Task 2.1: Implement repository path policy

**Objective:** Store contracts in a stable local-first location.

**Files:**

- Create: `src/ces/control/intake/repository.py`
- Create: `tests/unit/test_services/test_intake_repository.py`

**Path policy:**

```text
.ces/contracts/<contract_id>.yaml
```

If existing CES state uses a different internal root, adapt to existing project-root conventions rather than inventing a parallel store.

**Tests:**

- Creates `.ces/contracts/` when missing.
- Writes a contract file.
- Reads the same contract back.
- Rejects path traversal in `contract_id`.
- Lists contracts sorted by created time or filename.

---

### Task 2.2: Add contract ID generation

**Objective:** Generate stable readable IDs.

**Files:**

- Modify: `src/ces/control/intake/repository.py`, or create `src/ces/control/intake/ids.py`
- Modify: `tests/unit/test_services/test_intake_repository.py`

**ID shape:**

```text
EC-YYYYMMDD-slug
```

If collision occurs:

```text
EC-YYYYMMDD-slug-2
EC-YYYYMMDD-slug-3
```

**Tests:**

- Slugifies title.
- Avoids unsafe characters.
- Handles collisions.
- Keeps ID length reasonable.

---

## Phase 3: Implement source intake

### Task 3.1: Implement inline source reader

**Objective:** Convert raw CLI text into an intake source payload.

**Files:**

- Create: `src/ces/control/intake/source.py`
- Create: `tests/unit/test_services/test_intake_source.py`

**Behavior:**

- Non-empty string becomes `ContractSource(type="inline")`.
- Strip surrounding whitespace.
- Reject empty or whitespace-only strings.

---

### Task 3.2: Implement PRD file source reader

**Objective:** Read only stable local Markdown PRDs.

**Files:**

- Modify: `src/ces/control/intake/source.py`
- Modify: `tests/unit/test_services/test_intake_source.py`

**Behavior:**

- Accept `.md` and `.markdown`.
- Read UTF-8 text.
- Reject missing files.
- Reject directories.
- Reject empty files.
- Reject very large files above a conservative cap, for example 256 KB, unless there is an existing project-wide cap.
- Preserve path as provided or relative to project root.

**Tests:**

- Reads `tests/fixtures/intake/prd-minimal.md`.
- Rejects unsupported extension.
- Rejects nonexistent file.
- Rejects empty file.

---

### Task 3.3: Implement GitHub issue importer using `gh`

**Objective:** Fetch issue title/body/labels from the current GitHub repository without adding a heavy dependency.

**Files:**

- Create: `src/ces/harness/services/github_issue_importer.py`
- Create: `tests/unit/test_services/test_github_issue_importer.py`

**Initial approach:**

Use `gh issue view` via subprocess:

```bash
gh issue view 123 --json number,title,body,labels,url,state
```

**Behavior:**

- If `gh` is missing, return a clear actionable error.
- If unauthenticated, return a clear actionable error.
- If not in a GitHub repository, return a clear actionable error.
- Do not fetch comments in v1 unless explicitly requested later.
- Convert labels into risk hints only conservatively.

**Tests:**

Use monkeypatch/subprocess mocking. Do not require live GitHub in unit tests.

Test cases:

- Successful issue JSON parses into payload.
- Missing `gh` maps to friendly error.
- Nonzero `gh` exit maps stderr to friendly error.
- Labels `security`, `auth`, `billing`, `data`, `migration` set high-risk hints if the normalizer supports hints.

---

## Phase 4: Normalize source into Execution Contract

### Task 4.1: Create deterministic normalizer baseline

**Objective:** Generate a useful draft contract without requiring an LLM.

**Files:**

- Create: `src/ces/control/intake/normalizer.py`
- Create: `tests/unit/test_services/test_intake_normalizer.py`

**Behavior:**

- Title comes from:
  - GitHub issue title, or
  - first Markdown H1, or
  - first sentence/slug of inline intent.
- Objective comes from source body or intent.
- Acceptance criteria are extracted from obvious Markdown headings if present:
  - `Acceptance Criteria`
  - `Success Criteria`
  - `Requirements`
- Non-goals are extracted from obvious headings:
  - `Non-Goals`
  - `Out of Scope`
- Risks are extracted from `Risks` heading if present.
- Unknown fields are placed under `behavior_delta.unknown_or_unverified` rather than invented.

**Strict rule:** The deterministic normalizer must not hallucinate specifics.

Bad:

```text
Preserved: Existing import scripts remain compatible.
```

unless source says that or a brownfield template asks the human to confirm it.

Good:

```text
Unknown/unverified: Preserved behavior has not been specified.
```

---

### Task 4.2: Add risk classification hints

**Objective:** Set policy defaults from source content and labels.

**Files:**

- Modify: `src/ces/control/intake/normalizer.py`
- Modify: `tests/unit/test_services/test_intake_normalizer.py`

**Rules:**

If source contains or labels include:

- `auth`
- `security`
- `billing`
- `payment`
- `migration`
- `database`
- `export`
- `import`
- `delete`
- `destructive`

then set one or more of:

```yaml
policy:
  worktree_required: true
  dependency_review_required: true, only for dependency/package wording
  human_approval_required: true
```

For export/import/data-like changes, require preserved behavior to be explicit before approval is safe.

---

### Task 4.3: Add optional LLM polish hook behind kill switch

**Objective:** Improve contract wording without making the LLM authoritative.

**Files:**

- Modify: `src/ces/control/intake/normalizer.py` or add harness service
- Modify: tests as appropriate

**Behavior:**

- Default deterministic flow works with no provider.
- Optional flag later:

```bash
ces intake docs/prd.md --polish
```

- LLM may rewrite prose and suggest missing fields.
- LLM output must be validated by deterministic `ExecutionContractValidator`.
- Failed LLM call falls back to deterministic draft.
- Suggested fields that are not grounded in source should be marked as assumptions or unknown, not facts.

Do not implement this in the first thin slice unless it is already easy to reuse `SpecImporter` safely.

---

## Phase 5: Validate contracts

### Task 5.1: Implement contract validator

**Objective:** Decide whether a contract is ready to decompose/build.

**Files:**

- Create: `src/ces/control/intake/validator.py`
- Create: `tests/unit/test_services/test_intake_validator.py`

**Validation levels:**

- `ok`
- `warning`
- `blocker`

**Validation rules:**

Blockers:

- missing objective
- no acceptance criteria for normal/high-risk work
- high-risk work with no required evidence
- brownfield work with no preserved behavior or explicit unknown marker
- unsupported source type

Warnings:

- no non-goals
- no rollback plan, if rollback is added to the model
- vague acceptance criteria like `works` or `done`
- unknown affected area

**Output model:**

```python
class ContractValidationFinding(CESBaseModel):
    severity: Literal["warning", "blocker"]
    code: str
    message: str
    field: str | None = None

class ContractValidationReport(CESBaseModel):
    status: Literal["ok", "warning", "blocked"]
    findings: tuple[ContractValidationFinding, ...] = ()
```

---

### Task 5.2: Add CLI validation output

**Objective:** Let users see why a contract is or is not build-ready.

**Files:**

- Modify or create: `src/ces/cli/intake_contract_cmd.py`
- Test: `tests/unit/test_cli/test_intake_contract_cmd.py`

**Command:**

```bash
ces intake validate EC-20260516-csv-invoice-notes
```

**Output examples:**

```text
Contract: EC-20260516-csv-invoice-notes
Status: blocked

Blockers:
- behavior_delta.preserved: Brownfield/export-like work must state preserved behavior or mark it unknown.

Warnings:
- non_goals: No non-goals specified.
```

JSON mode should return the model dump.

---

## Phase 6: Connect contracts to existing spec/decompose path

### Task 6.1: Convert Execution Contract to SpecDocument

**Objective:** Reuse the existing spec/decomposer pipeline rather than duplicating manifest creation.

**Files:**

- Create: `src/ces/control/intake/contract_to_spec.py`
- Create: `tests/unit/test_services/test_contract_to_spec.py`

**Mapping:**

- `contract.title` -> `SpecFrontmatter.title`
- `contract.owner` -> `SpecFrontmatter.owner`
- `contract.objective` -> `SpecDocument.problem`
- `contract.acceptance_criteria` -> success criteria and/or story acceptance criteria
- `contract.non_goals` -> `SpecDocument.non_goals`
- `contract.risks` -> `SpecDocument.risks`
- `contract.behavior_delta` -> new spec section or appended structured prose
- `contract.required_evidence` -> story acceptance criteria and later manifest evidence requirements

**Question to resolve during implementation:**

Should each contract produce one story by default, or infer multiple stories from PRD sections?

Recommendation for v1:

- Inline intent creates one story.
- GitHub issue creates one story.
- PRD creates one story unless the PRD has explicit story/task headings.

Keep v1 simple.

---

### Task 6.2: Extend SpecDocument with behavior delta, or keep contract as sidecar

**Objective:** Avoid losing behavior-delta semantics when using existing spec tooling.

Preferred approach:

- Keep Execution Contract as authoritative sidecar.
- Generate a `SpecDocument` that includes behavior delta sections in Markdown for human readability.
- Avoid expanding the spec model too much until the contract model proves itself.

Alternative:

- Add optional `behavior_delta` and `required_evidence` fields to `SpecDocument`.

Recommendation:

Use the sidecar-first approach for v1 to reduce migration risk.

**Files if sidecar-first:**

- Modify: `src/ces/control/spec/templates/default.md`
- Modify: `src/ces/control/spec/templates/default.yaml`
- Modify: parser/validator only if new sections become required

**Tests:**

- Contract to spec preserves behavior delta as Markdown.
- Existing spec fixtures still parse.
- Existing spec validator tests still pass.

---

### Task 6.3: Save generated spec under `docs/specs/`

**Objective:** Preserve the current `ces spec` lifecycle and make intake output inspectable.

**Files:**

- Modify: `src/ces/control/intake/repository.py` or create service
- Test: `tests/integration/test_intake_contract_to_spec.py`

**Output:**

```text
docs/specs/YYYY-MM-DD-<slug>.md
```

The contract should link to it:

```yaml
links:
  spec_path: docs/specs/2026-05-16-csv-invoice-notes.md
```

---

### Task 6.4: Decompose contract/spec to manifests

**Objective:** Let users move from contract to governed manifest drafts.

**Command:**

```bash
ces intake decompose EC-20260516-csv-invoice-notes
```

or later:

```bash
ces build --contract EC-20260516-csv-invoice-notes
```

V1 can call existing `SpecDecomposer` internally.

**Tests:**

- Creates manifest stubs.
- Manifest links back to contract/spec if model supports it.
- Existing `parent_spec_id` and `parent_story_id` continue working.
- Contract `links.manifest_ids` is updated after decomposition.

---

## Phase 7: Implement CLI thin slice

### Task 7.1: Replace current single-command `intake_cmd` with sub-app wrapper

**Objective:** Make `ces intake` own the new product flow while preserving old interview behavior.

**Files:**

- Modify: `src/ces/cli/intake_cmd.py`
- Modify: `src/ces/cli/__init__.py`
- Create/modify: `tests/unit/test_cli/test_intake_contract_cmd.py`

**Implementation sketch:**

```python
intake_app = typer.Typer(help="Turn intent, PRDs, or GitHub issues into execution contracts.")

@intake_app.callback(invoke_without_command=True)
def intake(
    ctx: typer.Context,
    source: str | None = typer.Argument(None),
    from_github_issue: str | None = typer.Option(None, "--from-github-issue"),
):
    ...

@intake_app.command("interview")
def intake_interview(phase: int):
    ...
```

If Typer callback-with-argument becomes awkward, use explicit commands instead:

```bash
ces intake create "..."
ces intake create docs/prd.md
```

But the desired UX is the top-level shorthand, so try to preserve it.

---

### Task 7.2: Implement inline CLI path

**Objective:** Support the headline command.

**Command:**

```bash
ces intake "Add CSV invoice notes"
```

**Tests:**

- Creates contract file.
- Creates spec draft if v1 includes spec generation.
- Prints contract ID.
- Prints next command.
- JSON mode prints machine-readable contract summary.

---

### Task 7.3: Implement PRD file CLI path

**Objective:** Support local Markdown import.

**Command:**

```bash
ces intake docs/prd.md
```

**Tests:**

- Reads file.
- Preserves source path.
- Creates contract.
- Does not modify source file.
- Clear error for missing file.

---

### Task 7.4: Implement GitHub issue CLI path

**Objective:** Support stable operational issue intake.

**Command:**

```bash
ces intake --from-github-issue 123
```

**Tests:**

- Calls importer.
- Creates contract with `source.type == "github_issue"`.
- Includes issue URL in source if available.
- Clear error for missing `gh`.
- Clear error if used together with positional source.

**Mutual exclusion rule:**

Reject:

```bash
ces intake docs/prd.md --from-github-issue 123
```

with:

```text
Choose exactly one intake source: inline text, PRD file, or --from-github-issue.
```

---

### Task 7.5: Preserve phase interview

**Objective:** Avoid breaking the existing Q&A phase interview.

**Command:**

```bash
ces intake interview 1
```

Compatibility:

```bash
ces intake 1
```

should route to interview with a deprecation notice, or be rejected only if there are no users and release notes call it out.

**Tests:**

- `ces intake interview 1` calls existing interview engine.
- `ces intake 1` compatibility behavior is tested if kept.

---

## Phase 8: Review and show commands

### Task 8.1: Implement `ces intake show`

**Objective:** Display contracts cleanly.

**Command:**

```bash
ces intake show EC-20260516-csv-invoice-notes
```

**Human output sections:**

- Contract ID and status
- Source
- Objective
- Acceptance criteria
- Behavior delta
- Required evidence
- Policy
- Links
- Next safe command

No giant YAML dump by default.

**JSON mode:** full contract model.

---

### Task 8.2: Implement `ces intake review`

**Objective:** Show whether the contract is ready for build.

**Command:**

```bash
ces intake review EC-20260516-csv-invoice-notes
```

Can be an alias for validate plus human-centered formatting.

**Output should say:**

- ready
- ready with warnings
- blocked

Example:

```text
Contract: EC-20260516-csv-invoice-notes
Decision: blocked

Why:
- Export-like change has no preserved behavior statement.
- Required evidence is empty.

Next:
- Edit .ces/contracts/EC-20260516-csv-invoice-notes.yaml
- Add preserved behavior and at least one test command
- Run ces intake review EC-20260516-csv-invoice-notes
```

---

## Phase 9: Connect to proof and approval semantics

### Task 9.1: Mark proof cards with contract context

**Objective:** Make `ces proof` answer whether execution satisfied the contract.

**Files:**

- Inspect and modify proof/report modules according to current implementation.
- Likely: `src/ces/cli/report_cmd.py`, `src/ces/cli/verify_cmd.py`, or proof-related modules.

**Proof card sections:**

```text
Requested
Contract
Behavior delta
Evidence found
Evidence missing
Unproven claims
Approval status
```

**Rule:** If required evidence from contract is missing, approval should not look safe.

---

### Task 9.2: Add claim verification status

**Objective:** Prevent “done” claims without evidence.

**Statuses:**

- proven
- partially proven
- unproven
- contradicted

**V1 rule:**

A contract cannot be `complete` if:

- required tests were not run
- required artifacts are missing
- manual checks are required but not attached
- behavior_delta.preserved is unverified for brownfield/high-risk tasks

---

## Phase 10: Documentation and examples

### Task 10.1: Update README quickstart

**Objective:** Make the product wedge obvious.

**Files:**

- Modify: `README.md`

**Add a section:**

```markdown
## Start from intent, PRD, or GitHub issue

ces intake "Add CSV invoice notes"
ces intake docs/prd.md
ces intake --from-github-issue 123
ces build --contract EC-...
ces verify
ces proof
ces approve
```

**Messaging:**

- “CES does not replace your planning tool.”
- “CES turns the result into governed execution with proof.”

---

### Task 10.2: Add importer boundary docs

**Objective:** Prevent future scope creep.

**Files:**

- Create: `docs/intake.md`, or add to existing docs if there is a docs index.

**Must include:**

```text
Supported intake sources:
- inline text
- local Markdown PRD
- GitHub issue

Unsupported by design:
- framework-specific importers for spec-kit, OpenSpec, BMAD, GSD, Kiro, etc.

Why:
- CES avoids chasing unstable third-party artifact layouts.
- Markdown and GitHub issues are stable boundaries.
```

---

### Task 10.3: Add worked example

**Objective:** Show the exact flow Chris proposed.

**Example:**

```bash
ces intake "Add CSV invoice notes"
ces intake show EC-20260516-csv-invoice-notes
ces intake review EC-20260516-csv-invoice-notes
ces build --contract EC-20260516-csv-invoice-notes
ces verify
ces proof
```

Include expected proof-card outcome if preserved behavior is missing:

```text
APPROVAL: unsafe
Reason: CSV export behavior changed, but preserved behavior regression evidence is missing.
```

---

## Testing Strategy

### Unit tests

Run targeted tests per phase:

```bash
uv run pytest tests/unit/test_services/test_execution_contract_models.py -v
uv run pytest tests/unit/test_services/test_intake_source.py -v
uv run pytest tests/unit/test_services/test_intake_normalizer.py -v
uv run pytest tests/unit/test_services/test_intake_validator.py -v
uv run pytest tests/unit/test_services/test_intake_repository.py -v
uv run pytest tests/unit/test_services/test_github_issue_importer.py -v
uv run pytest tests/unit/test_cli/test_intake_contract_cmd.py -v
```

### Integration tests

```bash
uv run pytest tests/integration/test_intake_to_contract.py -v
uv run pytest tests/integration/test_intake_contract_to_spec.py -v
uv run pytest tests/integration/test_spec_end_to_end.py -v
```

### Regression tests

Existing spec tests must keep passing:

```bash
uv run pytest tests/unit/test_services/test_spec_models.py -v
uv run pytest tests/unit/test_services/test_spec_parser.py -v
uv run pytest tests/unit/test_services/test_spec_validator.py -v
uv run pytest tests/unit/test_services/test_spec_decomposer.py -v
uv run pytest tests/unit/test_cli/test_spec_cmd.py -v
uv run pytest tests/unit/test_cli/test_run_cmd_from_spec.py -v
```

### Full suite before merge

```bash
uv run pytest
```

If the repo has lint/type commands in `pyproject.toml`, run them too.

---

## Release Criteria

The feature is ready when:

- `ces intake "..."` creates a contract.
- `ces intake docs/prd.md` creates a contract.
- `ces intake --from-github-issue 123` creates a contract when `gh` is available and authenticated.
- Unsupported external framework importers are documented as intentionally unsupported.
- `ces intake show` displays the contract clearly.
- `ces intake validate` reports blockers/warnings deterministically.
- Existing `ces spec` tests still pass.
- Existing phase interview flow is either preserved under `ces intake interview` or explicitly migrated with tests and release notes.
- The proof path can at least reference contract-required evidence, even if deeper proof integration lands in a follow-up.

---

## Non-Goals

Do not implement:

- `ces intake --from-speckit`
- `ces intake --from-openspec`
- `ces intake --from-bmad`
- `ces intake --from-gsd`
- full Linear/Jira/Notion importers
- multi-framework artifact syncing
- spec-kit constitution compatibility
- OpenSpec archive compatibility
- BMAD role orchestration
- broad PRD generation product surface

Do not make the LLM mandatory for any intake path.

Do not auto-run `ces build` after intake unless the user explicitly requests a combined flow later.

---

## Implementation Risks

### Risk: `ces intake` command conflict

Current `ces intake <phase>` exists. The new UX wants `ces intake <source>`.

Mitigation:

- Move old flow to `ces intake interview <phase>`.
- Keep integer compatibility briefly.
- Add tests for both.

### Risk: Contract and SpecDocument duplicate each other

Mitigation:

- Treat Execution Contract as authoritative for governance.
- Treat SpecDocument as compatibility with existing decomposition path.
- Avoid expanding both models aggressively in v1.

### Risk: GitHub issue fetching becomes unreliable

Mitigation:

- Use `gh issue view` as a thin optional dependency.
- Fail gracefully.
- Keep local PRD and inline paths fully functional without GitHub.

### Risk: Behavior delta creates too much ceremony

Mitigation:

- Require strict behavior delta only for normal/brownfield/high-risk work.
- Tiny inline tasks can have unknown/unverified placeholders and warnings instead of blockers.

### Risk: Scope creep into external importers

Mitigation:

- Document unsupported importers explicitly.
- Centralize source type enum and tests that reject unsupported types.
- Error message tells users to export/copy to `prd.md`.

---

## Suggested Commit Sequence

1. `docs: define CES intake execution contract strategy`
2. `feat(intake): add execution contract models`
3. `feat(intake): persist execution contracts locally`
4. `feat(intake): normalize inline and PRD sources`
5. `feat(intake): import GitHub issues via gh`
6. `feat(intake): validate execution contracts`
7. `feat(cli): add ces intake contract flow`
8. `feat(intake): map contracts to specs`
9. `feat(proof): surface contract evidence requirements`
10. `docs: document intake sources and examples`

---

## My Final Product Recommendation

Yes: support the three forms Chris proposed.

```bash
ces intake "Add CSV invoice notes"
ces intake docs/prd.md
ces intake --from-github-issue 123
```

No: do not maintain importers for every adjacent planning framework.

The right boundary is:

```text
Other tools can produce PRDs, Markdown, or GitHub issues.
CES consumes those stable boundaries and turns them into governed execution contracts with proof.
```

That keeps CES sharp, maintainable, and differentiated.
