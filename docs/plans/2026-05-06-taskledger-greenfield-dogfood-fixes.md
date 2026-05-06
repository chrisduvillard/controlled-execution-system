# TaskLedger Greenfield Dogfood Fixes Implementation Plan

> **For Hermes:** Implement this in small, sequential PRs. Start with failing regression tests for each dogfood finding, then make the smallest production change that turns each test green. Do not bundle unrelated cleanup.

**Source dogfood report:** `/home/chris/.Hermes/workspace/ces-dogfood-taskledger-20260506T1709Z/CES_DOGFOOD_FINDINGS.md`  
**CES repo under test:** `/home/chris/.Hermes/workspace/controlled-execution-system`  
**Observed CES commit:** `46646294feed030a3e2635503781b5b74a301a27`  
**Dogfood scenario:** new user creates a greenfield TaskLedger Python CLI through `ces build` in an isolated target repo.  
**Verdict to fix:** CES generated a good project, but post-build governance/state reconciliation made the workflow untrustworthy.

---

## Goal

Make the greenfield builder workflow end in one coherent, trustworthy state:

1. A successful approved build with valid evidence must complete/merge cleanly, or report one concrete blocker with one actionable next command.
2. `ces status`, `ces why`, `ces explain`, `ces review`, `ces recover`, `ces approve`, `ces complete`, and `ces report builder` must agree on the same builder session state.
3. Recovery and manual reconciliation must preserve provenance, runtime-safety, and superseded evidence metadata.
4. Runtime readiness diagnostics must remain useful without leaking noisy/private provider output.
5. Source-checkout/new-project invocation must be documented clearly.

---

## Current failure summary

The TaskLedger dogfood run produced working code and passed independent verification, but CES ended with:

```text
Outcome: approved, but merge is blocked
Triage: red
Next: ces why
Merge blocked: evidence_exists
```

Then surfaces disagreed:

- `status`: `stage=blocked`, while `review_state=approved`, `latest_outcome=approved`, `workflow_state=approved`, `triage_color=green`.
- `why`: no active blocker; latest run approved.
- `explain`: blocked; waiting for another review pass.
- `review`: refused because manifest was already `approved`.
- `recover --auto-evidence --auto-complete`: verification passed but `completed=false`, `next_action=review_evidence`.
- `approve --project-root`: unsupported option.
- `approve --yes --json` from target cwd: `merge_allowed=false`, `merge_reason=evidence_exists, review_complete`.
- `complete --evidence ... --yes`: finally reconciled the session, but manual completion lost/bypassed some provenance fields.

---

## Finding-to-fix coverage

| Finding | Severity | Root theme | Fix track |
|---|---:|---|---|
| F-001 Source-checkout invocation needs clearer docs | Low | Docs/onboarding | Track 6 |
| F-002 Runtime auth probe output noisy/sensitive | Medium | Diagnostics/secrets | Track 5 |
| F-003 Approved build reports `merge blocked: evidence_exists` | High | Evidence packet shape/hash reconciliation | Track 1 |
| F-004 Status/why/explain/review/recover disagree | High | Builder state source of truth | Track 2 |
| F-005 Recovery/approval path dead-ends | High | Recovery/approval idempotency | Track 3 |
| F-006 `ces approve` lacks `--project-root` | Medium | CLI consistency | Track 4 |
| F-007 Manual completion erases provenance | Medium | Completion evidence metadata | Track 3 |
| F-008 Working generated project | Good behavior | Preserve builder generation quality | Acceptance guard |
| F-009 `ces init` updates `.gitignore` well | Good behavior | Preserve init hygiene | Regression guard |

---

## Architecture direction

### Single source of truth

Add or formalize a builder session state resolver that every surface uses:

- New module candidate: `src/ces/cli/_builder_state.py`.
- Inputs:
  - latest builder session snapshot from `LocalProjectStore.get_latest_builder_session_snapshot()`
  - manifest row/workflow state
  - evidence packet and reviewed evidence integrity status
  - approval row
  - merge decision/checks if available or recomputable
  - completion contract and verification state when relevant
- Output model:
  - `canonical_state`: `not_started | collecting | running | awaiting_review | approved | completed | blocked | failed`
  - `blocking_reasons`: structured list with check name, human summary, and next command
  - `next_action`: one enum-like action used by all renderers
  - `review_allowed`: bool + reason
  - `approval_allowed`: bool + reason
  - `recovery_allowed`: bool + reason
  - `completion_allowed`: bool + reason

