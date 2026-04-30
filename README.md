# Controlled Execution System (CES)

Local-first governance for AI agent-driven software delivery.

CES is a command-line tool that keeps AI-assisted changes inside an auditable
workflow. It turns an operator request into a bounded manifest, runs the work
through a local agent runtime, reviews the result, records evidence, and keeps
project state in the repo-local `.ces/` directory.

The supported default path is local and builder-first:

- no hosted control plane
- no required Docker, Postgres, Redis, or server process
- project state stored under `.ces/`
- local execution through an installed `codex` or `claude` CLI

Historical server-oriented docs are retained under `docs/historical/` as design
archives, not as the current product contract.

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- A supported local runtime on `PATH`: Codex CLI or Claude Code

### Install Globally

For normal use, install the published CLI from PyPI with `uv`:

```bash
uv tool install controlled-execution-system
uv tool update-shell
ces --help
```

`uv tool install controlled-execution-system` installs the package from the
configured Python package index. With uv's default configuration, that index is
PyPI. The installed executable is `ces`.

To install a specific published version:

```bash
uv tool install controlled-execution-system==0.1.6
```

To upgrade an existing global install after a new version is published:

```bash
uv tool upgrade controlled-execution-system
```

### Install From Source

```bash
git clone https://github.com/chrisduvillard/controlled-execution-system.git
cd controlled-execution-system
uv sync
uv run ces --help
```

Use the source checkout when developing CES itself or testing changes that have
not been published to PyPI yet. From a source checkout, run commands with
`uv run ces ...` if the global `ces` executable is not active in your shell.

To install the current checkout as a global editable tool:

```bash
uv tool install --force --editable .
ces --help
```

Editable installs are useful for local development, but they are not the
published PyPI release.

The examples below use `ces` for the project being governed. If you are running
directly from a CES source checkout instead of an installed command, run the
same command from the checkout with:

```bash
uv run ces ...
```

### Publishing Releases

Merging or pushing code to `master` runs CI, but it does not publish to PyPI.
PyPI publishing is tag-driven: update the version, update the changelog, push
the version-bump commit, then push a `v*` tag such as `v0.1.6`.

The tag triggers `.github/workflows/publish.yml`, which runs tests, builds the
wheel and source distribution, smoke-tests the installed CLI, and publishes to
PyPI through trusted publishing. Follow [docs/RELEASE.md](docs/RELEASE.md) for
the full maintainer checklist.

### Verify Your Environment

```bash
ces doctor
```

`ces build` and `ces execute` need a real local runtime. `CES_DEMO_MODE=1`
only affects optional helper/provider behavior; it does not replace Codex CLI or
Claude Code for local execution.

### Run A Governed Build

From the project you want CES to govern:

```bash
ces build "Add a healthcheck endpoint that returns JSON status" --yes
```

On first use in a repo, CES creates local state under `.ces/`. The builder flow
then gathers missing context, drafts the governance contract, runs the local
runtime, reviews the result, and records the evidence trail.

If you prefer to create local state explicitly before the first build:

```bash
ces init my-project
```

## Daily Operator Flow

Start with builder-first commands for normal work:

| Command | Use it for |
|---|---|
| `ces build "<request>"` | Start a governed local task from a natural-language request |
| `ces continue` | Resume the latest saved builder session |
| `ces explain` | Read the current request, blockers, evidence, and next step in plain language |
| `ces explain --view decisioning` | Inspect the governance decision path for the active request |
| `ces explain --view brownfield` | Inspect preserved existing-behavior context for the active request |
| `ces status` | Show the concise builder-first project status |
| `ces report builder` | Export a markdown and JSON handoff report under `.ces/exports/` |

Use expert workflow commands when you need direct artifact control:

| Command | Use it for |
|---|---|
| `manifest` / `classify` | Create and classify manifests directly |
| `execute` | Run a manifest-bound local agent task |
| `review` / `triage` / `approve` | Inspect evidence and make approval decisions |
| `audit` | Expert operations audit inspection; for example, `ces audit --limit 20` |
| `status --expert` | Show the broader expert status view; add `--watch` for `ces status --expert --watch` |
| `emergency declare` | Expert operations emergency declaration; for example, `ces emergency declare "Security incident detected"` |
| `scan` / `baseline` | Capture repo inventory and day-0 sensor snapshots |
| `brownfield ...` | Expert legacy behavior capture, review, and promotion |
| `spec ...` | Author, validate, decompose, reconcile, or inspect specs |
| `setup-ci` | Generate GitHub or GitLab CI gating workflow templates |
| `dogfood` | Use CES to review changes to this repository; for example, `ces dogfood --base origin/master` |

All commands support the global `--json` option where that command has a
machine-readable output path.

## Greenfield And Brownfield Work

CES supports both new projects and existing codebases.

- Greenfield: CES starts with an empty or new project and does not need to
  preserve existing behavior.
