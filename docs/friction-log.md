# CES Friction Log

This log records friction found during the production-readiness dogfood pass. Friction is not hidden; each item includes the attempted step, expected behavior, actual behavior, severity, fix status, and evidence.

## FL-001: README ran `ces` before install guidance

- **Step attempted:** Follow README Quick Start from the top.
- **Expected:** Install appears before any `ces` command.
- **Actual:** README previously asked users to run `ces`, `ces --help`, and `ces doctor` before showing `uv tool install controlled-execution-system`.
- **Severity:** High.
- **Status:** Fixed.
- **Fix:** README Quick Start now installs CES first and includes the Python 3.11 recovery command.
- **Evidence after fix:** `README.md` has `### 1. Install CES` before first `ces` command.

## FL-002: README lacked explicit beginner Greenfield and Brownfield sections

- **Step attempted:** Use README to decide how to start a new project vs apply CES to an existing repo.
- **Expected:** Two scannable sections with copy-paste commands and success criteria.
- **Actual:** Greenfield and brownfield commands were interleaved across quickstart and operator workflow sections.
- **Severity:** High.
- **Status:** Fixed.
- **Fix:** Added `Greenfield project: create a new project from scratch` and `Brownfield project: apply CES to an existing project` sections.
- **Evidence after fix:** README contains explicit sections, commands, and “how to know it worked” checks.

## FL-003: Approval guidance was too easy to miss

- **Step attempted:** Determine when a CES run is safe to approve.
- **Expected:** A clear beginner quality-gate checklist.
- **Actual:** Proof and risk-track details existed but were dense and scattered.
- **Severity:** High.
- **Status:** Fixed.
- **Fix:** Added `Quality gates: how to know it worked` to README and expected proof output to Quickstart.
- **Evidence after fix:** README says not to approve from agent claims; Quickstart says not to approve when proof is `partially_proven`, `unproven`, or `contradicted`.

## FL-004: `ces create` can suggest accidental nested folders

- **Step attempted:** In a folder already named `notes-tasks`, run `ces create ... --name "Notes Tasks"`.
- **Expected:** CES should suggest using the current folder or warn about a nested duplicate.
- **Actual:** CES suggested `notes-tasks/notes-tasks`.
- **Severity:** Medium.
- **Status:** Documented, not fixed in code yet.
- **Proposed fix:** Add `--here` or a warning when the current directory basename matches the inferred slug.
- **Evidence:** Greenfield dogfood trial report under a local `ces-friction-tests/greenfield-quickstart-*` workspace.

## FL-005: Safe non-interactive greenfield preflight was not obvious

- **Step attempted:** Run `ces build --from-scratch ... --runtime codex` without side-effect consent.
- **Expected:** A beginner understands how to stop at the safe boundary and what flag is needed next.
- **Actual:** The run created `.ces/`, prompted for constraints, and stopped under non-interactive logging; `--yes` plus acceptance criteria made the preflight clearer.
- **Severity:** Medium.
- **Status:** Partially fixed in docs.
- **Fix:** README and Quickstart now explain Codex side-effect consent and `--accept-runtime-side-effects`.
- **Remaining:** Consider a future `--preflight-only` mode.

## FL-006: `--from-scratch` first scan displayed `Project mode: brownfield`

- **Step attempted:** Run greenfield `ces build --from-scratch` in the trial project.
- **Expected:** User-visible project mode consistently says greenfield.
- **Actual:** First scan showed brownfield even though later status showed greenfield.
- **Severity:** Medium.
- **Status:** Documented, not fixed in this pass.
- **Proposed fix:** Make displayed scan mode honor explicit `--from-scratch` before any generated local state affects detection.
- **Evidence:** Greenfield dogfood trial logs under a local `ces-friction-tests/greenfield-quickstart-*` workspace.

## FL-007: Runtime summaries could recommend approval from exit code

- **Step attempted:** Review runtime evidence summary behavior.
- **Expected:** Approval recommendation comes only from verification/proof, not a runtime adapter.
- **Actual:** Default runtime adapter emitted `Recommendation: approve` when exit code was 0.
- **Severity:** High.
- **Status:** Fixed.
- **Fix:** Runtime summaries now say raw runtime status only and point to `ces verify` and `ces proof`.
- **Evidence after fix:** `tests/unit/test_execution/test_runtime_evidence_summary.py` asserts no `Recommendation: approve` appears.

