# CES Harness Evolution Layer Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task. Keep PRs sequential and non-stacked unless Chris explicitly asks otherwise.

**Goal:** Add an evidence-driven harness evolution layer to CES so agent-runtime improvements are component-observable, trajectory-grounded, falsifiable, reversible, and regression-aware.

**Architecture:** Build this as a conservative local-first extension of existing CES primitives, not as a new autonomous self-modifying system. The first milestone introduces read-only models, persistence, and reports; later milestones add dogfood trajectory distillation, post-success protection, cross-step risk sensing, and controlled runtime prompt injection. Existing builder/expert execution should be consolidated enough to avoid duplicating policy logic before deeper harness evolution is wired into default workflows.

**Tech Stack:** Python 3.12+, Typer/Rich CLI, Pydantic models, existing SQLite local store, pytest, ruff, mypy, no new runtime dependency unless separately justified.

---

## 0. Design posture and constraints

### What this plan deliberately does

- Treat CES itself as an AI-agent control plane whose harness should be observable and improvable.
- Implement the paper’s useful ideas in CES terms:
  - component observability
  - experience / trajectory observability
  - decision observability
  - falsifiable change manifests
  - regression attribution
  - post-success state protection
  - cross-step risk monitoring
- Keep everything local-first under `.ces/` and SQLite.
- Prefer deterministic/static analysis before LLM-enhanced analysis.
- Preserve current public boundaries: CES is not a sandbox and not a hosted control plane.

### What this plan deliberately does **not** do yet

- No fully autonomous harness self-modification loop in the first implementation.
- No benchmark leaderboard claims.
- No remote service, Postgres, Redis, or hosted control plane.
- No hidden-check infrastructure until the normal trajectory/evidence loop works.
- No broad prompt rewrite as the primary mechanism.
- No new dependency unless a PR explicitly argues for it.
- No push/merge/release as part of implementation.

---

## 1. Recommended PR sequence

### PR 1 — Harness component substrate and change-manifest model

**Purpose:** Introduce a file-level local harness substrate and falsifiable change-manifest schema without affecting runtime behavior.

**Why first:** The AHE paper’s core finding is that harness evolution only works when the editable action space is explicit and rollbackable. CES should make this substrate real before adding analysis or injection.

**Primary files:**

- Create: `src/ces/harness_evolution/__init__.py`
- Create: `src/ces/harness_evolution/models.py`
- Create: `src/ces/harness_evolution/paths.py`
- Create: `src/ces/harness_evolution/manifest_io.py`
- Create: `src/ces/cli/harness_cmd.py`
- Modify: `src/ces/cli/__init__.py`
- Test: `tests/unit/test_harness_evolution/test_models.py`
- Test: `tests/unit/test_harness_evolution/test_manifest_io.py`
- Test: `tests/unit/test_cli/test_harness_cmd.py`
- Docs: `docs/Operator_Playbook.md`
- Docs: `docs/Quick_Reference_Card.md`

**Acceptance criteria:**

- `ces harness init --dry-run` shows intended `.ces/harness/` layout without writing.
- `ces harness init` creates only local `.ces/harness/` directories and an `index.json`.
- Harness change manifests validate via Pydantic.
- Manifests include predicted fixes and predicted regressions.
- Secret-looking content is rejected or redacted in manifests.
- No runtime prompt injection yet.

---

### PR 2 — Local persistence for harness changes and attribution-ready records

**Purpose:** Persist harness change manifests and later validation verdicts in SQLite.

**Why second:** CES needs durable attribution before dogfood/evaluation can prove whether changes helped or hurt.

**Primary files:**

- Modify: `src/ces/local_store/schema.py`
- Modify: `src/ces/local_store/records.py`
- Modify: `src/ces/local_store/repositories.py`
- Modify: `src/ces/local_store/store.py`
- Create: `src/ces/harness_evolution/repository.py`
- Test: `tests/unit/test_local_store_schema.py`
- Test: `tests/unit/test_harness_evolution/test_repository.py`

**Acceptance criteria:**