Then wire `status`, `why`, `explain`, `review`, `recover`, `approve`, and `report builder` to this resolver instead of each command reinterpreting state independently.

### Evidence integrity contract

The merge controller currently requires an evidence packet with:

- embedded manifest hash
- caller/packet manifest hash agreement
- reviewed evidence hash
- reviewed evidence hash integrity
- review complete state

The dogfood failure strongly suggests the builder-generated `reviewed_evidence_packet` or recovery packet did not satisfy this contract even though runtime evidence existed. The fix should not weaken merge validation. Instead, make builder/recovery/manual evidence creation emit the same canonical evidence packet shape that `MergeController._check_evidence_exists()` expects.

---

## Track 1 — Fix approved-build merge/evidence reconciliation

**Primary findings:** F-003, also F-004/F-005.  
**Likely files:**

- `src/ces/cli/run_cmd.py`
- `src/ces/cli/_builder_evidence.py`
- `src/ces/cli/_builder_report.py`
- `src/ces/control/services/merge_controller.py`
- `src/ces/control/services/evidence_integrity.py`
- `src/ces/local_store.py`
- tests under `tests/unit/test_cli/`, `tests/unit/test_control/`, `tests/integration/`

### Desired behavior

For a greenfield `ces build --yes --greenfield --accept-runtime-side-effects` where:

- runtime exits `0`,
- completion claim is parsed,
- verification commands pass,
- sensors do not block,
- operator auto-approval is permitted,

CES must end with:

- builder session `stage=completed`,
- manifest workflow state `merged` or the canonical terminal state CES uses after `WorkflowEngine.approve_merge`,
- merge validation allowed,
- final output titled success, not red/yellow blocked,
- next action `start_new_session`,
- `ces why` says no blocker because the session is complete,
- `ces status --json` shows no contradictory blocked/approved combination.

### Implementation steps

1. Add a regression fixture that simulates the TaskLedger path without invoking a real runtime:
   - Use a fake runtime adapter returning a `ces:completion` claim with criteria satisfied.
   - Create a workspace delta with generated files.
   - Make verification pass.
   - Auto-approve with `--yes`.
   - Assert merge decision passes and session is completed.
2. Inspect `run_cmd._run_brief_flow()` around lines ~1180-1330:
   - verify the packet passed to `merge_controller.validate_merge()` is the same packet saved to local evidence.
   - verify `reviewed_evidence_packet` includes embedded manifest hash equal to the final signed manifest `content_hash`.
   - verify `reviewed_evidence_hash` is computed after all packet fields that affect the hash are present.
3. Add a small helper, e.g. `build_reviewed_evidence_packet(...)`, that owns packet creation for builder, recovery, approval, and completion paths.
4. Ensure manifest signing/scope changes occur before evidence packet hash binding:
   - greenfield scope from workspace delta (`_manifest_with_effective_greenfield_scope`) must be applied,
   - manifest must be signed/saved,
   - evidence packet embeds that final `content_hash`.
5. Re-run merge validation only after review state reaches decision and manifest state is approved.
6. If merge is allowed, update session to completed and avoid raising `typer.Exit(code=1)`.
7. If merge is blocked, save structured failed check details into the builder session/report (`last_error`, `merge_checks`, `blocking_reasons`) so diagnostics can be precise.

### Regression tests

Add tests such as:

- `tests/integration/test_builder_greenfield_merge.py::test_successful_greenfield_build_completes_with_valid_evidence`
- `tests/unit/test_cli/test_builder_evidence_packet.py::test_builder_evidence_packet_matches_merge_controller_contract`
- `tests/unit/test_control/test_merge_controller.py::test_valid_builder_packet_passes_evidence_exists`

Acceptance assertions:

```python
assert session.stage == "completed"
assert session.next_action == "start_new_session"
assert session.last_action in {"approval_recorded", "merge_completed", "approval_recorded_merge_applied"}
assert merge_decision.allowed is True
assert not merge_decision.reason
```

---

## Track 2 — Unify state/next-action diagnostics across status, why, explain, review, recover, report

**Primary finding:** F-004.  
**Likely files:**

- `src/ces/cli/_builder_state.py` (new)
- `src/ces/cli/status_cmd.py`
- `src/ces/cli/why_cmd.py`
- `src/ces/cli/_explain_views.py`
- `src/ces/cli/review_cmd.py`
- `src/ces/cli/recover_cmd.py`
- `src/ces/cli/_blocker_diagnostics.py`
- `src/ces/cli/_builder_report.py`
- `src/ces/recovery/planner.py`

