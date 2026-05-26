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
- **Proposed fix:** Add `--here` or a warning when the current directory basename matches the inferred slug; for source-checkout users, docs now emphasize running in a separate target folder or passing `--project-root`.
- **Evidence:** Greenfield dogfood trial report under an external dogfood workspace; source-checkout guidance in `docs/Getting_Started.md`.

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
- **Status:** Fixed.
- **Fix:** Domain challenge now deduplicates objective terms and treats common technology-context terms such as provider, browser, support, local, language, speech, recognition, capability, and UI as informational when their meanings come only from visible code identifiers rather than repo glossary/ADR context.
- **Evidence after fix:** `tests/unit/test_verification/test_production_autopilot.py::test_deliberate_challenge_keeps_common_tech_terms_informational`.

## FL-011: Auralis `next-prompt` file scope was too generic

- **Step attempted:** Generate a Developer Intent Contract for a scoped Auralis UI change.
- **Expected:** Likely file areas include relevant TypeScript app and speech modules.
- **Actual:** Contract allowed generic areas like `README.md`, `tests/`, and project config while omitting likely relevant files.
- **Severity:** Medium.
- **Status:** Fixed.
- **Fix:** Next-prompt objective matching now splits camelCase/PascalCase TypeScript path tokens such as `BrowserSpeechRecognition`, `providerCapabilities`, and `ProviderCapabilityPanel`, and places objective-specific file areas before generic fallback areas.
- **Evidence after fix:** `tests/unit/test_verification/test_production_autopilot.py::test_next_prompt_brownfield_file_areas_split_typescript_compound_names`.

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

## FL-014: Auralis brownfield trial verifies useful planning but exposed stale runtime/readiness signals

- **Step attempted:** Run read-only CES brownfield flow against local Auralis checkout (`ces mri`, `ces next`, `ces next-prompt`, `ces ship`, `ces proof`, `ces verify`) and direct Auralis checks.
- **Expected:** CES understands the repo, plans safely, validates existing commands, and preserves tracked git cleanliness.
- **Actual:** CES correctly classified Auralis as a Node/Vite production candidate and generated a useful brownfield contract, but missed Electron desktop runtime evidence, flagged `package-lock.json` as a large-file maintainability risk, and `ces proof` surfaced prior local proof without enough freshness/objective warning.
- **Severity:** High for signal quality, low for repo safety.
- **Status:** Fixed.
- **Fix:** MRI now infers Electron runtime declarations from package `main`, Electron deps/scripts, and desktop smoke scripts; large-file risk ignores dependency lockfiles; proof evidence is now bound to a deterministic objective/context fingerprint.
- **Evidence after fix:** `tests/unit/test_verification/test_mri.py::test_project_mri_infers_electron_runtime_from_package_json`, `::test_project_mri_does_not_flag_lockfiles_as_large_source_files`, `tests/unit/test_verification/test_proof_binding.py`, `tests/unit/test_verification/test_proof_card.py::test_proof_card_rejects_latest_verification_for_different_objective_binding`, and `::test_proof_card_rejects_legacy_verification_without_binding_hash`; Auralis tracked git status stayed clean before/after trial.

## FL-015: Greenfield `ces diff` crashed on bracketed paths

- **Step attempted:** After a failed greenfield runtime attempt, run `ces diff` to inspect drift.
- **Expected:** CES prints the git name-status output or `(no changes)`.
- **Actual:** Rich interpreted bracketed file/path text as markup and raised `MarkupError`.
- **Severity:** High for recovery/debugging.
- **Status:** Fixed.
- **Fix:** `ces diff` now escapes git diff text before rendering it inside a Rich panel.
- **Evidence after fix:** `tests/unit/test_cli/test_diff_cmd.py::test_diff_output_escapes_rich_markup_characters`.

## FL-016: Brownfield scan and baseline could write through symlinked `.ces`

- **Step attempted:** Inspect/write brownfield scan and baseline local-state artifacts in a repo with an existing `.ces` path.
- **Expected:** CES refuses local state that escapes the project root before writing governance artifacts.
- **Actual:** `ces scan` and `ces baseline` had write paths that did not consistently validate an existing `.ces` directory.
- **Severity:** High for brownfield safety and local-state hygiene.
- **Status:** Fixed.
- **Fix:** `ces scan` and `ces baseline` now validate `.ces` and the concrete nested state write path with the shared state-path guard before writing; dry-run scan remains read-only.
- **Evidence after fix:** `tests/unit/test_cli/test_scan_cmd.py::test_scan_rejects_symlinked_ces_dir_before_writing`, `::test_scan_rejects_symlinked_brownfield_dir_before_writing`, `::test_scan_dry_run_does_not_touch_symlinked_ces_dir`, `tests/unit/test_cli/test_baseline_cmd.py::test_baseline_rejects_symlinked_ces_dir_before_writing`, and `::test_baseline_rejects_symlinked_baseline_dir_before_writing`.