- SQLite schema includes harness change records.
- Change manifests can be saved, listed, loaded, and marked with a verdict.
- Existing `.ces/state.db` initialization still works.
- Tests cover idempotent schema creation.
- No irreversible schema migration is introduced without a backup path.

---

### PR 3 — Trajectory/evidence distillation for dogfood runs

**Purpose:** Convert raw runtime transcripts and dogfood logs into structured, drill-down failure/success reports.

**Why third:** Experience observability should feed future harness changes. CES should not evolve from raw logs or vibes.

**Primary files:**

- Create: `src/ces/harness_evolution/trajectory.py`
- Create: `src/ces/harness_evolution/distiller.py`
- Create: `src/ces/harness_evolution/patterns.py`
- Modify: `src/ces/cli/dogfood_cmd.py`
- Create: `src/ces/cli/harness_analyze_cmd.py` or extend `harness_cmd.py`
- Test: `tests/unit/test_harness_evolution/test_trajectory.py`
- Test: `tests/unit/test_harness_evolution/test_distiller.py`
- Test: `tests/unit/test_cli/test_harness_analyze_cmd.py`

**Acceptance criteria:**

- `ces harness analyze --from-transcript <path>` emits JSON and markdown.
- Distillation output includes:
  - task/run id when available
  - pass/fail/unknown outcome
  - failure class
  - suspected root cause
  - validation commands observed
  - proxy-validation warnings
  - evidence pointers
- Raw transcript contents are not duplicated into giant reports by default.
- Secret scrubbing is applied.

---

### PR 4 — Change attribution and regression-aware verdicts

**Purpose:** Compare predicted change effects against observed dogfood/evaluation deltas.

**Why fourth:** The paper found self-attribution works better for fixes than regressions. CES should explicitly score both.

**Primary files:**

- Create: `src/ces/harness_evolution/attribution.py`
- Create: `src/ces/harness_evolution/verdicts.py`
- Modify: `src/ces/cli/harness_cmd.py`
- Test: `tests/unit/test_harness_evolution/test_attribution.py`
- Test: `tests/unit/test_cli/test_harness_verdict_cmd.py`

**Acceptance criteria:**

- `ces harness verdict <change-id> --from <analysis.json>` computes:
  - predicted fixes observed
  - predicted fixes missed
  - predicted regressions observed
  - unexpected regressions
  - net verdict: `keep`, `revise`, `rollback`, `inconclusive`
- Verdicts are persisted.
- Regression blindness is visible, not hidden behind net-positive language.

---

### PR 5 — Post-success state protection sensor

**Purpose:** Prevent agents from reaching a verified state and then damaging it with cleanup or extra changes.

**Why fifth:** This is one of the most directly actionable AHE findings and maps to CES’s existing completion gate.

**Primary files:**

- Create: `src/ces/harness/sensors/post_success_state.py`
- Modify: `src/ces/harness/services/sensor_orchestrator.py`
- Modify: `src/ces/cli/run_cmd.py` only minimally, or preferably through extracted pipeline hooks if available
- Test: `tests/unit/test_sensors/test_post_success_state.py`
- Test: `tests/unit/test_cli/test_run_post_success_state.py`

**Acceptance criteria:**

- Sensor detects protected outputs/files after successful verification.
- Sensor warns or blocks if later workspace delta deletes/modifies protected outputs.
- Override path is explicit and recorded in evidence.
- Revalidation is required after override.

---

### PR 6 — Cross-step execution-risk monitor

**Purpose:** Detect behavioral anti-patterns across command sequences, not only individual outputs.

**Why sixth:** CES already has sensors and evidence, but lacks temporal command-sequence intelligence.

**Primary files:**

- Create: `src/ces/harness/services/execution_risk_monitor.py`
- Create: `src/ces/harness/models/execution_risk.py`
- Modify: `src/ces/execution/output_capture.py` or transcript parsing layer as needed
- Modify: `src/ces/harness/services/evidence_synthesizer.py`
- Test: `tests/unit/test_harness/test_execution_risk_monitor.py`

