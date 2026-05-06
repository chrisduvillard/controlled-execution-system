# Getting Started with CES

> **Want the fastest path?** See the [5-Minute Quickstart](Quickstart.md).

CES is a local builder-first tool. This guide shows the full supported setup:
install CES, verify a local runtime, and use the builder-first plus expert
workflow surfaces inside one repository.

## 1. Install CES

```bash
git clone https://github.com/chrisduvillard/controlled-execution-system.git
cd controlled-execution-system
uv sync
uv run ces --help
```

If you are working from a source checkout, use `uv run ces ...` unless you have
installed the package as a tool. For normal day-to-day use, prefer the PyPI tool
install shown in the Quickstart.

## 2. Verify a Local Runtime

```bash
uv run ces doctor
```

You need `codex` or `claude` on PATH for real local execution. `CES_DEMO_MODE=1`
can help with optional LLM-backed assistant flows, but it does not replace the
runtime requirement for `ces build` or `ces execute`.

## 3. Start in Your Repo

```bash
mkdir freshcart && cd freshcart
ces build "Fix null pointer in product search when category is empty"
```

`ces build` is the default entrypoint. It creates or resumes the local builder
session, gathers only the missing context, runs the change, shows plain-language
review output, and points you to the next action.

If you prefer manual setup before your first build, CES still supports:

```bash
ces init freshcart
```

## 4. Continue the Builder-First Flow

```bash
ces continue
ces explain
ces explain --view decisioning
ces explain --view brownfield
```

`ces continue` resumes the latest saved builder session from the right stage. If
the session is already complete, CES tells you to start a new request with
`ces build` instead of replaying the old one.

Add `--governance` when you want manifest IDs, risk tiers, and triage detail.
Add `--export-prl-draft` to write a lightweight PRL-style draft into `.ces/exports/`.

## 5. Monitor Status

```bash
ces status
```

The default status view answers:
- what you asked CES to build
- whether the repo is being treated as greenfield or brownfield
- what stage the current builder session is in
- what the current review state and latest outcome are
- what CES did most recently
- whether there is grouped brownfield progress or pending brownfield work
- what the next action is

Use `ces status --expert` for the full expert view.

## 6. Choose Builder-First vs Expert Workflow

Use `builder-first` when you want CES to keep the active request, artifacts, and
recovery path together:

- `ces build` to start a request
- `ces continue` to resume the same request
- `ces explain` and `ces status` to understand the current builder truth
- `ces why`, `ces recover --dry-run`, `ces verify`, and `ces complete` when the current builder run is blocked, interrupted, missing evidence, or finished outside CES

For brownfield work, keep the day-to-day delivery loop builder-first with
`ces build`, `ces continue`, and `ces explain --view brownfield`. Switch into the
expert brownfield commands only when you need to register, review, or promote a
named legacy behavior yourself. The [Brownfield Guide](Brownfield_Guide.md)
covers that boundary in more detail.

Use the `expert workflow` when you need explicit governance control over review,
triage, approval, manifest lifecycle, or exported handoff artifacts:

- `ces manifest` and `ces classify` for explicit manifest-first work
- `ces execute`, `ces review`, `ces triage`, and `ces approve` for direct execution and review control
- `ces report builder` for an audit/reviewer handoff artifact from the latest builder session

When you leave the single-request builder loop and need system-wide visibility
or incident response, switch to the expert operations surfaces instead of
relying on builder-first `ces status`:

```bash
ces status --expert
ces status --expert --watch
ces audit --limit 20
ces emergency declare "Security incident detected"
```

The [Operations Runbook](Operations_Runbook.md) covers incident drills and
recovery expectations for those commands.

The [Operator Playbook](Operator_Playbook.md) has the decision table and
recommended command sequences.

## 7. Expert Workflow

If you want the explicit manifest-first flow, CES still supports it:

```bash
ces manifest "Fix null pointer in product search when category is empty" --yes
ces classify M-<manifest-id>
```

Shows classification confidence with color coding:
- Green (>90%): Auto-accepted
- Yellow (70-90%): Human review recommended
- Red (<70%): Manual classification required

## 8. Execute the Agent Task

```bash
ces execute M-<manifest-id> --runtime auto
```

The selected runtime executes locally. CES records the manifest, expected scope, evidence, and workspace delta; Claude receives an allowed-tools list, while Codex runs under its disclosed local sandbox mode and is governed by CES evidence/delta gates rather than manifest tool allowlist enforcement.

Because Codex cannot enforce manifest tool allowlists before its subprocess starts, builder-first and direct execute commands fail closed before Codex launch unless you pass `--accept-runtime-side-effects`. Use that flag only when you explicitly accept the full-access runtime boundary; prefer Claude Code when runtime-level tool allowlist enforcement is required.

