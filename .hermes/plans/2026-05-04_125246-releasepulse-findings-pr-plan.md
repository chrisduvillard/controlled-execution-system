# ReleasePulse CES Dogfood Findings — Multi-PR Implementation Plan

> **For Hermes:** Use `test-driven-development` and `github-pr-workflow`. Implement sequential, non-stacked PRs from fresh `master`; after each merge, sync `master`, clean the branch, then start the next PR.

**Goal:** Fix the concrete CES frictions found in the ReleasePulse 0→100 + brownfield dogfood wave (`RP-CES-001` through `RP-CES-007`) without hiding evidence, weakening governance, or bundling unrelated changes.

**Architecture:** Keep product-completion verification, builder evidence review, recovery evidence, and brownfield governance as separate concepts. First clean operator-facing command/status semantics; then make independently verified completion authoritative where safe; then fix brownfield manifest/claim identity; finally clarify brownfield counts.

**Tech Stack:** Python 3.13-compatible `uv` project; Typer CLI; local SQLite store; existing CES builder/recovery/brownfield services; pytest + Ruff + mypy + pip-audit + build/twine checks.

---

## Findings-to-PR Coverage

| Finding | Severity | Planned PR | Fix Summary |
|---|---:|---|---|
| `RP-CES-001` | Low | PR E | Add `--project-root` to `ces doctor`; resolve `.ces/`, dependency freshness, security checks, and runtime auth probe cwd against explicit target root. |
| `RP-CES-002` | Medium | PR F | Make passed completion-contract verification authoritative for completion when runtime succeeded; demote legacy artifact warnings to non-blocking diagnostics. |
| `RP-CES-003` | Medium | PR F | Support expected non-zero verification/acceptance checks so negative-path criteria are not treated as failed evidence. |
| `RP-CES-004` | Low | PR E | Split active vs superseded verification findings in builder status/report JSON after recovery; do not show stale pre-recovery blockers as active failures. |
| `RP-CES-005` | High | PR G | Infer/populate brownfield manifest scope from requested source-of-truth, critical flows, and runtime-edited files before evidence validation. |
| `RP-CES-006` | Medium | PR G | Separate observed legacy IDs (`OLB-*`) from active manifest IDs; prevent or repair completion claims that use OLB IDs as `task_id`. |
| `RP-CES-007` | Low | PR H | Audit and clarify brownfield reviewed count semantics; expose entry-level counts distinctly from lower-level item counts. |

---

# PR E — Command-root Symmetry and Recovery Status Clarity

**Branch:** `fix/releasepulse-command-root-recovery-status`

**Goal:** Remove operator confusion from `ces doctor --project-root` and from stale verification failures after `ces recover --auto-evidence --auto-complete`.

**Findings fixed:** `RP-CES-001`, `RP-CES-004`.

**Key design decisions:**
- `ces doctor --project-root PATH` should behave like running `ces doctor` from `PATH`, without requiring `chdir`.
- Runtime auth probe should use the resolved target root as `cwd`, not the orchestrator cwd.
- Security and dependency checks should inspect the target project’s `.ces/` and project files.
- Recovered evidence already stores old evidence under `superseded_evidence`; status/report should represent that as historical, not active.
- Keep backward-compatible `verification_findings` as active findings only. Add `superseded_verification_findings` and optionally `has_superseded_verification_findings` for machine consumers.

## Files

- Modify: `src/ces/cli/doctor_cmd.py`
- Modify: `src/ces/cli/_builder_report.py`
- Modify: `tests/unit/test_cli/test_doctor_cmd.py`
- Modify: `tests/unit/test_cli/test_builder_report_cmd.py`
- Modify: `tests/unit/test_cli/test_recover_cmd.py` or `tests/unit/test_cli/test_status_cmd.py` if an end-to-end CLI assertion is simpler.
- Plan/docs: `.hermes/plans/2026-05-04_125246-releasepulse-findings-pr-plan.md`

## Tasks