**Acceptance criteria:**

- Detects at least:
  - repeated same failing command
  - shallow validation replacing project test/evaluator
  - proxy validator patterns
  - timeout loops
  - destructive command after success
  - compile-only validation for behavioral changes
- Findings appear in builder report and evidence packet.
- Findings have severity and recommended next action.

---

### PR 7 — Framework reminder injection for critical findings

**Purpose:** Promote high-salience warnings into the next runtime prompt context rather than burying them in logs.

**Why seventh:** The paper found agents ignore warnings in tool output. CES can make critical warnings salient at the next reasoning step.

**Primary files:**

- Create: `src/ces/harness/services/framework_reminders.py`
- Modify: `src/ces/cli/run_cmd.py` or shared prompt-builder service
- Modify: `src/ces/cli/execute_cmd.py` through shared execution pipeline if available
- Test: `tests/unit/test_harness/test_framework_reminders.py`
- Test: `tests/unit/test_cli/test_run_framework_reminders.py`

**Acceptance criteria:**

- Critical sensor/risk findings can generate a concise framework reminder.
- Reminder is included in next runtime prompt only when relevant.
- Reminder content is deterministic and non-secret.
- Evidence records which reminder was injected and why.

---

### PR 8 — Evidence-backed local memory / skills integration

**Purpose:** Convert recurring dogfood lessons into compact local harness memory or skills with source evidence and hashes.

**Why eighth:** AHE’s ablation suggests memory/skills can outperform prompt-only changes. CES already has a vault direction but needs persistence and hashable evidence-backed artifacts.

**Primary files:**

- Create or extend: `src/ces/harness_evolution/memory.py`
- Create or extend: `src/ces/harness_evolution/skills.py`
- Modify: `src/ces/knowledge/services/vault_service.py`
- Modify: `src/ces/cli/vault_cmd.py`
- Possibly modify: `src/ces/local_store/schema.py`
- Test: `tests/unit/test_knowledge/test_vault_persistence.py`
- Test: `tests/unit/test_harness_evolution/test_memory.py`

**Acceptance criteria:**

- Local memory lessons are persisted.
- Each lesson has evidence links and content hash.
- Draft lessons are not injected by default.
- Activated lessons can be selected for a builder run.
- Evidence records exact lesson hashes used.

---

### PR 9 — Builder/expert execution consolidation

**Purpose:** Reduce lifecycle drift by extracting shared execution/evidence/policy services from CLI modules.

**Why ninth:** This can be done earlier if needed, but it becomes especially important before harness reminders/memory are injected into both builder and expert paths.

**Primary files:**

- Create: `src/ces/execution/pipeline.py`
- Create: `src/ces/harness/services/evidence_pipeline.py`
- Create: `src/ces/control/services/approval_pipeline.py`
- Modify: `src/ces/cli/run_cmd.py`
- Modify: `src/ces/cli/execute_cmd.py`
- Modify: `src/ces/cli/approve_cmd.py`
- Test: `tests/unit/test_execution/test_pipeline.py`
- Test: existing CLI tests for run/execute/approve

**Acceptance criteria:**

- Builder and expert paths share completion-prompt construction or at least shared completion-contract fragments.
- Risk gate mapping lives in service code, not duplicated CLI helpers.
- Existing CLI behavior remains stable.
- Tests verify equivalent lifecycle transitions for common scenarios.

---

### PR 10 — Harness evolution operator report

**Purpose:** Give Chris/operator a clear report that explains what CES learned, what it changed, whether it helped, and what remains risky.

**Primary files:**

- Create: `src/ces/harness_evolution/report.py`
- Modify: `src/ces/cli/harness_cmd.py`
- Test: `tests/unit/test_harness_evolution/test_report.py`
- Docs: `docs/Operator_Playbook.md`

**Acceptance criteria:**

- `ces harness report` outputs markdown and JSON.
- Report includes:
  - active harness components
  - change history
  - predictions vs observed outcomes
  - regressions
  - current recommendations
  - rollback candidates
