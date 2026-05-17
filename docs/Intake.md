# CES Intake

CES Intake is the narrow bridge from human intent to governed execution. It does not try to become a spec-framework compatibility layer.

## Supported sources

```bash
ces intake "Add CSV invoice notes"
ces intake docs/prd.md
ces intake --from-github-issue 123
```

CES accepts only:

- inline intent text
- local Markdown PRDs, including `prd.md`
- GitHub issues through the `gh` CLI

CES intentionally does not maintain importers for spec-kit, OpenSpec, BMAD, GSD, Kiro, Superpowers, or other project-specific planning layouts. Those projects may change internal file formats. If they produce a useful artifact, export or copy the stable human-facing result into a Markdown PRD or GitHub issue, then let CES compile the execution contract.

## What intake writes

Running `ces intake ...` writes project-local artifacts:

- `.ces/contracts/<contract-id>.json`
- `.ces/contracts/latest.json`
- `docs/contracts/<contract-id>.md`
- `docs/specs/<contract-id>.md`

The JSON contract is the authoritative machine-readable artifact. The Markdown contract is for review. The generated spec sidecar allows existing CES spec/decompose plumbing to keep working without making external framework importers part of the product surface.

## Execution contract shape

An execution contract records:

- objective
- source provenance
- problem statement
- acceptance criteria
- non-goals
- behavior delta
- required evidence
- policy modules
- next CES commands

Behavior deltas are split into:

- added behavior
- modified behavior
- removed behavior
- preserved behavior
- unresolved ambiguity (`unknown` in JSON)

For brownfield work, preserved behavior is part of the contract because approval safety depends on knowing what must not regress.

## Worked example

```bash
ces intake "Add CSV invoice notes"
ces intake show
ces intake review
ces build --from-contract
ces verify
ces proof
ces approve
```

A minimal PRD can be as simple as:

```markdown
# Add CSV invoice notes

## Problem
Users cannot export invoice notes.

## Success Criteria
- CSV export includes invoice notes.
- Existing invoices without notes still export.

## Non-Goals
- Do not redesign billing.

## Preserved Behavior
- Existing CSV column order remains stable.

## Required Evidence
- Regression test for invoices without notes.
```

The proof card includes the intake contract context when `.ces/contracts/latest.json` exists, so reviewers can see whether a completion contract and verification evidence have caught up to the original intent. Brownfield behavior deltas are carried into completion contracts and proof cards as `added`, `modified`, `removed`, `preserved`, and `unknown` where `unknown` means unresolved ambiguity. CES also attaches a risk track to the completion contract: Tier C has no extra risk artifact, Tier B requires `regression-evidence.md`, and Tier A requires `rollback-plan.md` plus `reviewer-signoff.md`. Treat unresolved ambiguity or missing risk artifacts as approval-blocking until they are clarified or backed by explicit evidence.

The proof is the hero artifact for approval. A reviewer should be able to answer what was requested, what changed, which tests/evidence ran, which policy gates are still closed, and the current approval status from `ces proof` before running `ces approve`.

`ces proof` also reports an operator-facing proof status:

- `proven`: fresh verification passed, matched the current completion contract, and required handoff artifacts are present.
- `partially_proven`: fresh verification passed and matched the contract, but required evidence or handoff artifacts are still missing.
- `unproven`: verification is missing, stale, or does not match the current completion contract.
- `contradicted`: the latest persisted verification failed.

Approval safety is derived from that status. `ces approve` fails closed for contract-bound work unless proof is `proven` and approval safety is `safe-to-review`. Treat anything else as no-ship until the missing or stale evidence is repaired.

The proof card also includes a `review_summary` object for reviewer triage:

- `decision`: `ready-for-review`, `needs-verification`, `needs-evidence`, or `blocked`.
- `approval_gate`: `open` only when approval is allowed; otherwise `closed`.
- `primary_blocker`: the first issue to repair before approval.
- `freshness`, `command_coverage`, `artifact_coverage`, `behavior_delta_coverage`, `risk_track`, and `risk_evidence`: compact evidence quality signals.
- `next_steps`: the next operator commands/actions to unblock review.

## Legacy interview

The older phase-based interview command remains available under:

```bash
ces intake interview 1
```