### Task E1: Add failing `ces doctor --project-root` JSON regression

**Objective:** Reproduce `RP-CES-001` in the test suite.

**Steps:**
1. Add a test in `tests/unit/test_cli/test_doctor_cmd.py` that:
   - Creates `target = tmp_path / "target"`.
   - Creates `target/.ces/config.yaml`.
   - Creates `target/pyproject.toml` and a fresh `target/uv.lock`.
   - Leaves cwd at `tmp_path` or another orchestrator directory.
   - Stubs `shutil.which` to return `/usr/bin/codex` for `codex`.
   - Invokes `runner.invoke(app, ["doctor", "--project-root", str(target), "--json"] )`.
   - Asserts exit code `0`.
   - Asserts `payload["project_dir"]["path"] == str(target / ".ces")`.
2. Run only that test and confirm it fails with `No such option: --project-root`.

### Task E2: Implement `--project-root` in `doctor_cmd.py`

**Objective:** Resolve all doctor project-specific checks against explicit root.

**Steps:**
1. Change `_check_project_dir()` to accept `project_root: Path | None`.
2. If `project_root` is supplied, call `find_project_root(project_root)` so callers can pass either the project root or a descendant.
3. Return `(exists, resolved_root / ".ces")`; if discovery fails, return `(False, project_root.resolve() / ".ces")` for actionable output.
4. Add `project_root: Path | None = typer.Option(None, "--project-root", help=...)` to `run_doctor`.
5. Compute `resolved_project_root = find_project_root(project_root) if project_root is not None else find_project_root()` when available; tolerate missing `.ces/` for normal doctor output.
6. Pass `resolved_project_root or Path.cwd()` into `_runtime_auth_status` / `_probe_runtime_auth` instead of hardcoded `Path.cwd()`.
7. Pass `project_path.parent` into dependency freshness.
8. Include `project_root` in JSON payload for machine consumers.
9. Run targeted doctor tests.

### Task E3: Add failing regression for superseded verification findings

**Objective:** Reproduce `RP-CES-004` as a pure builder-report unit test.

**Steps:**
1. In `tests/unit/test_cli/test_builder_report_cmd.py`, create a snapshot where:
   - latest evidence is recovery evidence with `content.independent_verification.passed == True`.
   - latest evidence contains `content.superseded_evidence.content.verification_result.passed == False` with findings.
   - approval decision is approved and session stage is completed.
2. Assert `build_builder_run_report(snapshot).verification_findings == ()`.
3. Assert `superseded_verification_findings` contains the old finding.
4. Run the new test and confirm it fails because stale findings currently appear as active findings and there is no `superseded_verification_findings` field.

### Task E4: Implement active vs superseded findings

**Objective:** Preserve recovery history without reporting stale blockers as active failures.

**Steps:**
1. Add `superseded_verification_findings: tuple[str, ...]` to `BuilderRunReport`.
2. Refactor `_verification_findings()` so it reads only the current evidence’s `content.verification_result`.
3. Add `_superseded_verification_findings()` to read `content.superseded_evidence.content.verification_result` only.
4. Populate both fields in `build_builder_run_report()`.
5. Change `manual_completion_supersedes_rejected_auto_review` to use `superseded_verification_findings`, not active findings.
6. Update `summarize_builder_run()` and `render_builder_run_report_markdown()`:
   - Active findings: `Verification findings`.
   - Historical findings: `Superseded verification findings`.
7. Ensure serialized JSON includes both fields through `asdict()`.
8. Run targeted builder-report/status/recover tests.

### Task E5: Live smoke for PR E

**Objective:** Prove the dogfood regressions are fixed in a real temp project.

**Steps:**
1. Create `/tmp/ces-pr-e-doctor-root-smoke`.
2. Run `uv run ces init --project-root /tmp/ces-pr-e-doctor-root-smoke --yes`.
3. From the CES repo cwd, run `uv run ces doctor --project-root /tmp/ces-pr-e-doctor-root-smoke --runtime-safety --json`.
4. Assert JSON parses and `project_dir.path` points to `/tmp/ces-pr-e-doctor-root-smoke/.ces`.
5. Run targeted tests and CI parity subset.

