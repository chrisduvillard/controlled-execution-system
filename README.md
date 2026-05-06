# Controlled Execution System (CES)

[![CI](https://github.com/chrisduvillard/controlled-execution-system/actions/workflows/ci.yml/badge.svg)](https://github.com/chrisduvillard/controlled-execution-system/actions/workflows/ci.yml)
[![Publish](https://github.com/chrisduvillard/controlled-execution-system/actions/workflows/publish.yml/badge.svg)](https://github.com/chrisduvillard/controlled-execution-system/actions/workflows/publish.yml)
[![PyPI](https://img.shields.io/pypi/v/controlled-execution-system.svg)](https://pypi.org/project/controlled-execution-system/)
[![Python](https://img.shields.io/pypi/pyversions/controlled-execution-system.svg)](https://pypi.org/project/controlled-execution-system/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

<p align="center">
  <img src="docs/assets/ces-avatar.png" alt="Controlled Execution System project avatar" width="320">
</p>

Local-first governance for AI agent-driven software delivery.

CES is a command-line tool that keeps AI-assisted changes inside an auditable
workflow. Describe the change you want, and CES turns it into a bounded
manifest, runs it through a supported local runtime, reviews the result,
records evidence, and stores project state under `.ces/`.

## In Plain English

CES is a safety wrapper for AI coding agents.

When you ask Codex CLI or Claude Code to change a codebase, the agent can start
editing files right away. That is useful, but it can also be risky: the agent
might misunderstand the task, change too many files, skip tests, or say it is
finished without proving that the result works.

CES adds a controlled workflow around that process. You give CES a coding
request, CES turns it into a clear work order, and then a local AI coding tool
does the implementation. Afterward, CES checks what changed, asks for evidence,
records what happened, and helps you decide whether to accept the work.

Think of Codex or Claude Code as a student writing an assignment. CES is the
rubric and supervision system around that assignment. It asks:

- What exactly is the task?
- Which files is the agent allowed to touch?
- What counts as done?
- Did the agent prove the result works?
- Were tests or checks run?
- What changed, and should a human approve it?

CES is not trying to replace coding agents. It is trying to make their work
safer, clearer, and easier to trust.

The default product shape is deliberately small:

| CES is | CES is not |
|---|---|
| Local-first CLI governance | A hosted control plane |
| Builder-first operator workflow | A managed service platform |
| Repo-local SQLite state under `.ces/` | A required Postgres or Redis service |
| Local runtime execution through Codex CLI or Claude Code | A replacement for your runtime credentials |

CES is trying to make AI coding accountable, not just smarter. Tools such as
GSD, BMAD Method, and Superpowers can improve how an agent plans, reasons, or
follows engineering habits; CES wraps the resulting work in a local execution
contract with saved state, evidence, review, approval, and audit history.

## Why trust this release?

The `0.1.12` release line was hardened through a real operator dogfood gauntlet
before public sharing: greenfield project creation, brownfield discovery and
review, interrupted-runtime recovery, continuation, status/report export,
installed-package smokes, and sequential regression-fix PRs. The resulting fixes
covered runtime process cleanup, `--project-root` consistency, explicit recovery
no-op messaging, runtime transcript visibility, brownfield report wording, and
Python 3.11 install guidance.

CES is intentionally honest about its boundary: it is a local governance and
evidence system around Codex CLI or Claude Code, not a hosted control plane, not a sandbox, and
not a substitute for the runtime's own credentials, sandboxing, or human review.

[Quickstart](docs/Quickstart.md) |
[Getting Started](docs/Getting_Started.md) |
[Operator Playbook](docs/Operator_Playbook.md) |
[Brownfield Guide](docs/Brownfield_Guide.md) |
[Operations Runbook](docs/Operations_Runbook.md) |
[Release Runbook](docs/RELEASE.md)

## Install

Prerequisites:

- Python 3.12 or 3.13
- [uv](https://docs.astral.sh/uv/)
- A local agent runtime on `PATH`: Codex CLI or Claude Code

Install the published CLI:

```bash
uv tool install controlled-execution-system
uv tool update-shell
ces --help
```

On machines where the ambient `python3` is Python 3.11, `pip install controlled-execution-system` can fail before CES starts with a resolver message such as `No matching distribution` because the published package requires Python 3.12 or 3.13. Ask uv to create the tool environment with a supported interpreter explicitly, such as Python 3.13:

```bash
uv tool install --python 3.13 controlled-execution-system
```

Install a pinned release:

```bash
uv tool install controlled-execution-system==0.1.12
```

Upgrade an existing install:

```bash
uv tool upgrade controlled-execution-system
```

Work from source when developing CES itself:

```bash
git clone https://github.com/chrisduvillard/controlled-execution-system.git
cd controlled-execution-system
uv sync
uv run ces --help
```

If `ces` is not active in your shell while you are inside a source checkout,
use `uv run ces ...`.

## First Governed Build

Run CES from the project you want to govern:

```bash
ces build "Add a healthcheck endpoint that returns JSON status"
```

On first use, CES creates `.ces/` in that project. It then gathers missing
context, drafts the governance contract, executes through the local runtime,
requires completion evidence for the acceptance criteria, reviews the result,
checks the actual workspace delta, and records the evidence trail.

If you want to initialize local state explicitly:

```bash
ces init my-project
ces doctor
ces doctor --runtime-safety
```

`ces build` and `ces execute` need a real local runtime. `CES_DEMO_MODE=1`
only affects optional helper/provider behavior; it does not replace Codex CLI
or Claude Code for local execution.

Codex is disclosed as a full-access local runtime: CES can review its output and
workspace delta after execution, but the Codex adapter does not enforce manifest
tool allowlists before the subprocess runs. `ces build`, `ces continue`, and
`ces execute` therefore fail closed before launching Codex unless you pass
`--accept-runtime-side-effects`. Prefer Claude Code when you need runtime-level
tool allowlist enforcement.

## How The Loop Works

```text
request
  -> builder brief
  -> manifest and governance context
  -> local runtime execution
  -> review and evidence
  -> operator decision or next step
```

Start with the builder-first loop for normal work:

| Command | Use it for |
|---|---|
| `ces build "<request>"` | Start a governed local task from a natural-language request |
| `ces continue` | Resume the latest saved builder session |
| `ces explain` | Read the current request, blockers, evidence, and next step |
| `ces explain --view decisioning` | Inspect the governance decision path for the active request |
| `ces explain --view brownfield` | Inspect existing-behavior context for the active request |
| `ces status` | Show concise builder-first project status without mutating local state |
| `ces why` | Explain why the latest builder run is blocked and show the next command |
| `ces recover --dry-run` | Preview recovery for stale, interrupted, or incomplete evidence states |
| `ces verify` | Run independent local verification for the current project without writing inferred contracts by default |
| `ces complete` | Reconcile externally completed builder work with the CES audit trail |
| `ces report builder` | Export a markdown and JSON handoff report under `.ces/exports/` |

When a run blocks, prefer `ces why` and `ces recover --dry-run` before rerunning
or manually completing work. `ces status` is read-only by default; pass
`ces status --reconcile` only when you explicitly want it to refresh stale local
builder session state before display. `ces verify` reads an existing completion
contract when present, otherwise verifies against an inferred in-memory contract;
pass `ces verify --write-contract` only when you want to persist that inferred
contract. Use `ces complete` only to reconcile work that was actually finished
outside CES.

Unattended `--yes` runs are still evidence-gated: CES blocks auto-approval if
the runtime omits the `ces:completion` claim, changes files outside the manifest
scope, omits required verification artifacts, trips a blocking sensor policy
finding, or uses a runtime boundary that cannot enforce manifest tool allowlists
without an explicit `--accept-runtime-side-effects` waiver.

Use the [Operator Playbook](docs/Operator_Playbook.md) when you need the full
builder-first versus expert workflow boundary for a single request.

## Greenfield And Brownfield

CES supports both empty projects and existing codebases.

| Mode | What CES optimizes for |
|---|---|
| Greenfield | Build new behavior without preserving an existing application surface |
| Brownfield | Detect existing source files, ask what must keep working, and carry those constraints into the manifest |

For day-to-day brownfield work, stay in the builder-first loop:

```bash
ces build "Add input validation to the billing API"
ces explain --view brownfield
ces continue
```

Use explicit brownfield governance surfaces only when you need to decide the
fate of a named legacy behavior:

```bash
ces brownfield review OLB-<entry-id> --disposition preserve
```

The [Brownfield Guide](docs/Brownfield_Guide.md) covers observed legacy
behavior registration, review, and promotion.

## Expert Workflow

Most operators should stay with `ces build`, `ces continue`, `ces explain`,
`ces status`, and `ces report builder`. Drop into expert workflow commands when
you need direct artifact control, audit inspection, or incident response.

| Command | Use it for |
|---|---|
| `manifest` / `classify` | Create and classify manifests directly |
| `execute` | Run a manifest-bound local agent task |
| `review` / `triage` / `approve` | Inspect evidence and make approval decisions |
| `audit` | Expert operations audit inspection; for example, `ces audit --limit 20` |
| `status --expert` | Show the full expert status view; add `--watch` for `ces status --expert --watch` |
| `emergency declare` | Expert operations emergency declaration; for example, `ces emergency declare "Security incident detected"` |
| `scan` / `baseline` | Capture repo inventory and day-0 sensor snapshots |
| `brownfield ...` | Expert legacy behavior capture, review, and promotion |
| `spec ...` | Author, validate, decompose, reconcile, or inspect specs |
| `setup-ci` | Generate GitHub or GitLab CI gating workflow templates |
| `dogfood` | Use CES to review changes to this repository; for example, `ces dogfood --base origin/master` |

Commands with machine-readable output support the global JSON form
(`ces --json status`) and the command-local form where exposed
(`ces status --json`). The [Operations Runbook](docs/Operations_Runbook.md)
covers system-wide visibility and incident response.

## Local State

CES writes operational state into the project being governed:

| Path | Purpose |
|---|---|
| `.ces/config.yaml` | Project metadata and local execution settings |
| `.ces/state.db` | SQLite store for manifests, audit entries, evidence, sessions, and local records |
| `.ces/keys/` | Project-local signing and audit integrity keys |
| `.ces/artifacts/` | Runtime and evidence artifacts |
| `.ces/exports/` | Builder reports and exported handoff files |
| `.ces/baseline/` | Day-0 sensor snapshots |

Keep `.ces/` untracked unless a specific exported artifact is intentionally
being shared.

## Configuration

Most local runs need no environment configuration. Optional settings can be
exported directly or copied from `.env.example`.

| Variable | Purpose | Default |
|---|---|---|
| `CES_DEFAULT_RUNTIME` | Preferred runtime when multiple local CLIs are available | `codex` |
| `CES_DEMO_MODE` | Use demo helper responses where supported | `0` |
| `CES_LOG_LEVEL` | Logging level | `INFO` |
| `CES_LOG_FORMAT` | Logging format: `json` or `text` | `json` |
| `CES_AUDIT_HMAC_SECRET` | Override the project-local audit HMAC secret in managed environments | unset |

Runtime credentials are handled by the installed runtime CLI, not by CES
package extras.

## Architecture

CES is organized around local CLI contexts:

| Area | Responsibility |
|---|---|
| `src/ces/cli/` | Typer command surface and builder-first operator flow |
| `src/ces/local_store/` | Project-scoped SQLite persistence and repositories |
| `src/ces/control/` | Deterministic governance models, manifests, workflow, policy, merge, and audit services |
| `src/ces/harness/` | Evidence, review routing, sensors, trust, guide packs, and completion verification |
| `src/ces/execution/` | Runtime adapters, providers, completion parsing, output capture, and secret-scrubbing helpers |
| `src/ces/brownfield/` | Observed legacy behavior capture and PRL promotion |

Historical server-oriented docs live under `docs/historical/` as design
archives, not as the current product contract.

## Development

Install the development environment:

```bash
uv sync
uv run ces --help
```

Run the local-first verification gate:

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/ces/ --ignore-missing-imports
uv run pytest tests/ -m "not integration" --cov=ces --cov-fail-under=90 --cov-report=term-missing -q -W error
uv build
uvx twine check dist/*
```

Builder-created manifests expect command-backed completion evidence. When a
manifest enables the completion-gate sensors, produce the matching artifacts
before claiming completion: `pytest-results.json`, `ruff-report.json`,
`mypy-report.txt`, and `coverage.json`. Dependency and security-sensitive
changes can also be backed by `pip-audit-report.json` and SAST JSON artifacts
such as `bandit-report.json`; CES parses those when present.

Run local integration tests:

```bash
uv sync --group ci
uv run pytest tests/ -m integration -q
```

Merging or pushing code to `master` runs CI, but it does not publish to PyPI.
PyPI publishing is tag-driven: update the version, update the changelog, push
the version-bump commit, then push a `v*` tag such as `v0.1.12`. The tag
triggers `.github/workflows/publish.yml`, which runs tests, builds the wheel
and source distribution, smoke-tests the installed CLI with help and real project initialization, validates the tag/version agreement, and publishes to PyPI
through trusted publishing. Follow [docs/RELEASE.md](docs/RELEASE.md) for the
maintainer checklist.

## Documentation Map

| Document | Start here when you need |
|---|---|
| [5-Minute Quickstart](docs/Quickstart.md) | The shortest local builder-first path |
| [Getting Started](docs/Getting_Started.md) | Full setup and workflow walkthrough |
| [Operator Playbook](docs/Operator_Playbook.md) | Builder-first versus expert workflow boundaries |
| [Brownfield Guide](docs/Brownfield_Guide.md) | Existing-codebase and legacy-behavior governance |
| [Operations Runbook](docs/Operations_Runbook.md) | Expert status, audit, and emergency operations |
| [Codex Scratch Project E2E](docs/Codex_Scratch_Project_E2E.md) | External greenfield and brownfield smoke harnesses |
| [Quick Reference Card](docs/Quick_Reference_Card.md) | Classification and gate lookup tables |
| [Troubleshooting](docs/Troubleshooting.md) | Common local setup and runtime issues |
| [Release Runbook](docs/RELEASE.md) | Maintainer release checklist |

Current design and plan records live under `docs/designs/` and `docs/plans/`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development workflow, tests, and
contribution expectations. Security-sensitive issues should follow
[SECURITY.md](SECURITY.md).

If you use external agent loops such as `gnhf`, keep them outside CES itself as
contributor tooling rather than part of the product. Run them from a clean
sibling worktree or clean clone, keep the scope away from manifest/policy,
approval/triage/review, audit, kill-switch, and runtime-boundary
changes, and review every generated branch manually before using it. Follow the
[GNHF Trial Guide](docs/GNHF_Trial_Guide.md) and
[`scripts/gnhf_trial.sh`](scripts/gnhf_trial.sh); CES's own builder-first or expert workflows remain the delivery path.

## License

MIT. See [LICENSE](LICENSE).
