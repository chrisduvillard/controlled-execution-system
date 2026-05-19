# CES Semantic Review Layer PRD

> **For CES implementation:** Use this PRD as the source artifact for `ces intake` / `ces build`. Implement sequentially. Keep the first implementation local-first, deterministic where possible, and reviewable through Markdown and JSON artifacts before attempting a richer UI.

**Author:** Vega for Chris
**Date:** 2026-05-19
**Status:** Draft PRD for implementation
**Target product:** Controlled Execution System (CES)
**Feature name:** Semantic Review Layer

---

## 1. Executive Summary

AI coding agents are shifting the engineering bottleneck from writing code to reviewing, steering, and approving generated work. Current code review tooling is poorly suited to this world: it presents file diffs alphabetically, assumes the reviewer already knows the intent, and leaves risk triage, architectural understanding, test adequacy, and agent provenance as manual work.

CES should productize the missing layer: a **Semantic Review Layer** that turns agent-produced changes into a reviewable engineering narrative.

The feature should generate structured review artifacts after CES execution and before human approval. These artifacts should explain what changed, why it changed, how it maps to the original intent, which files matter most, what risks remain, what tests verify the behavior, and where a human should focus review attention.

The strategic thesis:

```text
Most AI coding tools optimize for code generation.
CES should optimize for trustworthy review, proof, and human judgment.
```

This feature expands CES from an execution-governance and proof layer into a practical review cockpit for agent-generated code. It should make the human feel like an architect inspecting a system, not a janitor cleaning up agent output.

---

## 2. Problem Statement

### 2.1 Current review problem

When AI agents generate code, reviewers face a compounding burden:

- generated diffs can be large and multi-file
- changes often span tests, docs, CLI surfaces, runtime behavior, and safety-sensitive code
- raw Git diffs are ordered by file path, not review importance
- the connection between original intent and implementation is often implicit
- test coverage and verification evidence are disconnected from the changed behavior
- agent assumptions and failed checks are easy to lose
- human reviewers must reconstruct architecture, risk, and intent from low-level patches

This creates a poor experience and a safety problem. The reviewer either spends too much time manually reconstructing context, or approves work without fully understanding it.

### 2.2 CES-specific problem

CES already controls agent execution, evidence, proof, and approval. But if CES emits only code, logs, and proof summaries, it still leaves the reviewer with a raw diff-review burden.

CES needs to answer:

- What did the agent actually change?
- Which requirements were satisfied, partially satisfied, or missed?
- Which files are high-risk and should be reviewed first?
- Which behavior changed at runtime?
- Which tests prove the claims?
- What could not be verified?
- What assumptions did the agents make?
- What human decision is being requested?

Without this layer, CES risks becoming another AI execution tool that increases code throughput while pushing cognitive debt onto the human reviewer.

---

## 3. Product Vision

CES should generate a **reviewable engineering narrative** for every meaningful build.

The future review experience should be:

```text
I understand the intent, the implementation shape, the changed invariants, the risky files, the verification evidence, and the approval decision in minutes, before opening the raw diff.
```

The Semantic Review Layer should become a first-class part of the CES lifecycle:

```text
ces intake   -> capture intent as an execution contract
ces build    -> run bounded agent implementation
ces verify   -> collect fresh evidence
ces review   -> generate semantic review artifacts
ces proof    -> summarize approval safety
ces approve  -> record the human decision
```

In short:

```text
CES does not only produce code.
CES produces code that can be reviewed intelligently.
```

---

## 4. Goals

### 4.1 Primary goals

1. Generate a structured **Review Brief** for CES-produced changes.
2. Present changed files grouped by conceptual area, not alphabetically.
3. Rank review attention by risk and semantic importance.
4. Map original intent and requirements to changed files, tests, and verification evidence.
5. Preserve agent provenance, assumptions, dissent, and verification limits.
6. Produce durable local artifacts that can later power CLI, TUI, web, GitHub, or Obsidian surfaces.
7. Integrate the review layer into the CES proof and approval loop.
8. Keep the initial implementation safe, local-first, and deterministic where possible.

### 4.2 Secondary goals

1. Provide an optional GitHub PR comment summary.
2. Add a `ces review` command family.
3. Provide machine-readable JSON artifacts for future UI work.
4. Support review regeneration after additional commits or verification runs.
5. Enable semantic review of both CES-generated and non-CES local diffs where feasible.
6. Establish a foundation for later interactive review flows.

