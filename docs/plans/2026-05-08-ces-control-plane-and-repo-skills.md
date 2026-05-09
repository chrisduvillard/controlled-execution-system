# CES Control Plane + Repo Skills Improvement Plan

> Status: proposal / implementation plan candidate. No code changes yet.

**Goal:** Make CES clearly better than normal AI coding for real developers by tightening control-plane semantics, reducing greenfield friction, preserving full audit evidence, and adding project-local skill generation/maintenance for greenfield and brownfield repos.

**Why now:** The ReleaseNoteSmith benchmark showed CES works, but its advantage is auditability rather than raw implementation quality. It also exposed a trust issue: triage red due missing sensor artifacts could coexist with `Outcome: ready to ship` and `Merge Validation Passed`.

---

## 1. Product thesis

CES should stop trying to feel like “a better prompt wrapper” and become **the repo-aware control layer for AI coding agents**.

The winning promise:

> “CES turns repo context, product intent, existing behavior, and verification evidence into a controlled agent operating environment.”

That means CES should give developers:

1. **A trustworthy final state** — no ambiguous red/green semantics.
2. **A repo-specific operating manual** — generated and maintained skills/guidance for the runtime.
3. **A complete evidence trail** — full transcript, metrics, tool counts, artifacts, diffs, acceptance mapping.
4. **Low-friction modes** — quick greenfield path when governance can be light, stricter brownfield path when existing behavior matters.
5. **A skill lifecycle** — create, improve, disable, remove, diff, and regenerate repo skills over time.

---

## 2. Key design decision: repo skills are first-class CES artifacts

Chris’s idea is strong. I would make repo skills a core CES primitive, not a side feature.

### Concept

A **CES repo skill** is a project-local instruction package generated from the repo’s product docs, architecture, code, tests, conventions, risks, and known behaviors.

It should live under the governed repo, not the global assistant skill store:

```text
.ces/skills/
  index.json
  active/
    product-context/SKILL.md
    architecture-map/SKILL.md
    testing-and-verification/SKILL.md
    coding-conventions/SKILL.md
    risk-and-boundaries/SKILL.md
    brownfield-behaviors/SKILL.md
    release-process/SKILL.md
  archive/
  drafts/
```

Generated skills should be injected into runtime prompts, referenced in manifests, hashed into evidence packets, and versioned through `.ces/state.db`.

### Why this matters

Normal AI coding repeatedly relearns repo context. CES can win by making repo understanding **persistent, inspectable, and adjustable**.

For greenfield projects, CES can generate skills from PRD/spec/docs before writing code:

- product intent
- non-goals
- acceptance criteria
- target architecture
- quality bar
- testing strategy
- commands and expected outputs

For brownfield projects, CES can scan the codebase and docs to generate:

- architecture map
- critical flows
- existing behavior ledger
- testing commands
- local conventions
- dangerous files/modules
- integration boundaries
- known brittle areas

Then every subsequent build is better grounded.

---

## 3. Proposed CLI surface

### New top-level command group

```bash
ces skills --help
```

### Discovery / generation

```bash
ces skills init
ces skills generate --greenfield --from docs/PRD.md --from docs/architecture.md
ces skills generate --brownfield --scan-code --from docs/PRD.md --from README.md
ces skills refresh
```

### Inspection

```bash
ces skills list
ces skills show product-context
ces skills diff
ces skills explain testing-and-verification
```

### Maintenance

```bash
ces skills improve testing-and-verification "Add uv test command and CI parity note"
ces skills add "deployment-process" --from docs/RELEASE.md
ces skills disable brownfield-behaviors
ces skills remove obsolete-skill --archive
ces skills rename old-name new-name
```

### Runtime integration

```bash
ces build "Add export command" --use-skills auto
ces build "Refactor billing" --use-skills brownfield-behaviors,testing-and-verification
ces build "Spike new UI" --no-skills
```

Default: `--use-skills auto`.

---

## 4. Skill artifact format

A repo skill should be similar to existing agent skills, but with CES metadata and lifecycle data.

```markdown
---
name: testing-and-verification
type: ces-repo-skill
version: 1
scope: project
source_hashes:
  - path: pyproject.toml
    sha256: ...
  - path: docs/CI.md
    sha256: ...
confidence: medium
last_refreshed: 2026-05-08T00:00:00Z
status: active
applies_when:
  - modifying Python code
  - changing CLI behavior
verification_commands:
  - uv run pytest
  - uv run ruff check
---

# Testing and Verification

## Use when
...

## Required commands
...

## Pitfalls
...

## Evidence expected
...
```

