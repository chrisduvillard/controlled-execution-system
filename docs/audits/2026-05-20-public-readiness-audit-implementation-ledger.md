# Public Readiness Audit Implementation Ledger

Source audit used: `docs/audits/2026-05-20-public-readiness-audit.md`.

The audit source and this implementation ledger are kept as separate artifacts so the source-of-truth audit remains unchanged while reconciliation evidence lives here.

## Pass 1 - P0 Runtime, Approval, Completion, Transcript Safety

Audit items addressed:
- P0-1: Stop passing runtime prompt packs in subprocess argv.
- P0-2: Separate wizard pre-run execution consent from post-evidence approval.
- P0-3: Keep completion-gate failures as blockers even when independent verification passes.
- P0-4: Preserve full redacted runtime transcript artifacts separately from capped CLI/SQLite excerpts.
- P2-2 partial: Centralize runtime execution normalization and scrubbing.

Files changed:
- `src/ces/execution/runtimes/adapters.py`
- `src/ces/execution/pipeline.py`
- `src/ces/cli/run_cmd.py`
- `tests/unit/test_execution/test_runtime_adapters.py`
- `tests/unit/test_execution/test_pipeline.py`
- `tests/unit/test_cli/test_wizard.py`
- `tests/unit/test_cli/test_run_cmd.py`

Evidence/tests run:
- `uv run pytest tests/unit/test_execution/test_runtime_adapters.py tests/unit/test_execution/test_pipeline.py -q` -> 24 passed.
- `uv run pytest tests/unit/test_cli/test_wizard.py tests/unit/test_cli/test_run_cmd.py -q` -> 87 passed.

Remaining risk:
- Runtime prompt delivery now uses stdin pipes for Codex and Claude. This removes prompt body text from `Popen` argv, but external CLI behavior can still change; runtime adapter docs and matrix still need updating.
- Codex full transcript preservation is covered for oversized output. SQLite/CLI still intentionally receive capped excerpts through `stdout`.
- The completion blocker helper no longer accepts independent verification as a bypass. Broader end-to-end build scenarios remain covered by the full suite later.

Next highest-priority item:
- P1: enforce secret scanning in CI/pre-commit, strengthen `.gitignore`, expand redaction/security sensor coverage, add audit verification command, and fill boundary/integrity docs.

## Pass 2 - P1 Public Safety, Trust, and Boundary Documentation

Audit items addressed:
- P1: Add gitleaks to CI and pre-commit using `.gitleaks.toml`.
- P1: Add safe synthetic-secret validation before the CI secret scan.
- P1: Strengthen `.gitignore` for env variants, logs, local DBs, keys, credentials, and local artifacts while preserving `.env.example`.
- P1: Expand secret redaction for GitHub fine-grained tokens, GitLab tokens, JWTs, credential-bearing URLs, Google service-account JSON, private key material, and Slack variants.
- P1: Expand deterministic security sensor coverage for the same token/credential formats and add an oversized-file skipped-warning blocker.
- P1: Add public `ces audit verify` path with JSON output and tamper failure tests.
- P1: Add data-boundary, audit-integrity, runtime-boundary, onboarding, docs-index, and public-release checklist docs.
- P2 partial: Bring `audit_cmd.py` back under coverage and add public command coverage for `ces audit verify`.
- P2 partial: Reconcile mypy "strict" messaging by documenting the current compatibility profile.
- P2 partial: Remove hardcoded source-tree version fallback by reading `pyproject.toml`.
- P2 partial: Extract post-evidence approval decision logic from the main builder flow.

Files changed:
- `.gitleaks.toml`
- `.github/workflows/ci.yml`
- `.pre-commit-config.yaml`
- `.gitignore`
- `CONTRIBUTING.md`
- `README.md`
- `SECURITY.md`
- `pyproject.toml`
- `docs/Audit_Integrity.md`
- `docs/Data_Boundary.md`
- `docs/Docs_Index.md`
- `docs/First_15_Minutes.md`
- `docs/Public_Release_Checklist.md`
- `docs/Runtime_Adapter_Matrix.md`
- `docs/Database_Operations.md`
- `docs/Getting_Started.md`
- `docs/Operations_Runbook.md`
- `src/ces/__init__.py`
- `src/ces/cli/__init__.py`
- `src/ces/cli/audit_cmd.py`
- `src/ces/cli/run_cmd.py`
- `src/ces/harness/sensors/security.py`
- `src/ces/shared/secrets.py`
- related unit/docs tests under `tests/unit/`

