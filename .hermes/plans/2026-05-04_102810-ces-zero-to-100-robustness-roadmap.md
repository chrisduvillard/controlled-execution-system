# CES Zero-to-100 Robustness Roadmap Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task. Do not collapse phases; ship as small PRs with focused tests, local CI parity, and live dogfood validation after each PR.

**Goal:** Make CES robust and frictionless enough that a user can start a real project and reliably get from 0 to 100%, with clear self-diagnosis and recovery when GSD/runtime execution fails.

**Architecture:** Add a user-facing 0→100 delivery layer on top of existing CES build/review/status primitives, backed by structured completion contracts, independent product verification, explicit blocker diagnosis, and safe recovery automation. Keep governance/audit correctness, but optimize the operator experience around “what happened, can I trust the product, and what do I do next?”

**Tech Stack:** Python 3.12/3.13, Typer/Rich CLI, existing CES local store, builder flow/report/status/review commands, pytest/ruff/mypy/uv CI.

---

## Current Context

The recent dogfood waves exposed a clear pattern:

- Traceforge / RunLens: runtime and recovery diagnostics needed hardening.
- SpecTrail: status/review/project-root consistency, workflow reconciliation, actor redaction, and blocker details were missing.
- PromptVault: CES could build a working product but rejected completion evidence too generically; manual recovery worked but needed stronger evidence preservation.

PRs #6 and #7 fixed the immediate findings. The next step is not more one-off patches; it is a product-level robustness layer that treats CES as a 0→100 delivery harness.

## Non-Negotiable Product Principle

If GSD/runtime execution fails, CES must not leave the user with a red state and vague explanation. Every failure must end with:

1. **Diagnosis** — exact category and source of failure.
2. **Reality check** — whether the product appears complete based on independent verification.
3. **Next command** — exact retry/recover/manual command.
4. **Audit preservation** — original failure/evidence remains visible after recovery.

## Target UX

```bash
ces build --gsd "Build a CLI app for managing reusable prompts"
```

Expected end states:

```text
✅ Completed and verified
Next: cd <project> && run generated app
```

or:

```text
⚠️ Product appears complete, but runtime evidence is incomplete
Blocked because: missing evidence for acceptance criterion 3
Verified independently: pytest passed, CLI smoke passed
Next: ces recover --auto-evidence --dry-run
```

or:

```text
❌ Runtime failed before producing changes
Cause: codex auth probe failed / sandbox failed / no file changes
Next: ces doctor --deep --runtime codex
```

---

# Roadmap Overview

Ship in four PRs:

1. **PR A — 0→100 UX and Blocker Explanation**
   - Add `ces build --gsd` mode/alias.
   - Add `ces why` / `ces explain blocked`.
   - Improve final build summaries and next-command UX.

2. **PR B — Completion Contract and Independent Verification**
   - Add `.ces/completion-contract.json` generation.
   - Add product-type detection and verification command inference.
   - Store structured acceptance criteria and verification results.

3. **PR C — Self-Recovery**
   - Add `ces recover --dry-run` and `ces recover --auto-evidence`.
   - Auto-generate recovery evidence from passing independent checks.
   - Preserve original runtime failure and safety metadata.

4. **PR D — Greenfield Benchmark Harness and Friction Metrics**
   - Add deterministic benchmark projects/scenarios.
   - Add 0→100 success/intervention/friction score reporting.
   - Add CI tests for failure categories and recovery flows.

Each PR must include:

- Unit tests for each new behavior.
- A live spot check against `/home/chris/.Hermes/workspace/promptvault-ces-dogfood` or a fresh throwaway target.
- Local CI parity using `.github/workflows/ci.yml` commands.
- PR body mapping implementation to user-facing failure modes.

---

# PR A — 0→100 UX and Blocker Explanation

## Goal

Make CES answer the user’s panic question: “What happened, can I trust the product, and what do I do now?”