### Desired behavior

After any builder phase, all user-facing surfaces answer the same three questions consistently:

1. What state is the session in?
2. Is there a blocker? If yes, exactly which one?
3. What is the next command?

### Implementation steps

1. Introduce `BuilderStateSummary` dataclass.
2. Normalize contradictory raw states into canonical states:
   - `session.stage=blocked` + manifest `approved` + no failing merge checks => `completed` or `approved_pending_completion`, not blocked.
   - `session.stage=blocked` + failed merge check `evidence_exists` => blocked with `next_action=recover_auto_evidence` or `complete_with_evidence`, not generic `review_evidence`.
   - `session.stage=awaiting_review` + manifest `approved` => approval already happened; do not suggest `review` unless review is actually allowed.
3. Replace duplicated mappings:
   - `status_cmd._describe_builder_next_step()`
   - `_explain_views.describe_blocker()`
   - `_explain_views.describe_next_step()`
   - `_blocker_diagnostics.diagnose_builder_report()`
   with resolver output.
4. Teach `review_cmd` to use `review_allowed` from resolver:
   - If manifest already approved, do not just fail with “must be in_flight or under_review”. Instead print: “This manifest is already approved; next step is X.”
5. Teach `recover_cmd` to use resolver recovery reason and not claim auto-complete will work if the safe auto-completion predicate will reject it.
6. Make JSON payloads expose `canonical_state`, `blocking_reasons`, and `next_command` consistently.

### Regression tests

Add snapshot-style CLI tests with a seeded local store representing the dogfood contradictory state:

- `tests/unit/test_cli/test_builder_state_resolver.py::test_approved_manifest_blocked_session_resolves_to_single_next_action`
- `tests/unit/test_cli/test_status_why_explain_coherence.py::test_surfaces_agree_for_evidence_blocked_approved_session`
- `tests/unit/test_cli/test_review_cmd.py::test_review_already_approved_prints_actionable_next_step`
- `tests/unit/test_recovery/test_recovery_planner.py::test_recovery_plan_matches_builder_state_resolver`

Acceptance assertions:

```python
assert status_json["builder"]["canonical_state"] == why_json["diagnostic"]["canonical_state"]
assert status_json["builder"]["next_command"] == why_json["diagnostic"]["next_command"]
assert "review" not in next_command_when_review_is_disallowed
```

---

## Track 3 — Make recovery/approval/completion idempotent and provenance-preserving

**Primary findings:** F-005, F-007.  
**Likely files:**

- `src/ces/recovery/executor.py`
- `src/ces/recovery/planner.py`
- `src/ces/cli/recover_cmd.py`
- `src/ces/cli/approve_cmd.py`
- `src/ces/cli/complete_cmd.py`
- `src/ces/cli/_builder_report.py`
- `src/ces/local_store.py`

### Desired behavior

1. `recover --auto-evidence --auto-complete` completes only when safe, and says exactly why when not safe.
2. A session blocked only by missing/malformed evidence after successful independent verification can be auto-completed safely.
3. `approve` is idempotent:
   - if already approved and evidence is valid, it should not create a new contradiction;
   - if already approved but evidence is invalid, it should say which recovery/completion command to run.
4. `complete --evidence` must preserve existing runtime evidence, runtime-safety metadata, approval, manifest hash, completion contract, and superseded packet references.

### Implementation steps

1. Revisit `recovery.executor._safe_to_auto_complete()`:
   - current disallowed markers include `merge_blocked`; dogfood evidence shows this can prevent auto-completion of precisely the “evidence packet malformed/missing but verification passed” case.
   - Replace fragile text-marker logic with structured blocker checks from `BuilderStateSummary`.
2. Update `_save_recovery_evidence()` to emit canonical merge-compatible evidence packet fields:
   - `manifest_hash`,
   - reviewed evidence hash,
   - independent verification result,
   - original runtime evidence under `superseded_evidence`,
   - runtime safety metadata copied from old evidence/session.
3. If `auto_complete=True` and structured blockers are limited to evidence/verification evidence, complete the session and save approval once.
4. Update `complete_cmd.py`:
   - load existing evidence by `evidence_packet_id` and manifest id,
   - create a new packet that includes manual evidence plus `superseded_evidence`, not a replacement that erases provenance,
   - record `completion_mode=manual_reconciliation`, `manual_evidence_path`, `manual_rationale`, and `completed_by`.
