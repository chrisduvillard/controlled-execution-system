# CES Control Plane + Repo Skills Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Turn the approved CES improvement proposal into a sequential implementation program that fixes trust semantics first, then adds project-aware verification, benchmark accounting, and project-local repo skills.

**Architecture:** Keep CES local and operator-first. Add small typed domain modules behind existing Typer commands, persist outputs under `.ces/`, record hashes in evidence packets, and gate ship/merge messaging through explicit control-plane status instead of loose triage color strings. Repo skills are project-local markdown artifacts with a JSON index and source-backed metadata; generated skills start as drafts unless explicitly activated.

**Tech Stack:** Python 3.12/3.13, Typer/Rich CLI, Pydantic models, local SQLite store, existing CES harness sensors, `uv run pytest`, `uv run ruff`, `uv run mypy`.

---

## PR Sequence Overview

1. **PR 1 — Trust semantics and status model**
   - Fix the benchmark trust bug: red/blocking governance must not render as “ready to ship” or “Merge Validation Passed.”
   - Add an explicit `ControlPlaneStatus` model and use it in builder summaries.

2. **PR 2 — Project-aware verification profile**
   - Add `.ces/verification-profile.json` and profile detection.
   - Mark missing artifacts as blocking only when configured/required.

3. **PR 3 — Runtime metrics and transcript accounting**
   - Capture duration, command count, token usage when available, tool-call counts, and transcript paths/hashes.
   - Store these in evidence and builder reports.

4. **PR 4 — Repo skills MVP**
   - Add `.ces/skills/` model, index, hashing, and CLI commands: `list`, `show`, `generate`, `activate`, `disable`, `remove`, `doctor`.
   - Keep generation deterministic/template-first for MVP.

5. **PR 5 — Build integration for repo skills**
   - Add `ces build --use-skills auto|none|skill1,skill2`.
   - Inject selected skill content into runtime prompts and record exact skill hashes in evidence.

6. **PR 6 — Brownfield skill refresh and improvement loop**
   - Add codebase/docs/test scan summaries to skill generation.
   - Add `ces skills improve`, `refresh`, `diff`, `prune --dry-run`.

7. **PR 7 — Comparative benchmark suite**
   - Add `ces benchmark compare` to run/replay CES vs non-CES workflows with native metrics.

---

## Shared Verification Commands

Run these after every PR unless the task says otherwise:

```bash
uv run pytest tests/unit/test_harness/test_risk_sensor_policy.py -q
uv run pytest tests/unit/test_cli/test_run_cmd.py -q
uv run pytest tests/unit/test_cli/test_approve_cmd.py -q
uv run ruff check src tests
uv run mypy src
```

For final integration before merge:

```bash
uv run pytest -q
uv run ruff check src tests
uv run mypy src
```

---

# PR 1 — Trust Semantics and Control-Plane Status

## Acceptance Criteria

- `ces build --yes` cannot auto-approve when governance has blocking findings.
- Builder output cannot say `Outcome: ready to ship` unless all these are true:
  - runtime exited 0
  - completion/independent verification passed or is explicitly not configured
  - no workspace scope violations
  - risk-aware sensor policy has no blocking findings
  - approval decision is approve
  - merge controller, if present, allows merge or returns a known “merge not applied” soft state
- Rich panels cannot show `[green]Merge Validation Passed[/green]` when evidence triage is red or sensor policy is blocking.
- Evidence packets contain the explicit control-plane status object.

## Task 1.1: Add status model

**Objective:** Centralize final CES status into a typed model so output does not infer readiness from approval alone.

**Files:**
- Create: `src/ces/harness/models/control_plane_status.py`
- Modify: `src/ces/harness/models/__init__.py`
- Test: `tests/unit/test_harness/test_control_plane_status.py`

**Step 1: Write failing tests**

Create `tests/unit/test_harness/test_control_plane_status.py`:

```python
from ces.harness.models.control_plane_status import ControlPlaneStatus, GovernanceState


def test_ready_to_ship_requires_governance_clear() -> None:
    status = ControlPlaneStatus(
        code_completed=True,
        acceptance_verified=True,
        governance_state=GovernanceState.BLOCKING_RED,
        approval_decision="approve",
        merge_allowed=True,
    )

    assert status.ready_to_ship is False
    assert status.needs_review is True
    assert status.summary_outcome == "approved, but governance is blocked"


def test_ready_to_ship_when_all_gates_clear() -> None:
    status = ControlPlaneStatus(
        code_completed=True,
        acceptance_verified=True,
        governance_state=GovernanceState.CLEAR,
        approval_decision="approve",
        merge_allowed=True,
    )

    assert status.ready_to_ship is True
    assert status.needs_review is False
    assert status.summary_outcome == "ready to ship"
```