## User-Facing Features

### Feature A1: `ces build --gsd`

`--gsd` is a frictionless greenfield mode. It should be additive; do not break current `ces build` flags.

Example:

```bash
ces build --gsd "Build a CLI app for managing reusable prompts"
```

Behavior:

- Sets greenfield defaults.
- Enables final “0→100 summary” output.
- Runs preflight checks before runtime execution where safe.
- Prints exact next command at every terminal state.
- Preserves standard `ces build` behavior when `--gsd` is absent.

### Feature A2: `ces why`

Add a command that explains the current blocker or success state from the current project root.

Example:

```bash
ces why
ces why --json
ces why --project-root /path/to/project
```

Output should include:

- Current builder stage.
- Workflow state.
- Review state.
- Evidence quality state.
- Blocker category.
- Blocker source.
- Human-readable reason.
- Exact next command.
- Whether product appears independently complete, if known.

### Feature A3: Rejected builder-run UX

All terminal rejected/blocked summaries should include:

```text
Blocked because:
- <specific reason>

Suggested next command:
  ces why
```

If the block is evidence-related:

```text
Suggested next command:
  ces recover --dry-run
```

## Likely Files

- Modify: `src/ces/cli/run_cmd.py`
- Modify: `src/ces/cli/_builder_report.py`
- Modify: `src/ces/cli/status_cmd.py`
- Modify: `src/ces/cli/__init__.py`
- Create: `src/ces/cli/why_cmd.py`
- Create: `src/ces/cli/_blocker_diagnostics.py`
- Test: `tests/unit/test_cli/test_run_cmd.py`
- Test: `tests/unit/test_cli/test_builder_report_cmd.py`
- Create: `tests/unit/test_cli/test_why_cmd.py`

## Implementation Tasks

### Task A1: Add blocker diagnostic model

**Objective:** Create a reusable internal representation of CES blocker explanations.

**Files:**

- Create: `src/ces/cli/_blocker_diagnostics.py`
- Create: `tests/unit/test_cli/test_blocker_diagnostics.py`

**Model sketch:**

```python
from dataclasses import dataclass, field
from typing import Literal

BlockerCategory = Literal[
    "runtime_unavailable",
    "runtime_auth_failed",
    "sandbox_failed",
    "runtime_no_changes",
    "runtime_no_completion_claim",
    "evidence_malformed",
    "evidence_missing_artifacts",
    "product_incomplete",
    "parser_failed",
    "state_reconciliation_needed",
    "none",
]

@dataclass(frozen=True)
class BlockerDiagnostic:
    category: BlockerCategory
    reason: str
    source: str
    next_command: str
    product_may_be_complete: bool = False
    evidence: tuple[str, ...] = field(default_factory=tuple)
```

**Test cases:**

- Evidence quality `missing_artifacts` maps to `evidence_missing_artifacts` and `ces recover --dry-run`.
- Runtime auth failure maps to `runtime_auth_failed` and `ces doctor --deep --runtime <runtime>`.
- Approved/completed maps to category `none`.

### Task A2: Add `ces why` command

**Objective:** Surface blocker diagnostics as CLI output.

**Files:**

- Create: `src/ces/cli/why_cmd.py`
- Modify: `src/ces/cli/__init__.py`
- Test: `tests/unit/test_cli/test_why_cmd.py`

**CLI behavior:**

```bash
ces why
ces why --json
ces why --project-root /path/to/project
```

**Implementation outline:**

- Resolve project root like `status_cmd.py`.
- Use existing local store snapshot/report helpers.
- Build `BuilderRunReport` via `_builder_report.py`.
- Convert to `BlockerDiagnostic`.
- Render concise Rich panel or JSON.

**Tests:**

- `test_why_reports_missing_evidence_next_recover_command`
- `test_why_reports_completed_project_no_blocker`
- `test_why_accepts_project_root`
- `test_why_json_contains_category_reason_next_command`

