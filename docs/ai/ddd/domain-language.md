# Domain Language

Purpose: give future coding agents a compact glossary grounded in current CES evidence. `Fact` means the term is backed by repository artifacts. `Inferred` means the repository points strongly in that direction, but a maintainer should confirm before changing behavior.

## Evidence Inspected

- Docs: `README.md`, `docs/Quickstart.md`, `docs/Getting_Started.md`, `docs/Operator_Playbook.md`, `docs/Brownfield_Guide.md`, `docs/Database_Operations.md`, `docs/Production_Deployment_Guide.md`, `docs/Operations_Runbook.md`, `docs/Troubleshooting.md`, historical docs under `docs/historical/`, and current plans/designs under `docs/plans/` and `docs/designs/`.
- Tests: `tests/unit/`, `tests/integration/`, `tests/property/`, docs contract tests under `tests/unit/test_docs/`, builder scenario fixtures under `tests/fixtures/`, and compatibility tests under `tests/integration/_compat/`.
- Schemas and models: Pydantic models in `src/ces/control/models/` and `src/ces/harness/models/`, dataclass records in `src/ces/local_store/records.py` and `src/ces/brownfield/records.py`, spec templates in `src/ces/control/spec/templates/`, and starter manifest/CI templates in `src/ces/cli/templates/`.
- APIs and public interfaces: Typer CLI in `src/ces/cli/__init__.py`, package exports in package `__init__.py` files, runtime protocol in `src/ces/execution/runtimes/protocol.py`, completion-claim fenced block parser in `src/ces/execution/completion_parser.py`, `CES_*` settings in `src/ces/shared/config.py`, and `.env.example`.
- Persistence and migrations: SQLite schema plus in-app migrations in `src/ces/local_store/store.py`; compatibility Alembic revisions under `tests/integration/_compat/alembic/`; root `alembic.ini` points at that compatibility test tree.
- Deployment units: package metadata and console entry point in `pyproject.toml`, CI/publish workflows under `.github/workflows/`, generated CI templates under `src/ces/cli/templates/ci/`, and scratch harness scripts under `scripts/`.

## Core Terms

