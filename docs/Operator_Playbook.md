# Operator Playbook

This playbook explains when to stay in the builder-first CES flow, when to switch to the expert workflow, and how to read the validation evidence surfaces that CES ships today (Agent-Native Software Delivery Operating Model v4).

## Choose Your Path

| Situation | Recommended path | Why |
|-----------|------------------|-----|
| You are starting a new request and want CES to gather context for you | `builder-first` | CES can collect missing constraints, preserve brownfield expectations, and move the current session forward without you wiring every artifact ID manually |
| You paused a request and want to resume it | `builder-first` | `ces continue` resumes the saved builder session instead of replaying the whole setup |
| You want a plain-language summary of what CES knows right now | `builder-first` | `ces explain` and `ces status` are the shortest path to the current request, stage, blockers, and next step |
| You need brownfield context for the active request before making any legacy call | `builder-first` | `ces explain --view brownfield` keeps the current request and grouped review state visible before you drop into explicit brownfield governance |
| You need a read-only project maturity and risk diagnostic | `builder-first` | `ces mri` scans without mutating `.ces/` state and recommends the next CES action before you launch build or verification work |
| You want the next safest production-readiness step and an agent-ready prompt | `builder-first` | `ces next` and `ces next-prompt` explain the next maturity target, blockers, validation commands, non-goals, and secret-handling expectations without running an agent |
| You need local proof of readiness for a handoff | `builder-first` | `ces passport` summarizes deterministic signals, blockers, warnings, missing readiness signals, recommended promotion, and available CES evidence sources |
| You want to promote readiness one checkpoint at a time | `builder-first` | `ces promote production-candidate` produces a plan-only sequence rather than bypassing existing governance gates |
| You need conservative project constraints or AI-native failure findings | `builder-first` | `ces invariants` and `ces slop-scan` mine evidence-backed constraints and deterministic slop findings without LLM calls |
| You need to inspect or persist project-specific verification expectations | `expert workflow` | `ces profile detect`, `ces profile show`, and `ces profile doctor` expose the required/optional/advisory/unavailable check policy before approval |
| You need explicit governance control over review, triage, approval, or manifest lifecycle | `expert workflow` | `ces review`, `ces triage`, `ces approve`, `ces manifest`, and `ces classify` expose the lower-level governance surfaces directly |
| You need to make a named legacy-behavior decision | `expert workflow` | `ces brownfield register`, `ces brownfield review OLB-<entry-id> --disposition preserve`, and `ces brownfield promote` are the explicit brownfield governance surfaces after the builder-first loop identifies the behavior |
| You need an audit or reviewer handoff artifact | `expert workflow` | `ces report builder` exports a concise builder run report from the latest builder session chain |
| You need system-wide visibility, live incident monitoring, or audit inspection | `expert workflow` | `ces status --expert`, `ces status --expert --watch`, `ces audit --limit 20`, and `ces emergency declare "Security incident detected"` are the supported operator surfaces; use the Operations Runbook when you leave the single-request builder loop |

## Builder-First Flow

Use the builder-first flow when you want CES to keep the operator context together around one active request.

```bash
# First run in a repo is enough; CES bootstraps local state if `.ces/` is missing
ces build "Add invoice notes to billing exports"

# Resume or retry the same request
ces continue

# Explain the latest request in plain language
ces explain --view decisioning
ces explain --view brownfield

# Keep an eye on the default builder-first status surface
ces status
```

Builder-first is the default for most day-to-day operator work because it keeps these questions connected:

- what request CES is working on
- whether the repo is being treated as greenfield or brownfield
- what evidence exists already
- what the next action should be

For governed builder-first runs, evidence includes the runtime's `ces:completion`
claim, the actual workspace delta, runtime safety disclosure, configured sensor
results, project-aware verification profile classifications, and any scope or
verification blockers. Required profile checks fail closed when artifacts are
missing or failing; optional, advisory, and unavailable checks relax only the
missing-artifact blocker. If those checks are explicitly run and fail, the
failure remains real sensor evidence rather than being treated as clean. Profile
changes in the same run are treated as untrusted governance changes so a runtime
cannot weaken its own approval policy.
`--yes` skips the interactive prompt only when that evidence is clean enough for
unattended approval. Missing configured required verification artifacts are
blockers. If the selected runtime cannot enforce manifest tool allowlists,
unattended approval also requires an explicit `--accept-runtime-side-effects`
waiver.
`ces explain --view decisioning --governance` and `ces report builder` surface
the evidence-quality state, runtime side-effect waiver state, tool-allowlist
boundary, and MCP-grounding support so reviewers do not have to infer those
risks from raw runtime output.

For day-to-day brownfield delivery, stay builder-first with `ces build`, `ces continue`, and `ces explain --view brownfield`. Switch into the expert brownfield commands only when you need to make a named legacy-behavior decision such as `ces brownfield review OLB-<entry-id> --disposition preserve`. The [Brownfield Guide](Brownfield_Guide.md) covers that handoff in more detail.

If you want manual setup before the first builder-first run, use `ces init <name>`. It is no longer required for the default flow.

## Harness evolution substrate