### Task A3: Add `--gsd` to `ces build`

**Objective:** Provide a frictionless 0→100 entrypoint while preserving current behavior.

**Files:**

- Modify: `src/ces/cli/run_cmd.py`
- Test: `tests/unit/test_cli/test_run_cmd.py`

**Behavior:**

- `--gsd TEXT` should be accepted as a convenience alias for greenfield build request.
- If both positional request and `--gsd` are provided, fail with a clear message.
- `--gsd` should enable an explicit final summary mode.
- Keep current options available for advanced users.

**Tests:**

- `test_build_gsd_uses_request_text_and_greenfield_defaults`
- `test_build_gsd_conflicts_with_positional_request`
- `test_build_gsd_final_summary_includes_next_command`

### Task A4: Add final next-command summary

**Objective:** Make every build terminal state actionable.

**Files:**

- Modify: `src/ces/cli/run_cmd.py`
- Modify: `src/ces/cli/_builder_report.py`
- Test: `tests/unit/test_cli/test_run_cmd.py`

**Rules:**

- Completed/approved: suggest `ces report builder`.
- Blocked/evidence issue: suggest `ces why` and `ces recover --dry-run`.
- Runtime unavailable/auth issue: suggest `ces doctor --deep --runtime <runtime>`.
- Rejected review: suggest `ces review --full` or `ces recover --dry-run` depending on evidence.

### Task A5: Live validation

**Objective:** Prove UX works on real dogfood state.

**Commands:**

```bash
/home/chris/.Hermes/workspace/controlled-execution-system/.venv/bin/ces why --project-root /home/chris/.Hermes/workspace/promptvault-ces-dogfood
/home/chris/.Hermes/workspace/controlled-execution-system/.venv/bin/ces why --project-root /home/chris/.Hermes/workspace/promptvault-ces-dogfood --json
/home/chris/.Hermes/workspace/controlled-execution-system/.venv/bin/ces build --help | grep -- '--gsd'
```

**Expected:** Commands exit 0 and produce actionable output.

---

# PR B — Completion Contract and Independent Verification

## Goal

Make CES verify project reality independently, instead of relying mainly on runtime completion claims.

## User-Facing Features

- `.ces/completion-contract.json` generated for every greenfield build.
- `ces verify` command or internal verifier pass that runs inferred product checks.
- Structured acceptance criteria with stable IDs.
- Product type and verification commands visible in reports/status.

## Completion Contract Shape

```json
{
  "version": 1,
  "project_type": "python-cli",
  "request": "Build PromptVault...",
  "acceptance_criteria": [
    {"id": "AC-001", "text": "Provides add, list, render, export, and delete commands"}
  ],
  "inferred_commands": [
    {"id": "VC-001", "kind": "test", "command": "python -m pytest -q", "required": true},
    {"id": "VC-002", "kind": "compile", "command": "python -m compileall src tests", "required": true},
    {"id": "VC-003", "kind": "smoke", "command": "python -m promptvault --help", "required": true}
  ],
  "runtime": {
    "name": "codex",
    "sandbox": "danger-full-access"
  }
}
```

## Likely Files

- Create: `src/ces/verification/completion_contract.py`
- Create: `src/ces/verification/project_detector.py`
- Create: `src/ces/verification/command_inference.py`
- Create: `src/ces/verification/runner.py`
- Modify: `src/ces/cli/run_cmd.py`
- Create or modify: `src/ces/cli/verify_cmd.py`
- Modify: `src/ces/cli/__init__.py`
- Test: `tests/unit/test_verification/test_completion_contract.py`
- Test: `tests/unit/test_verification/test_project_detector.py`
- Test: `tests/unit/test_verification/test_command_inference.py`
- Test: `tests/unit/test_cli/test_verify_cmd.py`

## Implementation Tasks

### Task B1: Add completion contract model

**Objective:** Persist build expectations before runtime execution.