---

## 5. Non-Goals

1. Do not build a complex web dashboard in the first implementation wave.
2. Do not require LLM calls for core diff classification, artifact collection, or risk ordering.
3. Do not replace human code review or approval.
4. Do not auto-approve changes.
5. Do not post to GitHub, send messages, or make external side effects without explicit user approval.
6. Do not treat generated commentary as authoritative over tests, diffs, or proof evidence.
7. Do not ingest secrets or print secret values in review artifacts.
8. Do not render repository content as executable instructions inside agent prompts without explicit boundaries.

---

## 6. Users and Use Cases

### 6.1 Primary user: senior engineer or technical founder

The user delegates implementation to CES-backed agents and needs to quickly understand whether the result is safe, coherent, and worth approving.

Needs:

- fast orientation
- architectural understanding
- risk-first review path
- evidence-backed confidence
- clear approval decision support

### 6.2 Secondary user: reviewer of a CES-generated PR

The user receives a PR produced through CES and wants a concise explanation before reading the diff.

Needs:

- PR comment summary
- changed behavior summary
- tests and verification evidence
- high-risk files first
- known limitations

### 6.3 Secondary user: maintainer dogfooding CES on CES

The maintainer uses CES to implement CES features and wants recurring review artifacts that reduce slop and improve auditability.

Needs:

- local artifact history
- reproducible review outputs
- ability to compare review briefs across iterations
- friction log entries for weak review outputs

---

## 7. Core Product Concepts

### 7.1 Review Brief

A human-readable Markdown artifact that explains the change at a semantic level.

It should answer:

- What was the goal?
- What changed?
- Why was this approach taken?
- What files matter most?
- What behavior changed?
- What tests and verification ran?
- What remains risky or unverified?
- What should the human review first?

### 7.2 Risk Map

A machine-readable JSON artifact ranking changed files, changed areas, and review checkpoints by risk.

Risk factors may include:

- file write or deletion behavior
- subprocess execution
- network calls
- external sends
- secrets or credentials handling
- auth/authz surfaces
- persistence and migrations
- public CLI/API behavior
- concurrency and retries
- generated code volume
- low test coverage for changed paths
- verification failures
- broad cross-cutting changes

### 7.3 Intent Coverage Map

A structured mapping from the original execution contract, PRD, issue, or objective to implementation evidence.

For each requirement or objective item:

- status: implemented, partially implemented, not implemented, intentionally deferred, unknown
- changed files
- tests or verification commands
- evidence snippets or references
- confidence level
- notes and caveats

### 7.4 Review Path

A recommended sequence for human review.

The path should be risk-first and concept-first, for example:

1. safety-sensitive runtime paths
2. filesystem, network, subprocess, and external effects
3. persistence, migrations, and state changes
4. public CLI/API behavior
5. core implementation logic
6. tests proving changed behavior
7. docs and examples

### 7.5 Agent Provenance

A record of how the change was produced.

It should include:

- runtime or agent used
- execution contract or source intent
- plan or approach summary if available
- independent critique or dissent if available
- assumptions made
- verification commands attempted
- failed or skipped checks
- human approvals or gates, where relevant

### 7.6 Semantic Review Artifacts

A durable artifact bundle written under CES-owned local state.

Proposed local artifact paths:

```text
.ces/reviews/<review-id>/review-brief.md
.ces/reviews/<review-id>/risk-map.json
.ces/reviews/<review-id>/intent-coverage.json
.ces/reviews/<review-id>/intent-coverage.md
.ces/reviews/<review-id>/review-path.md
.ces/reviews/<review-id>/agent-provenance.json
.ces/reviews/<review-id>/verification-summary.json
.ces/reviews/<review-id>/diff-index.json
.ces/reviews/<review-id>/metadata.json
```

The implementation may start with fewer files if schemas are well-defined and forward-compatible, but the product should target the full bundle.

---

## 8. User Experience

### 8.1 CLI command family

Add a first-class command family:

```bash
ces review generate
ces review show
ces review list
ces review open
ces review export
ces review github-comment
```

Suggested behavior:

```bash
ces review generate
```

Generate review artifacts for the current working tree or latest CES build.