**Step 2: Run test to verify failure**

```bash
uv run pytest tests/unit/test_harness/test_control_plane_status.py -q
```

Expected: FAIL — module not found.

**Step 3: Implement model**

Create `src/ces/harness/models/control_plane_status.py`:

```python
from __future__ import annotations

from enum import StrEnum

from ces.shared.base import CESBaseModel


class GovernanceState(StrEnum):
    CLEAR = "clear"
    ADVISORY_YELLOW = "advisory_yellow"
    BLOCKING_RED = "blocking_red"
    NOT_CONFIGURED = "not_configured"


class ControlPlaneStatus(CESBaseModel):
    code_completed: bool
    acceptance_verified: bool
    governance_state: GovernanceState
    approval_decision: str | None = None
    merge_allowed: bool | None = None
    merge_not_applied: bool = False
    blocking_reasons: tuple[str, ...] = ()

    @property
    def governance_clear(self) -> bool:
        return self.governance_state in {GovernanceState.CLEAR, GovernanceState.NOT_CONFIGURED}

    @property
    def needs_review(self) -> bool:
        return not self.ready_to_ship

    @property
    def ready_to_ship(self) -> bool:
        return (
            self.code_completed
            and self.acceptance_verified
            and self.governance_clear
            and self.approval_decision == "approve"
            and (self.merge_allowed is True or self.merge_not_applied)
        )

    @property
    def summary_outcome(self) -> str:
        if self.approval_decision != "approve":
            return "held for another pass"
        if not self.code_completed:
            return "approved, but runtime did not complete"
        if not self.acceptance_verified:
            return "approved, but acceptance verification is blocked"
        if self.governance_state == GovernanceState.BLOCKING_RED:
            return "approved, but governance is blocked"
        if self.merge_allowed is False and not self.merge_not_applied:
            return "approved, but merge is blocked"
        if self.merge_not_applied:
            return "approved, but merge was not applied"
        return "ready to ship"
```

Export from `src/ces/harness/models/__init__.py`.

**Step 4: Verify**

```bash
uv run pytest tests/unit/test_harness/test_control_plane_status.py -q
```

Expected: PASS.

## Task 1.2: Derive governance state from sensor policy and triage

**Objective:** Convert existing sensor policy/triage results into `GovernanceState` consistently.

**Files:**
- Create: `src/ces/harness/services/control_plane_status.py`
- Test: `tests/unit/test_services/test_control_plane_status_service.py`

**Step 1: Write failing tests**

Test cases:
- blocking sensor policy => `BLOCKING_RED`
- red triage without blocking policy => `ADVISORY_YELLOW` unless explicit blocking reasons exist
- green triage and no blocking => `CLEAR`
- governance disabled => `NOT_CONFIGURED`

**Step 2: Implement helper**

Create a helper such as:

```python
def derive_governance_state(*, governance_enabled: bool, triage_color: str | None, sensor_policy_blocking: bool) -> GovernanceState:
    if not governance_enabled:
        return GovernanceState.NOT_CONFIGURED
    if sensor_policy_blocking:
        return GovernanceState.BLOCKING_RED
    if str(triage_color or "").lower() == "red":
        return GovernanceState.ADVISORY_YELLOW
    return GovernanceState.CLEAR
```

**Step 3: Verify**

```bash
uv run pytest tests/unit/test_services/test_control_plane_status_service.py -q
```

Expected: PASS.

## Task 1.3: Use status model in `ces build` summary

**Objective:** Replace `_build_completion_summary` readiness logic with `ControlPlaneStatus.summary_outcome`.

**Files:**
- Modify: `src/ces/cli/run_cmd.py:484-532`
- Modify: `src/ces/cli/run_cmd.py:1170-1316`
- Test: `tests/unit/test_cli/test_run_cmd.py`

**Step 1: Add failing unit test**

Add a focused test for `_build_completion_summary` or public builder scenario asserting:

```python
assert "Outcome: ready to ship" not in summary
assert "approved, but governance is blocked" in summary
```

when `decision="approve"`, `merge_allowed=True`, and `governance_state=GovernanceState.BLOCKING_RED`.

**Step 2: Modify `_build_completion_summary`**

- Add a `control_status: ControlPlaneStatus` parameter.
- Remove readiness inference from `decision`/`merge_allowed` alone.
- Print explicit lines:
  - `Code completed: yes/no`
  - `Acceptance verified: yes/no`
  - `Governance: clear/advisory_yellow/blocking_red/not_configured`
  - `Ready to ship: yes/no`

