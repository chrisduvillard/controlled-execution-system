# Operator Playbook

This playbook explains when to stay in the builder-first CES flow, when to switch to the expert workflow, and how to read the validation evidence surfaces that CES ships today (Agent-Native Software Delivery Operating Model v4).

## Choose Your Path

| Situation | Recommended path | Why |
|-----------|------------------|-----|
| You are starting a new request and want CES to gather context for you | `builder-first` | CES can collect missing constraints, preserve brownfield expectations, and move the current session forward without you wiring every artifact ID manually |
| You paused a request and want to resume it | `builder-first` | `ces continue` resumes the saved builder session instead of replaying the whole setup |
| You want a plain-language summary of what CES knows right now | `builder-first` | `ces explain` and `ces status` are the shortest path to the current request, stage, blockers, and next step |
| You need brownfield context for the active request before making any legacy call | `builder-first` | `ces explain --view brownfield` keeps the current request and grouped review state visible before you drop into explicit brownfield governance |
| You need explicit governance control over review, triage, approval, or manifest lifecycle | `expert workflow` | `ces review`, `ces triage`, `ces approve`, `ces manifest`, and `ces classify` expose the lower-level governance surfaces directly |
| You need to make a named legacy-behavior decision | `expert workflow` | `ces brownfield register`, `ces brownfield review OLB-<entry-id> --disposition preserve`, and `ces brownfield promote` are the explicit brownfield governance surfaces after the builder-first loop identifies the behavior |
| You need an audit or reviewer handoff artifact | `expert workflow` | `ces report builder` exports a concise builder run report from the latest builder session chain |
| You need system-wide visibility, live incident monitoring, or audit inspection | `expert workflow` | `ces status --expert`, `ces status --expert --watch`, `ces audit --limit 20`, and `ces emergency declare "Security incident detected"` are the supported operator surfaces; use the Operations Runbook when you leave the single-request builder loop |

## Builder-First Flow

Use the builder-first flow when you want CES to keep the operator context together around one active request.

```bash
# First run in a repo is enough; CES bootstraps local state if `.ces/` is missing
ces build "Add invoice notes to billing exports" --yes

# Resume or retry the same request
ces continue --yes

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

For day-to-day brownfield delivery, stay builder-first with `ces build`, `ces continue`, and `ces explain --view brownfield`. Switch into the expert brownfield commands only when you need to make a named legacy-behavior decision such as `ces brownfield review OLB-<entry-id> --disposition preserve`. The [Brownfield Guide](Brownfield_Guide.md) covers that handoff in more detail.

If you want manual setup before the first builder-first run, use `ces init <name>`. It is no longer required for the default flow.

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