**Files:**

- Create: `src/ces/verification/completion_contract.py`
- Create: `tests/unit/test_verification/test_completion_contract.py`

**Model requirements:**

- Stable `version`.
- Request text.
- Project type.
- Acceptance criteria as objects with IDs.
- Verification commands as objects with IDs/kind/required/cwd.
- JSON roundtrip.

### Task B2: Generate contract during greenfield build

**Objective:** Ensure every CES greenfield run has an explicit contract.

**Files:**

- Modify: `src/ces/cli/run_cmd.py`
- Modify or create local-store helpers if needed.
- Test: `tests/unit/test_cli/test_run_cmd.py`

**Behavior:**

- Generate `.ces/completion-contract.json` before runtime execution.
- Include normalized acceptance criteria from `_builder_flow.py`.
- Include runtime name/sandbox metadata.
- If `.ces` does not exist yet, create it via existing initialization path.

### Task B3: Project detector

**Objective:** Infer project type from files.

**Files:**

- Create: `src/ces/verification/project_detector.py`
- Create: `tests/unit/test_verification/test_project_detector.py`

**Detection rules:**

- Python CLI: `pyproject.toml` with `[project.scripts]` or package under `src/`.
- Python package: `pyproject.toml` without scripts.
- Node CLI/app: `package.json`.
- Vite/React: `package.json` with vite/react deps/scripts.
- Unknown: fallback generic.

### Task B4: Command inference

**Objective:** Infer verification commands from project type and files.

**Files:**

- Create: `src/ces/verification/command_inference.py`
- Create: `tests/unit/test_verification/test_command_inference.py`

**Python inference examples:**

- If `tests/` exists: `python -m pytest -q`.
- If `src/` exists: `python -m compileall src tests`.
- If `[project.scripts]` exists: `<script> --help` or `python -m <module> --help`.
- If `uv.lock` exists: prefer `uv run ...`; otherwise local Python.

**Node inference examples:**

- If `package.json` has `test`: `npm test`.
- If `lint`: `npm run lint`.
- If `build`: `npm run build`.

### Task B5: Add verification runner

**Objective:** Execute inferred commands safely and capture evidence.

**Files:**

- Create: `src/ces/verification/runner.py`
- Create: `tests/unit/test_verification/test_runner.py`

**Requirements:**

- Timeout per command.
- stdout/stderr capture.
- exit code capture.
- no shell injection; use `shlex.split` or explicit arrays.
- JSON-serializable result.

### Task B6: Add `ces verify`

**Objective:** Let users run independent product verification directly.

**Files:**

- Create: `src/ces/cli/verify_cmd.py`
- Modify: `src/ces/cli/__init__.py`
- Test: `tests/unit/test_cli/test_verify_cmd.py`

**CLI:**

```bash
ces verify
ces verify --project-root /path/to/project
ces verify --json
ces verify --contract .ces/completion-contract.json
```

**Output:**

- Commands run.
- Pass/fail per command.
- Acceptance criteria coverage if known.
- Suggested next command.

### Task B7: Report integration

**Objective:** Make status/report include contract and independent verification summary.

**Files:**

- Modify: `src/ces/cli/_builder_report.py`
- Modify: `src/ces/cli/status_cmd.py`
- Test: `tests/unit/test_cli/test_builder_report_cmd.py`
- Test: `tests/unit/test_cli/test_status_cmd.py`

---

# PR C — Self-Recovery

## Goal

When CES is blocked but the product appears complete, CES should safely generate recovery evidence and reconcile state with minimal user work.

## User-Facing Features

```bash
ces recover --dry-run
ces recover --auto-evidence
ces recover --approve-if-tests-pass
ces recover --project-root /path/to/project
```

## Recovery Philosophy

Recovery must be safe by default:

- `--dry-run` shows what would happen.
- `--auto-evidence` writes evidence but does not approve unless `--yes` or `--approve-if-tests-pass` is supplied.
- Preserve original runtime failure/evidence metadata.
- Do not hide governance failures; supersede them with explicit manual/auto recovery evidence.

## Likely Files

- Create: `src/ces/cli/recover_cmd.py`
- Create: `src/ces/recovery/recovery_planner.py`
- Create: `src/ces/recovery/evidence_writer.py`
- Modify: `src/ces/cli/complete_cmd.py`
- Modify: `src/ces/cli/_builder_report.py`
- Modify: `src/ces/cli/__init__.py`
- Test: `tests/unit/test_cli/test_recover_cmd.py`
- Test: `tests/unit/test_recovery/test_recovery_planner.py`
- Test: `tests/unit/test_recovery/test_evidence_writer.py`

## Implementation Tasks

### Task C1: Recovery planner

**Objective:** Decide if a blocked build is recoverable.

**Inputs:**

- Builder run report.
- Completion contract.
- Verification results.
- Evidence quality state.

**Outputs:**

- Recoverable yes/no.
- Reason.
- Verification commands to run.
- Evidence file path to write.
- Suggested complete command.

### Task C2: Auto evidence writer

**Objective:** Generate human-readable evidence markdown from verification results.

**Evidence format:**

```markdown
# CES Auto-Recovery Evidence

Generated: <timestamp>
Project: <path>
Original blocker: <category/reason>

## Verification Commands

| Command | Exit | Result |
| --- | ---: | --- |
| `python -m pytest -q` | 0 | PASS |

## Acceptance Criteria Mapping

- AC-001: satisfied by CLI smoke commands.
- AC-002: satisfied by pytest output.

## Governance Note

This evidence supersedes runtime evidence packet <id> but does not erase the original failure.
```

### Task C3: Add `ces recover --dry-run`

**Objective:** Show exact recovery plan without writing or approving.

**Tests:**

- Blocked evidence failure + verification pass → recoverable.
- Runtime auth failure → not recoverable; suggest doctor.
- Product verification fail → not recoverable; show failing command.

### Task C4: Add `ces recover --auto-evidence`

**Objective:** Write `.ces/manual-evidence/auto-recovery-<timestamp>.md` from verification results.

**Tests:**

- Evidence file written.
- File path printed.
- Suggested `ces complete --evidence <path>` printed.
- Existing runtime evidence preserved.

### Task C5: Add `ces recover --approve-if-tests-pass --yes`

**Objective:** Optionally complete/reconcile state automatically after verification passes.

**Safety:**

- Require `--yes` or interactive confirmation.
- Only complete if all required verification commands pass.
- Preserve superseded evidence.

### Task C6: Live validation

Use a fresh throwaway project with intentionally incomplete runtime evidence, or a copied PromptVault `.ces` state, to verify:

```bash
ces recover --dry-run --project-root <target>
ces recover --auto-evidence --project-root <target>
ces complete --evidence <generated> --yes --project-root <target>
ces report builder --project-root <target> --json
```

---

# PR D — Greenfield Benchmark Harness and Friction Metrics

## Goal

Continuously measure whether CES can go 0→100 on real project archetypes, and quantify friction.

## User-Facing Features

```bash
ces dogfood benchmark --scenario python-cli
ces dogfood benchmark --all
ces report friction
```

Or, if this should remain internal initially:

```bash
python -m tests.benchmarks.greenfield_runner --scenario python-cli
```

## Benchmark Scenarios

Add deterministic scenarios:

1. `python-cli-promptvault-lite`
2. `python-package-library`
3. `node-ts-cli`
4. `fastapi-service`
5. `vite-react-app`
6. `fullstack-tiny-app`
7. `brownfield-add-feature`
8. `runtime-no-completion-claim`
9. `runtime-evidence-malformed`
10. `ambiguous-comma-rich-criteria`

## Friction Metrics

Capture per run:

- Did CES reach approved/completed?
- Number of user interventions.
- Number of commands required.
- Number of retries/recoveries.
- Runtime errors.
- Evidence parser errors.
- Independent verification result.
- Time to terminal state.
- Final friction score 0–10.

Example formula:

```text
score = min(10,
  2 * manual_interventions +
  2 * runtime_failures +
  2 * evidence_failures +
  1 * ambiguous_next_steps +
  1 * recovery_required
)
```

## Likely Files

- Create: `src/ces/dogfood/benchmarks.py`
- Create: `src/ces/dogfood/scenarios.py`
- Modify: `src/ces/cli/dogfood_cmd.py`
- Create: `src/ces/reporting/friction.py`
- Test: `tests/unit/test_dogfood/test_benchmarks.py`
- Test: `tests/unit/test_reporting/test_friction.py`
- Possibly create: `tests/fixtures/greenfield_scenarios/`

## Implementation Tasks

### Task D1: Add benchmark scenario model

**Objective:** Define deterministic scenario specs.

Fields:

- name
- request
- expected project type
- acceptance criteria
- required verification commands
- simulated runtime behavior if using fake runtime

### Task D2: Add fake runtime adapter for benchmark CI

**Objective:** Avoid calling real Codex/Claude in CI while testing CES 0→100 logic.

**Requirements:**

- Simulates success.
- Simulates no completion claim.
- Simulates malformed evidence.
- Simulates product complete but evidence incomplete.

Likely files:

- Modify: `src/ces/execution/runtimes/adapters.py`
- Modify: `src/ces/execution/runtimes/registry.py`
- Test: `tests/unit/test_execution/test_runtime_adapters.py`

### Task D3: Add benchmark runner

**Objective:** Execute scenario in temp workspace and collect metrics.

**Tests:**

- Successful fake Python CLI scenario reaches completed.
- Malformed evidence scenario becomes recoverable.
- Friction score increases with intervention/failure count.

### Task D4: Add friction report

**Objective:** Make friction measurable and visible.

CLI candidates:

```bash
ces report friction
ces status --friction
ces dogfood benchmark --json
```

Start with JSON and concise text; avoid overbuilding UI.

### Task D5: Add benchmark CI job or nightly workflow

**Objective:** Run benchmark suite regularly without blocking normal PR velocity initially.

Suggested path:

- Add unit-level fake runtime benchmark tests to normal CI.
- Add nightly GitHub Actions workflow for heavier benchmarks.

---

# Cross-Cutting Design Requirements

## 1. Preserve `--project-root` everywhere

Any new command must support:

```bash
--project-root PATH
```

Commands:

- `ces why`
- `ces verify`
- `ces recover`
- benchmark/report commands where applicable

## 2. JSON parity

Every new user-facing command should support `--json` for automation.

## 3. Never erase failure context

Recovery must not overwrite evidence without embedding or linking the superseded evidence packet.

## 4. No external side effects without explicit opt-in

- `ces verify`: local commands only.
- `ces recover --dry-run`: read-only.
- `ces recover --auto-evidence`: writes under `.ces/manual-evidence/` only.
- `ces recover --approve-if-tests-pass`: requires `--yes` or confirmation.

## 5. Keep CLI output boring and actionable

Prefer:

```text
Blocked because: <reason>
Next: ces recover --dry-run
```

over large verbose tables by default. Put details behind `--verbose`, `--full`, or `--json`.

---

# Verification Strategy for Every PR

## Required local commands

Read `.github/workflows/ci.yml` and run the corresponding lanes.

```bash
uv sync --frozen --group ci
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/ces/ --ignore-missing-imports
uv export --frozen --group ci --format requirements-txt --no-emit-project --no-hashes --output-file /tmp/ces-ci-requirements.txt
uv run pip-audit --strict -r /tmp/ces-ci-requirements.txt
```

