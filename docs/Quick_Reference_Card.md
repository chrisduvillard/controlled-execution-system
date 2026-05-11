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
| Need independent verification | `ces verify` | Run local verification for the current project before approval; add `--write-contract` only when you want to persist an inferred contract |
| Need a read-only project-health diagnostic | `ces mri` | Review maturity, readiness score, detected signals, prioritized risks, missing production-readiness signals, and recommended next CES actions |
| Need the next readiness step or an agent handoff prompt | `ces next`, `ces next-prompt` | Keep the next agent request bounded to one safest production-readiness gap |
| Need a local readiness proof packet | `ces passport` | Summarize deterministic evidence, blockers, warnings, missing signals, and recommended promotion |
| Need plan-only maturity promotion | `ces promote production-candidate` | Plan one checkpoint at a time without bypassing governance or consent gates |
| Need constraints, slop findings, or rehearsal checks | `ces invariants`, `ces slop-scan`, `ces launch rehearsal` | Mine evidence-backed invariants, surface AI-native failure patterns, and rehearse validation without mutation |
| Need to inspect verification policy | `ces profile doctor` | Confirm which checks are required, optional, advisory, or unavailable before interpreting missing artifacts |
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

## 6. Harness evolution substrate

Harness evolution is local and explicit by default. The current substrate does
not autonomously modify CES behavior and does not inject runtime prompts.

```bash
ces harness init --dry-run
ces harness init
ces harness inspect
ces harness changes validate path/to/manifest.json
ces harness changes add path/to/manifest.json
ces harness changes list
ces harness changes show hchg-...
ces harness analyze --from-transcript runs/dogfood.log --json-output report.json --markdown-output report.md
ces harness verdict hchg-... --from-analysis report.json
```

Manifests must include predicted fixes, predicted regressions, validation plans,
and rollback conditions. Secret-looking content is rejected. Transcript analysis
emits compact reports with evidence pointers rather than raw transcript replay.
Verdicts persist predicted fixes observed/missed, predicted regressions observed,
unexpected regressions, and a keep/revise/rollback/inconclusive outcome.

---

## 7. Brownfield handoff

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

## 8. Completion evidence

Builder-created manifests require inspected repo context, verification command evidence, and configured completion-gate artifacts. A persisted `.ces/verification-profile.json` can classify checks as required, optional, advisory, or unavailable for the project. Missing artifacts for required checks such as `pytest-results.json`, `ruff-report.json`, or `mypy-report.txt` are blockers; missing optional/advisory/unavailable checks are relaxed by the missing-artifact policy. Present failing artifacts remain real sensor evidence rather than being treated as clean. Profile changes in the same reviewed run are treated as untrusted governance changes, so an agent cannot downgrade a required check and immediately approve against the weaker policy.

For the full policy format and command workflow, see [Verification Profiles](Verification_Profile.md).

Keep `.ces/` local unless you intentionally export a report. It can contain SQLite state, runtime transcripts, evidence, local keys, and audit records.

---

## 9. Spec authoring

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
