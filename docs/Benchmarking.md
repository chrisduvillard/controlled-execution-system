# Benchmarking CES Value

This A/B gauntlet answers one product question:

> Is CES adding value over vanilla Codex CLI or Claude Code?

The answer should be based on measured workflow outcomes, not positioning language. CES is valuable only when the additional governance friction buys better completion, evidence, control, or review confidence than a normal agent run.

## Gauntlet shape

Run the same task through two arms:

1. **Vanilla arm** - Codex CLI or Claude Code directly, with the same objective and acceptance criteria.
2. **CES arm** - CES front door and proof loop, normally `ship -> build -> verify -> proof` for greenfield or `mri/next-prompt -> build -> verify -> proof` for brownfield.

Use 10 scenarios:

- 5 greenfield scenarios for people building a new project from scratch.
- 5 brownfield scenarios for developers improving an existing project.

The sample scenario file is `docs/benchmark/ab-gauntlet-sample.json`. It is intentionally unmeasured: all metric values are null/missing, and running `ces benchmark compare` against it should produce `insufficient-measured-evidence`. Treat it as a template, not as product evidence.

## Metrics

Every scenario compares the same side-by-side fields:

- `completion` - did the workflow satisfy the requested outcome?
- `time_minutes` - wall-clock time to final candidate.
- `tokens` - runtime token usage when available.
- `tool_calls` - shell/file/tool iterations or equivalent observable actions.
- `corrections` - human corrections or reruns needed after first candidate.
- `tests` - meaningful tests or checks added/run.
- `docs` - useful docs or usage notes created/updated.
- `maintainability` - 0-5 reviewer score for simplicity, scope control, and future change cost.
- `bugs` - confirmed defects in the final candidate.
- `friction` - 0-5 operator friction where lower is better.
- `auditability` - 0-5 ability to understand what happened and why.
- `control` - 0-5 ability to constrain scope, preserve behavior, and approve safely.

Lower is better for `time_minutes`, `tokens`, `tool_calls`, `corrections`, `bugs`, and `friction`.
Higher is better for the other fields.

## Evidence rules

Each metric has an evidence label:

- `measured` - observed from the run, logs, generated artifacts, tests, or review.
- `inferred` - plausible hypothesis, useful for planning but not counted as proof.
- `missing` - not yet captured.

Each measured or inferred metric should use `note` to cite the evidence source: log path, command output, artifact path, reviewer note, CI run, or verification command. Empty notes are accepted for backward compatibility, but they make a benchmark weaker.

The comparison report separates measured findings from inferred expectations and missing data. Inferred rows are hypothesis only and do not count as evidence that CES adds value.

A scenario is `recommendation-comparable` only when `completion` is `measured` for both arms. Secondary metrics are `secondary-metric-counted` only when a scenario is recommendation-comparable and both arms completed successfully. Secondary metrics from one-sided, missing-completion, or failed-completion rows stay visible in the row detail but do not swing the headline recommendation. Failed-row secondary metrics remain visible but do not prove CES value.

JSON and Markdown row details include a recommendation-comparable flag, a secondary-metric-counted flag, and an exclusion reason so reviewers can see which scenarios drove the verdict.

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

`.ces/` is ignored local state. Use it for scratch runs, not for benchmark evidence that a PR or public claim needs to cite.

## For PR evidence packs

A benchmark PR must be self-contained. Do not cite `.ces/benchmarks/latest` unless the relevant artifacts are copied into tracked docs.

Recommended layout:

```bash
mkdir -p docs/benchmark/evidence/<run-id>/report
cp docs/benchmark/ab-gauntlet-sample.json docs/benchmark/evidence/<run-id>/ab-gauntlet.json
ces benchmark compare \
  --project-spec docs/benchmark/evidence/<run-id>/ab-gauntlet.json \
  --out docs/benchmark/evidence/<run-id>/report
```

Commit the filled input spec plus the generated outputs:

- `docs/benchmark/evidence/<run-id>/ab-gauntlet.json`
- `docs/benchmark/evidence/<run-id>/report/comparison-report.json`
- `docs/benchmark/evidence/<run-id>/report/comparison-report.md`

Also include or link sanitized raw evidence:

- exact prompts/commands per arm
- runtime/model versions
- CES version/commit
- scenario fixture/base commit
- verification outputs
- reviewer scoring notes
- known missing metrics

Brownfield evidence needs a reproducible source of truth: fixture repo/path, base commit, expected behavior, must-not-break behavior, verification commands, and evidence refs.

## Interpreting the recommendation

- `ces-adds-measured-value` - CES has more measured successful completions than vanilla, or measured successful completion is tied and counted secondary metric wins favor CES.
- `vanilla-outperformed-ces` - vanilla has more measured successful completions than CES, or measured successful completion is tied and counted secondary metric wins favor vanilla.
- `no-successful-completion` - completion was measured for both arms but neither arm completed successfully, so secondary metrics cannot prove value.
- `inconclusive-measured-tie` - measured completion and counted metric evidence exists but does not clearly favor either arm.
- `insufficient-measured-evidence` - no scenario has two-sided measured completion evidence.

This recommendation is not a universal product truth. It is the result for the chosen scenario set and evidence quality.

Acceptable claim:

> In the tracked benchmark run at `<path>`, N/M recommendation-comparable scenarios supported `<recommendation>`; the result is scoped to those scenarios and evidence quality.

Unacceptable claims:

- CES beats Codex.
- CES is proven better.
- CES guarantees safer code.
- The sample benchmark proves value.

## Practical scoring guidance

Use a fresh temp directory or worktree per arm. Keep prompts as identical as possible, except that the CES arm should use CES commands and the vanilla arm should invoke Codex CLI or Claude Code directly.

For greenfield tasks, verify the generated project independently. Do not count `ces proof` or an agent summary as the project check itself.

For brownfield tasks, require at least one source of truth: existing tests, docs, snapshots, traces, or an explicit must-not-break behavior. Brownfield is where CES should win most clearly; if it does not improve auditability and control there, the product claim is weak.

For subjective 0-5 scores, use reviewer notes and evidence refs:

- `maintainability`: 0 means hard to safely change, 3 means acceptable but nontrivial future cost, 5 means simple, bounded, and easy to extend.
- `friction`: 0 means no notable operator drag, 3 means moderate but manageable intervention, 5 means high drag or confusing recovery.
- `auditability`: 0 means reviewer cannot reconstruct what happened, 3 means basic artifacts exist, 5 means intent, commands, diffs, tests, proof, and rationale are easy to inspect.
- `control`: 0 means scope/approval drifted, 3 means scope stayed mostly bounded, 5 means clear gates, preserved behavior, and explicit approvals controlled the run.

When reporting results, include both:

- the side-by-side scorecard
- a short reviewer note explaining the tradeoff, especially if CES was slower but produced stronger proof

## Deterministic harness vs product evidence

`ces benchmark greenfield` uses a deterministic fake runtime. It is useful for checking scorecard generation, friction accounting, fake-runtime behavior, and benchmark harness regressions.

It does not compare CES against vanilla Codex CLI or Claude Code, and it does not prove CES-vs-vanilla value. Only `ces benchmark compare` over a two-arm measured spec can support scenario-scoped product-value claims.
