# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.7] - 2026-05-04

0→100 builder robustness release. This release makes CES materially easier to
use on real greenfield projects when runtime evidence, independent build proof,
or recovery steps are ambiguous.

### Added
- `ces build --gsd`: greenfield delivery alias for the builder workflow, making
  the intended 0→100 product-build path explicit from the CLI.
- `ces why`: first-class blocker diagnosis command for explaining why a builder
  run is blocked or rejected and which command to run next.
- Completion contracts at `.ces/completion-contract.json`, describing expected
  project artifacts and independent verification commands for completed builder
  work.
- `ces verify`: reruns completion-contract verification independently from the
  runtime so users and automation can prove a project actually works after a
  builder run.
- `ces recover`: non-mutating recovery planning via `--dry-run`, plus guarded
  `--auto-evidence` and `--auto-complete` flows for blocked sessions whose
  artifacts can be independently verified.
- `ces benchmark greenfield`: deterministic 0→100 benchmark harness with a
  built-in `python-cli` scenario, fake runtime, persisted scorecards, friction
  metrics, and machine-readable JSON output.

### Changed
- Builder summaries now surface actionable next commands, including `ces why`,
  `ces recover --dry-run`, `ces verify`, and `ces report builder` depending on
  the session state.
- Builder evidence now records completion-contract paths and independent
  verification results when verification commands are available.

### Fixed
- Blocked builder sessions now distinguish runtime, review, evidence,
  verification, and recovery blockers instead of leaving users to infer the
  cause from raw state.
- Recovery evidence preserves superseded packet metadata and original runtime
  context so self-recovery does not hide the failure that required recovery.

## [0.1.6] - 2026-04-30

Public GitHub readiness hardening before making the repository visible.

### Added
- Dependabot configuration for GitHub Actions and Python dependency updates.
- CodeQL Python analysis workflow.

### Changed
- README release examples now point at the 0.1.6 line.
- `CONTRIBUTING.md` now consistently documents the 90% CI coverage gate.
- `SECURITY.md` and the archival security audit wording were refreshed for the
  public repository surface.
- Development-only service fixtures now bind Postgres and Redis to localhost
  by default instead of all network interfaces.

## [0.1.4] - 2026-04-30

Release workflow and documentation update that clarifies how operators install
and update CES from PyPI.

### Changed
- README Quick Start now leads with `uv tool install
  controlled-execution-system` for the normal global install path, explains
  that uv uses PyPI by default, and separates published installs from source
  checkout and editable-tool workflows.
- README now states that pushes to `master` run CI only; PyPI publishing is
  triggered by pushing a `v*` release tag and follows `docs/RELEASE.md`.

### Fixed
- CI dependency auditing now exports the resolved CI dependency set without the
  editable CES project before running `pip-audit --strict`, so version-bump
  commits can pass before that new CES version exists on PyPI.

## [0.1.3] - 2026-04-23

Follow-up hardening of the 0.1.2 security posture. No product-shape changes.

### Added
- `SECURITY.md` gained a Threat Model section enumerating what CES
  defends against, what it explicitly does NOT defend against
  (prompt injection, supply chain, network MITM, etc.), and the
  operator responsibilities that CES's guarantees presume.
  Documents adversarial-review diversity as the primary mitigation
  for prompt injection and ties it to the new
  `AggregatedReview.degraded_model_diversity` flag from 0.1.2.
- `ces doctor --security`: supplemental posture check for the 0.1.2 key
  material. Verifies that `.ces/keys/` is mode `0700`, the Ed25519
  signing keypair and audit HMAC secret are present and mode `0600`,
  `.ces/state.db` is `0600`, and that `CES_AUDIT_HMAC_SECRET` is not
  set to the hardcoded dev default. JSON output via `ces --json doctor
  --security` is the machine-readable form. Exits non-zero when any
  check fails so adopters can wire this into their own onboarding
  scripts.

### Fixed
- `ces init` now sets `.ces/state.db` to mode `0600` directly rather
  than deferring to the first `LocalProjectStore` open. Closes a gap
  in the 0.1.2 B1/B2 hardening where a freshly-initialised project had
  a world-readable state DB until a subsequent CES command ran.
  Surfaced by the new `ces doctor --security` check.