## FL-017: Workspace delta followed symlinked files during runtime-change capture

- **Step attempted:** Inspect runtime workspace-delta capture used to decide what changed.
- **Expected:** CES should not hash or track files that escape a brownfield repo through symlinks.
- **Actual:** `Path.is_file()` followed symlinks, so external files could be hashed as if they were project files.
- **Severity:** Medium-high for messy brownfield repos.
- **Status:** Fixed.
- **Fix:** Workspace snapshots now skip symlinks, ignore out-of-root resolved files, and continue on unreadable files.
- **Evidence after fix:** `tests/unit/test_execution/test_workspace_delta.py::test_workspace_snapshot_skips_symlinks_to_outside_files` and `::test_workspace_snapshot_ignores_broken_symlink`.

## FL-018: Brownfield guide documented dispositions the CLI does not accept

- **Step attempted:** Compare `docs/Brownfield_Guide.md` with `ces brownfield review --help`.
- **Expected:** Documented dispositions match the CLI-supported values.
- **Actual:** The guide used `migrate` and `remove`, while the CLI supports `change`, `new`, `preserve`, `retire`, and `under_investigation`.
- **Severity:** Medium.
- **Status:** Fixed.
- **Fix:** Brownfield guide now documents the actual CLI dispositions.
- **Evidence after fix:** `docs/Brownfield_Guide.md` uses `<preserve|change|retire|new|under_investigation>`.

## FL-019: Pytest was inferred from a `tests/` directory alone

- **Step attempted:** Inspect verification command inference against the verification-profile docs and brownfield projects with tests but no pytest setup.
- **Expected:** CES infers `python -m pytest -q` only when pytest is configured or declared.
- **Actual:** Any Python-ish project with a `tests/` directory received a pytest verification command, even without pytest config/dependency evidence.
- **Severity:** Medium-high for brownfield adoption because it can create false blockers in non-pytest repos.
- **Status:** Fixed.
- **Fix:** Python verification inference now requires pytest evidence from `pyproject.toml`, dependency groups, optional dependencies, `pytest.ini`, common requirements files, `tox.ini`, `noxfile.py`, `setup.cfg`, or `setup.py` before adding a pytest command.
- **Evidence after fix:** `tests/unit/test_verification/test_command_inference.py::test_does_not_infer_pytest_from_tests_directory_alone`, `::test_infers_pytest_from_requirements_file`, and `::test_infers_pytest_from_tox_config`.

## FL-020: CI dependency audit command used an invalid `pip-audit` flag combination

- **Step attempted:** Run local CI-parity dependency audit from the workflow command.
- **Expected:** `pip-audit` audits the exported requirements file and exits cleanly when no CVEs are present.
- **Actual:** Current `pip-audit` rejects `--disable-pip` unless the requirements file is hashed or `--no-deps` is used.
- **Severity:** High because CI and release workflows can fail before testing CES.
- **Status:** Fixed.
- **Fix:** CI, TestPyPI, and PyPI workflows now run `uv run pip-audit --strict -r ...`; `uv.lock` was refreshed to idna 3.15 to clear CVE-2026-45409.
- **Evidence after fix:** Local `uv export --frozen --group ci ... && uv run pip-audit --strict -r /tmp/ces-ci-requirements.txt` reports `No known vulnerabilities found`; latest-bounds worktree audit also passes.

## FL-021: Review command needed a semantic artifact layer without breaking legacy manifest review

- **Step attempted:** Add the Semantic Review Layer while preserving existing `ces review` governance evidence review muscle memory.
- **Expected:** `ces review generate/show/list/open/export/github-comment` create and expose local review artifacts, while `ces review` and `ces review <manifest-id>` still run the legacy manifest review flow.
- **Actual:** The old single-command shape could not host the semantic review command family without an explicit compatibility route.
- **Severity:** High for adoption and approval safety.
- **Status:** Fixed.
- **Fix:** `ces review` is now a command family; root argument rewriting routes legacy calls to hidden `ces review run`, semantic artifacts are written under `.ces/reviews/`, proof cards reference the latest semantic review, and approvals record semantic review evidence refs with stale/high-risk warnings.
- **Evidence after fix:** `tests/unit/test_review_semantic_layer.py`, `uv run pytest tests/unit/test_review_semantic_layer.py -q`, and docs in `docs/Getting_Started.md` plus `docs/Quick_Reference_Card.md`.

