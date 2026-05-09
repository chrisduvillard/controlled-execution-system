<div align="center">

# Controlled Execution System

[![CI](https://github.com/chrisduvillard/controlled-execution-system/actions/workflows/ci.yml/badge.svg)](https://github.com/chrisduvillard/controlled-execution-system/actions/workflows/ci.yml)
[![Publish](https://github.com/chrisduvillard/controlled-execution-system/actions/workflows/publish.yml/badge.svg)](https://github.com/chrisduvillard/controlled-execution-system/actions/workflows/publish.yml)
[![PyPI](https://img.shields.io/pypi/v/controlled-execution-system.svg)](https://pypi.org/project/controlled-execution-system/)
[![Python](https://img.shields.io/pypi/pyversions/controlled-execution-system.svg)](https://pypi.org/project/controlled-execution-system/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

<img src="docs/assets/ces-avatar.png" alt="Controlled Execution System project avatar" width="300">

**Local-first governance for AI coding agents.**

Turn an intent into a bounded manifest, execute it through Codex CLI or Claude Code,<br>
collect evidence, review the result, and make approval explicit.

[5-Minute Quickstart](docs/Quickstart.md) ·
[Getting Started](docs/Getting_Started.md) ·
[Operator Playbook](docs/Operator_Playbook.md) ·
[Quick Reference](docs/Quick_Reference_Card.md) ·
[Verification Profile](docs/Verification_Profile.md) ·
[Changelog](CHANGELOG.md)

<br>

<a href="docs/assets/ces-demo.mp4">
  <img src="docs/assets/ces-demo.gif" alt="20-second CES explainer demo" width="760">
</a>

<sub>Click the animation to open the MP4.</sub>

</div>

---

## What CES is

CES is a safety and evidence layer around local AI coding tools.

You describe the change. CES turns that request into a governed work order, runs the work through a supported local runtime, checks what changed, asks for evidence, records the audit trail, and helps you decide whether to approve the result.

It is deliberately local and operator-first: project state lives under `.ces/`; runtime credentials stay with your installed `codex` or `claude` CLI; final judgment stays with you.

| CES is | CES is not |
|---|---|
| A local CLI for governed AI-assisted software delivery | A hosted control plane |
| A manifest, evidence, review, recovery, and approval workflow | A replacement for source control, CI, or human review |
| SQLite-backed project state under `.ces/` | A required Postgres/Redis service for normal local use |
| A wrapper around Codex CLI and Claude Code | A runtime credential manager or universal sandbox |

> [!IMPORTANT]
> CES is not a sandbox. It governs the workflow around local runtime execution, records evidence, and enforces approval gates. Runtime sandboxing, credentials, repo protections, deployments, and final operator responsibility remain outside CES.

### Why trust this release?

CES is built and shipped through its own public control surfaces: CI runs the local-first test suite, package build, metadata checks, dependency audit, lint, formatting, and typecheck gates; release publishing adds installed-CLI smoke coverage before PyPI publication. The repository also carries a CES dogfood gauntlet so the project can review its own changes instead of treating governance as a brochure claim.

The boundary is intentionally narrow. CES is not a hosted control plane, not a substitute for source control or CI, and not a substitute for the runtime's own credentials, authentication, or sandboxing. It gives operators a local evidence trail: `ces:completion` claims, verification artifacts, audit entries, and workspace delta inspection before approval.

---

## Quick start

### Prerequisites

| Need | Notes |
|---|---|
| Python | 3.12 or 3.13 |
| Package tool | [`uv`](https://docs.astral.sh/uv/) |
| Local runtime | Codex CLI or Claude Code installed, authenticated, and on `PATH` |

### Install from PyPI

```bash
uv tool install controlled-execution-system
uv tool update-shell
ces --help
```

If your ambient `python3` is Python 3.11, direct `pip install controlled-execution-system` may fail with `No matching distribution` before CES starts because the package requires Python 3.12 or 3.13. Ask `uv` for a supported interpreter explicitly:

```bash
uv tool install --python 3.13 controlled-execution-system
```

Install or pin a specific release:

```bash
uv tool install controlled-execution-system==0.1.13
```

Upgrade later:

```bash
uv tool upgrade controlled-execution-system
```

### Verify the runtime boundary

```bash
ces doctor
ces doctor --runtime-safety
# Optional: may contact the runtime provider and consume a small request.
ces doctor --verify-runtime --runtime all
```

`ces build` and `ces execute` require Codex CLI or Claude Code. `CES_DEMO_MODE=1` only affects optional helper/provider behavior; it does not replace the local execution runtime.

### First governed run

Run CES from the repository you want to govern:

```bash
cd path/to/your-project
ces build "Add a healthcheck endpoint that returns JSON status"
```

On first use, CES creates `.ces/` in that project, gathers missing context, drafts the manifest, executes through the selected local runtime, checks the workspace delta, records evidence, and shows the next operator action.

If you prefer to initialize state manually first:

```bash
ces init my-project
ces doctor
ces doctor --runtime-safety
```

---

## How CES works

```text
Intent ──▶ Manifest ──▶ Runtime ──▶ Evidence ──▶ Review ──▶ Approval
  │           │            │            │           │           │
  │           │            │            │           │           └─ explicit operator decision
  │           │            │            │           └─ adversarial and policy-aware review
  │           │            │            └─ verification artifacts + workspace delta
  │           │            └─ Codex CLI or Claude Code subprocess
  │           └─ bounded scope, tools, acceptance criteria, risk context
  └─ natural-language request from the operator
```

| Stage | What happens | Operator value |
|---|---|---|
| Intent | You describe the change in plain language. | Fast entry; no manifest authoring required for normal work. |
| Manifest | CES captures scope, allowed work, acceptance criteria, and governance context. | The runtime gets a bounded assignment instead of an open-ended prompt. |
| Runtime | CES launches a supported local AI coding runtime. | Work happens in your repo, using your local tool configuration. |
| Evidence | CES records artifacts, completion claims, verification results, transcripts, and workspace delta. | Approval is tied to proof, not confidence. |
| Review | CES summarizes the result, flags blockers, and routes evidence through review/triage surfaces. | You see what matters before approving. |
| Approval | The decision is recorded in the local audit trail. | The delivery history is inspectable later. |

Local state is stored in the governed project:

| Path | Purpose |
|---|---|
| `.ces/config.yaml` | Project metadata and local execution settings |
| `.ces/state.db` | SQLite store for manifests, audit entries, evidence, sessions, and local records |
| `.ces/keys/` | Project-local signing and audit integrity keys |
| `.ces/artifacts/` | Runtime and evidence artifacts |
| `.ces/exports/` | Builder reports and exported handoff files |
| `.ces/baseline/` | Day-0 sensor snapshots |
| `.ces/verification-profile.json` | Optional project-aware verification policy for required, optional, advisory, and unavailable checks |

Keep local `.ces/` state untracked unless you intentionally share an exported report. A repository may intentionally track `.ces/verification-profile.json` when the team wants a shared verification policy.

---

## Operator workflow

Start with the builder-first loop for almost all delivery work:

```bash
ces build "Describe the change"
ces explain
ces status
ces continue
ces report builder
```

| Command | Use it for |
|---|---|
| `ces build "<request>"` | Start a governed local task from a natural-language request. |
| `ces continue` | Resume the latest saved builder session from the right stage. |
| `ces explain` | Read the current request, blockers, evidence, and next step. |
| `ces explain --view decisioning` | Inspect the governance decision path for the active request. |
| `ces explain --view brownfield` | Inspect existing-behavior context for the active request. |
| `ces status` | Show concise builder-first project status without mutating local state. |
| `ces why` | Explain why the latest builder run is blocked and show the next command. |
| `ces recover --dry-run` | Preview recovery for stale, interrupted, or incomplete evidence states. |
| `ces verify` | Run independent local verification without writing inferred contracts by default. |
| `ces complete` | Reconcile work that was actually completed outside CES. |
| `ces report builder` | Export markdown and JSON handoff reports under `.ces/exports/`. |

When a run blocks, use this sequence before rerunning work or approving anything manually:

```bash
ces why
ces recover --dry-run
ces verify
ces report builder
```

Use expert workflow commands when you need direct artifact control:

| Command group | Use it for |
|---|---|
| `ces manifest` / `ces classify` | Create and classify manifests directly. |
| `ces execute` | Run a manifest-bound local agent task. |
| `ces review` / `ces triage` / `ces approve` | Inspect evidence and make approval decisions directly. |
| `ces audit` | Inspect the local audit ledger, for example `ces audit --limit 20`. |
| `ces status --expert` | Show the full expert status view; use `ces status --expert --watch` for live monitoring. |
| `ces emergency declare` | Record an expert operations emergency declaration, for example `ces emergency declare "Security incident detected"`. |
| `ces scan` / `ces baseline` | Inventory the repo and capture day-0 sensor snapshots. |
| `ces profile detect/show/doctor` | Detect, persist, and inspect project-aware verification requirements. |
| `ces brownfield ...` | Capture, review, and promote named legacy behavior decisions. |
| `ces spec ...` | Author, validate, decompose, reconcile, or inspect specs. |
| `ces setup-ci` | Generate GitHub or GitLab CI gating workflow templates. |
| `ces dogfood` | Use CES to review changes to this repository. |

Brownfield work starts with builder-first context, then uses explicit legacy-behavior decisions when needed:

```bash
ces explain --view brownfield
ces brownfield review OLB-<entry-id> --disposition preserve
```

Commands with machine-readable output support the global JSON form where applicable:

```bash
ces --json status
ces status --json
```

---

## Runtime safety

CES is intentionally explicit about the runtime boundary.

| Safety behavior | What to remember |
|---|---|
| Unsafe runtimes require explicit consent | `ces build`, `ces continue`, and `ces execute` fail closed before launching a runtime that cannot enforce manifest tool allowlists unless you pass `--accept-runtime-side-effects`. |
| `--yes` is not side-effect consent | Unattended approval does not imply permission to launch an unsafe runtime boundary. You still need `--accept-runtime-side-effects`. |
| `ces status` is read-only by default | It displays builder-first state without refreshing stale sessions. Use `ces status --reconcile` only when you explicitly want state reconciliation before display. |
| `ces verify` does not write inferred contracts by default | It reads an existing completion contract when present; otherwise it verifies against an inferred in-memory contract. Use `ces verify --write-contract` only when you want to persist it. |
| `ces scan --dry-run` is non-mutating | It previews repository inventory without bootstrapping local state or writing `.ces/brownfield/scan.json`. |

Codex is disclosed as a full-access local runtime for CES purposes. CES can review its output and workspace delta after execution, but the Codex adapter does not enforce manifest tool allowlists before the subprocess starts. Prefer Claude Code when you need runtime-level tool allowlist enforcement.

Unattended `--yes` runs remain evidence-gated. CES should block auto-approval when completion evidence is incomplete, required verification artifacts are missing, workspace deltas exceed scope, blocking sensors fail, or the runtime boundary needs an explicit side-effect waiver.

---

## Core commands

| Command | Purpose |
|---|---|
| `ces --help` | Show CLI help and command groups. |
| `ces doctor` | Run preflight checks for Python, providers, extras, and project setup. |
| `ces doctor --runtime-safety` | Show runtime-boundary disclosures. |
| `ces build "<request>"` | Default builder-first governed delivery path. |
| `ces continue` | Resume the latest builder session. |
| `ces explain` | Summarize request, blockers, evidence, and next step. |
| `ces status` | Show read-only builder-first status by default. |
| `ces why` | Diagnose a blocked builder run. |
| `ces recover --dry-run` | Preview recovery before mutation. |
| `ces verify` | Independently verify the current project. |
| `ces complete` | Reconcile externally completed work. |
| `ces report builder` | Export the latest builder handoff report. |
| `ces manifest "<request>"` | Create a task manifest directly. |
| `ces classify M-<manifest-id>` | Classify manifest risk and routing. |
| `ces execute M-<manifest-id>` | Execute a manifest-bound task locally. |
| `ces review` / `ces triage` / `ces approve` | Review, screen, and decide on evidence. |
| `ces scan --dry-run` | Preview repository inventory without mutation. |
| `audit` | Expert operations audit inspection; use `ces audit --limit 20` to inspect recent ledger events. |
| `emergency declare` | Expert operations emergency declaration; for example `ces emergency declare "Security incident detected"`. |
| `brownfield ...` | Expert legacy behavior capture, review, and promotion. Use `ces brownfield review OLB-<entry-id> --disposition preserve` for a named legacy-behavior decision. |
| `ces spec ...` | Work with governed specs and manifest drafts. |

For the complete command boundary, use the [Quick Reference Card](docs/Quick_Reference_Card.md) and [Operator Playbook](docs/Operator_Playbook.md).

---

## Development

Work from source when developing CES itself:

```bash
git clone https://github.com/chrisduvillard/controlled-execution-system.git
cd controlled-execution-system
uv sync
uv run ces --help
```

If `ces` is not active in your shell while you are inside a source checkout, use `uv run ces ...`.

Run the local-first verification gate:

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/ces/ --ignore-missing-imports
uv run pytest tests/ -m "not integration" --cov=ces --cov-fail-under=90 --cov-report=term-missing -q -W error
uv build
uvx twine check dist/*
```

Run local integration tests:

```bash
uv sync --group ci
uv run pytest tests/ -m integration -q
```

Builder-created manifests expect command-backed completion evidence. When completion-gate sensors are enabled, produce matching artifacts before claiming completion: `pytest-results.json`, `ruff-report.json`, `mypy-report.txt`, and `coverage.json`. Dependency and security-sensitive changes can also be backed by `pip-audit-report.json` and SAST JSON artifacts such as `bandit-report.json`; CES parses those when present.

PyPI publishing is tag-driven. Pushing to `master` runs CI only; pushing a `v*` tag such as `v0.1.13` triggers `.github/workflows/publish.yml`, which runs tests, builds distributions, smoke-tests the installed CLI, validates tag/version agreement, and publishes through trusted publishing. Follow [docs/RELEASE.md](docs/RELEASE.md) for the maintainer checklist.

---

## Documentation map

| Document | Start here when you need |
|---|---|
| [5-Minute Quickstart](docs/Quickstart.md) | The shortest local builder-first path. |
| [Getting Started](docs/Getting_Started.md) | Full setup and workflow walkthrough. |
| [Operator Playbook](docs/Operator_Playbook.md) | Builder-first versus expert workflow boundaries. |
| [Brownfield Guide](docs/Brownfield_Guide.md) | Existing-codebase and legacy-behavior governance. |
| [Operations Runbook](docs/Operations_Runbook.md) | Expert status, audit, and emergency operations. |
| [Quick Reference Card](docs/Quick_Reference_Card.md) | Command and gate lookup tables. |
| [Troubleshooting](docs/Troubleshooting.md) | Common local setup and runtime issues. |
| [Release Runbook](docs/RELEASE.md) | Maintainer release checklist. |

Historical server-oriented docs live under `docs/historical/` as design archives, not as the current product contract. Current design and plan records live under `docs/designs/` and `docs/plans/`.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development workflow, tests, and contribution expectations. Security-sensitive issues should follow [SECURITY.md](SECURITY.md).

If you use external agent loops such as `gnhf`, keep them outside CES itself as contributor tooling rather than part of the product. Run them from a clean sibling worktree or clean clone, keep the scope away from manifest/policy, approval/triage/review, audit, kill-switch, and runtime-boundary changes, and review every generated branch manually before using it. Follow the [GNHF Trial Guide](docs/GNHF_Trial_Guide.md) and [`scripts/gnhf_trial.sh`](scripts/gnhf_trial.sh); CES's own builder-first or expert workflows remain the delivery path.

## License

MIT. See [LICENSE](LICENSE).