- Report is concise by default and drill-down capable.

---

## 2. Proposed final CLI surface

Initial commands should be conservative and mostly read-only:

```bash
ces harness init --dry-run
ces harness init
ces harness inspect
ces harness changes list
ces harness changes show <change-id>
ces harness changes validate <manifest.json>
ces harness analyze --from-transcript <path> --format markdown
ces harness verdict <change-id> --from-analysis <analysis.json>
ces harness report --format markdown
```

Later, after validation:

```bash
ces harness memory draft --from-analysis <analysis.json>
ces harness memory activate <lesson-id>
ces harness rollback <change-id> --dry-run
ces harness rollback <change-id> --yes
```

Avoid names like `ces harness evolve --auto` until the underlying reports and attribution prove reliable.

---

## 3. Data model sketch

### Harness component type

```python
from enum import StrEnum

class HarnessComponentType(StrEnum):
    SYSTEM_PROMPT = "system_prompt"
    TOOL_DESCRIPTION = "tool_description"
    TOOL_POLICY = "tool_policy"
    MIDDLEWARE = "middleware"
    SKILL = "skill"
    SUBAGENT = "subagent"
    MEMORY = "memory"
    RUNTIME_PROFILE = "runtime_profile"
```

### Harness change manifest

```python
from datetime import UTC, datetime
from pydantic import BaseModel, Field

class HarnessChangeManifest(BaseModel):
    change_id: str = Field(pattern=r"^hchg-[a-zA-Z0-9_.:-]+$")
    title: str
    component_type: HarnessComponentType
    files_changed: list[str]
    evidence_refs: list[str]
    failure_pattern: str
    root_cause_hypothesis: str
    predicted_fixes: list[str] = Field(default_factory=list)
    predicted_regressions: list[str] = Field(default_factory=list)
    validation_plan: list[str] = Field(default_factory=list)
    rollback_condition: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: str = "draft"
```

### Harness verdict

```python
class HarnessChangeVerdict(BaseModel):
    change_id: str
    observed_fixes: list[str]
    missed_fixes: list[str]
    observed_predicted_regressions: list[str]
    unexpected_regressions: list[str]
    verdict: str  # keep | revise | rollback | inconclusive
    rationale: str
```

### Distilled trajectory report

```python
class TrajectoryAnalysis(BaseModel):
    source_path: str
    task_id: str | None = None
    outcome: str  # pass | fail | blocked | unknown
    failure_class: str | None = None
    root_cause: str | None = None
    validation_commands: list[str] = Field(default_factory=list)
    proxy_validation_warnings: list[str] = Field(default_factory=list)
    destructive_after_success: bool = False
    evidence_refs: list[str] = Field(default_factory=list)
```

---

## 4. Implementation tasks by PR

## PR 1 detailed tasks — Harness substrate and change manifests

### Task 1.1: Add package skeleton

**Objective:** Create the new harness evolution package without behavior.

**Files:**

- Create: `src/ces/harness_evolution/__init__.py`
- Create: `tests/unit/test_harness_evolution/__init__.py`

**Steps:**

1. Create empty package files.
2. Run: `uv run pytest tests/unit/test_harness_evolution -q`
3. Expected: passes or no tests collected once test package exists.

---

### Task 1.2: Add component and manifest models

**Objective:** Define typed models for harness component and change-manifest records.

**Files:**

- Create: `src/ces/harness_evolution/models.py`
- Create: `tests/unit/test_harness_evolution/test_models.py`

**Test cases:**

- valid manifest accepts predicted fixes and regressions
- invalid `change_id` is rejected
- empty `rollback_condition` is rejected
- secret-looking evidence content is rejected or redacted depending on implementation choice

**Command:**

```bash
uv run pytest tests/unit/test_harness_evolution/test_models.py -q
```

**Expected:** fail before implementation, pass after.

---

### Task 1.3: Add deterministic harness paths

**Objective:** Centralize local `.ces/harness/` layout logic.

**Files:**

- Create: `src/ces/harness_evolution/paths.py`
- Create: `tests/unit/test_harness_evolution/test_paths.py`