**Step 3: Build status before rendering**

At `src/ces/cli/run_cmd.py` around the approval/merge section:

- compute `code_completed = execution["exit_code"] == 0`
- compute `acceptance_verified` from `completion_verification`, `independent_verification`, and workspace scope results
- compute `governance_state` using the new service
- pass the `ControlPlaneStatus` into `_build_completion_summary`
- save `control_plane_status` inside evidence content or update evidence after approval if necessary

**Step 4: Gate merge success panel**

Only print `[green]Merge Validation Passed[/green]` when `control_status.ready_to_ship` is true or when the panel text is explicitly renamed to `Merge Preconditions Passed — Governance Still Needs Review` for non-ready states.

Preferred MVP: suppress the green panel unless `control_status.ready_to_ship`.

**Step 5: Verify**

```bash
uv run pytest tests/unit/test_cli/test_run_cmd.py -q
uv run pytest tests/unit/test_harness/test_control_plane_status.py -q
uv run pytest tests/unit/test_services/test_control_plane_status_service.py -q
```

Expected: PASS.

## Task 1.4: Fix `ces approve` merge panel semantics

**Objective:** Prevent approve command from declaring merge validation passed when persisted evidence says blocking governance.

**Files:**
- Modify: `src/ces/cli/approve_cmd.py:533-561`
- Test: `tests/unit/test_cli/test_approve_cmd.py`

**Step 1: Add failing test**

Create a fixture evidence packet whose content includes:

```json
{
  "sensor_policy": {"blocking": true},
  "triage_color": "red"
}
```

Then assert CLI output does not contain `Merge Validation Passed` even if merge controller returns allowed.

**Step 2: Implement guard**

Before printing merge validation:

- inspect persisted `sensor_policy.blocking`
- inspect `control_plane_status.ready_to_ship` if present
- if blocking, print `[red]Governance Blocked[/red]` or `[yellow]Approval Recorded — Merge Not Cleared[/yellow]`

**Step 3: Verify**

```bash
uv run pytest tests/unit/test_cli/test_approve_cmd.py -q
```

Expected: PASS.

---

# PR 2 — Project-Aware Verification Profile

## Acceptance Criteria

- CES can explain which verification artifacts are required, optional, unavailable, or advisory for the current project.
- Missing `coverage.json`, `pytest-results.json`, `ruff-report.json`, or `mypy-report.txt` is blocking only when the verification profile marks that check required.
- Project profiles are stored at `.ces/verification-profile.json`.
- Sensors include `configured`, `required`, and `reason` metadata where possible.

## Task 2.1: Add verification profile model

**Files:**
- Create: `src/ces/verification/profile.py`
- Test: `tests/unit/test_verification/test_profile.py`

**Model outline:**

```python
class VerificationRequirement(CESBaseModel):
    sensor_id: str
    artifact: str | None = None
    command: str | None = None
    required: bool = False
    available: bool = True
    reason: str = ""

class VerificationProfile(CESBaseModel):
    version: int = 1
    project_root: str
    requirements: tuple[VerificationRequirement, ...] = ()
```

## Task 2.2: Detect default profile from repo

**Files:**
- Create: `src/ces/verification/profile_detector.py`
- Test: `tests/unit/test_verification/test_profile_detector.py`

**Detection rules MVP:**

- `pytest` required if `tests/` exists or `pyproject.toml` has pytest config.
- `ruff` required if `ruff` appears in `pyproject.toml` dependencies/config.
- `mypy` required if `mypy` appears in config/deps.
- `coverage` advisory unless explicitly configured.

## Task 2.3: Add CLI command to inspect/write profile

**Files:**
- Create: `src/ces/cli/profile_cmd.py`
- Modify: `src/ces/cli/__init__.py`
- Test: `tests/unit/test_cli/test_profile_cmd.py`

**Command surface:**

```bash
ces profile show
ces profile detect --write
ces profile doctor
```

## Task 2.4: Make completion-gate sensors profile-aware

**Files:**
- Modify: `src/ces/harness/sensors/completion_gate.py`
- Modify: `src/ces/harness/services/risk_sensor_policy.py`
- Test: `tests/unit/test_harness/test_risk_sensor_policy.py`
- Test: `tests/unit/test_sensors/test_completion_gate.py`

**Implementation notes:**

- Add `verification_profile` to sensor context.
- If sensor is not configured/required and artifact missing, mark skipped or advisory instead of failed blocking.
- If required and missing, keep failed high/critical finding.

