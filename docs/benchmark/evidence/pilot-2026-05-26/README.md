# Pilot 2026-05-26 benchmark evidence

Status: runtime-preflight-blocked.

This folder is not CES-vs-vanilla product evidence. It records a safe attempt to start a three-scenario measured A/B pilot and the runtime blockers that prevented honest measurement on this host.

## Planned scenarios

The planned pilot used three scenarios from `pilot-plan.json`:

1. `greenfield-python-cli` - small standard-library task tracker CLI.
2. `greenfield-text-stats` - standard-library text statistics CLI.
3. `brownfield-calculator-bugfix` - seeded regression fix with behavior-preservation checks.

Each scenario was intended to run in a fresh isolated temp workspace with one direct runtime arm and one CES-governed arm.

## Preflight result

`ces benchmark preflight --probe-runtime` reported `runtime-blocked` for both runtime candidates:

- Codex was installed, but the workspace write probe did not create the probe file. The observed blocker was `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`, followed by failed file-write attempts inside the benchmark workspace.
- Claude Code was installed, but the workspace write probe failed because runtime authentication or entitlement was unavailable on this host.

The sanitized machine-readable outputs are committed at:

- `preflight/codex.json`
- `preflight/claude.json`

## Decision

No measured A/B scorecard was produced. Filling `completion`, time, test, or auditability fields from these failed attempts would be inferred evidence, not measured product evidence.

The next measured benchmark run should begin only after at least one runtime preflight returns `runtime-ready` in the benchmark workspace. If Codex requires sandbox bypass to write on this host, that must be approved and labelled separately because it changes the runtime boundary being benchmarked.