**Expected layout:**

```text
.ces/harness/index.json
.ces/harness/prompts/
.ces/harness/tool_descriptions/
.ces/harness/tool_policies/
.ces/harness/middleware/
.ces/harness/skills/
.ces/harness/subagents/
.ces/harness/memory/
.ces/harness/runtime_profiles/
.ces/harness/change_manifests/
.ces/harness/analysis/
.ces/harness/verdicts/
```

**Command:**

```bash
uv run pytest tests/unit/test_harness_evolution/test_paths.py -q
```

---

### Task 1.4: Add manifest JSON IO

**Objective:** Read/write change manifests with stable JSON and safe permissions.

**Files:**

- Create: `src/ces/harness_evolution/manifest_io.py`
- Create: `tests/unit/test_harness_evolution/test_manifest_io.py`

**Test cases:**

- round-trip manifest preserves fields
- stable JSON ordering
- rejects path traversal for manifest filenames
- writes under `change_manifests/` only

**Command:**

```bash
uv run pytest tests/unit/test_harness_evolution/test_manifest_io.py -q
```

---

### Task 1.5: Add `ces harness init/inspect/changes validate`

**Objective:** Expose a minimal CLI without runtime integration.

**Files:**

- Create: `src/ces/cli/harness_cmd.py`
- Modify: `src/ces/cli/__init__.py`
- Create: `tests/unit/test_cli/test_harness_cmd.py`

**Commands to support:**

```bash
ces harness init --dry-run
ces harness init
ces harness inspect
ces harness changes validate path/to/manifest.json
```

**Test cases:**

- dry-run does not write
- init creates expected directories
- inspect works if not initialized and gives next action
- validate returns non-zero on invalid manifest

**Command:**

```bash
uv run pytest tests/unit/test_cli/test_harness_cmd.py -q
```

---

### Task 1.6: Document operator boundary

**Objective:** Explain harness evolution as local, explicit, and non-autonomous by default.

**Files:**

- Modify: `docs/Operator_Playbook.md`
- Modify: `docs/Quick_Reference_Card.md`
- Modify: `README.md` only if command surface is stable enough

**Validation:**

```bash
uv run pytest tests/unit/test_docs -q
```

---

## PR 2 detailed tasks — Persistence

### Task 2.1: Add schema tables

**Objective:** Add local tables for harness changes and verdicts.

**Files:**

- Modify: `src/ces/local_store/schema.py`
- Modify: `tests/unit/test_local_store_schema.py`

**Suggested tables:**

```sql
harness_changes(
  change_id TEXT PRIMARY KEY,
  component_type TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  manifest_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)

harness_change_verdicts(
  id TEXT PRIMARY KEY,
  change_id TEXT NOT NULL,
  verdict TEXT NOT NULL,
  verdict_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(change_id) REFERENCES harness_changes(change_id)
)
```

**Command:**

```bash
uv run pytest tests/unit/test_local_store_schema.py -q
```

---

### Task 2.2: Add repository methods

**Objective:** Save/list/load/update harness change records.

**Files:**

- Modify: `src/ces/local_store/records.py`
- Modify: `src/ces/local_store/repositories.py`
- Create: `src/ces/harness_evolution/repository.py`
- Create: `tests/unit/test_harness_evolution/test_repository.py`

**Required methods:**

- `save_change(manifest)`
- `get_change(change_id)`
- `list_changes(status=None)`
- `save_verdict(verdict)`
- `list_verdicts(change_id)`

**Command:**

```bash
uv run pytest tests/unit/test_harness_evolution/test_repository.py -q
```

---

### Task 2.3: Wire persistence into CLI

**Objective:** Persist validated manifests and list/show them.

**Files:**

- Modify: `src/ces/cli/harness_cmd.py`
- Modify: `tests/unit/test_cli/test_harness_cmd.py`

**Commands:**

```bash
ces harness changes add manifest.json
ces harness changes list
ces harness changes show hchg-...
```

**Validation:**

