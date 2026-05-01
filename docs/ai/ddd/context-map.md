# Context Map

Purpose: show likely bounded contexts and dependencies so future agents keep changes small, preserve contracts, and avoid copying historical/server assumptions into the local-first product.

## Likely Bounded Contexts

| Context | Type | Purpose | Owned Terms | Code/Data Locations | Inbound Contracts | Outbound Contracts | Evidence | Status |
|---|---|---|---|---|---|---|---|---|
| CLI / Operator Surface | Core | Public command surface for builder-first and expert workflows. | command, `--json`, build, continue, explain, status, report, doctor | `src/ces/cli/`; `README.md`; `docs/Getting_Started.md`; `docs/Operator_Playbook.md` | Shell commands, global `--json`, env vars, project config | Service factory calls, local state writes, reports, generated CI | `src/ces/cli/__init__.py`; CLI/docs tests | Fact |
| Builder Orchestration | Core | Convert operator intent into a builder brief, project mode, brownfield review checkpoints, manifest assist, runtime execution, and evidence handoff. | builder brief, project mode, must not break, critical flows, source of truth | `src/ces/cli/_builder_flow.py`; `src/ces/cli/run_cmd.py`; `builder_briefs` and `builder_sessions` tables | `ces build`, `ces continue`, prompt answers, `--greenfield`, `--brownfield`, spec-derived builds | Manifest proposals, brownfield OLB decisions, PRL drafts, runtime prompts, evidence snapshots | builder flow tests; FreshCart integration tests | Fact |
| Control Plane | Core | Deterministic governance models/services for manifests, classification, workflow state, policy, merge checks, audit, and truth artifacts. | manifest, risk tier, behavior confidence, change class, workflow state, audit ledger, truth artifact | `src/ces/control/models/`; `src/ces/control/services/`; `src/ces/shared/enums.py` | Builder/expert commands, spec decomposition, local repositories | Signed manifests, classifications, audit events, merge decisions, governed artifacts | model/service tests; `README.md` control-plane description | Fact |
| Harness / Review | Core | Evidence, review routing, sensors, trust, completion verification, guide packs, hidden checks, and self-correction. | evidence packet, review finding, sensor, completion gate, guide pack, trust tier | `src/ces/harness/`; persisted evidence/review tables | Manifests, runtime outputs, provider/reviewer outputs, configured sensors | Evidence summaries, triage readiness, findings, sensor results, repair prompts | harness/model/sensor tests | Fact |
| Execution | Core | Invoke local agent CLIs, capture output, parse completion claims, scrub secrets, and track runtime transcripts. | runtime, adapter, provider, prompt pack, transcript, completion claim | `src/ces/execution/`; `runtime_executions` table | Manifest description, prompt pack, working dir, allowed tools, runtime config | `AgentRuntimeResult`, completion claim, summary/challenge text | runtime/agent-runner tests | Fact |
| Local Store | Supporting | Project-scoped SQLite persistence, key/artifact directories, and repository adapters. | local project state, `.ces/state.db`, project settings, audit entry, runtime execution | `src/ces/local_store/`; `.ces/`; `docs/Database_Operations.md` | Service repository calls, `ces init`, project config | Typed records, SQLite rows, `.ces/keys/`, `.ces/artifacts/`, `.ces/exports/` | local-store tests; store DDL | Fact |
| Brownfield Governance | Core / Supporting | Capture observed existing behavior, review disposition, promote to PRL, or discard intentionally. | brownfield, legacy behavior, OLB, disposition, preserve, change, retire | `src/ces/brownfield/`; `src/ces/cli/brownfield_cmd.py`; `legacy_behaviors` table | Builder brownfield prompts, `ces brownfield ...`, `.ces/brownfield/scan.json` | Reviewed OLB entries, PRL items, audit truth-change events | brownfield service/CLI tests; `docs/Brownfield_Guide.md` | Fact |
| Spec Authoring | Supporting | Parse structured Markdown specs, validate/reconcile/tree stories, and decompose into manifests. | spec, story, frontmatter, signal hints, template, dependency | `src/ces/control/spec/`; `src/ces/control/models/spec.py`; `src/ces/control/spec/templates/`; `tests/fixtures/specs/` | Markdown spec files, `ces spec ...`, `ces build --from-spec` | Manifest drafts with `parent_spec_id` and acceptance criteria | spec CLI, property, and integration tests | Fact |
| Knowledge / Vault | Supporting | Store/query/rank knowledge notes and trust levels for decisions, patterns, discovery, calibration, and domain context. | vault, note, trust level, stale risk, agent inferred, verified | `src/ces/knowledge/`; `src/ces/cli/vault_cmd.py` | `ces vault ...`, query filters, audit events | Ranked notes, vault health/readouts | knowledge and vault CLI tests | Fact |
| Intake | Supporting | Phase interviews and assumption registration. | intake, assumption, block, flag, proceed, phase question | `src/ces/intake/`; `src/ces/intake/questions/phase_questions.yaml`; `src/ces/cli/intake_cmd.py` | `ces intake`, YAML phase questions | Assumption records and audit events | intake tests | Fact |
| Emergency Operations | Core safety / Supporting | Kill switch, emergency declaration, SLA/recovery support. | kill switch, emergency, halted action, recovery, escalation | `src/ces/emergency/`; `src/ces/control/services/kill_switch.py`; `src/ces/cli/emergency_cmd.py` | `ces emergency declare`, service calls | Halt/recovery decisions and audit events | emergency/kill-switch tests; operations docs | Fact |
| Observability | Generic / Supporting | Metrics, counters, OpenTelemetry helpers, and Grafana examples. | metrics, collector, OTEL, dashboard | `src/ces/observability/`; `examples/grafana-*.json` | Optional env vars and optional dependency extra | Metrics/counters/OTel instrumentation | observability tests; `pyproject.toml` optional extra | Fact |
| Packaging / Release / CI | Supporting | Build, publish, validate, and generate CI gating workflows. | console script, package, wheel, publish, setup-ci, dogfood workflow | `pyproject.toml`; `.github/workflows/`; `.github/`; `src/ces/cli/templates/ci/`; `src/ces/cli/setup_ci_cmd.py` | `uv sync`, `uv build`, `ces setup-ci`, GitHub/GitLab CI events | Built distributions, generated workflows, PR/issue templates | docs/packaging tests; CI workflow files | Fact |
| Compatibility Test Infrastructure | Generic / Compatibility | Keep optional SQLAlchemy/Postgres/Alembic coverage separate from supported local-first runtime. | compat-tests, Alembic, SQL compatibility | `tests/integration/_compat/`; `alembic.ini`; `pyproject.toml` `compat-tests` extra | Optional CI/dev test invocations | Test-only DB schema/migrations and compatibility repositories | integration fixtures; package extras | Fact |
| Scratch Harness Scripts | Supporting / Verification | External scratch and brownfield E2E proof scripts that drive CES and collect evidence bundles. | scratch harness, command transcript, prompt answers, summary | `scripts/codex_scratch_harness.py`; `scripts/run_codex_scratch_e2e.py`; `scripts/run_codex_brownfield_e2e.py`; `docs/Codex_Scratch_Project_E2E.md` | Script CLIs and local `codex` availability | Evidence bundle files and preserved temp repos on failure | script tests; docs | Fact |

