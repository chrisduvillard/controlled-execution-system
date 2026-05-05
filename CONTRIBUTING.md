# Contributing to CES

Thank you for your interest in contributing to the Controlled Execution System.

By participating in this project you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).
Security-sensitive issues should be reported through the process in [SECURITY.md](SECURITY.md)
rather than as public issues.

## Development Setup

### Prerequisites

- Python 3.12 or 3.13
- [uv](https://docs.astral.sh/uv/) (package manager)
- A supported local runtime (`codex` or `claude`) for governed builder runs.

### Getting Started

```bash
# Clone the repository
git clone https://github.com/chrisduvillard/controlled-execution-system.git
cd controlled-execution-system

# Install all dependencies (including dev tools)
uv sync

# Verify the installation
uv run ces --help
```

## Development Workflow

### External Agent Experiments

If you want to use an external orchestrator such as `gnhf` to help develop CES,
keep it outside CES itself and treat it as contributor tooling around this repo
rather than as a replacement for CES's own builder-first or expert workflows:

- use a clean sibling worktree or clean clone, never an in-flight dirty checkout
- keep runs bounded to docs, tests, CLI UX, or similarly scoped work
- exclude control-plane, approval/triage/review, manifest, audit, kill-switch,
  policy, and runtime-boundary changes
- review every generated branch manually before cherry-picking or merging

See the [GNHF Trial Guide](docs/GNHF_Trial_Guide.md) and
[`scripts/gnhf_trial.sh`](scripts/gnhf_trial.sh) for the recommended setup.

### Running Tests

```bash
# Run unit tests only (fast, no infrastructure needed)
uv run pytest tests/unit/ -q

# Run the default local-first suite
uv run pytest tests/ -m "not integration" -q

# Local integration tests
uv run pytest tests/ -m integration -q

# Run with coverage report
uv run pytest tests/ -m "not integration" --cov=ces --cov-fail-under=90 -q
```

### Coverage Gate

The project enforces **90% branch coverage** in CI. All new code must include
tests. The coverage configuration is in `pyproject.toml` under
`[tool.coverage.*]`.

### Linting and Formatting

```bash
# Check for lint errors
uv run ruff check src/ tests/

# Auto-fix lint errors
uv run ruff check --fix src/ tests/

# Check formatting
uv run ruff format --check src/ tests/

# Auto-format
uv run ruff format src/ tests/
```

### Type Checking

```bash
uv run mypy src/ces/
```

### Pre-commit Hooks

The project uses pre-commit hooks for automated quality checks:

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

## Branch Workflow

1. Create a feature branch from `master`
2. Make your changes with tests
3. Ensure all checks pass: `ruff check`, `mypy`, `pytest` with coverage
4. Commit with a descriptive message (see commit style below)
5. Open a pull request against `master`

### Commit Messages

Follow the existing style in the repository:

- Start with an imperative verb: "Add", "Fix", "Update", "Remove"
- Focus on the "why" rather than the "what"
- Keep the first line under 72 characters
- Add detail in the body if needed

## Architecture Overview

CES is organized into three planes:

- **Control Plane** (`src/ces/control/`): Deterministic governance — manifests, audit, classification, policy, workflow. No LLM calls allowed here (LLM-05).
- **Harness Plane** (`src/ces/harness/`): Quality assurance — evidence, reviews, sensors, trust management.
- **Execution Plane** (`src/ces/execution/`): Agent runtime — LLM providers, runtime adapters, output capture.

Supporting modules:
- `src/ces/cli/` — Typer CLI commands
- `src/ces/shared/` — Config, crypto, base models, enums
- `src/ces/local_store.py` — SQLite persistence for local mode

For deeper architecture details, see the [Implementation Guide](docs/historical/Implementation_Guide.md).

## Key Constraints

- **No LLM in control plane**: The control plane must be deterministic. All LLM integrations live in the execution plane.
- **90%+ branch coverage**: Enforced by CI (`pyproject.toml:fail_under = 90`).
- **Ruff for linting/formatting**: Single tool, single config. No black/flake8/isort.
- **Pydantic v2 models**: All YAML schemas and domain models use Pydantic v2.

## Releasing

See [docs/RELEASE.md](docs/RELEASE.md) for the release runbook — the
step-by-step checklist that catches the traps v0.1.2 and v0.1.3 hit.
Relevant if you're cutting a tag; safe to ignore otherwise.