```bash
uv run pytest tests/unit/test_cli/test_harness_cmd.py tests/unit/test_harness_evolution/test_repository.py -q
```

---

## PR 3 detailed tasks — Trajectory distillation

### Task 3.1: Add transcript parser abstraction

**Objective:** Parse transcript-like files into bounded events without assuming one runtime format forever.

**Files:**

- Create: `src/ces/harness_evolution/trajectory.py`
- Create: `tests/unit/test_harness_evolution/test_trajectory.py`

**Test fixtures:**

- simple command/pass transcript
- repeated failure transcript
- proxy validation transcript
- transcript containing fake secret that must be scrubbed

---

### Task 3.2: Add deterministic distiller

**Objective:** Produce compact analysis from trajectory events.

**Files:**

- Create: `src/ces/harness_evolution/distiller.py`
- Create: `tests/unit/test_harness_evolution/test_distiller.py`

**Failure classes v1:**

- `proxy_validation`
- `repeated_retry`
- `timeout_loop`
- `destructive_after_success`
- `missing_verification`
- `scope_drift`
- `unknown`

---

### Task 3.3: Add CLI analysis command

**Objective:** Let operators analyze a transcript/report file.

**Files:**

- Modify: `src/ces/cli/harness_cmd.py`
- Modify: `tests/unit/test_cli/test_harness_cmd.py`

**Command:**

```bash
ces harness analyze --from-transcript .ces/runtime-transcripts/<file> --format json
ces harness analyze --from-transcript .ces/runtime-transcripts/<file> --format markdown
```

---

## PR 4 detailed tasks — Attribution/verdicts

### Task 4.1: Add attribution model and scorer

**Objective:** Compare predictions to observed results.

**Files:**

- Create: `src/ces/harness_evolution/attribution.py`
- Create: `tests/unit/test_harness_evolution/test_attribution.py`

**Test cases:**

- predicted fix observed -> `keep`
- predicted fix missed -> `revise` or `inconclusive`
- predicted regression observed -> `rollback` unless outweighed and explicitly accepted
- unexpected regression -> `rollback` or `revise`
- no data -> `inconclusive`

---

### Task 4.2: Add verdict CLI

**Objective:** Persist and show change verdicts.

**Files:**

- Modify: `src/ces/cli/harness_cmd.py`
- Modify: `tests/unit/test_cli/test_harness_cmd.py`

**Commands:**

```bash
ces harness verdict hchg-... --from-analysis analysis.json
ces harness verdicts list hchg-...
```

---

## PR 5 detailed tasks — Post-success protection

### Task 5.1: Add model for protected state

**Objective:** Represent files/outputs/services protected after verification success.

**Files:**

- Create: `src/ces/harness/models/post_success_state.py`
- Create: `tests/unit/test_models/test_post_success_state.py`

---

### Task 5.2: Add post-success sensor

**Objective:** Detect deletion/modification of protected files after success.

**Files:**

- Create: `src/ces/harness/sensors/post_success_state.py`
- Create: `tests/unit/test_sensors/test_post_success_state.py`

**Test cases:**

- protected file unchanged -> pass
- protected file deleted -> high severity finding
- protected file modified after verification -> high severity finding
- temp/cache files ignored

---

### Task 5.3: Integrate into sensor orchestration

**Objective:** Include post-success findings in evidence and builder reports.

**Files:**

- Modify: `src/ces/harness/services/sensor_orchestrator.py`
- Modify: `src/ces/harness/services/evidence_synthesizer.py`
- Modify: relevant builder report code only if needed

**Validation:**

```bash
uv run pytest tests/unit/test_sensors/test_post_success_state.py tests/unit/test_harness -q
```

---

## PR 6 detailed tasks — Cross-step execution-risk monitor

### Task 6.1: Add execution-risk models

**Files:**

- Create: `src/ces/harness/models/execution_risk.py`
- Create: `tests/unit/test_models/test_execution_risk.py`

---

### Task 6.2: Add monitor service

**Files:**