Evidence/tests run:
- `uv run pytest tests/unit/test_shared/test_secrets.py tests/unit/test_sensors/test_security_sensor.py -q` -> 23 passed.
- `uv run pytest tests/unit/test_cli/test_audit_cmd.py tests/unit/test_services/test_audit_ledger.py -q` -> 82 passed.
- `uv run pytest tests/unit/test_docs/test_ci_workflow.py tests/unit/test_docs/test_public_repo_contract.py tests/unit/test_docs/test_package_contract.py -q` -> 49 passed.
- `uv run pytest tests/unit/test_cli/test_run_cmd.py tests/unit/test_cli/test_wizard.py -q` -> 89 passed.

Remaining risk:
- CI secret scan installs the pinned `gitleaks` `v8.30.0` release through Go, avoids a container runtime requirement, fetches full history, and runs repository-history scanning. Full-history findings are limited to two documented historical false-positive fixture commits allowlisted in `.gitleaks.toml`.
- Pre-commit uses the upstream gitleaks hook with `.gitleaks.toml`; contributors still need network access for hook installation.
- Remaining coverage omissions are `classify_cmd.py`, `gate_cmd.py`, `intake_cmd.py`, `report_cmd.py`, and `triage_cmd.py`; they are explicitly kept as 0.1.x follow-up coverage work because they predate the builder-first test harness.

Next highest-priority item:
- Run broad quality gates, fix regressions, then complete final audit recommendation classification and feasibility notes for P2/P3 items not fully implemented.

## Pass 3 - P2/P3 Supply Chain and Product-Usefulness Polish

Audit items addressed:
- P2: Pin GitHub Actions references to full commit SHAs instead of mutable tags.
- P2: Enforce a docs test that repository workflows use SHA-pinned external actions.
- P3: Add greenfield prompt-contract guidance without adding framework generators.
- P3: Add brownfield change-type playbooks, source-of-truth selection, test-selection guidance, monorepo guidance, and PR proof-card examples.

Files changed:
- `.github/workflows/ci.yml`
- `.github/workflows/codeql.yml`
- `.github/workflows/publish.yml`
- `.github/workflows/publish-testpypi.yml`
- `src/ces/cli/templates/ci/github.yml`
- `docs/Public_Release_Checklist.md`
- `docs/Product_Playbooks.md`
- `docs/Docs_Index.md`
- `docs/RELEASE.md`
- `README.md`
- `tests/unit/test_docs/test_ci_workflow.py`
- `tests/unit/test_docs/test_public_repo_contract.py`
- `tests/unit/test_release_workflows.py`

Evidence/tests run:
- Resolved action refs with `git ls-remote`:
  `actions/checkout@v6`,
  `astral-sh/setup-uv@v7`,
  `actions/setup-go@v6`,
  `actions/setup-python@v6`,
  `actions/upload-artifact@v7`,
  `github/codeql-action@v4`,
  `pypa/gh-action-pypi-publish@release/v1`.
- `uv run pytest tests/unit/test_docs/test_ci_workflow.py tests/unit/test_release_workflows.py -q` -> 22 passed.
- `uv run pytest tests/unit/test_docs/test_public_repo_contract.py tests/unit/test_docs/test_ci_workflow.py tests/unit/test_release_workflows.py -q` -> 53 passed.
- CI and pre-commit gitleaks enforcement verified by docs contract tests: pinned gitleaks install, safe synthetic-secret validation, and repo scan command are all asserted.
- `.gitleaks.toml` safe synthetic sentinel regex validated with Dockerized gitleaks v8.30.0 against a temporary fixture assembled from prefix `CES_GITLEAKS_SYNTHETIC_SECRET_` plus suffix `ABCDEF1234567890`; the scanner exited nonzero with one expected finding.
- `uv build` -> built `controlled_execution_system-0.1.30.tar.gz` and `controlled_execution_system-0.1.30-py3-none-any.whl`.
- `uv run --no-sync twine check dist/*` -> both artifacts passed.