5. Update `approve_cmd.py`:
   - if manifest already approved, skip redundant workflow transitions and recompute/validate merge using canonical evidence.
   - do not return `merge_reason=evidence_exists, review_complete` without detailed failed check payloads.
6. Ensure builder reports keep runtime safety metadata after manual completion.

### Regression tests

- `tests/unit/test_recovery/test_recovery_executor.py::test_auto_complete_allows_evidence_only_merge_blocker_after_verification_passes`
- `tests/unit/test_recovery/test_recovery_executor.py::test_recovery_packet_is_merge_compatible_and_preserves_old_runtime_safety`
- `tests/unit/test_cli/test_complete_cmd.py::test_manual_complete_preserves_superseded_evidence_and_runtime_safety`
- `tests/unit/test_cli/test_approve_cmd.py::test_approve_is_idempotent_for_already_approved_manifest`

Acceptance assertions:

```python
assert result.completed is True
assert recovered_packet["superseded_evidence"] is not None
assert recovered_packet["runtime_safety"] == old_packet["runtime_safety"]
assert recovered_packet["manual_completion"]["evidence_path"] == str(evidence_path)
assert merge_decision.allowed is True
```

---

## Track 4 — Add `--project-root` to `ces approve`

**Primary finding:** F-006.  
**Likely files:**

- `src/ces/cli/approve_cmd.py`
- `src/ces/cli/main.py` or command registration module, if needed
- tests under `tests/unit/test_cli/`

### Desired behavior

`ces approve` accepts `--project-root PATH`, matching `status`, `why`, `review`, `recover`, `report builder`, `complete`, and `build` workflows.

### Implementation steps

1. Add `project_root: Path | None = typer.Option(None, "--project-root", help="Repo/CES project root to approve; defaults to cwd/.ces discovery.")` to `approve_manifest()`.
2. Replace current root resolution with `find_project_root(project_root)`.
3. Ensure services are opened with `get_services(project_root=resolved_root)`.
4. Include `project_root` in `--json` output.
5. Update help tests.

### Regression tests

- `tests/unit/test_cli/test_approve_cmd.py::test_approve_accepts_project_root_option`
- `tests/integration/test_cli_project_root.py::test_approve_uses_explicit_project_root_outside_target_cwd`

Acceptance command:

```bash
ces approve --project-root /tmp/ces-target --yes --json
```

must not fail with “No such option”.

---

## Track 5 — Redact and summarize runtime auth probe output

**Primary finding:** F-002.  
**Likely files:**

- `src/ces/cli/doctor_cmd.py`
- `src/ces/execution/secrets.py`
- tests under `tests/unit/test_cli/test_doctor_cmd.py` or equivalent

### Desired behavior

`ces doctor --verify-runtime --json` should confirm runtime readiness without dumping raw hook/MCP/provider tails into normal output.

### Implementation steps

1. Change `_probe_runtime_auth()` to return structured fields, not a single detail string:
   - `runtime`, `command`, `exit_code`, `auth_ok`, `ready_signal_seen`, `stdout_summary`, `stderr_summary`, `raw_output_redacted=false`.
2. In human output, show only:
   - succeeded/failed,
   - exit code,
   - whether expected READY/success signal appeared,
   - where detailed logs can be found if CES writes them.
3. In JSON, either omit raw tails by default or include only aggressively scrubbed/length-limited summaries.
4. Add optional `--show-runtime-probe-output` only if operators explicitly request raw redacted tails.
5. Expand `scrub_secrets_from_text()` tests for common provider/MCP/hook patterns.

### Regression tests

- `tests/unit/test_cli/test_doctor_cmd.py::test_verify_runtime_json_does_not_include_raw_stdout_stderr_tails_by_default`
- `tests/unit/test_cli/test_doctor_cmd.py::test_verify_runtime_optional_probe_output_is_redacted`
- `tests/unit/test_execution/test_secrets.py::test_scrubs_runtime_provider_noise_and_secret_like_values`

Acceptance assertions:

```python
assert "stdout_tail" not in payload["runtime_auth"]["codex"]["detail"]
assert "stderr_tail" not in payload["runtime_auth"]["codex"]["detail"]
assert "[REDACTED]" in raw_output_when_requested_if_secret_like_text_present
```

---

## Track 6 — Improve source-checkout/new-project docs and help

