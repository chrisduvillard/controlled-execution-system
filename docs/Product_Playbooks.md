# Product Playbooks

Use these playbooks when the question is not "what command exists?" but "how should I frame this work so CES can govern it well?"

CES should not generate framework sprawl. Treat these as prompt contracts and proof expectations that keep the runtime bounded.

## Greenfield Prompt Contracts

Start with boring defaults and explicit acceptance criteria. A good greenfield request names the user, scope, stack, non-goals, checks, and proof expectation.

```text
Build a small Python CLI task tracker.

Users can add, list, and complete tasks.
Use only the standard library unless a dependency is necessary.
Acceptance criteria:
- `task add "Buy milk"` stores a task.
- `task list` shows open tasks.
- `task done 1` marks task 1 complete.
- Unit tests cover add, list, and done.
Non-goals:
- No sync, database server, web UI, or auth.
Verification:
- Run the unit test suite.
- Include a short README with usage examples.
```

Bad prompt:

```text
Make me a task app. Use whatever is best.
```

Improved CES prompt:

```text
Create a small task tracker with add/list/done commands, tests, a README, no server, and no dependencies unless justified.
```

## Beginner Proof Card

Before approval, check the proof card rather than trusting the runtime summary.

- Scope matches the original request.
- Changed files are expected.
- Verification commands ran after the final changes.
- `ces proof` is `proven`.
- Recommendation is `safe-to-review`.
- Any warnings have an operator decision.

## Brownfield Change-Type Playbooks

Bug fix:

- State the failing behavior and the desired behavior.
- Name at least one must-not-break behavior.
- Point CES at the source of truth, such as tests, docs, screenshots, traces, or a known-good release.
- Ask for the smallest patch that proves the fix.

Feature addition:

- Name the new behavior and boundaries.
- Preserve current public APIs unless explicitly changing them.
- Require tests for the new behavior and regression checks for adjacent behavior.

Refactor:

- Make "no behavior change" the primary acceptance criterion.
- Require before/after verification with the same command set.
- Prefer small file scopes and one mechanical refactor at a time.

Documentation-only change:

- State that code should not change.
- Require docs link consistency and example command accuracy.
- Do not approve if runtime code changes appear without justification.

## Source Of Truth Selection

Use the narrowest trustworthy source:

- Existing passing tests for current behavior.
- API docs or CLI help for public contracts.
- Production traces, fixtures, screenshots, or exported examples for legacy behavior.
- Human operator decision for ambiguous behavior that may be accidental.

If the source is weak, make that explicit in the prompt and require CES to preserve the uncertainty in proof.

## Test Selection

Pick checks that prove the behavior, not just that the repository still imports.

- Unit tests for pure logic.
- CLI smoke tests for public command behavior.
- Integration tests for persistence, workflow, or runtime-boundary behavior.
- Static checks for docs-only, packaging, or API-surface changes.
- Manual evidence only when automation cannot observe the behavior directly.

## Monorepo Guide

Run CES from the smallest project root that owns the change. In a monorepo, prefer a package or service root over the repository root when that package has its own tests and lockfile.

Use the repository root only when the change crosses package boundaries, shared tooling, or top-level release configuration.

For each subproject, write down:

- Project root.
- Source of truth.
- Verification command.
- Must-not-break flows.
- Ownership boundary.

Example:

```text
Project root: services/billing
Source of truth: services/billing/tests and docs/billing-api.md
Verification: uv run pytest services/billing/tests
Must not break: invoice CSV export, tax calculation, public API response fields
Ownership boundary: services/billing and shared/schema only
```

## Proof In Pull Requests

When CES is used before a pull request, include the proof summary rather than a runtime success claim.

```markdown
CES proof:
- Objective: Add invoice notes to CSV exports.
- Scope: services/billing and tests.
- Verification: `uv run pytest services/billing/tests`
- Proof status: proven
- Recommendation: safe-to-review
- Audit check: `ces audit verify`
```

If `ces proof` is not proven, the PR should say what evidence is missing instead of presenting the work as complete.