---

# PR 3 — Runtime Metrics and Transcript Accounting

## Acceptance Criteria

- CES evidence contains a `runtime_metrics` object.
- Metrics include duration seconds, exit code, command/tool counts where available, token usage where available, transcript path, and transcript hash.
- Benchmark reports no longer require manual Codex JSONL inspection for basic accounting.

## Task 3.1: Add runtime metrics model

**Files:**
- Create: `src/ces/execution/models/runtime_metrics.py`
- Test: `tests/unit/test_execution/test_runtime_metrics.py`

**Fields:**

```python
runtime_name: str
started_at: datetime | None
finished_at: datetime | None
duration_seconds: float | None
exit_code: int | None
total_tokens: int | None
input_tokens: int | None
cached_input_tokens: int | None
output_tokens: int | None
reasoning_output_tokens: int | None
tool_call_count: int | None
command_count: int | None
iteration_count: int | None
transcript_path: str | None
transcript_sha256: str | None
```

## Task 3.2: Parse Codex session JSONL opportunistically

**Files:**
- Create: `src/ces/execution/services/codex_metrics.py`
- Test: `tests/unit/test_execution/test_codex_metrics.py`

**Rules:**

- Never fail the build if metrics parsing fails.
- Prefer latest `total_token_usage` from event payloads.
- Count function/custom tool calls from `response_item` payloads.
- Redact or hash transcript path when shown in user-facing output if needed, but store local absolute path in evidence.

## Task 3.3: Attach metrics to build evidence/report

**Files:**
- Modify: `src/ces/cli/run_cmd.py`
- Modify: `src/ces/cli/_builder_report.py`
- Test: `tests/unit/test_cli/test_builder_report_cmd.py`

---

# PR 4 — Repo Skills MVP

## Acceptance Criteria

- `ces skills` command exists.
- Project-local skill directory is created under `.ces/skills/`.
- Skills have names, status, source references, hashes, and markdown content.
- Generated skills are deterministic enough to test.
- Skills can be listed, shown, activated, disabled, archived/removed, and diagnosed.

## Task 4.1: Add repo skill models

**Files:**
- Create: `src/ces/skills/models.py`
- Create: `src/ces/skills/store.py`
- Test: `tests/unit/test_skills/test_store.py`

**Directory layout:**

```text
.ces/skills/
  index.json
  active/
  drafts/
  archive/
```

**Model outline:**

```python
class RepoSkillStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"
    ARCHIVED = "archived"

class RepoSkill(CESBaseModel):
    name: str
    status: RepoSkillStatus
    path: str
    sha256: str
    sources: tuple[str, ...] = ()
    confidence: str = "medium"
    created_at: datetime
    updated_at: datetime
```

## Task 4.2: Add deterministic greenfield skill generator

**Files:**
- Create: `src/ces/skills/generator.py`
- Test: `tests/unit/test_skills/test_generator.py`

**MVP generated skills:**

- `product-context`
- `acceptance-and-quality`
- `testing-and-verification`
- `runtime-boundaries`

## Task 4.3: Add deterministic brownfield skill generator

**Files:**
- Modify: `src/ces/skills/generator.py`
- Test: `tests/unit/test_skills/test_generator.py`

**MVP generated skills:**

- `architecture-map`
- `coding-conventions`
- `testing-and-verification`
- `risk-and-boundaries`
- `change-playbooks`

## Task 4.4: Add `ces skills` CLI

**Files:**
- Create: `src/ces/cli/skills_cmd.py`
- Modify: `src/ces/cli/__init__.py`
- Test: `tests/unit/test_cli/test_skills_cmd.py`

**Command surface MVP:**

```bash
ces skills init
ces skills generate --greenfield --from docs/PRD.md
ces skills generate --brownfield --scan-code --from docs/PRD.md
ces skills list
ces skills show testing-and-verification
ces skills activate testing-and-verification
ces skills disable testing-and-verification
ces skills remove testing-and-verification --archive
ces skills doctor
```

---

# PR 5 — Build Integration for Repo Skills

## Acceptance Criteria

- `ces build` accepts `--use-skills auto|none|skill1,skill2`.
- Runtime prompt includes selected active skills.
- Evidence records selected skill names and SHA-256 hashes.
- Skills cannot silently override the user request, manifest constraints, or acceptance criteria.

## Task 5.1: Add skill selection service

**Files:**
- Create: `src/ces/skills/selection.py`
- Test: `tests/unit/test_skills/test_selection.py`