**Primary finding:** F-001.  
**Likely files:**

- `README.md`
- `docs/Getting_Started.md`
- `docs/dogfood/` or a new `docs/Greenfield_Dogfood.md`
- CLI help text in `run_cmd.py`, `init_cmd.py`, possibly `doctor_cmd.py`

### Desired behavior

A developer running CES from a source checkout against a separate new target should immediately see the safe pattern:

```bash
cd /path/to/controlled-execution-system
uv sync
CES=/path/to/controlled-execution-system/.venv/bin/ces
mkdir -p /tmp/ces-dogfood-taskledger
cd /tmp/ces-dogfood-taskledger
"$CES" init --project-root "$PWD" --yes
"$CES" build '...' --project-root "$PWD" --greenfield --yes ...
```

Also document the installed-user equivalent:

```bash
uv tool install controlled-execution-system
cd /tmp/my-new-project
ces build '...' --greenfield
```

### Implementation steps

1. Add a short “Using a source checkout against another target directory” section to `docs/Getting_Started.md`.
2. Add a warning to not run dogfood generated projects inside the CES repo.
3. Mention that `uv run ces ...` executes relative to the current working directory unless `--project-root` is supplied; for source checkout + separate cwd, prefer the checkout venv binary or installed tool.
4. Include `doctor --verify-runtime` and `doctor --runtime-safety` as preflight commands.
5. Add a docs test or markdown grep test to ensure the source-checkout target pattern remains documented.

### Regression tests

- `tests/unit/test_docs/test_getting_started.py::test_source_checkout_separate_target_pattern_documented`
- Existing docs link/check tests if available.

---

## Track 7 — Preserve good behavior as explicit regression guards

**Primary findings:** F-008, F-009.  
**Likely files:**

- `src/ces/cli/init_cmd.py`
- `src/ces/verification/build_contract.py`
- `src/ces/verification/runner.py`
- builder integration tests

### Desired behavior to preserve

1. CES can generate a simple, maintainable Python CLI project matching acceptance criteria.
2. `ces init` keeps local governance and verification artifacts out of git:
   - `.ces/`, `.coverage`, `coverage.json`, etc.
3. Builder evidence contains enough information to verify the final project outside CES.

### Implementation steps

1. Add a lightweight greenfield benchmark/fixture for a Python CLI shape that does not require live LLM runtime:
   - fake runtime writes minimal files,
   - builder verification runs `python -m pytest -q`,
   - assert README and tests exist.
2. Add/init preserve `.gitignore` regression test if not already present.
3. Ensure all fixes above do not loosen acceptance criteria or skip verification just to get a green state.

### Regression tests

- `tests/integration/test_builder_greenfield_python_cli.py::test_greenfield_python_cli_happy_path_has_tests_readme_and_completed_state`
- `tests/unit/test_cli/test_init_cmd.py::test_init_gitignore_preserves_ces_and_verification_artifacts`

---

## Suggested PR sequence

### PR 1 — Evidence packet contract and greenfield happy-path completion

Scope:

- Track 1 only, plus minimal helper extraction.
- Add failing tests for builder evidence packet and successful greenfield merge.
- Fix builder evidence/manifest hash ordering.

Verification:

```bash
uv run pytest tests/unit/test_control/test_merge_controller.py tests/unit/test_cli/test_builder_evidence_packet.py tests/integration/test_builder_greenfield_merge.py -q
uv run ruff check src tests
uv run mypy src
```

### PR 2 — State resolver and surface coherence

Scope:

- Track 2.
- Add `BuilderStateSummary` resolver.
- Wire `status`, `why`, `explain`, `review`, `recover`, `report builder` to it.

Verification:

```bash
uv run pytest tests/unit/test_cli/test_builder_state_resolver.py tests/unit/test_cli/test_status_why_explain_coherence.py tests/unit/test_cli/test_review_cmd.py tests/unit/test_recovery/test_recovery_planner.py -q
uv run ruff check src tests
uv run mypy src
```

### PR 3 — Recovery/approval/completion reconciliation

Scope:

- Track 3.
- Structured auto-complete safety.
- Idempotent approve.
- Manual completion provenance preservation.

Verification:

```bash
uv run pytest tests/unit/test_recovery/test_recovery_executor.py tests/unit/test_cli/test_complete_cmd.py tests/unit/test_cli/test_approve_cmd.py -q
uv run ruff check src tests
uv run mypy src
```