## FL-022: Semantic review strict PRD closure exposed shallow build binding and export gaps

- **Step attempted:** Verify the Semantic Review Layer against the full PRD rather than the initial implementation slice.
- **Expected:** `ces review generate --from-build` binds intent/provenance to the requested CES builder run and fails if it cannot; review export supports machine-readable JSON; builder/verify completion output nudges reviewers to inspect semantic review artifacts; installed-wheel CI smokes the semantic review command family.
- **Actual:** The first semantic review implementation stored a `from_build` reference but could still fall back to the latest builder snapshot, exported only the Markdown brief, and did not explicitly smoke semantic review commands from the built wheel.
- **Severity:** Medium-high for audit fidelity and PRD confidence.
- **Status:** Fixed.
- **Fix:** Added build-context lookup by session/manifest/runtime identifiers, fail-closed unknown build IDs, builder-derived intent coverage inputs, JSON export, stable GitHub comment update marker, review next-step hints, and built-wheel semantic review smoke coverage.
- **Evidence after fix:** `tests/unit/test_review_semantic_layer.py::test_generate_from_build_uses_requested_builder_snapshot_not_latest`, `::test_generate_from_build_fails_closed_when_build_id_is_unknown`, `::test_review_export_json_and_stable_github_comment_marker`, `tests/unit/test_cli/test_verify_cmd.py::test_verify_rich_output_suggests_semantic_review_next_step`, and `.github/workflows/ci.yml` built-wheel review smoke.

## FL-023: Benchmark docs could imply value before measured evidence

- **Step attempted:** Review README, positioning docs, and A/B benchmark sample before creating a benchmark evidence pack.
- **Expected:** Public docs distinguish product thesis, process trust evidence, unmeasured templates, and measured A/B evidence.
- **Actual:** README and positioning used some value language while the only tracked benchmark spec was still an unmeasured template with missing metrics.
- **Severity:** Medium-high because public claims should not outrun the evidence artifact.
- **Status:** Fixed.
- **Fix:** README and positioning now label value as a thesis, Benchmarking documents template vs evidence-pack rules, and the sample spec declares `template-unmeasured` with an expected `insufficient-measured-evidence` recommendation.
- **Evidence after fix:** `tests/unit/test_docs/test_benchmarking_docs.py::test_sample_ab_gauntlet_spec_is_unmeasured_template_not_evidence`, `::test_benchmarking_docs_require_self_contained_evidence_packs`, and `tests/unit/test_docs/test_public_repo_contract.py::test_readme_exposes_benchmark_evidence_status_without_overclaiming`.

## FL-024: Measured A/B benchmark pilot can fail before scoring because runtime cannot write

- **Step attempted:** Start a three-scenario measured CES-vs-vanilla benchmark pilot in isolated temp workspaces.
- **Expected:** The chosen direct runtime can create files inside the isolated benchmark workspace before the pilot spends tokens on full scenario arms.
- **Actual:** Codex was installed but the workspace write path failed with `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`; Claude Code was installed but runtime authentication or entitlement was unavailable on this host.
- **Severity:** High for benchmark operations because a runtime readiness failure can masquerade as poor task performance if it is scored as a scenario result.
- **Status:** Fixed for detection and documentation; benchmark measurement remains blocked until at least one runtime preflight returns `runtime-ready`.
- **Fix:** Added `ces benchmark preflight --probe-runtime`, documented runtime preflight before measured A/B runs, and committed a sanitized blocked pilot evidence pack under `docs/benchmark/evidence/pilot-2026-05-26/`.
- **Evidence after fix:** `tests/unit/test_benchmark/test_runtime_preflight.py`, `tests/unit/test_cli/test_benchmark_cmd.py::test_benchmark_preflight_json_reports_blocked_runtime_probe`, `tests/unit/test_docs/test_benchmarking_docs.py::test_benchmark_docs_track_blocked_runtime_pilot_without_product_claims`, and sanitized preflight outputs in `docs/benchmark/evidence/pilot-2026-05-26/preflight/`.