Remaining risk:
- GitHub Action SHAs are pinned and documented, but maintainers must refresh them intentionally through normal dependency-review PRs.
- GitHub repository settings were applied through the GitHub API: branch protection now requires lint, typecheck, quality ratchets, dependency audit, secret scan, tests, latest dependency bounds, and CodeQL; secret scanning and push protection are enabled; `v*` release tags have an active tag ruleset blocking deletion/update; `pypi` and `testpypi` GitHub environments require reviewer approval. GitHub reports non-provider secret scanning and validity checks as disabled after a best-effort enable attempt, so coverage remains delegated to gitleaks plus provider scanning.
- PyPI and TestPyPI projects are reachable at version `0.1.30`, and repository workflows use OIDC trusted publishing with no stored PyPI repository secrets. Exact PyPI/TestPyPI trusted-publisher settings are not exposed through the current unauthenticated PyPI JSON API, so final confirmation still requires PyPI/TestPyPI project-owner UI/API access.

Next highest-priority item:
- Run the full requested validation suite against the final repository state and record the result below.

## Final Recommendation Classification

| Audit recommendation | Classification | Evidence | Remaining risk or follow-up |
|---|---|---|---|
| Stop passing runtime prompt packs in subprocess argv | Implemented | Runtime adapters pass prompt text through subprocess stdin; tests assert prompt body text is absent from `Popen` command arguments. | External Codex/Claude CLI behavior can change; runtime boundary docs now describe the contract. |
| Separate wizard execution consent from post-evidence approval | Implemented | Wizard flow no longer passes pre-run confirmation as post-evidence `--yes`; regression tests require a separate approval prompt. | None known. |
| Make completion-gate failures independent blockers | Implemented | Missing, malformed, failed, and valid completion-claim tests cover blocker behavior even when independent verification passes. | None known. |
| Preserve full runtime transcripts separately from capped excerpts | Implemented | Codex transcript path keeps full redacted output; CLI/SQLite receive capped excerpts; oversized-output tests cover the split. | Claude transcript semantics remain bounded by that adapter's available transcript source. |
| Enforce gitleaks in CI and pre-commit | Implemented | CI `secret-scan` job installs pinned gitleaks, validates a harmless synthetic sentinel, fetches full history, and scans repository history with `.gitleaks.toml`; pre-commit hook added. | Historical false-positive fixture commits are narrowly allowlisted and must be revisited on release checklist passes. |
| Strengthen `.gitignore` | Implemented | Env variants, local DBs, logs, keys, credentials, caches, and local artifacts are ignored while `.env.example` is preserved; git-ignore contract tests pass. | None known. |
| Expand redaction and security sensor patterns | Implemented | Redaction and sensor tests cover GitHub fine-grained tokens, GitLab tokens, JWTs, credential-bearing URLs, Google service-account JSON, private key material, and Slack variants. | Pattern-based controls remain defense in depth, not a guarantee for every future provider format. |
| Add `ces audit verify` | Implemented | Public `ces audit verify` command added with JSON support; audit-ledger tamper tests cover chain and HMAC-secret failures. | None known. |
| Add data-boundary documentation | Implemented | `docs/Data_Boundary.md`, `docs/Runtime_Adapter_Matrix.md`, and `SECURITY.md` document local state, runtime data flow, redaction, and env pass-through. | None known. |
| Document audit integrity | Implemented | `docs/Audit_Integrity.md` explains HMAC chain verification, `ces audit verify`, local key/state coupling, and tamper expectations. | None known. |
| Add onboarding docs and docs index by audience | Implemented | `docs/First_15_Minutes.md`, `docs/Docs_Index.md`, README nav updates, and docs contract tests. | None known. |
| Document runtime-boundary/auth variables | Implemented | Runtime adapter matrix and data-boundary docs explain Codex/Claude runtime distinction and allowed credential pass-through. | None known. |
| Add maintainer release checklist for branch protection, push protection, secret scanning, tag protection, and PyPI trusted publishing | Implemented | `docs/Public_Release_Checklist.md` records required external checks; GitHub branch protection, provider secret scanning, push protection, protected release tags, and reviewer-gated `pypi`/`testpypi` environments were applied/verified through the GitHub API. | Exact PyPI/TestPyPI trusted-publisher settings still require PyPI/TestPyPI project-owner UI/API confirmation. |
| Pin GitHub Actions to SHAs | Implemented | Repository workflows and generated GitHub CI template use full commit SHAs; docs tests reject unpinned workflow action refs. | Maintainers must refresh pins intentionally. |
| Reduce `run_cmd.py` high-risk coupling or refactor services | Implemented | Runtime normalization moved to `ces.execution.pipeline`; post-evidence approval decision extracted; completion-gate behavior fixed and tested. | A broader command-service split remains useful but is deferred to avoid churn beyond the audit's highest-risk coupling. |
| Centralize runtime execution normalization and scrubbing | Implemented | Shared normalization helper scrubs dict/object runtime outputs; tests cover sanitized stdout/stderr. | None known. |
| Reconcile mypy strict messaging with relaxed config | Implemented | Pre-commit hook and contributing guide describe the current compatibility profile and tightening path. | Future work should reduce relaxations module by module. |
| Bring omitted CLI modules under coverage or justify omissions | Implemented | `audit_cmd.py` returned under coverage through `ces audit verify`; remaining five omitted expert commands are named in `pyproject.toml` with 0.1.x follow-up rationale. | Remaining coverage work is explicitly documented. |
| Avoid source-tree fallback version drift | Implemented | Source-tree fallback reads `pyproject.toml`; tests cover installed metadata fallback and source-tree fallback. | None known. |
| Large-file security-scan behavior | Implemented | Security sensor reports an oversized-file skipped-warning blocker instead of silently skipping; tests cover the behavior. | None known. |
| Gitleaks allowlist review after enabling CI | Implemented | `.gitleaks.toml` now has a narrow CES synthetic sentinel rule, generated-cache path exclusions, and release-checklist allowlist review. | Allowlist should be reviewed on future fixture changes. |
| Brownfield scope confidence and workspace snapshot policy clarity | Already satisfied | Existing brownfield, workspace-delta, completion-verifier, recovery, and docs tests cover scope/project-root behavior; data-boundary docs clarify local state and artifacts. | More scenario tests may still be added as product workflows expand. |
| Runtime timeout artifact tests | Already satisfied | Existing runtime adapter and process tests cover timeout fallback, configured subprocess timeout, and actionable timeout diagnostics. | None known. |
| Docs link checker and quickstart golden-output tests | Already satisfied | Existing docs contract tests cover public links, Quickstart/Getting Started/First 15 Minutes command paths, and workflow docs. | A full external-link crawler is intentionally not added to avoid flaky network-dependent tests. |
| CLI command registry rewrite | Not applicable | The audit identified maintainability risk, but no current public-ready safety failure. | A declarative registry remains optional future cleanup. |
| Public repo docs/planning-file curation | Not applicable | Historical/planning docs are clearly separated in `docs/Docs_Index.md` rather than removed. | Maintainers can archive more aggressively before a marketing launch if desired. |
| Greenfield prompt-contract templates and beginner examples | Implemented | Existing starter manifest templates are retained; `docs/Product_Playbooks.md` adds prompt-contract, bad-prompt, and beginner proof-card guidance. | Golden prompt fixtures can be added when template output stabilizes further. |
| Brownfield change-type playbooks, source-of-truth selection, test selection, and monorepo docs | Implemented | `docs/Product_Playbooks.md`, `docs/Brownfield_Guide.md`, and README/Getting Started cover these workflows. | Example-repo tests remain a future expansion item. |
| Proof-card PR examples and CI/PR integration guidance | Implemented | `docs/Product_Playbooks.md` adds a PR proof-summary example; setup-ci templates and existing PR template support team workflow adoption. | GitHub comment snapshot tests remain future polish. |
| Branch protection, GitHub secret scanning, push protection, protected tags, and PyPI trusted-publishing settings | Partially implemented, partially blocked | GitHub API verification: required status checks now include lint, typecheck, quality-ratchets, audit, secret-scan, test, latest-dependency-bounds, and CodeQL `Analyze Python`; provider secret scanning and push protection are enabled; release tag ruleset `Protect release tags` blocks deletion/update of `v*`; `pypi` and `testpypi` environments require reviewer approval; repository has no PyPI secrets. PyPI and TestPyPI package JSON endpoints both report version `0.1.30`. | PyPI/TestPyPI trusted-publisher configuration is not exposed through the current unauthenticated PyPI JSON API; needs project-owner UI/API confirmation for exact publisher binding. |