Skills should be deliberately compact. They are operating instructions, not a document dump.

---

## 5. Greenfield skill flow

### Problem

Greenfield CES currently asks for intent/constraints/acceptance, then runs the agent. It does not turn the PRD/spec into durable project guidance before code is created.

### Proposed flow

```text
PRD / prompt / docs
  ↓
Skill Generator
  ↓
Draft skills
  ↓
User review / auto-approve in --yes mode
  ↓
Build manifest references skill pack hash
  ↓
Runtime receives compact skill pack
  ↓
Completion evidence records which skills were used
```

### Greenfield skill pack

Minimum generated skills:

1. `product-context` — product goal, users, non-goals, UX constraints.
2. `architecture-target` — expected stack, module boundaries, design constraints.
3. `acceptance-and-quality` — acceptance criteria, done definition, anti-slop rules.
4. `testing-and-verification` — test strategy and exact commands.
5. `runtime-boundaries` — allowed side effects, forbidden files, security boundaries.

### Example command

```bash
ces build --greenfield --from-prd docs/PRD.md "Build the MVP"
```

Under the hood CES should:

1. generate/refresh skills,
2. show a short skill summary,
3. create manifest,
4. run with skill pack injected,
5. record skill hashes in evidence.

---

## 6. Brownfield skill flow

### Problem

Brownfield work is where CES should shine, but brownfield context is still scattered across scan results, legacy behaviors, critical flows, docs, and the user’s prompt.

### Proposed flow

```text
Codebase + docs + tests + PRD + prior CES runs
  ↓
Brownfield Scanner
  ↓
Repo Skill Synthesizer
  ↓
Behavior review / disposition
  ↓
Active brownfield skill pack
  ↓
Build / verify / update skills after completion
```

### Brownfield skill pack

Minimum generated skills:

1. `architecture-map` — modules, entrypoints, data flow, dependencies.
2. `critical-flows` — flows that must not break and how to test them.
3. `existing-behavior-ledger` — promoted legacy behaviors and dispositions.
4. `coding-conventions` — style, patterns, naming, error handling.
5. `testing-and-verification` — exact local commands, CI parity, fixture patterns.
6. `risk-and-boundaries` — risky modules, migrations, security constraints.
7. `change-playbooks` — how to modify common subsystems safely.

### Brownfield scan inputs

- file tree and language mix
- package manifests
- tests and CI workflows
- README/docs/PRD/design docs
- existing CES state: manifests, evidence, approvals, legacy behaviors
- git history summaries
- configured source-of-truth docs

### Brownfield output should be reviewable

CES should never silently trust generated brownfield skills. It should show:

- “high confidence” facts with sources,
- “inferred” facts requiring review,
- stale facts where source files changed,
- conflicting docs/code observations.

---

## 7. Skill lifecycle and governance

Repo skills must not become stale hidden prompt sludge.

### Store lifecycle state

Add skill tables to `.ces/state.db`:

- `repo_skills`
  - `skill_id`
  - `name`
  - `status`: draft / active / disabled / archived
  - `version`
  - `content_hash`
  - `source_hashes`
  - `confidence`
  - `created_at`, `updated_at`
- `repo_skill_events`
  - created, refreshed, improved, disabled, archived, used_in_manifest
- `repo_skill_sources`
  - source path, hash, extraction notes

### Staleness model

A skill becomes stale when:

- source docs changed,
- referenced files disappeared,
- verification command fails repeatedly,
- runtime reports contradiction,
- user marks it wrong,
- N days or N commits elapsed since refresh.

Commands:

```bash
ces skills doctor
ces skills refresh --stale-only
ces skills prune --dry-run
```

### Post-run feedback loop

After every build, CES should ask or infer:

- Did the runtime discover new repo facts?
- Did any skill mislead it?
- Did verification reveal missing commands?
- Should a behavior be promoted into `existing-behavior-ledger`?

Then:

```bash
ces skills improve --from-run latest
```

This is the part that can make CES compound in quality over time.

---

## 8. Fix plan for CES core issues

### Phase 0 — Define control-plane semantics