## Key Relationships

| From | To | Pattern | Contract / Translation Layer | Risk For Agents |
|---|---|---|---|---|
| CLI / Operator Surface | Service contexts | Open Host Service | Typer commands and `CESServices` factory | Renaming flags/output breaks docs, tests, and shell users. |
| Builder Orchestration | Control Plane | Customer/Supplier | Builder brief -> manifest proposal -> persisted manifest | Changing manifest requirements can strand saved builder sessions. |
| Builder Orchestration | Brownfield Governance | Anticorruption Layer | Operator prose and repo signals -> OLB entries/dispositions | Skipping brownfield review loses preserve/change/retire decisions. |
| Control Plane | Local Store | Shared Kernel | Pydantic/enums <-> SQLite rows/repositories | Schema or enum changes can break existing `.ces/state.db`. |
| Harness / Review | Control Plane | Customer/Supplier | Evidence/review depends on manifest risk, BC, class, and workflow state | Classification changes alter review routing and merge gates. |
| Execution | External Agent CLIs | Anticorruption Layer | `AgentRuntimeProtocol`, runtime adapters, completion claim parser | External CLI behavior drifts; do not overstate runtime-boundary guarantees. |
| Spec Authoring | Control Plane | Customer/Supplier | Spec stories decompose into manifests with parent IDs and acceptance criteria | Spec file changes can break existing stories or generated manifests. |
| Brownfield Governance | Control Plane | Published Language | OLB dispositions and PRL promotion | Docs/code vocabulary mismatch (`migrate/remove` vs `change/retire`) can become a compatibility bug. |
| Packaging / Release / CI | CLI / Execution | Open Host Service | Console script and generated CI templates invoke `ces doctor` and `ces dogfood` | Tightening generated gates can break user CI. |
| Compatibility Test Infrastructure | Product Runtime | Separate Ways | Root `alembic.ini` is a compatibility-test helper | Agents may copy Postgres paths into supported docs/code by mistake. |
| Examples | Tests / Compatibility | Boundary smell | `examples/freshcart/seed_data.py` imports test compatibility DB modules | Treat this as demo/test coupling, not a production dependency pattern. |

## Allowed Dependencies

- CLI may orchestrate across contexts through `src/ces/cli/_factory.py` and service interfaces.
- Control Plane may depend on `ces.shared` and repository abstractions, but should stay deterministic and avoid direct LLM/runtime calls.
- Harness may consume control models/enums and execution/provider outputs, but should not mutate manifests/audit history directly.
- Execution may consume manifest descriptions and completion models, but should not own governance decisions.
- Local Store owns SQLite shape and repository adapters; domain services should not bypass it with ad hoc SQL.
- Compatibility test infrastructure may depend on Postgres/Alembic, but production/default local-first flow should not.

## Forbidden Or High-Risk Dependencies

- Do not add production dependencies from `src/ces/` into `tests/integration/_compat/`.
- Do not use historical FastAPI/Celery/Redis/Postgres docs as product requirements without an explicit scope change.
- Do not let LLM provider output become deterministic control-plane truth without validation, audit, and tests.
- Do not modify audit ledger append-only behavior, manifest signing/hash payloads, or enum serialized values casually.
- Do not treat `.worktrees/`, `.venv/`, `.pytest_cache/`, or generated `__pycache__` artifacts as product contexts.

## Inferred Boundaries To Confirm

- The Control/Harness split is practical and heavily tested, but not enforced by import rules. Future refactors should add tests before tightening imports.
- `ces spec` appears implemented and tested, but product stability of the Markdown format still needs an owner decision.
- Observability metrics are optional today; external dashboard users would make metric names a stronger published contract.