| Term | Context | Definition | Source Evidence | Confidence | Agent Guidance |
|---|---|---|---|---|---|
| CES | Whole product | Local builder-first CLI for governed AI-assisted software delivery. | `README.md`; `pyproject.toml`; `src/ces/cli/__init__.py` | Fact | Do not revive historical API/server-control-plane assumptions unless requested. |
| Local-first | CLI / Local Store | Supported runtime and persistence posture: local CLI, `.ces/state.db`, `.ces/keys/`, local `codex` or `claude`. | `README.md`; `docs/Database_Operations.md`; `src/ces/cli/_factory.py`; `.env.example` | Fact | Treat Postgres and server services as historical or test infrastructure, not the default product path. |
| Builder-first flow | CLI / Builder Orchestration | Default operator path through `ces build`, `ces continue`, `ces explain`, `ces status`, and `ces report builder`. | `README.md`; `src/ces/cli/__init__.py`; `src/ces/cli/run_cmd.py`; `src/ces/cli/_builder_flow.py` | Fact | Prefer this path for user-facing docs and smoke tests. |
| Expert workflow | CLI / Governance Operations | Direct lower-level commands for manifests, classification, execution, review, triage, approval, gates, audit, emergency, vault, spec, scan, baseline, and brownfield decisions. | `src/ces/cli/__init__.py`; `README.md`; `docs/Operator_Playbook.md` | Fact | Some commands are older or lower-priority; check tests before treating every command as equally central. |
| Greenfield | Builder Orchestration | New or empty project mode where CES does not need to preserve existing system behavior. | `src/ces/cli/_builder_flow.py`; `tests/support/builder_scenarios.py`; `scripts/run_codex_scratch_e2e.py` | Fact | Do not ask brownfield preservation questions in forced greenfield mode. |
| Brownfield | Brownfield Governance / Builder | Existing-codebase mode where current behavior must be discovered and preserved, changed, retired, or investigated deliberately. | `docs/Brownfield_Guide.md`; `src/ces/cli/_builder_flow.py`; `src/ces/brownfield/` | Fact | Do not equate brownfield with old server mode. |
| Legacy behavior | Brownfield Governance | Observed behavior in an existing system, stored as an OLB register entry before it can be promoted to PRL. | `src/ces/brownfield/services/legacy_register.py`; `src/ces/brownfield/records.py`; `src/ces/local_store/store.py` | Fact | Register entries are not PRL items until copy-on-promote. |
| Disposition | Brownfield Governance | Decision for a legacy behavior. Code accepts `preserve`, `change`, `retire`, `under_investigation`, and `new` via `LegacyDisposition`. | `src/ces/shared/enums.py`; `src/ces/cli/brownfield_cmd.py`; `src/ces/cli/_builder_flow.py` | Fact | Docs still mention `migrate/remove`; do not introduce more aliases without a compatibility decision. |
| PRL | Control Plane / Brownfield | Prioritized Requirements List item model; reviewed brownfield behavior can be promoted into PRL through copy-on-promote. | `src/ces/control/models/prl_item.py`; `src/ces/brownfield/services/legacy_register.py`; `src/ces/local_store/store.py` | Fact | Preserve source OLB back-reference when changing promotion behavior. |
| Manifest | Control Plane | Signed governance contract bounding one agent task: scope, risk, files, tools, TTL, workflow state, dependencies, and completion sensors. | `src/ces/control/models/manifest.py`; `src/ces/control/services/manifest_manager.py`; `src/ces/local_store/store.py` | Fact | Serialized fields, enum values, signatures, and content hashes are contract surfaces. |
| Workflow state | Control Plane | Main manifest lifecycle values: `queued`, `in_flight`, `verifying`, `under_review`, `approved`, `merged`, `deployed`, `rejected`, `failed`, `cancelled`. | `src/ces/shared/enums.py`; workflow command tests | Fact | Reconstruct from persisted manifest state; do not assume a command always starts from queued. |
| Risk tier | Control Plane | Ordered risk dimension where `A` is highest and `C` is lowest. | `src/ces/shared/enums.py`; `README.md`; classification tests | Fact | Do not sort lexicographically; code has explicit ordering. |
| Behavior confidence | Control Plane | Ordered predictability dimension where `BC3` is highest risk. | `src/ces/shared/enums.py`; `README.md` | Fact | Keep separate from risk tier. |
| Change class | Control Plane | Ordered change type dimension with serialized values `Class 1` through `Class 5`. | `src/ces/shared/enums.py`; `README.md` | Fact | Do not replace with shorthand such as `class_1` in persisted/public data. |
| Gate | Control Plane / Harness | Overloaded term: review/merge gate (`GateType`, `GateDecision`) or completion gate sensor set on a manifest. | `src/ces/shared/enums.py`; `src/ces/control/services/merge_controller.py`; `src/ces/harness/services/completion_verifier.py` | Fact | Always name the exact gate type before editing. |
| Evidence packet | Harness / Review | Structured proof trail containing decision view, chain of custody, test outcomes, honesty disclosures, and raw evidence links; local store also persists evidence dicts. | `src/ces/control/models/evidence_packet.py`; `src/ces/local_store/store.py`; review/triage tests | Fact | Keep Pydantic model and persisted dict shape aligned. |
| Review finding | Harness / Review | Structured reviewer finding with severity, category, location, title, description, recommendation, and confidence. | `src/ces/harness/models/review_finding.py`; `src/ces/local_store/store.py` | Fact | `finding_id` is reviewer-provided; local schema uses a synthetic integer PK. |
| Completion claim | Execution / Harness | JSON payload emitted inside a fenced `ces:completion` block and parsed into `CompletionClaim`. | `src/ces/execution/completion_parser.py`; `src/ces/harness/models/completion_claim.py`; execute command tests | Fact | Parser failures return `None`; verifier turns that into schema-violation feedback. |
| Runtime | Execution | Local agent CLI adapter used to execute work; currently `codex` and `claude` are registered. | `src/ces/execution/runtimes/registry.py`; `src/ces/execution/runtimes/protocol.py`; `.env.example` | Fact | Do not confuse runtime with LLM provider. |
| Provider | Execution / Review | LLM-backed helper registry used for manifest assist, review, and evidence synthesis; can run demo/fallback behavior. | `src/ces/execution/providers/`; `src/ces/cli/_factory.py`; `src/ces/shared/config.py` | Fact | `CES_DEMO_MODE=1` does not replace real runtime execution for `ces build`. |
| Local project state | Local Store | Per-project `.ces/` directory containing `state.db`, keys, artifacts, exports, baseline, and config. | `src/ces/local_store/store.py`; `docs/Database_Operations.md`; `.gitignore` | Fact | Do not delete `.ces/` when audit history matters. |
| Audit ledger | Control Plane / Local Store | Append-only HMAC-linked governance event history with no-update/no-delete SQLite triggers. | `src/ces/control/services/audit_ledger.py`; `src/ces/local_store/store.py`; `src/ces/shared/enums.py` | Fact | Event enum currently contains more than old docs' "14 event types"; verify counts from code, not prose. |
| Truth artifact | Control Plane | Published governed artifact union for vision anchor, PRL item, architecture blueprint, interface contract, and migration control pack. | `src/ces/control/models/__init__.py`; `src/ces/shared/base.py` | Fact | `TaskManifest` inherits governed artifact behavior but is not in the `TruthArtifact` union. |
| Spec | Spec Authoring | Markdown plus YAML frontmatter parsed into stories and decomposed into manifests. | `src/ces/control/models/spec.py`; `src/ces/control/spec/parser.py`; `src/ces/control/spec/templates/` | Fact | Treat required sections and signal fields as a file-format contract if `ces spec` is public. |
| Scan | CLI / Brownfield Support | Repository inventory command that can feed `.ces/brownfield/scan.json` and brownfield register import. | `src/ces/cli/scan_cmd.py`; `src/ces/cli/brownfield_cmd.py`; scan tests | Fact | Scan output is a potential contract; check tests before reshaping. |
| Baseline | CLI / Harness Support | Day-0 sensor snapshot under `.ces/baseline/`. | `src/ces/cli/baseline_cmd.py`; CLI registration; tests | Fact | Do not confuse with manifest baseline or Git base ref. |
| Dogfood | CLI / CI | CES reviewing its own or another repo's diff through `ces dogfood`, used by generated CI templates. | `src/ces/cli/dogfood_cmd.py`; `src/ces/cli/templates/ci/`; `README.md` | Fact | Generated workflow behavior is user-facing. |
| Compatibility infrastructure | Tests / Packaging | Optional Postgres/Alembic/SQLAlchemy paths kept for compatibility tests, not supported default runtime. | `pyproject.toml`; `alembic.ini`; `tests/integration/_compat/` | Fact | Future agents are likely to guess wrong here; keep docs explicit. |