## FL-008: Brownfield observed edits were added to manifest scope after runtime

- **Step attempted:** Inspect brownfield scope enforcement after workspace delta capture.
- **Expected:** Declared/operator scope authorizes changes; observed edits are evidence.
- **Actual:** Runtime-changed product files were added to `affected_files` before workspace-scope violation checks.
- **Severity:** High.
- **Status:** Fixed.
- **Fix:** Brownfield scope helper now derives only operator truth paths, and workspace scope checks ignore `.ces/` local state but report out-of-scope product edits.
- **Evidence after fix:** `tests/unit/test_cli/test_run_cmd.py` and `tests/unit/test_cli/test_builder_evidence.py` cover the boundary.

## FL-009: Audit HMAC env override accepted weak secrets

- **Step attempted:** Inspect audit-HMAC secret loading.
- **Expected:** Env override gets the same minimum length check as file-backed secrets.
- **Actual:** Any non-placeholder env override was accepted.
- **Severity:** Medium.
- **Status:** Fixed.
- **Fix:** `CES_AUDIT_HMAC_SECRET` overrides shorter than 32 bytes now raise `ValueError`.
- **Evidence after fix:** `tests/unit/test_crypto.py::TestAuditHmacPersistence::test_env_override_rejects_short_secret`.

## FL-010: Auralis `deliberate --challenge` over-blocked common terminology

- **Step attempted:** Generate an Approach Decision Brief for a scoped Auralis provider-capability UI objective.
- **Expected:** Challenge mode flags truly ambiguous domain terms.
- **Actual:** It treated common terms like provider, browser, support, local, SpeechRecognition, and language as blocking overloads, including duplicate provider entries.
- **Severity:** Medium.
- **Status:** Documented, not fixed in this pass.
- **Proposed fix:** Tune challenge-mode term scoring and de-duplicate blockers.
- **Evidence:** Auralis dogfood report under a local `ces-auralis-dogfood-trial/` workspace.

## FL-011: Auralis `next-prompt` file scope was too generic

- **Step attempted:** Generate a Developer Intent Contract for a scoped Auralis UI change.
- **Expected:** Likely file areas include relevant TypeScript app and speech modules.
- **Actual:** Contract allowed generic areas like `README.md`, `tests/`, and project config while omitting likely relevant files.
- **Severity:** Medium.
- **Status:** Documented, not fixed in this pass.
- **Proposed fix:** Improve objective-specific codebase relevance selection for `next-prompt`.
- **Evidence:** Auralis dogfood report under a local `ces-auralis-dogfood-trial/` workspace.

## FL-012: Source checkout dogfood output is noisy under Hermes venv

- **Step attempted:** Run `uv run --project <CES> ces ...` from the Hermes environment.
- **Expected:** Clear command output.
- **Actual:** uv repeatedly warns that the active Hermes `VIRTUAL_ENV` does not match the project `.venv`.
- **Severity:** Low.
- **Status:** Documented.
- **Proposed fix:** Add a source dogfood note or recommend running from a shell without an active unrelated venv.

## FL-013: Source-checkout invocation can target the wrong repo root

- **Step attempted:** Run greenfield trial from external folder using `uv run --directory <CES_SRC> ces ship/build ...` without consistently pinning `--project-root`.
- **Expected:** Commands operate on the external target folder.
- **Actual:** CES analyzed the source checkout instead, misclassifying flow as brownfield.
- **Severity:** High.
- **Status:** Partially fixed in docs.
- **Fix:** README/Getting Started now emphasize beginner mode selection and explicit project-root safety patterns.
- **Evidence after fix:** Greenfield trial findings captured from parallel dogfood run; README now includes explicit “beginner journey” and pitfalls.

## FL-014: Brownfield Auralis trial blocked by network access in this environment

- **Step attempted:** Clone `https://github.com/chrisduvillard/auralis` for mandated brownfield dogfood.
- **Expected:** Repo clones and CES brownfield flow can run.
- **Actual:** `git clone` failed with `CONNECT tunnel failed, response 403`.
- **Severity:** High (environmental blocker).
- **Status:** Open (cannot fix in CES code/docs alone).
- **Proposed next step:** Provide local checkout, reachable mirror, or artifact bundle for Auralis to complete mandatory trial.
- **Evidence:** Parallel brownfield testing agent report with clone command output.