For test/build lane, avoid local Python 3.14 false failures from deprecation-as-error if still present. Use supported Python 3.13 and keep CI venv outside the repo:

```bash
export UV_PROJECT_ENVIRONMENT=/tmp/ces-venv-ci313
uv sync --frozen --group ci --python 3.13
uv run --python 3.13 pytest tests/ -m "not integration" --cov=ces --cov-fail-under=90 --cov-report=term-missing -q -W error
uv build
uvx twine check dist/*
```

## Required live dogfood spot checks

Use at least one real target after each PR:

```bash
CES=/home/chris/.Hermes/workspace/controlled-execution-system/.venv/bin/ces
PV=/home/chris/.Hermes/workspace/promptvault-ces-dogfood

$CES status --project-root "$PV" --json
$CES report builder --project-root "$PV" --json
```

PR-specific checks:

- PR A: `$CES why --project-root "$PV"`
- PR B: `$CES verify --project-root "$PV" --json`
- PR C: `$CES recover --dry-run --project-root <blocked-copy>`
- PR D: `$CES dogfood benchmark --scenario python-cli --json`

## Required PR body sections

- Summary
- User-facing UX impact
- Finding/failure-mode coverage
- Verification commands and exact results
- Live dogfood evidence
- Known limitations / follow-up

---

# Risks and Tradeoffs

## Risk: Over-automation may approve incomplete work

Mitigation:

- `recover --approve-if-tests-pass` requires all required commands to pass.
- Keep default recovery as dry-run.
- Preserve superseded runtime failure metadata.
- Make auto-generated evidence explicit.

## Risk: Command inference becomes too magical

Mitigation:

- Store inferred commands in the completion contract.
- Show them before running in verbose/dry-run modes.
- Allow overrides later, but do not block initial implementation on full configurability.

## Risk: Benchmark harness becomes large and slow

Mitigation:

- Start with fake runtime and small fixtures.
- Put heavy real-runtime dogfood in manual/nightly workflow.
- Track friction score even for fake scenarios.

## Risk: `--gsd` duplicates `ces build`

Mitigation:

- Implement `--gsd` as a thin UX mode over the existing builder flow.
- Keep core build logic centralized.

---

# Recommended Execution Order

1. Create branch `improve/zero-to-100-ux` from fresh `master`.
2. Implement PR A fully and merge.
3. Dogfood PR A on PromptVault and one fresh tiny project.
4. Create branch `improve/completion-contract-verification`.
5. Implement PR B and merge.
6. Dogfood with fresh Python CLI and Node/TS CLI if local tooling allows.
7. Create branch `improve/self-recovery`.
8. Implement PR C and merge.
9. Create a deliberately blocked scenario and verify `ces recover` closes it.
10. Create branch `improve/greenfield-benchmarks`.
11. Implement PR D and merge.
12. Start tracking 0→100 success rate across future dogfood waves.

---

# Definition of Done for the Full Roadmap

CES is meaningfully more robust/frictionless when all are true:

- A new user can run one command, `ces build --gsd "..."`, and receive a clear terminal state.
- Every blocked/rejected state has `ces why` output with an exact next command.
- CES independently verifies product reality for common Python and Node projects.
- Recovery from “product works but evidence failed” can be dry-run, evidence-generated, and approved safely.
- Original runtime failure/evidence metadata remains visible after recovery.
- A benchmark suite reports 0→100 success, intervention count, and friction score.
- CI covers success, runtime failure, malformed evidence, missing evidence, and recovery paths.
- Live dogfood can build at least PromptVault-class projects with zero or one explicit user intervention.

---

# Suggested First PR Scope

Start with PR A only:

```text
Title: improve: add CES 0-to-100 blocker diagnosis UX
```

Deliver:

- `ces why`
- `ces build --gsd`
- blocker diagnostic model
- final next-command summaries
- tests + PromptVault spot check

This gives the fastest user-visible improvement without prematurely building the full verification/recovery engine.