- Create: `src/ces/harness/services/execution_risk_monitor.py`
- Create: `tests/unit/test_harness/test_execution_risk_monitor.py`

**Rules v1:**

- same command fails 3+ times
- verification claim contains only compile/lint for behavioral change
- command pattern writes a custom validator and uses only that validator
- timeout repeated without strategy change
- deletion after success marker

---

### Task 6.3: Surface findings in evidence

**Files:**

- Modify: `src/ces/harness/services/evidence_synthesizer.py`
- Modify: `src/ces/harness/models/evidence_packet.py` if model extension is needed
- Update tests around evidence packet serialization

---

## PR 7 detailed tasks — Framework reminders

### Task 7.1: Add reminder generator

**Files:**

- Create: `src/ces/harness/services/framework_reminders.py`
- Create: `tests/unit/test_harness/test_framework_reminders.py`

**Reminder examples:**

- Proxy validation:
  > Your last validation was proxy-level only. Before claiming completion, run the project’s actual test/evaluator command or explain why unavailable.

- Repeated retry:
  > You repeated the same failing command without changing inputs. Inspect the root cause before retrying.

- Post-success risk:
  > A verified output is now protected. Do not delete or rewrite it unless you explicitly revalidate afterward.

---

### Task 7.2: Add prompt-builder hook

**Files:**

- Prefer create/modify shared prompt builder rather than directly expanding `run_cmd.py`.
- Candidate: create `src/ces/harness/services/runtime_prompt_builder.py`
- Modify: `src/ces/cli/run_cmd.py`
- Modify: `src/ces/cli/execute_cmd.py` only through shared code where possible

**Acceptance:**

- Reminder injection is deterministic.
- Reminder source is recorded in evidence.
- No reminder is injected for low-confidence findings.

---

## PR 8 detailed tasks — Memory / skills

### Task 8.1: Fix or clarify vault persistence

**Objective:** Ensure `ces vault write` either persists or honestly reports non-persistence.

**Files:**

- Inspect/modify: `src/ces/knowledge/services/vault_service.py`
- Modify: `src/ces/cli/_factory.py`
- Possibly modify: `src/ces/local_store/schema.py`
- Test: `tests/unit/test_knowledge/test_vault_persistence.py`

**Acceptance:**

- A written note can be read after a new service instance is created.
- If not implementing persistence, docs and CLI must say so explicitly.

---

### Task 8.2: Add evidence-backed harness memory lessons

**Files:**

- Create: `src/ces/harness_evolution/memory.py`
- Create: `tests/unit/test_harness_evolution/test_memory.py`

**Fields:**

- lesson id
- pattern
- recommendation
- evidence refs
- confidence
- applies_to project types
- content hash
- activation status

---

### Task 8.3: Record memory hashes in evidence

**Files:**

- Modify: `src/ces/harness/services/evidence_synthesizer.py`
- Modify: evidence packet model if needed
- Test: relevant evidence tests

---

## PR 9 detailed tasks — Execution consolidation

### Task 9.1: Extract completion prompt contract

**Objective:** Remove duplicated completion instruction fragments from builder/expert CLI paths.

**Files:**

- Create: `src/ces/verification/completion_prompt.py`
- Modify: `src/ces/cli/run_cmd.py`
- Modify: `src/ces/cli/execute_cmd.py`
- Test: `tests/unit/test_verification/test_completion_prompt.py`

---

### Task 9.2: Extract risk gate mapping

**Objective:** Move duplicated risk/gate mapping into service code.

**Files:**

- Create or modify: `src/ces/control/services/gate_policy.py`
- Modify: `src/ces/cli/run_cmd.py`
- Modify: `src/ces/cli/review_cmd.py`
- Modify: `src/ces/cli/approve_cmd.py`
- Test: `tests/unit/test_services/test_gate_policy.py`

---

### Task 9.3: Extract execution result normalization

**Objective:** Normalize runtime results in one place.

**Files:**

- Create: `src/ces/execution/result_normalizer.py`
- Modify: `src/ces/cli/run_cmd.py`
- Modify: `src/ces/cli/execute_cmd.py`
- Test: `tests/unit/test_execution/test_result_normalizer.py`