```bash
ces review generate --from-build <build-id>
```

Generate review artifacts from a specific CES build, using captured execution contract, manifest, proof, verification, and workspace delta data.

```bash
ces review generate --base main --head HEAD
```

Generate semantic review artifacts for an arbitrary local diff.

```bash
ces review show
```

Render the latest Review Brief in the terminal with Rich formatting.

```bash
ces review show --section risks
ces review show --section path
ces review show --section coverage
```

Render targeted sections.

```bash
ces review export --format markdown --output review.md
ces review export --format json --output review.json
```

Export artifacts for external use.

```bash
ces review github-comment --dry-run
ces review github-comment --pr 123
```

Prepare or post a GitHub PR comment. Posting must require explicit confirmation or a clear non-interactive approval flag.

### 8.2 Integration into existing flow

After `ces build` and `ces verify`, CES should suggest:

```text
Review artifacts are available:
  ces review show
  ces review show --section path
  ces proof
```

After `ces proof`, the proof output should reference the latest review artifact:

```text
Semantic review: .ces/reviews/20260519-.../review-brief.md
Risk map: medium, 2 high-attention files
Intent coverage: 6 implemented, 1 partial, 0 missing
```

### 8.3 Review Brief format

The generated `review-brief.md` should use this structure:

```markdown
# CES Review Brief: <title>

## Bottom Line
<plain-language summary of whether the change appears reviewable, risky, blocked, or ready for approval consideration>

## Objective
<source objective or execution contract summary>

## What Changed
<conceptual summary grouped by feature area>

## Review This First
1. <file or area> - <reason>
2. <file or area> - <reason>

## Architecture and Behavior Impact
<changed boundaries, public interfaces, runtime flows, data/state changes>

## Intent Coverage
- <requirement>: <implemented/partial/missing> via <files/tests>

## Risk Map
- High: <items>
- Medium: <items>
- Low: <items>

## Verification Evidence
- <command>: <passed/failed/skipped> <summary>

## Agent Provenance and Assumptions
<agent/runtime, assumptions, dissent, skipped checks>

## Human Review Checklist
- [ ] <semantic checkpoint>
- [ ] <semantic checkpoint>

## Not Changed / Deferred
<explicit boundaries>

## Raw Artifact Links
<paths to JSON, diff index, proof, logs>
```

### 8.4 Human review checklist examples

CES should generate contextual checkpoints such as:

- Does this change introduce a new filesystem write path?
- Can retries double-send or double-write?
- Is user-controlled input passed into subprocesses or shell commands?
- Are generated paths normalized and contained under the project root?
- Is prompt-injected repository text treated as data, not instructions?
- Does the CLI behavior match existing user-facing conventions?
- Are tests proving the new behavior rather than only implementation details?
- Are failed or skipped verification commands acceptable before approval?

---

## 9. Functional Requirements

### 9.1 Artifact generation

**FR-1:** CES shall generate a Review Brief Markdown artifact for a completed build or local diff.

**FR-2:** CES shall generate a machine-readable risk map.

**FR-3:** CES shall generate an intent coverage map when source intent, execution contract, PRD, issue, manifest, or story metadata is available.

**FR-4:** CES shall generate a review path ordered by risk and conceptual dependency, not file path.

**FR-5:** CES shall generate an agent provenance artifact when CES execution metadata is available.

**FR-6:** CES shall generate a diff index containing changed files, statuses, line counts, and classified file roles.

**FR-7:** CES shall generate a verification summary from available CES verification records and optionally from recent command evidence.

**FR-8:** CES shall write artifacts only under CES-owned paths and must reject unsafe symlinked `.ces` or review artifact paths.

### 9.2 Diff and file classification

**FR-9:** CES shall classify changed files into conceptual groups such as CLI, runtime, execution, harness, sensors, persistence, docs, tests, CI, packaging, security, and unknown.

**FR-10:** CES shall identify high-risk file types and paths using deterministic heuristics.

**FR-11:** CES shall detect broad cross-cutting changes and surface them as review risk.

**FR-12:** CES shall identify generated or lockfile-like artifacts and avoid over-weighting them as source risk unless they affect packaging, dependency, or release safety.

**FR-13:** CES shall include deleted, renamed, and newly added files in the review artifacts.

### 9.3 Intent coverage