**Verification commands for PR E:**

```bash
uv run pytest tests/unit/test_cli/test_doctor_cmd.py tests/unit/test_cli/test_builder_report_cmd.py tests/unit/test_cli/test_recover_cmd.py tests/unit/test_cli/test_status_cmd.py -q
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src
uv run pytest tests/unit -q
UV_PROJECT_ENVIRONMENT=/tmp/ces-venv-ci313 uv run --python 3.13 pytest tests/ -m "not integration" --cov=ces --cov-report=term-missing
```

**PR body must mention:** Fixes `RP-CES-001` and `RP-CES-004`; includes smoke command output for `ces doctor --project-root`.

---

# PR F — Completion Contract Authority and Expected-Failure Evidence

**Branch:** `fix/releasepulse-completion-contract-authority`

**Goal:** Prevent CES from marking a real completed product red when independent verification passed, and stop penalizing correct negative-path checks.

**Findings fixed:** `RP-CES-002`, `RP-CES-003`.

## Design

- Extend verification command model to support `expected_exit_code` or `expected_exit_codes` with default `0`.
- Update `VerificationCommand`, `run_verification_commands()`, JSON serialization, and contract writing/reading.
- Add parser/inference support for simple negative-path language: “nonzero”, “exit 1”, “fails with helpful message”.
- Builder review should treat `independent_verification.passed == true` as authoritative for product completion if runtime exit code is `0` and manifest/claim identity are sane.
- Legacy evidence-artifact failures can be retained as warnings/diagnostics but should not force `latest_outcome=rejected` if the contract passed.

## Files

- Modify: `src/ces/verification/completion_contract.py`
- Modify: `src/ces/verification/runner.py`
- Modify: `src/ces/verification/command_inference.py`
- Modify: `src/ces/verification/build_contract.py`
- Modify: `src/ces/cli/run_cmd.py`
- Modify: `src/ces/cli/_builder_report.py`
- Tests:
  - `tests/unit/test_verification/test_completion_contract.py`
  - `tests/unit/test_verification/test_runner.py`
  - `tests/unit/test_verification/test_command_inference.py`
  - `tests/unit/test_cli/test_run_cmd.py`
  - `tests/unit/test_cli/test_builder_report_cmd.py`

## Tasks

1. RED: Add runner test where `VerificationCommand(expected_exit_codes=(1,))` passes when command exits `1`.
2. GREEN: Add expected exit support to model/runner.
3. RED: Add contract serialization round-trip test preserving expected exit codes.
4. GREEN: Update contract model serialization and defaults.
5. RED: Add command inference tests for negative-path criteria.
6. GREEN: Infer expected non-zero commands conservatively only when criteria explicitly says nonzero/fails.
7. RED: Add builder run report/run command test for runtime success + independent verification pass + legacy artifact warnings => non-rejected actionable state.
8. GREEN: Adjust builder integration/report state to separate warnings from completion blockers.
9. Live smoke: reproduce a small CLI with one positive and one expected-failure check; verify `ces verify --json` passes.

**Verification commands:** targeted verification tests, builder CLI tests, full unit suite, ruff/mypy, live smoke.

---

# PR G — Brownfield Manifest Scope and OLB/Manifest Identity Separation

**Branch:** `fix/releasepulse-brownfield-scope-identity`

**Goal:** Fix high-impact brownfield false governance failures: empty manifest scope and completion claims using `OLB-*` IDs instead of active manifest IDs.

**Findings fixed:** `RP-CES-005`, `RP-CES-006`.

## Design

