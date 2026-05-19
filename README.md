<div align="center">

# Controlled Execution System

[![CI](https://github.com/chrisduvillard/controlled-execution-system/actions/workflows/ci.yml/badge.svg)](https://github.com/chrisduvillard/controlled-execution-system/actions/workflows/ci.yml)
[![Publish](https://github.com/chrisduvillard/controlled-execution-system/actions/workflows/publish.yml/badge.svg)](https://github.com/chrisduvillard/controlled-execution-system/actions/workflows/publish.yml)
[![PyPI](https://img.shields.io/pypi/v/controlled-execution-system.svg)](https://pypi.org/project/controlled-execution-system/)
[![Python](https://img.shields.io/pypi/pyversions/controlled-execution-system.svg)](https://pypi.org/project/controlled-execution-system/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/chrisduvillard/controlled-execution-system/blob/master/LICENSE)

<img src="https://raw.githubusercontent.com/chrisduvillard/controlled-execution-system/master/docs/assets/ces-avatar.png" alt="Controlled Execution System project avatar" width="300">

**Local-first governance for AI coding agents.**

Turn an intent into a bounded manifest, execute it through Codex CLI or Claude Code,<br>
collect evidence, review the result, and make approval explicit.

[5-Minute Quickstart](https://github.com/chrisduvillard/controlled-execution-system/blob/master/docs/Quickstart.md) ·
[Getting Started](https://github.com/chrisduvillard/controlled-execution-system/blob/master/docs/Getting_Started.md) ·
[Positioning](https://github.com/chrisduvillard/controlled-execution-system/blob/master/docs/Positioning.md) ·
[Operator Playbook](https://github.com/chrisduvillard/controlled-execution-system/blob/master/docs/Operator_Playbook.md) ·
[Quick Reference](https://github.com/chrisduvillard/controlled-execution-system/blob/master/docs/Quick_Reference_Card.md) ·
[Verification Profile](https://github.com/chrisduvillard/controlled-execution-system/blob/master/docs/Verification_Profile.md) ·
[Semantic Codebase Mapping](https://github.com/chrisduvillard/controlled-execution-system/blob/master/docs/Semantic_Codebase_Mapping.md) ·
[Changelog](https://github.com/chrisduvillard/controlled-execution-system/blob/master/CHANGELOG.md)

<br>

<a href="https://raw.githubusercontent.com/chrisduvillard/controlled-execution-system/master/docs/assets/ces-demo.mp4">
  <img src="https://raw.githubusercontent.com/chrisduvillard/controlled-execution-system/master/docs/assets/ces-demo.gif" alt="20-second CES explainer demo" width="760">
</a>

<sub>Click the animation to open the MP4.</sub>

</div>

---

## What CES is

CES is a safety and evidence layer around local AI coding tools.

More precisely, CES is the accountability layer for AI execution: it turns intent into an execution contract, runs a local coding agent under explicit governance, collects verification evidence, generates proof, and makes approval explicit.

You describe the change. CES turns that request into a governed work order, runs the work through a supported local runtime, checks what changed, asks for evidence, records the audit trail, and helps you decide whether to approve the result.

CES helps builders produce better, safer, more verifiable work with AI agents — especially on complex software projects — by enforcing intent clarity, risk gating, and evidence-backed completion.

It is deliberately local and operator-first: project state lives under `.ces/`; runtime credentials stay with your installed `codex` or `claude` CLI; final judgment stays with you.

### The strong promise

CES can credibly improve AI-assisted work by making the operating loop stricter:

1. **Better task definition** — users are less likely to start from vague prompts.
2. **Fewer unsafe or accidental actions** — high-risk actions are blocked or require explicit consent.
3. **More reproducible work** — intent, decisions, evidence, and outputs are recorded.
4. **Higher verification discipline** — "done" means backed by checks, not vibes.
5. **Better operator leverage** — skilled users can delegate more safely and consistently.
6. **Reduced hallucinated completion** — CES creates pressure to prove rather than merely assert.
7. **More focused brownfield context** — CES maps the repo, selects relevant areas for the objective, and injects stable invariants before runtime execution.

| CES is | CES is not |
|---|---|
| A local CLI for governed AI-assisted software delivery | A hosted control plane |
| A manifest, evidence, review, recovery, and approval workflow | A replacement for source control, CI, or human review |
| SQLite-backed project state under `.ces/` | A required Postgres/Redis service for normal local use |
| A wrapper around Codex CLI and Claude Code | A runtime credential manager or universal sandbox |

> [!IMPORTANT]
> CES is not a sandbox. It governs the workflow around local runtime execution, records evidence, and enforces approval gates. Runtime sandboxing, credentials, repo protections, deployments, and final operator responsibility remain outside CES.

### Why trust this release?

CES is built and shipped through its own public control surfaces: CI runs the local-first test suite, package build, metadata checks, dependency audit, lint, formatting, and typecheck gates; release publishing adds installed-CLI smoke coverage before PyPI publication. The repository also carries a CES dogfood gauntlet so the project can review its own changes instead of treating governance as a brochure claim.

The boundary is intentionally narrow. CES is not a hosted control plane, not a substitute for source control or CI, and not a substitute for the runtime's own credentials, authentication, or sandboxing. It gives operators a local evidence trail: `ces:completion` claims, verification artifacts, audit entries, workspace delta inspection before approval, and a Simplicity Guard that pushes agents toward the smallest boring solution instead of unnecessary frameworks, services, dependencies, or rewrites.

---

## Quick start

### 1. Install CES

| Need | Notes |
|---|---|
| Python | 3.12 or 3.13 |
| Package tool | [`uv`](https://docs.astral.sh/uv/) |
| Local runtime | Codex CLI or Claude Code installed, authenticated, and on `PATH` |

```bash
uv tool install controlled-execution-system
uv tool update-shell
ces --help
ces doctor
```

If your ambient `python3` is Python 3.11, direct `pip install controlled-execution-system` may fail with `No matching distribution` before CES starts because the package requires Python 3.12 or 3.13. Ask `uv` for a supported interpreter explicitly:

```bash
uv tool install --python 3.13 controlled-execution-system
```

Run `ces` with no arguments to print the Start Here guide. Use `ces --help` when you want the full command reference.

CES governs a local coding runtime; it does not bundle one. Before the first mutating `ces build`, make sure one runtime is installed and authenticated:

```bash
codex --version   # for Codex CLI
claude --version  # for Claude Code
ces doctor --runtime-safety
```

Prefer Claude Code when you need enforceable tool allowlists. Prefer Codex when you accept the sandbox/side-effect boundary and will explicitly pass `--accept-runtime-side-effects` after reading the notice.

### 2. Choose your path

| Situation | Start with |
|---|---|
| I have an idea and no folder yet | `ces create "..."` |
| I am inside an empty folder | `ces start` or `ces build --from-scratch "..."` |
| I have an existing repo | `ces mri`, then `ces next` |
| I need a safe prompt before running an agent | `ces next-prompt "..."` |
| I already have a PRD or GitHub issue | `ces intake ...` |

`ces create`, `ces start`, and `ces ship` are read-only front doors: they do not launch a runtime, create `.ces/`, or mutate files.


## Beginner journey (10-minute map)

If you are new to CES, use this exact order to avoid the most common mistakes:

1. **Install + preflight**: `ces --help` then `ces doctor`
2. **Pick project mode**:
   - New app/empty folder -> **greenfield**
   - Existing repo with behavior to preserve -> **brownfield**
3. **Stay read-only first**:
   - Greenfield: `ces create "..."`
   - Brownfield: `ces mri`, `ces next`, `ces next-prompt "..."`
4. **Run exactly one governed implementation command**:
   - Greenfield: `ces build --from-scratch "..."`
   - Brownfield: `ces build "..."`
5. **Require proof before approval**: `ces verify` -> `ces proof` -> `ces approve --yes` (only if recommendation is `safe-to-review`)

### Greenfield vs brownfield quick decision

| If this is true | Use | Avoid |
|---|---|---|
| I am creating a brand-new project skeleton | `ces build --from-scratch "..."` | Plain `ces build` if you expect full project generation |
| I am changing an existing repository | Plain `ces build "..."` | `--from-scratch` unless intentionally rewriting |
| I only want a plan/prompt first | `ces create`, `ces start`, `ces ship`, `ces next-prompt` | Running `ces build` immediately |

### New operator pitfalls (and fixes)

- **Pitfall:** Treating `ces create/start/ship` as mutating commands.  
  **Fix:** They are read-only front doors; they print next steps only.
- **Pitfall:** Using `--from-scratch` in a brownfield repo.  
  **Fix:** Use plain `ces build` after `ces mri` + `ces next-prompt`.
- **Pitfall:** Approving on agent claims instead of evidence.  
  **Fix:** Require successful `ces verify` and `ces proof` first.

## Greenfield project: create a new project from scratch

Use this when you have an idea but no existing app yet. Start with a read-only plan, then run the governed build inside the new project folder.

```bash
ces create "Create a small task tracker app with add/list/complete tasks, tests, and a README" --name "Task Tracker"
mkdir -p task-tracker && cd task-tracker
ces ship "Create a small task tracker app with add/list/complete tasks, tests, and a README"
ces build --from-scratch "Create a small task tracker app with add/list/complete tasks, tests, and a README"
ces verify
ces proof
```

If you use Codex, `ces build` stops before subprocess launch unless you explicitly accept the runtime boundary. After reading the prompt, rerun with:

```bash
ces build --from-scratch "Create a small task tracker app with add/list/complete tasks, tests, and a README" --accept-runtime-side-effects
```

Expected `ces create` output includes a target directory and a copy-paste sequence with `mkdir`, `ces ship`, `ces build --from-scratch`, `ces verify`, and `ces proof`.

You know the greenfield path worked when `.ces/` exists in the new project, app files were created, `ces verify` passed or reported concrete missing evidence, and `ces proof` reports `proven` with a `safe-to-review` recommendation.

## Brownfield project: apply CES to an existing project

Use this when files already exist and behavior must not silently break. Start read-only, turn the objective into a bounded contract, then run plain `ces build`.

```bash
cd path/to/existing-repo
ces mri
ces next
ces next-prompt "Add invoice notes to CSV exports" \
  --acceptance "CSV exports include invoice notes when present." \
  --must-not-break "Existing CSV export columns and import compatibility."
ces build "Add invoice notes to CSV exports"
ces verify
ces proof
```

You know the brownfield path worked when CES identifies the repo as brownfield, the contract/proof includes must-not-break behavior, changed files stay inside the declared scope, verification evidence is fresh, and `ces proof` reports `proven` or names the exact blocker.

For non-interactive brownfield automation, `--yes` is intentionally stricter. Include the source of truth and at least one critical flow so CES does not silently preserve inferred behavior:

```bash
ces build "Add invoice notes to CSV exports" \
  --yes \
  --source-of-truth "tests/test_export.py and docs/export-format.md" \
  --critical-flow "Existing CSV exports remain import-compatible" \
  --acceptance "CSV exports include invoice notes when present." \
  --must-not-break "Existing CSV export columns and import compatibility."
```

## Quality gates: how to know it worked

Do not approve because the agent says it is done. Approve only when CES evidence supports it.

A run is ready for review when:

1. The runtime emitted a valid `ces:completion` claim.
2. Changed files match the requested scope.
3. Required verification commands passed.
4. Brownfield must-not-break behavior has evidence.
5. `ces proof` reports `proven`.
6. The recommendation is `safe-to-review`.

If any item is missing, run:

```bash
ces why
ces verify
ces proof
```

### Compile the next agent contract before touching code

CES does not replace your coding agent. CES gives your coding agent a narrow, testable, evidence-backed mission.

Use `ces deliberate` when the approach itself needs pushback before you hand work to Codex, Claude Code, or another coding agent. It produces a read-only Approach Decision Brief with alternatives, implementation/maintainer/risk perspectives, preserved dissent, blockers, and the next CES command. Add `--challenge` when vague domain language should be challenged against `CONTEXT.md`, `CONTEXT-MAP.md`, `docs/adr/`, and visible code identifiers before runtime work:

```bash
ces deliberate "Add invoice notes to CSV exports"
ces deliberate "Add account-level invoice export settings" --challenge
ces deliberate "Rotate production database credentials" \
  --acceptance "Old credentials are revoked only after the new ones pass smoke verification." \
  --must-not-break "Existing deploy and rollback commands."
```

`--challenge` stays deterministic and read-only. It surfaces domain context sources, overloaded terminology, code/doc contradictions, blocking clarifying questions, and documentation capture suggestions without editing glossary or ADR files.

Use `ces next-prompt` when you are ready for CES to turn an objective plus repo context into a strict Developer Intent Contract:

```bash
ces next-prompt "Add invoice notes to CSV exports"
ces next-prompt "Rotate production database credentials" \
  --acceptance "Old credentials are revoked only after the new ones pass smoke verification." \
  --must-not-break "Existing deploy and rollback commands."
```

Both commands are read-only. They do not create `.ces/`, edit files, or launch a runtime. The deliberation brief reports alternatives, implementation/maintainer/risk critique, preserved dissent, blockers, and the next CES command. The contract reports:

- the original objective
- greenfield, brownfield, or thin/born-thin rescue mode
- detected project type and maturity from MRI
- explicit scope, non-goals, must-not-break rules, and forbidden changes
- anti-slop limits, scope-drift kill switch, verification commands, and `ces:completion` expectations
- one safest next step for thin/vibe-coded repos instead of a giant rescue roadmap

Examples:

```bash
# New project from an idea
ces next-prompt "Create a small task tracker with tests and run instructions" --project-root /tmp/task-tracker

# Existing thin/vibe-coded app rescue
ces next-prompt "Stabilize this AI-built app enough to safely add signup error handling" --project-root ./messy-app

# Normal brownfield feature change
ces next-prompt "Add invoice notes to CSV exports" --project-root .
```

### Turn intent into an execution contract

Use `ces intake` when you want a persisted bridge from a human request, PRD, or GitHub issue into CES-governed execution:

```bash
ces intake "Add CSV invoice notes"
ces intake docs/prd.md
ces intake --from-github-issue 123
```

`ces intake` deliberately supports only stable boundaries:

- inline intent text
- local Markdown PRDs such as `prd.md`
- GitHub issue numbers or URLs via the `gh` CLI

It does **not** import spec-kit, OpenSpec, BMAD, GSD, Kiro, or other project-specific methodology layouts. If those tools produce a useful plan, copy or export the stable human-facing result into `prd.md` or a GitHub issue, then let CES own the execution contract and proof loop.

Intake writes:

- `.ces/contracts/<contract-id>.json`
- `.ces/contracts/latest.json`
- `docs/contracts/<contract-id>.md`
- `docs/specs/<contract-id>.md`, a generated CES spec sidecar for the existing `--from-spec` path

After intake, the intended loop is:

```bash
ces build --from-contract
ces verify
ces proof
ces approve
```

`ces proof` is the approval checkpoint and the proof is the hero artifact. It reports what was requested, what changed, tests/evidence, policy gates, behavior-delta coverage, risk-track evidence, approval status, and the next operator action. The proof status is `proven`, `partially_proven`, `unproven`, or `contradicted`, and the recommendation stays at no-ship unless fresh verification matches the current completion contract and required evidence is present. It also includes a review summary with the decision, approval gate, primary blocker, evidence freshness, command coverage, artifact coverage, behavior-delta coverage, risk-track coverage, and next steps. For brownfield work, proof cards carry CES-native behavior deltas (`added`, `modified`, `removed`, `preserved`, `unknown`) where `unknown` means unresolved ambiguity. CES infers risk tracks: Tier C for low-risk additive work, Tier B when modified/preserved behavior needs regression evidence, and Tier A when removed or unknown behavior requires rollback/reviewer artifacts. Unresolved ambiguity or missing risk artifacts block approval as `partially_proven` until evidence or clarification resolves them. For contract-bound work, `ces approve` now fails closed unless proof is `proven` and approval safety is `safe-to-review`.

The legacy phase interview remains available as:

```bash
ces intake interview 1
```

### Install from PyPI

```bash
uv tool install controlled-execution-system
uv tool update-shell
ces --help
```

If your ambient `python3` is Python 3.11, direct `pip install controlled-execution-system` may fail with `No matching distribution` before CES starts because the package requires Python 3.12 or 3.13. Ask `uv` for a supported interpreter explicitly:

```bash
uv tool install --python 3.13 controlled-execution-system
```

Install or pin a specific release:

```bash
uv tool install controlled-execution-system==0.1.29
```

Upgrade later:

```bash
uv tool upgrade controlled-execution-system
```

### Verify the runtime boundary

```bash
ces doctor
ces doctor --runtime-safety
# Optional: may contact the runtime provider and consume a small request.
ces doctor --verify-runtime --runtime all
```

`ces build` and `ces execute` require Codex CLI or Claude Code. `CES_DEMO_MODE=1` only affects optional helper/provider behavior; it does not replace the local execution runtime.

### First governed run

Run CES from the repository you want to govern:

```bash
cd path/to/your-project
ces build "Add a healthcheck endpoint that returns JSON status"
```

On first use, CES creates `.ces/` in that project, gathers missing context, drafts the manifest, executes through the selected local runtime, checks the workspace delta, records evidence, and shows the next operator action.

Before manifest creation, CES Intent Gate may ask, assume, proceed, or block depending on task ambiguity and risk; see [Intent Gate](https://github.com/chrisduvillard/controlled-execution-system/blob/master/docs/Intent_Gate.md).

If you prefer to initialize state manually first:

```bash
ces init my-project
ces doctor
ces doctor --runtime-safety
```

---

## How CES works

```text
Intent ──▶ Manifest ──▶ Runtime ──▶ Evidence ──▶ Review ──▶ Approval
  │           │            │            │           │           │
  │           │            │            │           │           └─ explicit operator decision
  │           │            │            │           └─ adversarial and policy-aware review
  │           │            │            └─ verification artifacts + workspace delta
  │           │            └─ Codex CLI or Claude Code subprocess
  │           └─ bounded scope, tools, acceptance criteria, risk context
  └─ natural-language request from the operator
```

| Stage | What happens | Operator value |
|---|---|---|
| Intent | You describe the change in plain language. | Fast entry; no manifest authoring required for normal work. |
| Manifest | CES captures scope, allowed work, acceptance criteria, and governance context. | The runtime gets a bounded assignment instead of an open-ended prompt. |
| Runtime | CES launches a supported local AI coding runtime. | Work happens in your repo, using your local tool configuration. |
| Evidence | CES records artifacts, completion claims, verification results, transcripts, and workspace delta. | Approval is tied to proof, not confidence. |
| Review | CES summarizes the result, flags blockers, and routes evidence through review/triage surfaces. | You see what matters before approving. |
| Approval | The decision is recorded in the local audit trail. | The delivery history is inspectable later. |

Local state is stored in the governed project:

| Path | Purpose |
|---|---|
| `.ces/config.yaml` | Project metadata and local execution settings |
| `.ces/state.db` | SQLite store for manifests, audit entries, evidence, sessions, and local records |
| `.ces/keys/` | Project-local signing and audit integrity keys |
| `.ces/artifacts/` | Runtime and evidence artifacts |
| `.ces/exports/` | Builder reports and exported handoff files |
| `.ces/baseline/` | Day-0 sensor snapshots |
| `.ces/completion-contract.json` | Builder-produced completion contract with independent verification commands |
| `.ces/verification-profile.json` | Optional project-aware verification policy for required, optional, advisory, and unavailable checks |

Keep local `.ces/` state untracked unless you intentionally share an exported report. A repository may intentionally track `.ces/verification-profile.json` or `.ces/completion-contract.json` when the team wants shared verification policy or proof-loop expectations.

---

## Operator workflow

Start with the builder-first loop for almost all delivery work:

```bash
ces build "Describe the change"
ces explain
ces status
ces continue
ces report builder
```

| Command | Use it for |
|---|---|
| `ces build "<request>"` | Start a governed local task from a natural-language request. |
| `ces intake "<request>"` / `ces intake docs/prd.md` | Persist a narrow execution contract from inline intent, a local Markdown PRD, or `--from-github-issue`. |
| `ces build --from-contract` | Continue from the latest intake contract's generated CES spec sidecar. |
| `ces continue` | Resume the latest saved builder session from the right stage. |
| `ces explain` | Read the current request, blockers, evidence, and next step. |
| `ces explain --view decisioning` | Inspect the governance decision path for the active request. |
| `ces explain --view brownfield` | Inspect existing-behavior context for the active request. |
| `ces status` | Show concise builder-first project status without mutating local state. |
| `ces why` | Explain why the latest builder run is blocked and show the next command. |
| `ces recover --dry-run` | Preview recovery for stale, interrupted, or incomplete evidence states. |
| `ces verify` | Run independent local verification without writing inferred contracts by default. |
| `ces mri` | Run a read-only Project MRI diagnostic for maturity, readiness score, risks, missing production-readiness signals, and recommended next CES actions. |
| `ces next` | Show the next safest production-readiness action before launching more work. |
| `ces deliberate` | Generate a read-only Approach Decision Brief with alternatives, role-specific pushback, preserved dissent, blockers, and the next CES command. |
| `ces next-prompt` | Generate a scoped agent prompt for the next readiness step without running an agent. |
| `ces passport` | Produce a local Production Passport from deterministic signals and available CES evidence. |
| `ces promote production-candidate` | Produce a plan-only maturity promotion sequence, one checkpoint at a time. |
| `ces launch rehearsal` | Produce a non-destructive launch-readiness rehearsal plan and safe local smoke checks. |
| `ces complete` | Reconcile work that was actually completed outside CES. |
| `ces report builder` | Export markdown and JSON handoff reports under `.ces/exports/`. |

When a run blocks, use this sequence before rerunning work or approving anything manually:

```bash
ces why
ces recover --dry-run
ces verify
ces report builder
```

Use expert workflow commands when you need direct artifact control:

| Command group | Use it for |
|---|---|
| `ces manifest` / `ces classify` | Create and classify manifests directly. |
| `ces execute` | Run a manifest-bound local agent task. |
| `ces review` / `ces triage` / `ces approve` | Inspect evidence and make approval decisions directly. |
| `ces audit` | Inspect the local audit ledger, for example `ces audit --limit 20`. |
| `ces evidence attach` | Attach scrubbed manual evidence and command provenance to a manifest. |
| `ces diff --since-approval` | Show changed files since the latest evidence/approval git baseline. |
| `ces status --expert` | Show the full expert status view; use `ces status --expert --watch` for live monitoring. |
| `ces emergency declare` | Record an expert operations emergency declaration, for example `ces emergency declare "Security incident detected"`. |
| `ces scan` / `ces mri` / `ces baseline` | Inventory the repo, diagnose project maturity/readiness risks, and capture day-0 sensor snapshots. |
| `ces next` / `ces next-prompt` / `ces passport` | Plan and explain the next production-readiness move with deterministic evidence. |
| `ces invariants` / `ces slop-scan` / `ces launch rehearsal` | Mine conservative project constraints, surface AI-native failure patterns, and rehearse launch checks without mutation. |
| `ces profile detect/show/doctor` | Detect, persist, and inspect project-aware verification requirements. |
| `ces brownfield ...` | Capture, review, and promote named legacy behavior decisions. |
| `ces spec ...` | Author, validate, decompose, reconcile, or inspect specs. |
| `ces setup-ci` | Generate GitHub or GitLab CI gating workflow templates. |
| `ces dogfood` | Use CES to review changes to this repository. |

Brownfield work starts with builder-first context, then uses explicit legacy-behavior decisions when needed:

```bash
ces explain --view brownfield
ces brownfield review OLB-<entry-id> --disposition preserve
```

Commands with machine-readable output support the global JSON form where applicable:

```bash
ces --json status
ces status --json
```

---

## Runtime safety

CES is intentionally explicit about the runtime boundary.

| Safety behavior | What to remember |
|---|---|
| Unsafe runtimes require explicit consent | `ces build`, `ces continue`, and `ces execute` fail closed before launching a runtime that cannot enforce manifest tool allowlists unless you pass `--accept-runtime-side-effects`. |
| `--yes` is not side-effect consent | Unattended approval does not imply permission to launch an unsafe runtime boundary. You still need `--accept-runtime-side-effects`. |
| `ces status` is read-only by default | It displays builder-first state without refreshing stale sessions. Use `ces status --reconcile` only when you explicitly want state reconciliation before display. |
| `ces verify` does not write inferred contracts by default | It reads an existing completion contract when present; otherwise it verifies against an inferred in-memory contract. Use `ces verify --write-contract` only when you want to persist it. |
| `ces scan --dry-run` is non-mutating | It previews repository inventory without bootstrapping local state or writing `.ces/brownfield/scan.json`. |

Codex is disclosed as a full-access local runtime for CES purposes. CES can review its output and workspace delta after execution, but the Codex adapter does not enforce manifest tool allowlists before the subprocess starts. Prefer Claude Code when you need runtime-level tool allowlist enforcement.

Unattended `--yes` runs remain evidence-gated. CES should block auto-approval when completion evidence is incomplete, required verification artifacts are missing, workspace deltas exceed scope, blocking sensors fail, or the runtime boundary needs an explicit side-effect waiver.

---

## Core commands

| Command | Purpose |
|---|---|
| `ces --help` | Show CLI help and command groups. |
| `ces doctor` | Run preflight checks for Python, providers, extras, and project setup. |
| `ces doctor --runtime-safety` | Show runtime-boundary disclosures. |
| `ces build "<request>"` | Default builder-first governed delivery path. |
| `ces continue` | Resume the latest builder session. |
| `ces explain` | Summarize request, blockers, evidence, and next step. |
| `ces status` | Show read-only builder-first status by default. |
| `ces why` | Diagnose a blocked builder run. |
| `ces recover --dry-run` | Preview recovery before mutation. |
| `ces verify` | Independently verify the current project. |
| `ces mri` | Diagnose maturity, readiness score, risk findings, missing signals, and recommended next actions. |
| `ces next` | Show the next safest production-readiness action. |
| `ces next-prompt` | Generate a guardrailed prompt for an agent without running it. |
| `ces passport` | Produce a local Production Passport in markdown or JSON. |
| `ces promote <target-level>` | Plan a read-only one-checkpoint maturity promotion. |
| `ces invariants` / `ces slop-scan` | Mine conservative project constraints and AI-native failure findings. |
| `ces launch rehearsal` | Plan non-destructive launch-readiness checks. |
| `ces complete` | Reconcile externally completed work. |
| `ces evidence attach` | Attach scrubbed evidence files and recorded verification commands to a manifest. |
| `ces diff --since-approval` | Review changed files since the latest evidence packet's captured git HEAD. |
| `ces report builder` | Export the latest builder handoff report. |
| `ces manifest "<request>"` | Create a task manifest directly. |
| `ces classify M-<manifest-id>` | Classify manifest risk and routing. |
| `ces execute M-<manifest-id>` | Execute a manifest-bound task locally. |
| `ces review` / `ces triage` / `ces approve` | Review, screen, and decide on evidence. |
| `ces scan --dry-run` | Preview repository inventory without mutation. |
| `ces audit` | Expert operations audit inspection; use `ces audit --limit 20` to inspect recent ledger events. |
| `ces emergency declare` | Expert operations emergency declaration; for example `ces emergency declare "Security incident detected"`. |
| `ces brownfield ...` | Expert legacy behavior capture, review, and promotion. Use `ces brownfield review OLB-<entry-id> --disposition preserve` for a named legacy-behavior decision. |
| `ces spec ...` | Work with governed specs and manifest drafts. |

For the complete command boundary, use the [Quick Reference Card](https://github.com/chrisduvillard/controlled-execution-system/blob/master/docs/Quick_Reference_Card.md) and [Operator Playbook](https://github.com/chrisduvillard/controlled-execution-system/blob/master/docs/Operator_Playbook.md).

---

## Development

Work from source when developing CES itself:

```bash
git clone https://github.com/chrisduvillard/controlled-execution-system.git
cd controlled-execution-system
uv sync
uv run ces --help
```

If `ces` is not active in your shell while you are inside a source checkout, use `uv run ces ...`.

Run the local-first verification gate:

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/ces/ --ignore-missing-imports
uv run pytest tests/ -m "not integration" --cov=ces --cov-fail-under=90 --cov-report=term-missing -q -W error
uv build
uvx twine check dist/*
```

Run local integration tests:

```bash
uv sync --group ci
uv run pytest tests/ -m integration -q
```

Builder-created manifests expect command-backed completion evidence. When completion-gate sensors are enabled, produce matching artifacts before claiming completion: `pytest-results.json`, `ruff-report.json`, `mypy-report.txt`, and `coverage.json`. Dependency and security-sensitive changes can also be backed by `pip-audit-report.json` and SAST JSON artifacts such as `bandit-report.json`; CES parses those when present.

PyPI publishing is tag-driven. Pushing to `master` runs CI only; pushing a `v*` tag such as `v0.1.29` triggers `.github/workflows/publish.yml`, which runs tests, builds distributions, smoke-tests the installed CLI, validates tag/version agreement, and publishes through trusted publishing. Follow [docs/RELEASE.md](https://github.com/chrisduvillard/controlled-execution-system/blob/master/docs/RELEASE.md) for the maintainer checklist.

---

## Documentation map

| Document | Start here when you need |
|---|---|
| [5-Minute Quickstart](https://github.com/chrisduvillard/controlled-execution-system/blob/master/docs/Quickstart.md) | The shortest local builder-first path. |
| [Getting Started](https://github.com/chrisduvillard/controlled-execution-system/blob/master/docs/Getting_Started.md) | Full setup and workflow walkthrough. |
| [Operator Playbook](https://github.com/chrisduvillard/controlled-execution-system/blob/master/docs/Operator_Playbook.md) | Builder-first versus expert workflow boundaries. |
| [Brownfield Guide](https://github.com/chrisduvillard/controlled-execution-system/blob/master/docs/Brownfield_Guide.md) | Existing-codebase and legacy-behavior governance. |
| [Operations Runbook](https://github.com/chrisduvillard/controlled-execution-system/blob/master/docs/Operations_Runbook.md) | Expert status, audit, and emergency operations. |
| [Quick Reference Card](https://github.com/chrisduvillard/controlled-execution-system/blob/master/docs/Quick_Reference_Card.md) | Command and gate lookup tables. |
| [Troubleshooting](https://github.com/chrisduvillard/controlled-execution-system/blob/master/docs/Troubleshooting.md) | Common local setup and runtime issues. |
| [Release Runbook](https://github.com/chrisduvillard/controlled-execution-system/blob/master/docs/RELEASE.md) | Maintainer release checklist. |

Historical server-oriented docs live under `docs/historical/` as design archives, not as the current product contract. Current design and plan records live under `docs/designs/` and `docs/plans/`.

---

## Contributing

See [CONTRIBUTING.md](https://github.com/chrisduvillard/controlled-execution-system/blob/master/CONTRIBUTING.md) for development workflow, tests, and contribution expectations. Security-sensitive issues should follow [SECURITY.md](https://github.com/chrisduvillard/controlled-execution-system/blob/master/SECURITY.md).

If you use external agent loops such as `gnhf`, keep them outside CES itself as contributor tooling rather than part of the product. Run them from a clean sibling worktree or clean clone, keep the scope away from manifest/policy, approval/triage/review, audit, kill-switch, and runtime-boundary changes, and review every generated branch manually before using it. Follow the [GNHF Trial Guide](https://github.com/chrisduvillard/controlled-execution-system/blob/master/docs/GNHF_Trial_Guide.md) and [`scripts/gnhf_trial.sh`](https://github.com/chrisduvillard/controlled-execution-system/blob/master/scripts/gnhf_trial.sh); CES's own builder-first or expert workflows remain the delivery path.

## License

MIT. See [LICENSE](https://github.com/chrisduvillard/controlled-execution-system/blob/master/LICENSE).