**FR-14:** CES shall derive requirement items from the execution contract, spec, manifest, story, PRD, or issue when available.

**FR-15:** CES shall map requirement items to changed files using deterministic signals first: story IDs, task IDs, file paths, symbols, headings, test names, and manifest links.

**FR-16:** CES may use LLM-assisted summarization for narrative text, but core coverage status must be grounded in available artifacts and clearly marked when inferred.

**FR-17:** CES shall mark ambiguous coverage as unknown or partial rather than hallucinating completeness.

**FR-18:** CES shall distinguish intentionally deferred scope from missing implementation when that information exists in the execution contract, plan, or build notes.

### 9.4 Risk ranking

**FR-19:** CES shall compute a risk score for each changed file and conceptual area.

**FR-20:** Risk scoring shall consider path, file role, change size, operation type, verification status, source patterns, and CES-specific safety surfaces.

**FR-21:** CES shall surface the top review priorities with reasons.

**FR-22:** CES shall produce semantic checkpoints based on detected risk categories.

**FR-23:** CES shall downgrade risk only with evidence, such as targeted tests, proof records, or known non-runtime docs-only changes.

### 9.5 Verification integration

**FR-24:** CES shall include verification commands, statuses, durations, and output summaries when available.

**FR-25:** CES shall clearly label checks as passed, failed, skipped, not run, or unknown.

**FR-26:** CES shall never claim verification passed unless CES has fresh evidence.

**FR-27:** CES shall link verification evidence to intent coverage items where possible.

**FR-28:** CES shall surface failed or skipped safety-relevant checks in the Bottom Line and Risk Map.

### 9.6 GitHub integration

**FR-29:** CES shall support generating a GitHub PR comment body from the Review Brief.

**FR-30:** CES shall support `--dry-run` for GitHub comment generation.

**FR-31:** CES shall require explicit confirmation or an explicit non-interactive approval flag before posting a GitHub comment.

**FR-32:** CES shall avoid posting secrets, raw tokens, private IDs, or excessive logs in PR comments.

**FR-33:** CES shall support updating an existing CES review comment where feasible, rather than spamming repeated comments.

### 9.7 Regeneration and history

**FR-34:** CES shall allow listing historical review artifact bundles.

**FR-35:** CES shall record artifact metadata including review ID, timestamp, repo root, base ref, head ref, diff fingerprint, CES build ID when available, and schema versions.

**FR-36:** CES shall warn when a review artifact is stale relative to the current working tree or HEAD.

**FR-37:** CES shall support regenerating artifacts after additional commits or verification runs.

### 9.8 Approval integration

**FR-38:** CES proof output shall reference the latest relevant semantic review artifact.

**FR-39:** CES approval flow shall warn when no current semantic review artifact exists for the diff under approval.

**FR-40:** CES approval records should include the review artifact ID used during the approval decision.

---

## 10. Non-Functional Requirements

### 10.1 Safety

- All artifact writes must be confined to CES-owned local paths.
- Symlinked `.ces`, `.ces/reviews`, or artifact files must be rejected before writing.
- Review artifacts must redact or avoid secret-shaped values.
- Repository-derived content must be treated as untrusted data.
- LLM-generated commentary must never override deterministic evidence.

### 10.2 Determinism

- Diff indexing, file classification, risk scoring, artifact paths, and schema validation should be deterministic.
- LLM assistance, if used, should be optional and clearly labeled.
- Tests should not depend on exact full narrative snapshots where ranking or prose can change.

### 10.3 Local-first behavior

- The feature must work without network access.
- GitHub posting must be optional.
- Local Markdown and JSON artifacts are the canonical output.

### 10.4 Performance

- Review generation for typical PR-sized diffs should complete quickly enough to run after every CES build.
- Large diffs should degrade gracefully with truncation, caps, and clear warnings.
- Binary files and large generated files should be summarized, not fully read.

### 10.5 Usability

- CLI output should be concise and immediately actionable.
- The Review Brief should be readable on mobile and in GitHub Markdown.
- The review path should be short enough to guide attention, not become another dashboard.

### 10.6 Compatibility

- Support Python 3.12+.
- Follow existing CES Typer/Rich CLI conventions.
- Use existing CES base models, artifact/state path utilities, and verification/proof services where available.
- Preserve current `--from-scratch` public greenfield language. Do not reintroduce hidden legacy naming in user-facing docs.

