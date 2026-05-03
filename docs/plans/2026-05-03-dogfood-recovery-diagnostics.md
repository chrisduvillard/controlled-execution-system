# CES Dogfood Recovery & Diagnostics Implementation Plan

> **For Hermes:** This plan was generated from `CES_DOGFOOD_FINDINGS.md` after Traceforge dogfooding exposed onboarding, runtime readiness, diagnostics, recovery, and source-checkout targeting gaps.

**Goal:** Make CES easier to start, safer to diagnose, and recoverable after runtime failures or manual completion.

**Architecture:** Keep the fixes local-first and CLI-centered. Prefer explicit project-root targeting, redacted diagnostic artifacts under `.ces/`, clearer doctor/runtime language, and a small manual reconciliation command over large workflow rewrites.

**Tech Stack:** Python 3.12+, Typer CLI, Rich output, SQLite local store, pytest, Ruff.

---

## Finding-to-Fix Map

### F-001 — `ces init` guidance omits required `NAME`

**Fix:** Make `NAME` optional and derive a CES-safe project name from the target directory.

**Files:**
- Modify: `src/ces/cli/init_cmd.py`
- Test: `tests/unit/test_cli/test_init_cmd.py`

**Verification:**
- `ces init` succeeds with no positional name.
- Config `project_name` is derived via `derive_project_name()`.

### F-002 — Init success text says install/authenticate runtime after doctor

**Fix:** Make init messaging conditional on detected local runtimes.

**Files:**
- Modify: `src/ces/cli/init_cmd.py`
- Test: `tests/unit/test_cli/test_init_cmd.py`

**Verification:**
- When Codex/Claude is on PATH, output says detected runtime and does not tell the user to install one.
- When neither is on PATH, output still gives setup guidance.

### F-003 — Doctor conflates binary presence with auth/entitlement

**Fix:** Keep default doctor lightweight but downgrade runtime detail to `on PATH; auth not verified`, and expose structured `runtime_auth` metadata in JSON.

**Files:**
- Modify: `src/ces/cli/doctor_cmd.py`
- Test: `tests/unit/test_cli/test_doctor_cmd.py`

**Verification:**
- Human output no longer implies CLI auth is verified.
- JSON consumers can distinguish `installed` from `auth_checked`/`auth_ok`.

### F-004 — Runtime failures hide stderr/root cause

**Fix:** Add redacted runtime failure diagnostics.

**Files:**
- Create: `src/ces/cli/_runtime_diagnostics.py`
- Modify: `src/ces/cli/run_cmd.py`
- Test: `tests/unit/test_cli/test_run_cmd.py`

**Verification:**
- Failed builder runtime output shows redacted stderr in a `Runtime Failed` panel.
- A redacted artifact is written to `.ces/runtime-diagnostics/` with private permissions where possible.
- Builder session `last_error` includes the diagnostics path.

### F-005 — No manual reconciliation path after external completion

**Fix:** Add `ces complete` for operator-confirmed external/manual completion.

**Files:**
- Create: `src/ces/cli/complete_cmd.py`
- Modify: `src/ces/cli/__init__.py`
- Test: `tests/unit/test_cli/test_complete_cmd.py`

**Verification:**
- `ces complete --evidence <path> --rationale <text> --yes` attaches evidence, records approval, and marks the latest builder session completed.

### F-006 — Source-checkout invocation can target wrong project

**Fix:** Add explicit `--project-root` targeting to `ces init` and `ces build`, and thread explicit roots through the CLI service factory.

**Files:**
- Modify: `src/ces/cli/init_cmd.py`
- Modify: `src/ces/cli/run_cmd.py`
- Modify: `src/ces/cli/_factory.py`
- Test: `tests/unit/test_cli/test_init_cmd.py`

**Verification:**
- `ces init --project-root /target/repo` initializes `/target/repo`, not cwd.
- `ces build --project-root /target/repo` resolves services and runtime working directory from the requested root.

### F-007 — Codex workspace-write bubblewrap failure

**Fix status:** Already addressed on `master` by always invoking Codex with `--sandbox danger-full-access` and disclosing that boundary in runtime safety docs/tests. This plan preserves that decision and focuses on diagnostic/UX/recovery improvements around it.

---

## Implementation Tasks

1. Add failing CLI tests for optional init name, explicit project root, conditional init runtime text, doctor auth-state wording, runtime diagnostics, and manual completion.
2. Implement optional `ces init [NAME]` and `--project-root`.
3. Implement conditional runtime messaging in init.
4. Add doctor runtime-auth metadata and human wording that says auth is not verified unless actually probed.
5. Add redacted runtime diagnostics helper and wire it into builder runtime failures.
6. Add `ces complete` for manual recovery/reconciliation.
7. Thread explicit `project_root` into `get_settings()`/`get_services()` and `ces build`.
8. Run targeted tests, then CLI + execution suites, then full unit suite and Ruff.
9. Push branch and open PR for review.

---

## Non-goals for this PR

- Replacing the hardcoded Codex `danger-full-access` decision with a configurable sandbox.
- Running deep authenticated probes against live Claude/Codex during default `ces doctor`.
- Fully reconciling arbitrary historical manifest graph states; this PR adds the operator-confirmed completion path first.