### Changed
- Coverage omit list cleanup: removed `src/ces/cli/admin_cmd.py` (file no
  longer exists) and `src/ces/execution/runtimes/adapters.py` (now covered
  by the 0.1.2 hardening tests in `test_runtime_adapters.py` and
  `test_claude_adapter_hardening.py`). `adapters.py` now sits at 82 % under
  the gate; the 18 % uncovered is Windows-specific `shutil.which` edge
  cases and subprocess read paths that require real binaries.
- `CoverageSensor` (`src/ces/harness/sensors/test_coverage.py`) own-coverage
  **47 % → 100 %**. The sensor that powers CES's dogfooding now has full
  unit-test coverage of the dispatch shell, all four severity bands,
  branch-coverage reporting, and the three error paths (malformed JSON,
  unreadable file, empty totals). 16 new tests in
  `tests/unit/test_sensors/test_test_coverage_sensor_module.py`.
- Coverage gate restored to **90 %** (was temporarily 88 % in 0.1.1–0.1.2).
  The `test_freshcart_e2e_pipeline` xfail referenced in the 0.1.1
  CHANGELOG never actually landed — the fixture was rewritten in place —
  and the 0.1.2 local-first suite measures at 90.03 % on unit tests and
  90.27 % on the full suite, so the restore is a configuration change
  rather than a test-authoring effort.

## [0.1.2] - 2026-04-23

Security + release-readiness hardening. Three critical release blockers
identified in the 2026-04-23 release-readiness audit are resolved; no
product-shape changes. Full remediation plan archived at
`.planning/release-0.1.2-plan.md`.

### Security
- **Manifest signing is now actually enforced end-to-end.** The Ed25519
  keypair used by `ManifestManager` is generated and persisted to
  `.ces/keys/` (mode `0600`) on `ces init` and loaded by
  `_factory.get_services()` on every CLI invocation. Before 0.1.2 the
  keypair was regenerated per-process, so signatures produced in one
  CLI command could not be verified in the next one — D-13 manifest
  integrity was silently defeated. A new cross-invocation regression
  test in `tests/unit/test_cli/test_factory_signing.py` locks in the
  fixed behaviour.
- **Audit-ledger HMAC secret is now project-scoped by default.**
  `ces init` generates a random 32-byte secret and writes it to
  `.ces/keys/audit.hmac` (mode `0600`). `load_audit_hmac_secret`
  rejects the hardcoded development-default marker string so users
  who forget to override `CES_AUDIT_HMAC_SECRET` no longer silently
  ship with a publicly-known audit secret. `CES_AUDIT_HMAC_SECRET`
  is still honoured as an explicit override for CI/ops.
- **Claude builder runtime no longer runs with `acceptEdits`.**
  `ClaudeRuntimeAdapter.run_task` now uses `--permission-mode default`
  plus a `--allowedTools` allowlist. The default allowlist is
  `Read Grep Glob Edit Write`; `Bash` and `WebFetch` require explicit
  opt-in via `TaskManifest.allowed_tools`. A prompt-injected repo
  (hostile README, issue body, code comment) can no longer steer the
  model into executing arbitrary host commands via auto-approved tool
  calls. Regression test: `tests/unit/test_execution/test_claude_adapter_hardening.py`.
- **Subprocess stdout/stderr are secret-scrubbed** before being persisted
  to `.ces/state.db` and included in evidence packets. An agent that
  reads `.env`/`~/.aws/credentials` and echoes it no longer causes
  that material to land in CES persistence. Scrubber extracted as
  `scrub_secrets_from_text` in `src/ces/execution/secrets.py`.
- **`.ces/state.db` is created mode `0600`, parent dir `0700`.**
  Matches the pattern already used for runtime transcripts.
- **CLI provider subprocess env is now allowlist-filtered** (new
  `src/ces/execution/_subprocess_env.py` shared between the runtime
  adapters and the inline CLI provider). Previously the inline CLI
  provider inherited the full process env, leaking `AWS_*`,
  `DATABASE_URL`, `GITHUB_TOKEN`, etc. into every LLM subprocess.
- **Kill-switch guards added to two `spec_cmd.py` LLM paths**
  (`_polish_spec_document` and `_llm_section_mapping`) that previously
  bypassed the `is_halted()` check that CLAUDE.md promises for every
  LLM-dispatching service.