---

## 11. Proposed Architecture

### 11.1 New package structure

Proposed implementation modules:

```text
src/ces/review/
  __init__.py
  models.py
  diff_index.py
  file_classifier.py
  risk.py
  intent_coverage.py
  verification.py
  provenance.py
  renderer.py
  artifacts.py
  github_comment.py
  service.py

src/ces/cli/review_cmd.py
```

### 11.2 Core service

Create a `SemanticReviewService` responsible for orchestration:

```python
class SemanticReviewService:
    def generate(
        self,
        repo_root: Path,
        base_ref: str | None,
        head_ref: str | None,
        build_id: str | None,
        output_dir: Path | None,
        options: ReviewGenerationOptions,
    ) -> ReviewArtifactBundle:
        ...
```

Responsibilities:

1. Resolve repo and diff context.
2. Load CES build metadata when available.
3. Build diff index.
4. Classify files and conceptual areas.
5. Score risks.
6. Build intent coverage.
7. Load verification and proof evidence.
8. Load provenance and assumptions.
9. Render Markdown and JSON artifacts.
10. Persist artifacts safely.

### 11.3 Data models

Use `CESBaseModel` / Pydantic v2 models.

Suggested models:

```text
ReviewArtifactBundle
ReviewMetadata
DiffIndex
ChangedFile
ConceptualArea
RiskMap
RiskItem
RiskSignal
IntentCoverageMap
IntentCoverageItem
ReviewPath
ReviewPathStep
VerificationSummary
VerificationCommandResult
AgentProvenance
ReviewBrief
GithubReviewComment
```

Each model should include a `schema_version` where appropriate.

### 11.4 Artifact ownership and paths

Artifact writes should use existing CES state/path safety helpers where possible.

Proposed path pattern:

```text
<repo>/.ces/reviews/<YYYYMMDD-HHMMSS>-<short-head-or-fingerprint>/
```

If current CES policy places generated artifacts elsewhere, adapt to the canonical CES-owned local state location, but preserve the concept of review artifact bundles.

### 11.5 Diff indexing

`diff_index.py` should produce a compact, structured representation:

- base ref
- head ref
- merge base if relevant
- changed files
- status: added, modified, deleted, renamed, copied, unknown
- additions and deletions
- binary flag
- extension
- file size where safe
- patch availability
- top-level directory
- detected language or role
- test/doc/config/source classification

Use Git plumbing where available. Avoid shell injection by passing arguments as lists if using subprocess helpers.

### 11.6 File classification

Initial deterministic classification can use:

- path segments
- file names
- extensions
- known CES directories
- test path patterns
- workflow/config filenames
- source imports where cheap and safe

Classification should be explicit and explainable. Unknown is acceptable.

### 11.7 Risk scoring

Risk scoring should be transparent. Each score should include signals rather than only a numeric value.

Example risk signals:

```json
{
  "kind": "subprocess_execution",
  "severity": "high",
  "reason": "Changed file is under src/ces/execution and contains subprocess adapter logic"
}
```

Suggested risk categories:

- security
- data_loss
- filesystem_boundary
- subprocess
- network
- external_side_effect
- persistence
- migration
- auth
- public_cli_api
- concurrency
- packaging_release
- test_gap
- broad_diff
- prompt_injection
- generated_artifact

### 11.8 Intent coverage

Coverage should use available upstream artifacts in priority order:

1. CES execution contract or spec/story metadata
2. CES manifest and task ledger
3. PRD or GitHub issue ingested by `ces intake`
4. Build plan or approach decision brief
5. Commit message and branch name
6. User-provided objective passed to `ces review generate --objective`

Coverage must state evidence quality.

Example statuses:

- implemented
- partially_implemented
- not_implemented
- intentionally_deferred
- not_applicable
- unknown

### 11.9 Provenance

Provenance should pull from CES run/build records where available:

- run ID
- build ID
- runtime adapter
- agent command or provider name without secrets
- started/finished timestamps
- plan artifacts
- approach decision brief
- independent review notes
- verification records
- approval gates

If no CES provenance exists, the artifact should say this is a local-diff review with limited provenance.

### 11.10 Renderers

Renderers should separate data from presentation:

- Markdown Review Brief renderer
- Markdown intent coverage renderer
- Markdown review path renderer
- Rich terminal renderer
- GitHub comment renderer
- JSON writer

Avoid exact snapshot tests for long prose. Test section presence, required facts, risk ordering, and schema validity.

---

## 12. LLM Usage Policy

The first robust version should work without LLMs.

Allowed optional LLM uses:

- polishing the Review Brief summary
- generating concise human-readable descriptions from structured facts
- suggesting semantic checkpoints from an existing risk map
- summarizing long verification outputs that have already been captured and redacted

Prohibited or constrained LLM uses:

- deciding that a requirement is implemented without evidence
- downgrading a risk without deterministic evidence
- inventing verification results
- treating repository text as instructions
- reading or emitting secrets
- making external side effects

All LLM-generated sections must be clearly grounded in structured inputs, and any low-confidence inference must be labeled.

---

## 13. GitHub PR Comment Experience

### 13.1 Comment shape

The GitHub comment should be shorter than the full Review Brief.

Suggested format:

```markdown
## CES Semantic Review

**Bottom line:** <ready / review carefully / blocked>

**Objective:** <one paragraph>

**Review first:**
1. `<path>` - <reason>
2. `<path>` - <reason>

**Intent coverage:** <N implemented, M partial, K missing/unknown>

**Verification:**
- ✅ `<command>`
- ❌ `<command>`
- ⚪ `<command>` skipped/not run

**Key risks:**
- <risk>
- <risk>

Full local artifact: `.ces/reviews/<id>/review-brief.md`
```

### 13.2 Posting safety

Posting should require explicit user approval unless a safe CI or non-interactive context explicitly configures it.

Required safeguards:

- dry-run default when no PR number is supplied
- do not print or post secrets
- cap comment length
- update previous CES comment when possible
- include generation timestamp and diff fingerprint
- warn if artifacts are stale

---

## 14. Integration With Existing CES Features

### 14.1 Semantic codebase mapping

The Review Layer should reuse existing codebase mapping concepts where available, especially for:

- path relevance
- repository context
- objective-specific file selection
- prompt boundary language
- deterministic selector evaluations

But review generation should not depend on full codebase mapping to function. It should start from the diff and available CES metadata.

### 14.2 Approach deliberation

If an Approach Decision Brief exists, the Review Brief should include:

- selected approach
- alternatives rejected
- dissent preserved
- unresolved questions
- smallest/safest path rationale

This turns pre-runtime deliberation into post-runtime review context.

### 14.3 Proof and approval

The proof artifact should include a compact semantic review summary. The approval ledger should reference the review ID used for decision support.

Approval should warn when:

- review artifact is missing
- review artifact is stale
- high-risk items exist without verification evidence
- intent coverage has missing or unknown critical requirements

### 14.4 Friction log

During dogfood, weak review output should be captured in `docs/friction-log.md`:

- expected review behavior
- actual review behavior
- severity
- proposed fix
- fixed status
- evidence

---

## 15. Implementation Plan

This PRD is intentionally broader than an MVP. Implementation should still be sequential and reviewable.

### Phase 1: Data model and local artifact foundation

Deliverables:

- `src/ces/review/models.py`
- safe artifact path writer
- review ID and metadata model
- CLI skeleton for `ces review generate`, `show`, and `list`
- unit tests for path safety and schema serialization

Acceptance criteria:

- Can create an empty but valid review artifact bundle under a safe CES-owned path.
- Rejects symlinked or escaping artifact paths.
- `ces review list` shows generated artifacts.

### Phase 2: Diff index and file classification

Deliverables:

- Git diff indexer
- changed file model
- file role classifier
- conceptual area grouping
- Markdown section: What Changed
- tests for added, modified, deleted, renamed, binary, docs, tests, source, CI, config

Acceptance criteria:

- `ces review generate --base main --head HEAD` creates a diff index.
- Review Brief groups files by conceptual area.
- Unknown files are handled gracefully.

### Phase 3: Risk map and review path

Deliverables:

- risk scoring engine
- risk signal model
- review path generator
- semantic checkpoint generator
- Markdown sections: Review This First, Risk Map, Human Review Checklist
- tests for subprocess, filesystem, network, external side-effect, CLI/API, persistence, packaging, tests/docs-only

Acceptance criteria:

- High-risk files appear before docs/tests in the review path.
- Each risk item has an explainable signal.
- Docs-only changes are not over-escalated unless other signals exist.

### Phase 4: Intent coverage

Deliverables:

- loaders for execution contract/spec/story/manifest metadata
- coverage mapper
- Markdown and JSON coverage outputs
- CLI support for `--objective` fallback
- tests for implemented, partial, deferred, unknown statuses

Acceptance criteria:

- Review artifacts map requirements to changed files and tests when metadata exists.
- Ambiguous coverage is marked unknown or partial.
- The Review Brief never invents fulfilled requirements without evidence.

### Phase 5: Verification and provenance integration

Deliverables:

- verification summary loader
- proof/build/run metadata integration
- agent provenance artifact
- proof output references latest review artifact
- approval flow warns on missing or stale review artifact
- tests for passed, failed, skipped, not-run verification states

Acceptance criteria:

- Review Brief includes verification evidence from CES records.
- Failed or skipped checks appear in Bottom Line when risk-relevant.
- Approval record can reference the review artifact ID.

### Phase 6: GitHub comment export

Deliverables:

- GitHub comment renderer
- `ces review github-comment --dry-run`
- optional posting flow with explicit confirmation
- update-existing-comment behavior where feasible
- redaction and length caps
- tests with mocked `gh`/API behavior

Acceptance criteria:

- Dry-run produces a concise PR comment body.
- Posting cannot happen accidentally.
- Comment avoids secrets and stale artifacts.

### Phase 7: Review regeneration and stale detection

Deliverables:

- diff fingerprinting
- stale artifact detection
- regeneration command
- artifact history listing with status
- tests for dirty tree, changed HEAD, changed verification evidence

Acceptance criteria:

- CES warns when a Review Brief no longer matches the working tree or HEAD.
- Regeneration produces a new artifact bundle with updated metadata.

### Phase 8: Dogfood, polish, and release hardening

Deliverables:

- Dogfood on CES feature PRs
- update docs and examples
- add scenario matrix coverage
- update friction log
- full CI parity
- installed-wheel smoke test

Acceptance criteria:

- At least one CES-on-CES PR uses the Semantic Review Layer end to end.
- Review artifacts materially reduce review effort.
- All CI and release checks pass.

---

## 16. Testing Strategy

### 16.1 Unit tests

Cover:

- model serialization and schema versions
- safe artifact path handling
- symlink rejection
- diff index parsing
- file classification
- risk scoring signals
- review path ordering
- intent coverage statuses
- verification summary states
- provenance fallback behavior
- Markdown renderer section completeness
- GitHub comment dry-run rendering

### 16.2 Integration tests

Use temporary Git repositories to verify:

- local diff review generation
- base/head diff review generation
- added/modified/deleted/renamed files
- dirty working tree detection
- stale artifact detection
- CES build metadata integration where feasible
- proof and approval references

### 16.3 Golden-ish tests

Avoid brittle full Markdown snapshots. Instead assert:

- required headings exist
- top risk files appear in expected order
- requirement IDs appear with expected statuses
- failed verification appears in Bottom Line
- generated Markdown contains no raw secret-shaped fixtures

### 16.4 Dogfood tests

Dogfood against:

1. A small greenfield project with docs, source, and tests.
2. A brownfield repo with existing CLI/runtime code.
3. CES itself, especially changes touching runtime, filesystem safety, subprocesses, and review/proof paths.

---

## 17. Verification Commands