### PR 4 — CLI consistency and runtime diagnostics hygiene

Scope:

- Track 4 and Track 5.
- `approve --project-root`.
- Sanitized runtime probe detail.

Verification:

```bash
uv run pytest tests/unit/test_cli/test_approve_cmd.py tests/unit/test_cli/test_doctor_cmd.py tests/unit/test_execution/test_secrets.py -q
uv run ruff check src tests
uv run mypy src
```

### PR 5 — Docs and good-behavior regression guards

Scope:

- Track 6 and Track 7.
- Source checkout docs.
- Init `.gitignore` guard.
- Greenfield happy-path benchmark guard if not fully covered by PR 1.

Verification:

```bash
uv run pytest tests/unit/test_docs tests/unit/test_cli/test_init_cmd.py tests/integration/test_builder_greenfield_python_cli.py -q
uv run ruff check src tests
uv run mypy src
```

---

## End-to-end acceptance dogfood

After all PRs land, rerun a fresh TaskLedger dogfood target from scratch.

```bash
CES=/home/chris/.Hermes/workspace/controlled-execution-system/.venv/bin/ces
TARGET=/home/chris/.Hermes/workspace/ces-dogfood-taskledger-fix-verify-$(date -u +%Y%m%dT%H%MZ)
mkdir -p "$TARGET"
cd "$TARGET"
git init -q
"$CES" init --project-root "$TARGET" --yes
"$CES" doctor --runtime-safety --project-root "$TARGET" --json
"$CES" doctor --verify-runtime --runtime codex --project-root "$TARGET" --json
"$CES" build 'Create a small Python CLI app named TaskLedger. It should add, list, complete, and delete tasks; persist tasks locally in a JSON file; include pytest tests; include README setup and usage; keep implementation simple and local-only.' \
  --project-root "$TARGET" \
  --runtime codex \
  --greenfield \
  --yes \
  --accept-runtime-side-effects \
  --acceptance 'A Python package or module named taskledger provides a command-line interface runnable with python -m taskledger --help.' \
  --acceptance 'Users can add tasks with a title and list tasks showing identifiers, titles, and completion status.' \
  --acceptance 'Users can mark a task complete and delete a task through the CLI.' \
  --acceptance 'Tasks persist in a local JSON file, with a CLI option or documented environment variable to choose the data file for tests and manual use.' \
  --acceptance 'Pytest coverage verifies add, list, complete, delete, and JSON persistence behavior.' \
  --acceptance 'README documents setup, tests, and basic CLI usage.' \
  --constraint 'Keep implementation simple, local-only, and dependency-light.' \
  --constraint 'Do not build inside the CES repository.' \
  --must-not-break 'Existing README remains present.' \
  --full \
  --governance
"$CES" status --project-root "$TARGET" --json
"$CES" why --project-root "$TARGET" --json
"$CES" explain --project-root "$TARGET"
"$CES" report builder --project-root "$TARGET"
python -m pytest -q
python -m taskledger --help
```

Expected final CES state:

- build exits `0`,
- no `Merge blocked: evidence_exists`,
- `status`, `why`, `explain`, and `report builder` all say completed/no active blocker,
- `review` and `recover` either say “nothing to do, session complete” or provide non-mutating report output,
- runtime probe output contains no raw provider/MCP tails by default,
- independent generated-project tests pass.

---

## Risks and guardrails

- **Do not weaken merge validation** to make greenfield pass. Fix packet creation/hash ordering instead.
- **Do not make recovery auto-complete broad classes of blockers.** Auto-complete only when structured blockers are limited to evidence/verification evidence and independent verification passed.
- **Do not erase old runtime evidence.** Preserve as `superseded_evidence` with runtime-safety metadata.
- **Do not reintroduce raw provider output leaks.** Runtime diagnostics should be summary-first, raw only on explicit request and after redaction.
- **Do not conflate brownfield and greenfield.** Keep brownfield conservative; this plan addresses greenfield successful-build reconciliation.

---

## Definition of done

This plan is complete when:

1. Every finding F-001 through F-007 has at least one regression test.
2. Good behaviors F-008 and F-009 have guard tests.
3. Fresh TaskLedger dogfood completes without manual `ces complete`.
4. All state surfaces agree on final state and next action.
5. `approve --project-root` works.
6. Runtime auth probe output is redacted/summarized by default.
7. Manual completion and recovery preserve provenance.
8. Targeted tests, full test suite, lint, and typecheck pass.