## Ambiguous Or Overloaded Terms

- `legacy`: means brownfield observed behavior in `src/ces/brownfield/`, but can also mean historical server-era CES docs. Use `legacy behavior` or `historical server mode`.
- `gate`: can mean merge/review gate or completion gate. Cite `GateEvaluator`, `MergeController`, or `CompletionVerifier`.
- `runtime` vs `provider`: runtime executes local CLI work; provider supports LLM helper/review flows.
- `status`: appears as artifact status, workflow state, builder session stage, CLI output, and enum values.
- `manifest`: can mean Pydantic model, SQLite row, CLI command output, spec-derived work item, or signed artifact.
- `migration`: can mean product data migration model, local SQLite in-app migration, compatibility Alembic revision, or generic migration sensor finding.
- `source of truth`: brownfield operator input, truth artifact dependency, docs evidence, or persisted project state depending on context.

## Likely Places Agents Guess Wrong

- Treating root `alembic.ini` or `tests/integration/_compat/alembic/` as production deployment/migration surfaces.
- Changing public enum serialized values because Python identifiers look cleaner than wire values.
- Treating `CES_DEMO_MODE` as enough to execute real builder work without a detected `codex` or `claude` runtime.
- Collapsing `migrate/remove` docs wording into code without reconciling `change/retire` enum values.
- Assuming historical PRD/roadmap docs override current local-first docs and factory enforcement.
