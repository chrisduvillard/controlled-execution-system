# CES Positioning

CES is the accountability layer for AI execution.

It is not trying to be a richer prompt template, a planning-doc generator, or a methodology router. CES is not a spec-framework compatibility layer. The product thesis is narrower and stronger: turn intent into a bounded execution contract, run the agent inside explicit governance, collect verification evidence, generate proof, and make approval a conscious decision.

```text
intent → execution contract → governed run → verification evidence → proof → approval
```

## The category

CES sits after planning and before approval. It accepts stable human-facing input, converts it into CES-native execution control, and then asks the local coding runtime to work inside that control surface.

| Layer | Job | CES stance |
| --- | --- | --- |
| Planning/spec tools | Shape product intent, stories, PRDs, design notes, or change proposals | Useful upstream input when exported as plain Markdown or a GitHub issue |
| Coding agents | Modify files using Codex CLI, Claude Code, or another local runtime | Supported execution engines, not the source of truth for approval |
| CES | Govern execution, evidence, proof, and approval | Native accountability layer |
| CI/source control | Independent repo verification and collaboration | Complementary final check, not replaced by CES |

## Product bets CES is designed to test

1. **Execution contracts, not planning theater**  
   CES should make the next agent mission bounded, testable, and reviewable. It should not reward long documents that do not constrain execution.

2. **Brownfield behavior deltas**  
   Brownfield safety depends on more than "what to add." CES should explicitly track:
   - added behavior
   - modified behavior
   - removed behavior
   - preserved behavior
   - unresolved ambiguity

   Preserved behavior and unresolved ambiguity are first-class because regressions often hide in what the agent did not mention.

3. **Proof as the approval artifact**  
   `ces proof` should be the reviewer-facing artifact, not a decorative report. A useful proof card shows:
   - what was requested
   - what changed
   - tests/evidence
   - policy gates
   - unresolved behavior deltas or ambiguity
   - risk-track evidence
   - approval status
   - next operator action

4. **Fail-closed approval**  
   If verification is missing, stale, failed, mismatched, or incomplete, CES should keep the recommendation at no-ship. Approval should open only when proof is proven and review safety is explicit.

## What CES should not do now

Do not build import adapters for spec-kit, BMAD, or OpenSpec now.

That is a deliberate product boundary. External planning systems can change their internal formats, and compatibility work would pull CES toward being a methodology router instead of an execution accountability layer. If another tool produces useful planning output, copy or export the stable human-facing result into Markdown or a GitHub issue, then let CES own the execution contract and proof loop.

Unsupported for now:

- framework-specific importer maintenance
- artifact synchronization across planning systems
- spec-kit constitution compatibility
- OpenSpec archive compatibility
- BMAD role orchestration
- broad PRD-generation workflows

## Why not just Codex CLI?

Codex CLI is an excellent execution engine. It already brings strong local coding ergonomics: repository context, sandbox and approval modes, non-interactive execution, project instructions, and direct file-edit/test loops.

CES should not compete with that runtime. CES adds the missing accountability plane around it as an intended workflow layer:

- intent is compiled into a reviewable contract before the agent starts
- brownfield scope and behavior preservation stay visible during the run
- verification evidence is recorded as data, not just terminal optimism
- proof becomes the approval artifact, separate from the agent's self-report
- high-risk, ambiguous, or under-evidenced work fails closed instead of drifting into a polished but unapproved change

The value thesis to test is not "a smarter Codex." It is Codex plus contract, context discipline, evidence, proof, and explicit approval.

## Benchmark claim discipline

Public narrative can claim shipped workflow features, local-first boundaries, and proof surfaces. Benchmark or value claims must be scenario-scoped, cite the exact benchmark report path and summary counts, and never generalize from inferred, missing, or sample-template data.

## Public narrative

Short form:

> CES turns AI coding from "the agent said it was done" into "the work has an execution contract, evidence, proof, and explicit approval."

Slightly longer:

> CES is local-first governance for AI coding agents. It compiles intent into an execution contract, runs the local agent under explicit policy, records evidence, surfaces brownfield behavior deltas, and blocks approval until proof is fresh, complete, and reviewable.

## Product focus

The next increments should stay on the native CES loop:

1. Make the execution contract more legible and easier to review.
2. Keep behavior deltas visible from intake through completion and proof.
3. Make `ces proof` the hero artifact for review and approval.
4. Improve fail-closed approval semantics when evidence, risk artifacts, or ambiguity are unresolved.

If a feature does not strengthen one of those four points, it is probably distraction.