Harness evolution is a local, explicit, operator-controlled substrate for
describing proposed CES harness changes. It is not autonomous and does not inject
runtime prompts or memory into builder/expert execution. The initial layer
creates a file-level layout under `.ces/harness/`, validates falsifiable change
manifests with predicted fixes, predicted regressions, a validation plan, and a
rollback condition, can persist attribution-ready change records in local
`.ces/state.db`, can distill raw dogfood/runtime transcripts into compact
JSON/markdown trajectory reports without duplicating the raw transcript body, and
can persist regression-aware verdicts that compare predicted fixes/regressions
against observed analysis.

```bash
# Preview exactly which local paths would be created; writes nothing.
ces harness init --dry-run

# Create only .ces/harness directories and .ces/harness/index.json.
ces harness init

# Check whether the local substrate exists.
ces harness inspect

# Validate a proposed change manifest without persisting or activating it.
ces harness changes validate path/to/manifest.json

# Persist, list, and inspect attribution-ready harness change records locally.
ces harness changes add path/to/manifest.json
ces harness changes list
ces harness changes show hchg-...

# Distill a runtime/dogfood transcript into compact reports without raw replay.
ces harness analyze --from-transcript runs/dogfood.log --json-output report.json --markdown-output report.md

# Compare a persisted change's predictions with observed analysis and persist verdict.
ces harness verdict hchg-... --from-analysis report.json
```

Treat manifests, trajectory reports, and verdicts as review artifacts: keep evidence references
concise, avoid raw transcripts, and never include credentials or secret-looking values. Secret-like
manifest/report content is rejected or scrubbed before it can become part of the
harness substrate. Regression verdicts intentionally separate observed fixes from
observed and unexpected regressions so a net-positive summary cannot hide
regression blindness.

The `post_success_state` sensor protects green evidence after success. Callers can
pass `post_success_protected_files` snapshots with project-relative `path` and
`sha256` fields; if a protected file is deleted or modified, the sensor fails
unless the change is explicitly overridden **and** paired with revalidation. This
turns the paper's "post-success modification" risk into a local, deterministic
runtime guard without storing raw evidence contents.

The execution-risk monitor adds temporal command-sequence intelligence for
builder/evidence surfaces. It detects repeated identical failures, shallow/proxy
validation, timeout loops, destructive commands after success, and compile-only
validation for behavioral changes, then converts findings into the standard
`execution_risk_monitor` sensor result so builder reports and evidence packets can
carry severity and recommended next action.

## Expert Workflow

Use the expert workflow when you need explicit governance checkpoints or direct artifact control.

```bash
ces review
ces triage
ces approve --yes
ces report builder
```

If the latest builder session already knows the current manifest and evidence chain, `ces review`, `ces triage`, and `ces approve` can reuse that context directly. You can still pass explicit IDs when you need to target a different manifest or evidence packet.

When you are no longer operating one active request and instead need broad operator visibility or incident response, switch to the expert operations surfaces:

```bash
ces status --expert
ces status --expert --watch
ces audit --limit 20
ces emergency declare "Security incident detected"
```

Those commands sit outside the builder-first request loop. Follow the [Operations Runbook](Operations_Runbook.md) for incident drills, audit inspection patterns, and recovery expectations.

## Validation Evidence Surfaces

| Command | Best for | What it tells you |
|---------|----------|-------------------|
| `ces explain` | Plain-language builder recap | Current request, stage, blockers, and next step |
| `ces status` | Builder-first monitoring for one active request | Builder request, review state, latest outcome, activity, and brownfield progress |
| `ces status --expert` | System-wide expert status view | Broader CES status when you need more than the current builder chain |
| `ces review` | Review routing and summary | Reviewer assignments plus the active builder truth when the current builder chain is in scope |
| `ces triage` | Approval-readiness check | Triage color, reason, auto-approval eligibility, and current builder context |
| `ces approve` | Final operator decision | Approval/rejection plus the builder truth behind the current evidence chain |
| `ces report builder` | Audit and handoff | Exported markdown/json report with request, linked artifacts, review state, latest outcome, and next step |
| `ces next` | Production-readiness planning | Next maturity target, blockers, recommended command, and feature-work guidance |
| `ces next-prompt` | Agent prompt handoff | Scoped readiness prompt with validation commands, non-goals, secret-handling rule, and completion evidence expectations |
| `ces passport` | Readiness proof packet | Deterministic maturity, score, signals, blockers, warnings, missing signals, and evidence sources |
| `ces launch rehearsal` | Release-readiness rehearsal | Non-destructive validation plan and local smoke commands based on detected project type |
| `ces audit --limit 20` | Operator audit inspection | Event stream queries around incidents, recoveries, and other governance activity |

## Recommended Handoff Flow

Use this when another reviewer or operator needs the current story without opening the local store manually:

```bash
ces status
ces review
ces triage
ces report builder
```

That sequence gives you:

- the current builder request and stage
- the review-facing summary and assignments
- the triage decision for approval posture
- a portable builder run report in `.ces/exports/`

## Practical Rules

- Start with `ces build` unless you already know you need explicit manifest-level control.
- Stay in `builder-first` mode while CES is still gathering context, resuming work, or explaining the current request.
- Drop to the `expert workflow` when you need explicit review, triage, approval, manifest inspection, or exported audit/handoff artifacts.
- Use `ces status --expert`, `ces audit --limit 20`, and `ces emergency declare "Security incident detected"` when you need system-wide visibility or incident response rather than the current builder request story.
- Use `ces report builder` when the next person should consume a concise report instead of browsing raw local CES internals.
- Treat `ces explain` and `ces status` as the operator truth surfaces; expert commands should now agree with that builder truth when they target the current builder chain.
