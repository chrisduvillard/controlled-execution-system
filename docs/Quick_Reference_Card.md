# CES Quick Reference Card

Open this when you need the shipped local CES workflow in 30 seconds.

CES is **not a sandbox** and not a hosted control plane. It is a local control, evidence, review, and recovery layer around Codex CLI or Claude Code execution. Runtime credentials, runtime sandboxing, source-control protections, deployments, and final operator judgment remain outside CES.

For the fuller workflow boundary, use the [Operator Playbook](Operator_Playbook.md). For setup, use the [Quickstart](Quickstart.md). Historical operating-model design archives live under [`historical/`](historical/) and are not the current public product contract.

---

## 1. Start here

| If you need to... | Stay builder-first or switch? | Supported CES surface | Why |
|---|---|---|---|
| Start or resume one delivery request | `builder-first` | `ces build`, `ces continue`, `ces explain`, `ces status` | CES keeps the active request and recovery path together |
| Diagnose or recover a blocked builder run | `builder-first` | `ces why`, `ces recover --dry-run`, `ces recover --auto-evidence`, `ces complete`, `ces verify` | Use these before rerunning work or approving a questionable state |
| Export a reviewer or audit handoff from the latest builder chain | `expert workflow` | `ces report builder` | Use a portable report when another operator needs the current builder story without opening CES internals |
| Take direct control of manifest, review, triage, or approval artifacts | `expert workflow` | `ces manifest`, `ces classify`, `ces review`, `ces triage`, `ces approve` | Use the lower-level governance surfaces directly when you need explicit operator control |
| Check brownfield context for the active request | `builder-first` | `ces explain --view brownfield` | Use the current builder summary before deciding whether you need an explicit legacy-behavior review |
| Make explicit brownfield legacy decisions | `expert workflow` | `ces brownfield register`, `ces brownfield review OLB-<entry-id> --disposition preserve`, `ces brownfield promote` | Day-to-day brownfield delivery stays builder-first; use these commands only for named legacy-behavior decisions, then refer to the [Brownfield Guide](Brownfield_Guide.md) for the full handoff |
| Monitor CES broadly or respond to incidents | `expert workflow` | `ces status --expert`, `ces status --expert --watch`, `ces audit --limit 20`, `ces emergency declare "Security incident detected"` | System-wide monitoring and emergency handling sit outside the single-request builder loop; use the [Operations Runbook](Operations_Runbook.md) for drills and recovery follow-up |

Use the [Operator Playbook](Operator_Playbook.md) when you need the fuller builder-first versus expert workflow boundary for a single request.

---

## 2. Runtime preflight

```bash
ces doctor
ces doctor --runtime-safety
# Optional: may contact the runtime provider and consume a small request.
ces doctor --verify-runtime --runtime all
```

Bare `ces doctor` is a preflight check. Use `--runtime-safety` for runtime boundary disclosures and `--verify-runtime` only when you deliberately want to probe Codex/Claude authentication.

---

## 3. Builder-first loop

```bash
ces build "Describe the change"
ces explain
ces status
ces continue
ces report builder
```

Typical operator flow:

1. Start with `ces build "<request>"`.
2. Read the review/evidence summary.
3. If blocked, run `ces why` and then `ces recover --dry-run` before retrying or completing manually.
4. Export `ces report builder` when another reviewer or audit trail needs the current builder story.
5. Start a new request only after the previous builder session has a clear terminal state.

Unattended `--yes` is still evidence-gated. CES should block auto-approval when completion evidence is incomplete, a blocking sensor fails, workspace deltas exceed scope, or the runtime boundary needs an explicit side-effect waiver.

---

## 4. Blocked or interrupted runs

| Symptom | First command | Follow-up |
|---|---|---|
| “Why is this blocked?” | `ces why` | Inspect category, source, reason, next command, and evidence snippets |
| Stale or incomplete evidence | `ces recover --dry-run` | If safe, use `ces recover --auto-evidence`; add `--auto-complete` only when the recovery plan explicitly supports completion |
| Work completed outside CES | `ces complete` | Reconcile externally completed builder work with the audit trail |
| Need independent verification | `ces verify` | Run local verification for the current project before approval |
| Need a handoff artifact | `ces report builder` | Share the exported markdown/JSON, not raw `.ces/state.db` |

---

## 5. Expert evidence workflow

Use expert commands when you need direct artifact control:

```bash
ces manifest "Fix null pointer in product search" --yes
ces classify M-<manifest-id>
ces execute M-<manifest-id> --runtime auto
ces review
ces triage
ces approve
```

Notes:

- `ces review` can target a manifest ID or use the current builder session manifest when omitted.
- `ces triage` and `ces approve` operate on evidence packets or the current builder session evidence when omitted.
- Prefer current-builder omission when you are continuing a builder-first chain; pass explicit IDs only when you are intentionally operating on a different artifact.

---

## 6. Brownfield handoff

Stay builder-first for normal brownfield work:

```bash
ces build "Add validation to the billing API"
ces explain --view brownfield
ces continue
```

Switch to brownfield expert commands only for named legacy-behavior decisions:

```bash
ces brownfield register --system legacy-billing --description "Invoices above $1000 receive a 5% discount"
ces brownfield review OLB-<entry-id> --disposition preserve
ces brownfield promote OLB-<entry-id>
```

See the [Brownfield Guide](Brownfield_Guide.md) for the full register → review → promote handoff.

---

## 7. Completion evidence

Builder-created manifests require inspected repo context, verification command evidence, and configured completion-gate artifacts. Missing `pytest-results.json`, `ruff-report.json`, `mypy-report.txt`, or `coverage.json` is missing evidence, not a passing check. `pip-audit-report.json` and SAST JSON artifacts give CES deterministic dependency/security findings when those risks are in scope.

Keep `.ces/` local unless you intentionally export a report. It can contain SQLite state, runtime transcripts, evidence, local keys, and audit records.

---

## 8. Spec authoring

Turn a PRD into governed manifest drafts for the `ces build` pipeline.

```bash
ces spec author                                       # Interactive authoring
ces spec author --polish                              # Same, with optional LLM polish on long-form fields
ces spec import path/to/prd.md                        # Import existing PRD
ces spec import path/to/prd.md --no-llm               # Deterministic header match only
ces spec validate docs/specs/my.md                    # Structural checks
ces spec decompose docs/specs/my.md                   # Create one manifest per story
ces spec reconcile docs/specs/my.md                   # Diff spec vs. existing manifests
ces spec tree docs/specs/my.md                        # Show spec + manifest workflow status
ces build --from-spec docs/specs/my.md --story ST-01  # Preview build order
```

See `docs/designs/2026-04-21-ces-spec-authoring.md` for full design.