---

## PR 10 detailed tasks — Reports

### Task 10.1: Add report renderer

**Files:**

- Create: `src/ces/harness_evolution/report.py`
- Create: `tests/unit/test_harness_evolution/test_report.py`

---

### Task 10.2: Add `ces harness report`

**Files:**

- Modify: `src/ces/cli/harness_cmd.py`
- Modify: `tests/unit/test_cli/test_harness_cmd.py`

**Report sections:**

- active components
- changes by status
- latest verdicts
- predicted vs observed outcomes
- regression warnings
- rollback candidates
- recommended next CES action

---

## 5. Verification strategy

Run focused commands per PR, then the full local gate before opening a PR.

### Focused gates

```bash
uv run pytest tests/unit/test_harness_evolution -q
uv run pytest tests/unit/test_cli/test_harness_cmd.py -q
uv run pytest tests/unit/test_harness -q
uv run pytest tests/unit/test_sensors -q
```

### Standard full local gates

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/ces/ --ignore-missing-imports
uv run pytest tests/unit -q
uv run pytest tests/ -m "not integration" --cov=ces --cov-fail-under=90 --cov-report=term-missing -q -W error
uv build
uvx twine check dist/*
```

### Manual smoke checks

```bash
uv run ces harness init --dry-run
uv run ces harness init
uv run ces harness inspect
uv run ces harness changes list
uv run ces harness report --format markdown
uv run ces mri --format json > /tmp/ces-mri.json
python -m json.tool /tmp/ces-mri.json >/dev/null
```

---

## 6. Definition of done for the full epic

The epic is complete when:

- CES has a local `.ces/harness/` component substrate.
- Harness changes are represented as falsifiable manifests.
- Change manifests persist locally and can receive verdicts.
- Dogfood/runtime transcripts can be distilled into compact evidence reports.
- CES can compare predicted fixes/regressions against observed outcomes.
- CES surfaces post-success state damage as a blocking or high-severity finding.
- CES detects at least five cross-step execution-risk patterns.
- High-confidence findings can become next-turn framework reminders.
- Evidence-backed local memory/skills are persistent, hashable, and opt-in.
- Builder/expert paths share core completion/risk/result logic enough to avoid policy drift.
- `ces harness report` gives a useful operator-level summary.
- Full local gates pass.
- Documentation clearly states that harness evolution is local, explicit, and not autonomous by default.

---

## 7. Recommended first branch

```bash
git checkout -b feat/harness-evolution-substrate
```

Start with PR 1 only. Keep it small and non-runtime-affecting. The first PR should prove the data model and CLI surface without touching builder execution.

---

## 8. Risks and mitigations

### Risk: CES becomes too complex before core trust semantics are clean

**Mitigation:** Keep PR 1–4 mostly read-only/analysis. Do not inject anything into runtime prompts until attribution and reporting are credible.

### Risk: Prompt sprawl returns under a new name

**Mitigation:** Prefer structural components: middleware, sensors, tool/runtime policies, memory records. Prompt changes require manifests and validation.

### Risk: False positives block useful agent work

**Mitigation:** Start risk monitors as advisory findings. Escalate to blocking only for post-success state damage and explicit forbidden-path changes.

### Risk: Local DB schema instability

**Mitigation:** Add schema tests, idempotent migrations, and backup guidance before changing existing user state semantics.

### Risk: Autonomy exceeds user comfort

**Mitigation:** No automatic harness edits. Commands produce drafts, reports, and rollback plans. Activation remains explicit.

---

## 9. The strategic bet

CES already governs delivery work. This epic lets CES govern its own agent harness improvements.

The valuable leap is not “better prompts.” It is this loop:

```text
runtime traces
→ distilled failure patterns
→ falsifiable harness change manifest
→ component-level edit
→ dogfood/evaluation delta
→ keep / revise / rollback verdict
→ evidence-backed memory
```

That is the AHE paper translated into CES’s local-first governance language.