- Builder-created brownfield manifests must always have an explicit scope before evidence validation.
- Scope sources, in order:
  1. Explicit user-provided source-of-truth paths.
  2. Critical-flow referenced files when paths are parseable.
  3. Runtime-edited files from git diff / claim files before verifier runs.
  4. If still unknown, block before runtime or produce an actionable non-red status telling user to supply scope.
- Prompt/schema guidance should clearly state:
  - `task_id` must be manifest ID (`M-*`).
  - `OLB-*` IDs belong in `related_legacy_behavior_ids` or evidence metadata, not `task_id`.
- Add a repair guard: if claim task ID is `OLB-*` and exactly one active manifest exists, rewrite or reject with an auto-repair hint before final validation.

## Files

- Modify: `src/ces/cli/run_cmd.py`
- Modify: `src/ces/cli/_builder_flow.py`
- Modify: `src/ces/harness/services/completion_verifier.py`
- Modify: brownfield prompt/context builder files, located via search before implementation.
- Tests:
  - `tests/unit/test_cli/test_run_cmd.py`
  - `tests/unit/test_services/test_completion_verifier.py`
  - Brownfield-specific tests under `tests/unit/test_brownfield/` or existing CLI tests.

## Tasks

1. RED: Add test that brownfield build context with source-of-truth `README.md` produces manifest `affected_files` containing `README.md` plus runtime-edited source/tests when known.
2. GREEN: Populate scope before verification.
3. RED: Add test for empty brownfield scope producing pre-runtime actionable blocker, not post-runtime global rejection.
4. GREEN: Add early validation/hint.
5. RED: Add test that `Claim.task_id='OLB-*'` with active manifest `M-*` is diagnosed as OLB/manifest identity mix-up with repair hint.
6. GREEN: Add repair/hint logic and prompt/schema guidance.
7. Live smoke: brownfield toy repo with one registered behavior; improve one file; verify no `allowed=(), forbidden=()` and no OLB task mismatch.

**Verification commands:** completion verifier tests, run command tests, brownfield CLI tests, full unit, live smoke.

---

# PR H — Brownfield Status Count Semantics

**Branch:** `fix/releasepulse-brownfield-status-counts`

**Goal:** Make brownfield status counts trustworthy and explicit.

**Findings fixed:** `RP-CES-007`.

## Design

- Audit whether `brownfield_reviewed_count` currently counts observed behavior entries, lower-level scan records, accepted reviews, or checkpoint items.
- Preserve existing field if backward compatibility requires it, but add clearer machine fields:
  - `brownfield_entry_reviewed_count`
  - `brownfield_entry_remaining_count`
  - `brownfield_item_reviewed_count` if lower-level count still matters.
- Human status should say “1 behavior reviewed” when one OLB entry was reviewed.

## Files

- Modify: `src/ces/local_store/store.py` if persisted values are wrong at write time.
- Modify: `src/ces/cli/status_cmd.py`
- Modify: `src/ces/cli/_builder_report.py`
- Tests:
  - `tests/unit/test_cli/test_status_cmd.py`
  - `tests/unit/test_cli/test_status_metrics.py`
  - Brownfield register/review CLI tests.

## Tasks

1. RED: Reproduce ReleasePulse state: one visible OLB entry reviewed, status reports 13. Lock expected entry count to 1.
2. Trace source of inflated count.
3. GREEN: Fix count source or add explicit entry-level fields.
4. Update JSON and Rich output labels.
5. Live smoke with one scan-derived behavior.

**Verification commands:** status tests, brownfield tests, full unit, live smoke.

---

# Final ReleasePulse Re-Dogfood Gate

After PR E-H merge sequentially:

1. Create a fresh dogfood target, not reusing old `.ces/` state.
2. Greenfield build a small CLI project with positive and expected-negative checks.
3. Verify CES does not reject a passed completion contract.
4. Brownfield-register one behavior, improve the project, and verify:
   - manifest scope is non-empty,
   - completion claim task ID matches `M-*`,
   - status counts are entry-level and accurate,
   - recovery status has no active stale findings.
5. Save new markdown findings; only then consider a patch release.