- **`git diff {base_ref}` in the dogfood pipeline now `--`-delimits
  the ref** so a user-supplied `--base` argument cannot be parsed as
  git option flags.

### Changed
- **Server-era bytecode directories (`src/ces/api/`,
  `src/ces/tasks/`, `src/ces/polyrepo/`)** have been fully removed.
  The corresponding `.py` source was deleted in 0.1.1; this release
  removes the stale `__pycache__` shells. Nothing in `src/` or
  `tests/` imports from these paths.
- **Service fixture narrowed to `postgres` + `redis`.** The `api` and
  `celery-worker` services (whose backing code was removed in 0.1.1) have
  been deleted; the retained fixture no longer fails with `ModuleNotFoundError`
  or a dead health-probe URL.
- **`.env.example` trimmed** to variables actually consumed by
  `CESSettings` (`CES_LOG_LEVEL`, `CES_LOG_FORMAT`,
  `CES_DEFAULT_RUNTIME`, `CES_DEMO_MODE`, and an optional
  `CES_AUDIT_HMAC_SECRET` override), resolving the contradiction
  with the no-Postgres Quickstart.
- **`AggregatedReview.degraded_model_diversity: bool`** new field.
  Set to `True` when the dispatched triad resolves to fewer distinct
  underlying models than assignments (e.g. only one CLI provider
  installed against a Tier A triad). Surfaces an intentional signal
  in evidence packets instead of the silent aliasing in `bootstrap.py`.
- **Dependencies now pinned with upper bounds** (`<N`) to constrain
  supply-chain blast radius.
- **README Tech Stack** qualifies the mypy "strict mode" claim with
  "targeted relaxations"; see `[tool.mypy]` in `pyproject.toml` for
  the actual error codes disabled.
- **CLAUDE.md** Constraints section clarifies that PostgreSQL is only
  for the integration-test compatibility suite, not shipped product.
- CES now ships as a local builder-first CLI only. The supported public
  workflow is local `.ces/` state plus local `codex` / `claude` runtimes;
  server/API/worker/control-plane deployment surfaces are no longer part of
  the published product contract.
- The public CLI surface is narrowed to the local workflow and governance
  commands. Removed server-era command groups are no longer registered or
  documented.
- Fresh database migrations now prune obsolete server-era schemas and tables
  (`observability`, `polyrepo`, `control.api_keys`, and
  `control.project_members`) so a new PostgreSQL compatibility database
  matches the current local-first product shape.
- Sample builder prompts and spec fixtures now use framework-neutral HTTP
  wording instead of `FastAPI`-specific examples, keeping the public repo
  contract implementation-agnostic.

### Deprecated
- `TestCoverageSensor` is deprecated; use `CoverageSensor` instead. The
  legacy name remains importable from `ces.harness.sensors` and continues to
  function as a subclass of `CoverageSensor`, but instantiating it now emits
  `DeprecationWarning`. The alias will be removed in 0.2.x. The rename
  removes the `Test` prefix that previously collided with pytest's class
  collection (the `__test__ = False` workaround now lives only on the
  deprecated alias).

### Fixed
- Alembic migration bootstrap no longer imports deleted observability ORM
  modules, so the retained PostgreSQL compatibility tests run again.
- Audit-ledger hash continuation and integrity verification are now correctly
  project-scoped across both PostgreSQL and local SQLite repositories.
- PostgreSQL compatibility fixtures now wait for the database to accept
  connections before running Alembic, removing a startup timing race in the
  integration suite.
- `LocalProjectStore`: `review_findings` now uses a synthetic primary key
  scoped to `(manifest_id, finding_id)` so findings from different manifests
  no longer collide, and `.ces/state.db` startup recovers cleanly from an
  interrupted migration left by a previous aborted process.
- `ces status` no longer attempts telemetry/Postgres access for local-mode
  builder-first projects, so the documented local SQLite quickstart path stays
  responsive.
- Publishing now runs a maintained builder-first smoke test before PyPI
  release, replacing the stale xfailed end-to-end coverage path with an
  exercised local workflow gate.

### Known follow-ups

## [0.1.1] - 2026-04-17

Release-readiness hardening. No functional changes; hygiene, tooling, and
OSS-release artifacts only.