## Final Validation

Final validation commands run after all source, test, workflow, docs, and ledger updates:

| Command | Result |
|---|---|
| `uv run ruff check src/ tests/` | Passed: all checks passed. |
| `uv run ruff format --check src/ tests/` | Passed after formatting `tests/unit/test_shared/test_secrets.py` and `tests/unit/test_docs/test_public_repo_contract.py`: 585 files already formatted. |
| `uv run mypy src/ces/ --ignore-missing-imports` | Passed: no issues in 272 source files. |
| `uv run pytest tests/ -m "not integration" --cov=ces --cov-fail-under=90 --cov-report=term-missing -q -W error` | Passed: 3168 passed, 319 deselected; total coverage 90.03%, coverage gate reached. |
| `uv run pytest tests/unit/test_execution/test_runtime_adapters.py tests/unit/test_execution/test_pipeline.py tests/unit/test_cli/test_wizard.py tests/unit/test_cli/test_run_cmd.py tests/unit/test_cli/test_audit_cmd.py tests/unit/test_services/test_audit_ledger.py tests/unit/test_shared/test_secrets.py tests/unit/test_sensors/test_security_sensor.py tests/unit/test_docs/test_ci_workflow.py tests/unit/test_docs/test_public_repo_contract.py tests/unit/test_docs/test_package_contract.py tests/unit/test_release_workflows.py -q` | Passed: 279 targeted runtime, transcript, approval-flow, audit-ledger, security, docs, and gitleaks-contract tests. |
| `rm -rf dist && uv build && uv run --no-sync twine check dist/*` | Passed: built `controlled_execution_system-0.1.30.tar.gz` and `controlled_execution_system-0.1.30-py3-none-any.whl`; twine metadata checks passed for both artifacts. |
| `git diff --check` | Passed: no whitespace errors. |
| Duplicate audit-artifact check | The earlier duplicate audit file is now a 5-line provenance alias pointing to the canonical 1010-line audit source; SHA-256 values differ, removing source-of-truth ambiguity. |
| Independent final review | Three subagent reviews completed: security/runtime PASS, maintainability PASS, CI/docs/audit-ledger initially found stale release-runbook blockers; `docs/RELEASE.md` and docs contract tests were corrected, and focused re-review returned PASS. |
| Dockerized gitleaks synthetic validation | Passed: v8.30.0 scanner detected the temporary fixture assembled from prefix `CES_GITLEAKS_SYNTHETIC_SECRET_` plus suffix `ABCDEF1234567890` and exited nonzero as expected. |
| Dockerized gitleaks worktree scan | Passed after ledger wording avoided committing the full synthetic sentinel literal: `docker run --rm -v "$PWD:/src" -w /src zricethezav/gitleaks:v8.30.0 detect --source . --config .gitleaks.toml --redact --no-git`. |
| Dockerized gitleaks full-history scan | Passed after narrowly allowlisting two historical false-positive fixture commits: `docker run --rm -v "$PWD:/src" -w /src zricethezav/gitleaks:v8.30.0 detect --source . --config .gitleaks.toml --redact`. |
| GitHub repository setting verification | Applied/verified through `gh api`: required branch checks include lint, typecheck, quality-ratchets, audit, secret-scan, test, latest-dependency-bounds, and CodeQL; secret scanning and push protection are enabled; `v*` tags are protected against deletion/update; `pypi` and `testpypi` environments require reviewer approval; repository PyPI secrets list is empty. |

Validation status: green for local lint, format, typecheck, test, build, package metadata, whitespace, Dockerized gitleaks synthetic/worktree/history scans, targeted security/docs/runtime contract tests, and GitHub repository setting verification. Only exact PyPI/TestPyPI trusted-publisher binding remains blocked pending project-owner UI/API confirmation.
