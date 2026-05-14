# CES Vibe-Coder Completion Roadmap

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make CES credible as a Production Autopilot that can take a non-expert builder from idea or messy AI-built repo to a proof-backed, runnable project.

**Architecture:** Keep the path local-first and evidence-backed. Start with a read-only `ces ship` front door, then add guided greenfield execution, proof cards, claim verification, and fresh-project gauntlets. Avoid claiming hosted deployment, universal sandboxing, or zero-human-intervention.

**Tech Stack:** Python 3.12/3.13, Typer CLI, existing CES MRI/readiness/reporting modules, Codex CLI/Claude Code adapters, pytest/ruff/mypy/uv CI parity.

---

## Definition of complete enough

CES is complete enough for broad vibe-coder usage only when a fresh PyPI install can reliably handle this loop:

1. `ces ship "Create <project>"` explains a safe plan from an empty folder without mutation.
2. `ces build --gsd "Create <project>"` creates a runnable project with README, tests, and run instructions.
3. `ces verify`, `ces passport`, and `ces launch rehearsal` produce understandable proof and remaining-risk notes.
4. A fresh installed-package gauntlet independently verifies the created project, not just CES self-reports.
5. Failure states always include the next best command and never pretend a red/unknown evidence state is ready.

## Sequential PR roadmap

### PR A — Beginner front door: `ces ship`

Status: initial implementation branch `feat/vibe-coder-ship-front-door`.

Scope:
- Add read-only `ces ship [objective]`.
- Promote `ces build --gsd` for empty-folder creation.
- Make empty-project `ces next` recommend greenfield creation instead of readiness-only work.
- Fix Production Passport wording so incomplete readiness is not hidden as only “None detected.”
- Update README / Quickstart / Getting Started.

Verification:
- Unit tests for report model, CLI JSON/markdown, root help, docs contracts.
- Live smoke from a temporary empty project proving `ces ship` does not create `.ces/` or launch a runtime.

### PR B — Guided greenfield acceptance contract

Scope:
- Add a deterministic `--starter` / project-kind planner or structured objective extraction for common app types.
- Require README, run command, tests, and verification profile in greenfield completion evidence.
- Make `ces build --gsd` final output always include: how to run, how to test, what is unproven, next CES command.

Implemented in PR B:
- Completion contracts now persist required artifacts (`README.md`, run command, test command, verification evidence), proof requirements, and `ces verify --json` as the next CES command.
- Greenfield runtime prompts include a beginner-facing acceptance contract requiring README run/test instructions, verification evidence, and unproven-risk disclosure.
- Greenfield completion summaries include how to run, how to test, runnable smoke commands when inferred, unproven/remaining-risk guidance, and the next CES command.

Verification:
- Fresh temp project smoke with fake runtime where possible and real-runtime dogfood when authorized.
- Regression tests for completion-contract shape and greenfield final UX.

### PR C — Proof card / claim verifier

Scope:
- Add `ces proof` or enhance `ces passport` with a compact shareable card: objective, changed files, commands run, evidence status, unproven areas, ship/no-ship recommendation.
- Add `ces verify-claims` deterministic checks for overclaims: claimed tests absent, risky files omitted, missing proof for “done.”

Implemented so far in PR C:
- Added `ces proof` as a read-only compact proof card with JSON and markdown output.
- The proof card reports objective, changed files, planned verification commands, executed persisted verification commands, missing beginner artifacts, unproven areas, next command, and candidate/no-ship recommendation.
- Missing completion contract or missing handoff artifacts stays honest as no-ship/incomplete.

Verification:
- Fixture-backed tests for honest vs overclaiming completion summaries.
- JSON + markdown smoke.

### PR D — Vibe-coder gauntlet harness

Scope:
- Add `ces benchmark` or harness fixture that runs a fresh-project A-to-Z gauntlet from installed wheel.
- Emit a friction scorecard: setup blockers, command confusion, runtime consent, evidence quality, final app verification.

Verification:
- CI-friendly fake-runtime path plus optional live-runtime dogfood evidence.
- Artifact hygiene confirms gauntlet outputs do not ship in sdist/wheel.

### PR E — Release and public proof

Scope:
- Release prep after A-D are green and merged.
- Publish next patch only after explicit approval.
- Post-publish fresh install gauntlet from PyPI.

Verification:
- TestPyPI rehearsal, PyPI publish, fresh install, and public README sanity check.

## Non-goals

- No hosted control plane.
- No automatic deployment or merge claims.
- No promise that CES replaces runtime auth, repo permissions, CI, or human review.
- No unsafe default runtime launch from read-only planning commands.