## 9. Review the Evidence

```bash
ces review M-<manifest-id>
# Or, if the current builder session already owns the manifest/evidence chain:
ces review
```

Shows:
- 10-line evidence summary
- 3-line adversarial challenge
- Reviewer assignments
- the current builder truth when the active builder session matches the review target

## 10. Triage the Evidence

```bash
ces triage M-<manifest-id>
# Or reuse the current builder chain:
ces triage
```

Returns GREEN / YELLOW / RED based on the current triage matrix.

## 11. Approve or Reject

```bash
ces approve M-<manifest-id>
ces approve M-<manifest-id> --yes
ces approve --yes
```

Records the decision in the append-only audit ledger.

## 12. When a Builder Run Is Blocked

```bash
ces why
ces recover --dry-run
ces verify
ces complete
```

Use `ces why` to inspect the blocker category, reason, source, and next command.
Use `ces recover --dry-run` before mutating CES state. Use `ces verify` when you
need independent local verification, and `ces complete` only when the work was
actually completed outside CES and you need to reconcile that fact with the audit
trail.

## 13. Export a Builder Run Report

```bash
ces report builder
```

This writes paired markdown and JSON artifacts under `.ces/exports/` with the
request, linked artifacts, review state, latest outcome, and next step.

## 14. Brownfield Expert Commands

```bash
ces brownfield register --system legacy-billing --description "Invoices above $1000 receive a 5% discount"
ces brownfield list
ces brownfield review OLB-<entry-id> --disposition preserve
ces brownfield promote OLB-<entry-id>
```

## CLI Command Reference

| Command | Purpose |
|---------|---------|
| `ces build <desc>` | Default builder-first flow |
| `ces continue` | Resume the latest saved builder session |
| `ces explain` | Plain-language summary of the latest builder state; use `--view` for decisioning or brownfield detail |
| `ces status` | Builder-first project status; add `--expert` for the full expert view |
| `ces why` | Explain why the latest builder run is blocked and show the next command |
| `ces recover --dry-run` | Preview recovery before mutating CES state |
| `ces verify` | Run independent local verification for the current project |
| `ces complete` | Reconcile externally completed builder work with the audit trail |
| `ces report builder` | Export the latest builder run report for audit or reviewer handoff |
| `ces init <name>` | Optional manual setup before the first build |
| `ces manifest <desc>` | Create a task manifest |
| `ces classify <id>` | Classify a manifest |
| `ces execute <id>` | Execute agent task |
| `ces review <id>` | Run review pipeline |
| `ces triage <id>` | Pre-screen evidence |
| `ces approve <id>` | Approve/reject evidence |
| `ces gate <phase> <scope>` | Evaluate phase gate |
| `ces intake <phase>` | Run intake interview |
| `ces vault query <topic>` | Query knowledge vault |
| `ces vault write <cat>` | Write vault note |
| `ces vault health` | Vault health check |
| `ces audit` | Expert operations audit inspection; for example, `ces audit --limit 20` |
| `ces emergency declare` | Expert operations emergency declaration; for example, `ces emergency declare "Security incident detected"` |
| `ces brownfield ...` | Expert legacy behavior capture, review, and promotion |

Use the global form `ces --json <command>` for machine-readable output. Some commands also expose command-local `--json` flags where documented.

## Architecture Overview

```
CLI (Typer)          Governance + Harness             Execution Plane
┌─────────────┐     ┌──────────────────────────┐     ┌────────────────────┐
│ ces build    │────▶│ ClassificationOracle     │     │ AgentRunner        │
│ ces continue │     │ ManifestManager          │     │ RuntimeRegistry    │
│ ces execute  │     │ AuditLedgerService       │     │ Codex / Claude     │
│ ces review   │     │ WorkflowEngine           │     │ Runtime helpers    │
│ ces approve  │     │ KillSwitchService        │     │ Output capture     │
└─────────────┘     │ GateEvaluator            │     └────────────────────┘
                    │ ReviewRouter             │
                    │ SensorOrchestrator       │
                    └──────────────────────────┘

Local State: `.ces/config.yaml` + `.ces/state.db`
```

## Next Steps

- Read the [Production Deployment Guide](Production_Deployment_Guide.md) for workstation/CI rollout guidance
- Read the [Operations Runbook](Operations_Runbook.md) for emergency procedures
- Read the [Operator Playbook](Operator_Playbook.md) for builder-first vs expert workflow guidance
- Read the historical [PRD](historical/PRD.md) for the archived specification