**Rules:**

- `none` => no skills.
- `auto` => active skills whose names match the project mode and core defaults.
- explicit list => only named active skills; fail clearly if missing/disabled.

## Task 5.2: Inject selected skills into runtime context

**Files:**
- Modify: `src/ces/cli/run_cmd.py`
- Modify likely runtime prompt assembly/helper file discovered during implementation.
- Test: `tests/unit/test_cli/test_run_cmd.py`

**Prompt ordering:**

1. user request
2. manifest constraints/acceptance criteria
3. repo skills
4. runtime instructions

Add explicit line:

```text
Repo skills are advisory context. If they conflict with the user request or manifest, follow the user request/manifest and report the conflict.
```

## Task 5.3: Record skill hashes in evidence

**Files:**
- Modify: `src/ces/cli/run_cmd.py`
- Modify: `src/ces/cli/_builder_report.py`
- Test: `tests/unit/test_cli/test_builder_report_cmd.py`

---

# PR 6 — Skills Improvement Loop

## Acceptance Criteria

- Operators can improve, refresh, diff, and prune repo skills without hand-editing internal indexes.
- Brownfield skills include source references and confidence labels.
- Disabled/archived skills are not injected into builds.

## Task 6.1: Add `ces skills improve`

**Files:**
- Modify: `src/ces/cli/skills_cmd.py`
- Modify: `src/ces/skills/store.py`
- Test: `tests/unit/test_cli/test_skills_cmd.py`

**Command:**

```bash
ces skills improve testing-and-verification "Use uv run pytest -q instead of pytest"
```

MVP: append an `## Operator Notes` section with timestamp and recompute hash.

## Task 6.2: Add `refresh`, `diff`, and `prune --dry-run`

**Files:**
- Modify: `src/ces/cli/skills_cmd.py`
- Modify: `src/ces/skills/generator.py`
- Test: `tests/unit/test_cli/test_skills_cmd.py`

---

# PR 7 — Comparative Benchmark Suite

## Acceptance Criteria

- CES can run or ingest controlled vs non-controlled workflow metrics.
- Benchmark report has side-by-side fields matching the ReleaseNoteSmith evaluation:
  - completion
  - time
  - tokens
  - tool calls/iterations
  - corrections
  - tests
  - docs
  - maintainability
  - bugs
  - friction
  - auditability
  - control
- Results separate actual measured findings from inferred/hypothetical expectations.

## Task 7.1: Add benchmark comparison model

**Files:**
- Create: `src/ces/benchmark/compare.py`
- Test: `tests/unit/test_benchmark/test_compare.py`

## Task 7.2: Add CLI command

**Files:**
- Modify: `src/ces/cli/benchmark_cmd.py`
- Test: `tests/unit/test_cli/test_benchmark_cmd.py`

**Command:**

```bash
ces benchmark compare --project-spec docs/benchmark/release-note-smith.md --out .ces/benchmarks/latest
```

## Task 7.3: Add docs and sample report

**Files:**
- Create: `docs/benchmarking.md`
- Modify: `README.md`
- Test: `tests/unit/test_docs/test_package_contract.py` or dedicated docs test.

---

## Implementation Guardrails

- Do not implement PR 4+ before PR 1 and PR 2 are green; repo skills amplify CES, but trust semantics are the credibility foundation.
- Keep generated skills compact. Target <1,500 words per skill and <8 active skills in auto mode.
- Every generated skill must include:
  - purpose
  - when to use
  - source references
  - concise instructions
  - known uncertainty / confidence
- Never store secrets in skill content.
- Skills are advisory context; they must not silently override user instructions, manifest constraints, or acceptance criteria.
- Evidence must include exact skill hashes so a reviewer can reproduce what context the runtime saw.
- Prefer deterministic generation first; add LLM-enhanced skill drafting only after the file model, CLI, and tests are stable.

## Recommended First Branch

```bash
git checkout -b fix/control-plane-status-semantics
```

Then implement only PR 1 from this plan.

## Final Done Definition

The whole program is done when:

- The ReleaseNoteSmith benchmark trust bug has a regression test and cannot recur.
- `ces build` distinguishes code completion, acceptance verification, governance state, and ready-to-ship state.
- Project verification profiles prevent unconfigured artifacts from creating misleading red states.
- Benchmark metrics are captured natively enough to compare CES and non-CES workflows.
- Repo-specific skills can be generated, reviewed, activated, improved, disabled, removed, and injected into builds with evidence hashes.
- Documentation clearly tells developers when CES is worth the friction and when a normal AI coding workflow is simpler.