**Objective:** Remove ambiguity around red/green output.

Tasks:

1. Define statuses:
   - `code_completed`: runtime finished and changed files.
   - `acceptance_verified`: independent verification passed.
   - `governance_clear`: no blocking findings.
   - `ready_to_ship`: all required gates passed.
   - `needs_review`: advisory or blocking findings remain.
2. Split triage colors:
   - `blocking_red`
   - `advisory_red`
   - `yellow`
   - `green`
3. Update final `ces build` output hierarchy:
   - Code result
   - Acceptance result
   - Governance result
   - Blocking findings
   - Advisory findings
   - Next command
4. Add regression tests for the benchmark failure mode:
   - missing coverage artifacts must not print misleading `ready to ship` unless they are non-required advisory findings.

Likely files:

- `src/ces/cli/_builder_flow.py`
- `src/ces/cli/run_cmd.py`
- `src/ces/harness/models/triage_result.py`
- `src/ces/harness/services/risk_sensor_policy.py`
- `src/ces/control/services/merge_controller.py`
- tests under `tests/unit` and `tests/integration`

### Phase 1 — Make sensor policy project-aware

**Objective:** Stop treating unavailable/unrequested tools as universal gates.

Tasks:

1. Add project detector output for available tools:
   - pytest
   - coverage
   - ruff
   - mypy
   - npm/vitest/etc.
2. Generate a `VerificationProfile`:
   - required commands from manifest acceptance
   - inferred commands from project files
   - optional advisory sensors
3. Sensor result must include `required: true/false` and `why_required`.
4. Missing artifacts are blocking only if required by the manifest/profile.
5. Show “not configured” distinctly from “failed”.

Likely files:

- `src/ces/verification/project_detector.py`
- `src/ces/verification/build_contract.py`
- `src/ces/harness/sensors/completion_gate.py`
- `src/ces/harness/sensors/test_coverage.py`
- `src/ces/harness/services/risk_sensor_policy.py`

### Phase 2 — Capture full runtime metrics and transcript

**Objective:** Make CES benchmarkable without spelunking in Codex session files.

Tasks:

1. Extend runtime adapter result with:
   - duration
   - token usage if available
   - model/provider
   - tool call count
   - patch count
   - command count
   - failure/correction count
   - full transcript path
   - external session pointer/path if applicable
2. Store metrics in `runtime_executions` or a new `runtime_metrics` table.
3. Preserve full transcript or a hashed pointer to the runtime’s native session log.
4. Export metrics in `ces report builder` and benchmark scorecards.

Likely files:

- `src/ces/execution/runtimes/adapters.py`
- `src/ces/execution/agent_runner.py`
- `src/ces/local_store/schema.py`
- `src/ces/local_store/records.py`
- `src/ces/cli/_builder_report.py`

### Phase 3 — Add repo skill subsystem

**Objective:** Make generated/maintained project-local skills a first-class CES primitive.

New module:

```text
src/ces/skills/
  __init__.py
  models.py
  generator.py
  scanner.py
  renderer.py
  lifecycle.py
  injection.py
  staleness.py
```

New CLI:

```text
src/ces/cli/skills_cmd.py
```

Core services:

1. `RepoContextScanner`
   - reads docs, code tree, tests, CI, package files, CES history.
2. `SkillSynthesizer`
   - creates compact skill drafts from source context.
3. `SkillRenderer`
   - writes `SKILL.md` format with CES metadata.
4. `SkillLifecycleService`
   - active/disabled/archive/version/staleness operations.
5. `SkillInjectionService`
   - selects active skills for a manifest/runtime prompt.
6. `SkillEvidenceService`
   - records used skill hashes in evidence packets.

### Phase 4 — Integrate skills into build

**Objective:** Skills improve actual runs, not just sit on disk.

Tasks:

1. Add `--use-skills auto|none|all|name,name` to `ces build` and `ces execute`.
2. Add `--generate-skills` and `--refresh-skills` options.
3. Manifest includes:
   - skill names
   - skill hashes
   - skill confidence/staleness state
4. Runtime prompt includes selected skill content in a compact “repo guidance pack”.
5. Completion claim must list skills used and whether any were contradicted.

### Phase 5 — Brownfield excellence

**Objective:** Make CES clearly better than direct Codex for real repos.

Tasks:

1. Add `ces skills generate --brownfield --scan-code`.
2. Feed brownfield review candidates into `existing-behavior-ledger` skill.
3. Link critical flows to verification commands.
4. When a change touches risky areas, automatically include relevant skill sections.
5. After build, update skill facts from completed evidence.

### Phase 6 — Better benchmark harness

**Objective:** Measure CES value objectively over time.

Tasks:

1. Add realistic benchmark scenarios beyond fake-runtime python-cli:
   - greenfield CLI
   - brownfield bugfix
   - brownfield refactor preserving behavior
   - web app feature
   - docs/config-heavy repo
2. Compare CES vs direct runtime under identical specs.
3. Store metrics:
   - completion rate
   - time
   - token usage
   - tool calls
   - corrections
   - independent verification pass rate
   - audit completeness
   - friction score
4. Add `ces benchmark compare --runtime codex --scenario releasenotesmith`.

---

## 9. MVP cut

Do not build the whole vision first. The high-leverage MVP is:

### PR 1 — Fix trust semantics

- New status vocabulary.
- Final output cannot say ready-to-ship when blocking findings exist.
- Sensor findings are clearly advisory vs blocking.
- Regression tests from ReleaseNoteSmith benchmark.

### PR 2 — Project-aware verification profile

- Required vs optional sensors.
- Missing unconfigured artifacts become advisory/not-configured, not hard red.
- `ces why` explains exactly why a gate is blocking or advisory.

### PR 3 — Runtime metrics capture

- Token/tool/duration metrics stored in evidence/report when available.
- Full transcript pointer/hash preserved.

### PR 4 — Repo skills MVP

- `ces skills generate --greenfield --from <doc>`
- `ces skills list/show/disable/remove/improve`
- `.ces/skills/active/*.md`
- skill hashes injected into manifest/evidence
- manual skill content only or simple deterministic synthesis first; no complex AI scanner yet.

### PR 5 — Brownfield skills MVP

- `ces skills generate --brownfield --scan-code --from <doc>`
- generate architecture/testing/conventions/critical-flow drafts
- mark inferred facts with confidence and sources
- user can activate or edit.

---

## 10. Design guardrails

1. **Skills must be compact.** Repo skills should reduce context, not create another document dump.
2. **Skills must be sourced.** Every factual statement should have a source path or be marked inferred.
3. **Skills must be mutable.** The user needs commands to improve, remove, disable, and regenerate them.
4. **Skills must be auditable.** Every build records the exact skill hashes used.
5. **Skills must not override explicit user instructions.** Runtime prompt order: user request > manifest > active skill pack > inferred suggestions.
6. **Skills must not hide risk.** Stale/low-confidence skills should be visibly flagged.
7. **Greenfield stays light.** Do not force brownfield-grade ceremony on empty repos.
8. **Brownfield gets serious.** Existing behavior and critical flows become first-class context.

---

## 11. Open questions before implementation

1. Should repo skills be stored only under `.ces/skills`, or should CES optionally export them to `.agents/skills` / `.codex/skills` for direct runtime use outside CES?
2. Should `ces skills improve` invoke an AI runtime, or start deterministic/manual-only for safety?
3. Should skills be committed to git as project docs, or stay untracked under `.ces` by default?
4. Should greenfield builds auto-generate skills by default, or only when `--from-prd` / `--generate-skills` is used?
5. Should brownfield skill generation require user review before any generated skill becomes active?

My recommendation:

- Store under `.ces/skills` by default, untracked.
- Allow `ces skills export --to .agents/skills` later.
- Make greenfield skills opt-in initially.
- Make brownfield generated skills draft-only until reviewed.
- Use deterministic/manual improve first, then add AI-assisted `--runtime` improvement after the lifecycle is safe.

---

## 12. Success criteria

CES is materially improved when:

1. A red/green governance state is unambiguous to a new user.
2. Missing optional artifacts do not create misleading “red but merged” outcomes.
3. Builder reports include runtime duration, token metrics, tool counts, and full transcript pointers.
4. A user can run `ces skills generate`, inspect skills, improve them, disable bad ones, and use them in a build.
5. Brownfield builds automatically include repo-specific behavior/testing/convention guidance.
6. A repeat benchmark shows CES is slower only when it buys visible audit/control value, and faster/better on repeated brownfield work because repo skills compound.