### Added
- `CODE_OF_CONDUCT.md` adopting Contributor Covenant v2.1.
- Pre-commit `mypy` hook so type errors are caught locally before CI.

### Changed
- Runtime image build recipe now runs as an unprivileged user (`ces`, UID 1000).
- Ruff configuration consolidated into `pyproject.toml` (removed `ruff.toml`).
- README coverage badge set to `88%+` to match the enforced CI gate (temporary
  relaxation from the PRD-mandated 90%; see known follow-ups for restore plan).
- `CONTRIBUTING.md` links to `CODE_OF_CONDUCT.md` and `SECURITY.md`.
- CHANGELOG test-count figure corrected (2,800+ → 3,000+).

### Fixed
- Auto-fixed 30 ruff lint issues and reformatted 6 files under `alembic/`
  and `examples/` so `ruff check .` and `ruff format --check .` pass on a
  fresh clone.
- Silenced pytest collection warning on `TestCoverageSensor` via
  `__test__ = False`.
- `.gitignore` now includes `.ruff_cache/` and `.mypy_cache/`.
- CI checkout on the publish workflow (missing `contents: read` permission).
- Integration-test fixtures constructing `TaskManifest`, `DisclosureSet`, and
  `VaultNote` with lists are now tuples, matching `frozen=True` strict typing.
- `test_generate_formats_assistant_role`: silenced an AsyncMock/asyncio
  interaction warning under `pytest -W error` on CPython 3.12.

### Known follow-ups
- Coverage gate temporarily lowered from 90% to 88% while
  `test_freshcart_e2e_pipeline` is xfailed pending a fixture rewrite to match
  the current `review_cmd.py` service graph. Target: restore to 90% in 0.1.x.

## [0.1.0] - 2026-04-12

Initial alpha release of the Controlled Execution System.

### Added

- **Control Plane**: Manifest manager, audit ledger (HMAC-SHA256 chain), classification engine (deterministic TF-IDF), kill switch, policy engine, workflow state machine, gate evaluator, merge controller
- **Harness Plane**: Evidence synthesizer, review router (3-tier), sensor orchestrator (7 sensors), trust manager (4-state transitions), guide pack builder, hidden check engine
- **Execution Plane**: Agent runner with workspace-scoped runtime boundary, runtime registry (Codex CLI, Claude Code), LLM provider abstraction (Anthropic, OpenAI), chain-of-custody tracker, secret stripping
- **CLI**: 25+ command groups including `ces build`, `ces init`, `ces continue`, `ces explain`, `ces status`, `ces manifest`, `ces classify`, `ces review`, `ces approve`, `ces audit`, and command groups for vault, emergency, brownfield, alerts, events, registry, release, admin, and project management
- **Builder-first workflow**: `ces build` as default entrypoint with auto-bootstrap (creates `.ces/` on first run), interactive brief collection, local-mode SQLite persistence
- **Demo mode**: `CES_DEMO_MODE=1` enables dry-run without LLM API keys
- **Local-first architecture**: Full governance pipeline works with SQLite (`.ces/state.db`), no Postgres/Redis required for single-user local mode
- **REST API**: FastAPI control plane with auth, SSE streaming, endpoints for manifests, reviews, evidence, audit, trust, agents, telemetry, alerts, events, dependencies, registry, and releases
- **Database**: PostgreSQL 17 with 15 Alembic migrations for server-mode deployment
- **Observability**: OpenTelemetry integration, Prometheus metrics, structured logging (structlog), alert rules, health dashboard TUI
- **Cross-repo federation**: Polyrepo event bus, webhook delivery, federated bindings, dependency graph analysis
- **Brownfield support**: Legacy behavior detection, registration, grouped review, disposition-to-PRL workflow
- **Knowledge vault**: Zettelkasten-style notes with trust decay and ranking
- **Security**: Ed25519 manifest signing, HMAC-SHA256 audit chain, no secrets in task packages, workspace-scoped runtime execution
- **Testing**: 3,000+ tests (3,066 unit + 21 integration), 90%+ branch coverage gate, CI with GitHub Actions (lint, typecheck, test, build)
- **Documentation**: README, Getting Started guide, Operator Playbook, FreshCart worked example, Implementation Guide, Operations Runbook, Production Deployment Guide, Security doc, Quick Reference Card
