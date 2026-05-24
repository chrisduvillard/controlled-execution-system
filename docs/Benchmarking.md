# Benchmarking CES Value

This A/B gauntlet answers one product question:

> Is CES adding value over vanilla Codex CLI or Claude Code?

The answer should be based on measured workflow outcomes, not positioning language. CES is valuable only when the additional governance friction buys better completion, evidence, control, or review confidence than a normal agent run.

## Gauntlet shape

Run the same task through two arms:

1. **Vanilla arm** — Codex CLI or Claude Code directly, with the same objective and acceptance criteria.
2. **CES arm** — CES front door and proof loop, normally `ship -> build -> verify -> proof` for greenfield or `mri/next-prompt -> build -> verify -> proof` for brownfield.

Use 10 scenarios:

- 5 greenfield scenarios for people building a new project from scratch.
- 5 brownfield scenarios for developers improving an existing project.

The sample scenario file is `docs/benchmark/ab-gauntlet-sample.json`.

## Metrics

Every scenario compares the same side-by-side fields:

- `completion` — did the workflow satisfy the requested outcome?
- `time_minutes` — wall-clock time to final candidate.
- `tokens` — runtime token usage when available.
- `tool_calls` — shell/file/tool iterations or equivalent observable actions.
- `corrections` — human corrections or reruns needed after first candidate.
- `tests` — meaningful tests or checks added/run.
- `docs` — useful docs or usage notes created/updated.
- `maintainability` — 0-5 reviewer score for simplicity, scope control, and future change cost.
- `bugs` — confirmed defects in the final candidate.
- `friction` — 0-5 operator friction where lower is better.
- `auditability` — 0-5 ability to understand what happened and why.
- `control` — 0-5 ability to constrain scope, preserve behavior, and approve safely.

Lower is better for `time_minutes`, `tokens`, `tool_calls`, `corrections`, `bugs`, and `friction`.
Higher is better for the other fields.

## Evidence rules

Each metric has an evidence label:

- `measured` — observed from the run, logs, generated artifacts, tests, or review.
- `inferred` — plausible hypothesis, useful for planning but not counted as proof.
- `missing` — not yet captured.

The comparison report separates measured findings from inferred expectations and missing data. Inferred rows are hypothesis only and do not count as evidence that CES adds value. A scenario is recommendation-comparable only when `completion` is `measured` for both arms; secondary metrics from one-sided or missing-completion rows stay visible in the row detail but do not swing the headline recommendation. JSON and Markdown row details include a recommendation-comparable flag so reviewers can see which scenarios drove the verdict.

## Running the comparison report

After filling a scenario file with measured values, run:

```bash
ces benchmark compare \
  --project-spec docs/benchmark/ab-gauntlet-sample.json \
  --out .ces/benchmarks/latest
```

For machine-readable output:

```bash
ces --json benchmark compare \
  --project-spec docs/benchmark/ab-gauntlet-sample.json \
  --out .ces/benchmarks/latest
```

The command writes:

- `.ces/benchmarks/latest/comparison-report.json`
- `.ces/benchmarks/latest/comparison-report.md`

## Interpreting the recommendation

- `ces-adds-measured-value` — CES has more measured successful completions than vanilla, or two-sided measured completion is tied and measured CES metric wins outnumber measured vanilla wins.
- `vanilla-outperformed-ces` — vanilla has more measured successful completions than CES, or two-sided measured completion is tied and measured vanilla metric wins outnumber measured CES wins.
- `no-successful-completion` — completion was measured for both arms but neither arm completed successfully, so secondary metrics cannot prove value.
- `inconclusive-measured-tie` — measured completion and metric evidence exists but does not clearly favor either arm.
- `insufficient-measured-evidence` — no scenario has two-sided measured completion evidence.

This recommendation is not a universal product truth. It is the result for the chosen scenario set and evidence quality.

## Practical scoring guidance

Use a fresh temp directory or worktree per arm. Keep prompts as identical as possible, except that the CES arm should use CES commands and the vanilla arm should invoke Codex CLI or Claude Code directly.

For greenfield tasks, verify the generated project independently. Do not count `ces proof` or an agent summary as the project check itself.

For brownfield tasks, require at least one source of truth: existing tests, docs, snapshots, traces, or an explicit must-not-break behavior. Brownfield is where CES should win most clearly; if it does not improve auditability and control there, the product claim is weak.

When reporting results, include both:

- the side-by-side scorecard
- a short reviewer note explaining the tradeoff, especially if CES was slower but produced stronger proof