- Brownfield: CES detects existing source files, asks what behavior must keep
  working, carries those constraints into the manifest, and surfaces
  brownfield review context during the builder flow.

For day-to-day brownfield work, stay in the builder-first loop:

```bash
ces build "Add input validation to the billing API" --yes
ces explain --view brownfield
ces continue --yes
```

Drop into `ces brownfield ...` only when you need explicit observed-behavior
decisions outside the active builder flow. See
[Brownfield Guide](docs/Brownfield_Guide.md) for the detailed handoff.

For example, an explicit expert decision can preserve a named legacy behavior:

```bash
ces brownfield review OLB-<entry-id> --disposition preserve
```

When you leave a single active request and need system-wide visibility or
incident response, use the expert operations surfaces:

```bash
ces status --expert --watch
ces audit --limit 20
ces emergency declare "Security incident detected"
```

The [Operations Runbook](docs/Operations_Runbook.md) covers those procedures.

## Configuration

Most local runs need no environment configuration. `ces init` creates
project-local state and key material under `.ces/`.

Optional settings can be exported directly or copied from `.env.example`:

| Variable | Purpose | Default |
|---|---|---|
| `CES_DEFAULT_RUNTIME` | Preferred runtime when multiple local CLIs are available | `codex` |
| `CES_DEMO_MODE` | Use demo helper responses where supported | `0` |
| `CES_LOG_LEVEL` | Logging level | `INFO` |
| `CES_LOG_FORMAT` | Logging format: `json` or `text` | `json` |
| `CES_AUDIT_HMAC_SECRET` | Override the project-local audit HMAC secret in managed environments | unset |

Runtime credentials are handled by the installed runtime CLI, not by CES package
extras.

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

## Architecture

CES is organized around local CLI contexts:

- `src/ces/cli/`: Typer command surface and builder-first operator flow
- `src/ces/local_store/`: project-scoped SQLite persistence and repositories
- `src/ces/control/`: deterministic governance models, manifests, workflow,
  classification, policy, merge, and audit services
- `src/ces/harness/`: evidence, review routing, sensors, trust, guide packs, and
  completion verification
- `src/ces/execution/`: local runtime adapters, providers, completion parsing,
  output capture, and optional sandbox helpers
- `src/ces/brownfield/`: observed legacy behavior capture and PRL promotion
- `src/ces/knowledge/`, `src/ces/intake/`, `src/ces/emergency/`, and
  `src/ces/observability/`: supporting operator contexts

Compatibility Docker/Postgres/Alembic infrastructure exists for optional tests
and historical parity. It is not the supported default runtime path.

## Development Verification

CI uses the local-first gate plus packaging checks:

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/ces/ --ignore-missing-imports
uv run pytest tests/ -m "not integration" --cov=ces --cov-fail-under=90 --cov-report=term-missing -q -W error
uv build
uvx twine check dist/*
```

Optional compatibility tests may require Docker-backed services:

```bash
uv sync --group ci
uv run pytest tests/ -m integration -q
```

For release-specific checks, follow [docs/RELEASE.md](docs/RELEASE.md).

## Documentation

Start here:

| Document | Purpose |
|---|---|
| [5-Minute Quickstart](docs/Quickstart.md) | Fastest local builder-first path |
| [Getting Started](docs/Getting_Started.md) | Full setup and workflow walkthrough |
| [Operator Playbook](docs/Operator_Playbook.md) | Builder-first versus expert workflow boundary |
| [Brownfield Guide](docs/Brownfield_Guide.md) | Existing-codebase and legacy-behavior governance |
| [Operations Runbook](docs/Operations_Runbook.md) | Expert status, audit, and emergency operations |
| [Codex Scratch Project E2E](docs/Codex_Scratch_Project_E2E.md) | External greenfield and brownfield smoke harnesses |
| [Quick Reference Card](docs/Quick_Reference_Card.md) | Classification and gate lookup tables |
| [Troubleshooting](docs/Troubleshooting.md) | Common local setup and runtime issues |
| [Release Runbook](docs/RELEASE.md) | Maintainer release checklist |

Historical material lives under `docs/historical/` and current design/plan
records live under `docs/designs/` and `docs/plans/`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development workflow, tests, and
contribution expectations. Security-sensitive issues should follow
[SECURITY.md](SECURITY.md).

If you use external agent loops such as `gnhf`, keep them outside CES itself as
contributor tooling rather than part of the product. Run them from a clean
sibling worktree or clean clone, keep the scope away from manifest/policy,
approval/triage/review, audit, kill-switch, sandbox, and runtime-boundary
changes, and review every generated branch manually before using it. Follow
[GNHF Trial Guide](docs/GNHF_Trial_Guide.md) and
[`scripts/gnhf_trial.sh`](scripts/gnhf_trial.sh); CES's own builder-first or expert workflows remain the delivery path.

## License

MIT. See [LICENSE](LICENSE).