Use CES repo CI parity from the existing project skill:

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/ces/ --ignore-missing-imports
uv run pytest tests/ -m "not integration" --cov=ces --cov-fail-under=90 --cov-report=term-missing -q -W error
uv run --no-sync vulture src tests --min-confidence 80
uv export --frozen --group ci --format requirements-txt --no-hashes -o /tmp/ces-ci-requirements.txt
uv run pip-audit --strict -r /tmp/ces-ci-requirements.txt
uv build
uvx twine check dist/*
```

For user-facing CLI features, also run an installed-wheel smoke in a fresh Python 3.12+ or 3.13 venv against a throwaway real project.

---

## 18. Acceptance Criteria

The full feature is accepted when:

1. `ces review generate` produces Markdown and JSON review artifacts for a local diff.
2. Review Brief explains objective, conceptual changes, risk map, review path, intent coverage, verification, provenance, and human checkpoints.
3. Files are grouped semantically and review path is risk-first.
4. Intent coverage maps requirements to files/tests/evidence when metadata exists.
5. Verification evidence is included and never fabricated.
6. Provenance is included for CES-generated work and clearly limited for arbitrary local diffs.
7. Artifacts are safely written under CES-owned paths with symlink/root-escape protection.
8. Stale artifact detection works.
9. Proof and approval flows reference review artifacts.
10. GitHub comment export supports dry-run and gated posting.
11. Unit and integration tests cover the critical behavior.
12. CES dogfood confirms the Review Brief improves human review quality.
13. Full CI parity and installed-wheel smoke pass.

---

## 19. Product Copy

### 19.1 Short positioning

```text
CES makes agent-generated code reviewable.
```

### 19.2 Longer positioning

```text
CES turns AI coding output into an engineering review brief: intent, architecture, risks, tests, provenance, and the shortest safe path to human approval.
```

### 19.3 CLI help copy

```text
ces review generate

Generate semantic review artifacts for a CES build or local diff: a human-readable Review Brief, risk-ranked review path, intent coverage map, verification summary, and machine-readable JSON bundle.
```

---

## 20. Risks and Mitigations

### Risk: Review artifacts become verbose dashboards

Mitigation:

- Keep Bottom Line and Review This First short.
- Put details below the fold.
- Use risk-first ordering.
- Avoid vanity metrics.

### Risk: LLM commentary creates false confidence

Mitigation:

- Ground claims in deterministic artifacts.
- Label inferred or unknown coverage.
- Never invent verification.
- Prefer structured facts over prose.

### Risk: Review generation becomes slow or flaky

Mitigation:

- Start from Git diff and CES metadata.
- Cap file reads and patch sizes.
- Summarize large and binary files.
- Make LLM use optional.

### Risk: GitHub comments leak sensitive data

Mitigation:

- Redact secret-shaped values.
- Cap output length.
- Dry-run by default.
- Require explicit confirmation before posting.

### Risk: Risk scoring becomes opaque

Mitigation:

- Store risk signals with reasons.
- Test risk ordering with fixtures.
- Allow unknown rather than overconfident classification.

### Risk: Approval flow becomes too heavy

Mitigation:

- Warn, do not block, unless configured policy requires review artifacts.
- Keep CLI commands composable.
- Let advanced teams enforce stricter policies later.

---

## 21. Open Questions

1. Should `ces review generate` run automatically after every `ces build`, or only suggest the command?
2. Should review artifacts live in `.ces/reviews/` inside the repo or in the existing CES local-state directory for generated state?
3. Should GitHub comment posting be part of core CES or an optional integration module?
4. How much of intent coverage can be deterministic from current execution contract and manifest structures?
5. Should the approval command merely warn on missing/stale review artifacts or enforce a policy gate for high-risk changes?
6. Should Review Briefs be committed to the repository, ignored, or treated as local-only by default?
7. Should CES expose a future `ces review tui` after Markdown artifacts are stable?

---

## 22. Recommended First Implementation PR

Even though this PRD describes the full feature, the first PR should be deliberately narrow and lay the foundation cleanly.

Recommended first PR scope:

```text
Add Semantic Review Layer foundations: models, safe artifact bundles, diff index, file classification, risk-ranked Review Brief, and `ces review generate/show/list` for local diffs.
```

Do not include GitHub posting, approval enforcement, or LLM narrative polish in the first PR.

First PR should still be designed so later phases can add intent coverage, provenance, proof integration, and GitHub comments without rewriting the core models.

---

## 23. Definition of Done for CES Implementation

- New tests are written before or alongside implementation.
- Existing CI parity passes.
- Artifacts are safe under symlink/root-escape scenarios.
- Review Brief is readable and useful on a real CES diff.
- Risk ordering is explainable and tested.
- No external side effects occur without explicit approval.
- Documentation is updated.
- `docs/friction-log.md` records dogfood findings.
- A generated Semantic Review Brief is included in the PR description or attached as evidence.

---

## 24. Final Product Principle

The Semantic Review Layer should optimize for engineering judgment, not automation theater.

It should not say:

```text
Trust the agent.
```

It should say:

```text
Here is exactly what changed, why it matters, how it was verified, where the risk is, and what you should inspect before approving.
```
