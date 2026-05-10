# CES MRI Codex Goal Prompt

Complete the first bounded “Production Autopilot” thin slice for CES by designing, implementing, documenting, and validating a new `ces mri` repository-diagnostic command without stopping until `ces mri --format markdown` and `ces mri --format json` work locally, have unit coverage, are documented, pass the relevant quality gates, and produce a clear project-health report with prioritized risks and next CES actions.

## Context and objective

CES should evolve from a governance CLI into a production-quality autopilot for vibe-coded and agent-built software. The first concrete, bounded feature is `ces mri`: a non-mutating project diagnostic command that scans the current or specified repository and reports whether the project looks like a prototype, shareable app, production candidate, or operated product. It should help users understand the biggest risks in an AI-built repo and what to do next.

## Inspect first, before editing

- `README.md`
- `CHANGELOG.md`
- `docs/Operator_Playbook.md`
- `docs/Verification_Profile.md`
- `docs/Quick_Reference_Card.md`
- existing CLI structure under `src/ces/cli/`
- existing verification/project-detection code under `src/ces/verification/`
- existing sensor/orchestration patterns under `src/ces/harness/`
- existing tests under `tests/unit/test_cli/`, `tests/unit/test_docs/`, and any nearby verification/project detector tests
- `.ces/verification-profile.json`
- `.github/workflows/ci.yml`
- recent git history for the last 10 commits

## One clear objective

Implement a minimal, maintainable `ces mri` command that performs a read-only repository scan and emits a useful “Project MRI” report in both markdown and JSON.

## Functional requirements

- Add a CLI command named `ces mri`.
- Support `--project-root PATH`, defaulting to the current working directory.
- Support `--format markdown` and `--format json`; markdown should be the default.
- The command must not mutate the target project.
- The command must classify the project into one clear maturity/status label, for example:
  - `vibe-prototype`
  - `local-app`
  - `shareable-app`
  - `production-candidate`
  - `production-ready`
  Use simple deterministic heuristics, not LLM calls.
- The scan should detect and report at least:
  - project type signals, e.g. Python package, Node package, containerized app, unknown
  - test signals, e.g. pytest config/dependency, tests directory, test files
  - lint/typecheck signals, e.g. ruff, mypy, eslint, typescript config where easy to detect
  - CI signals, e.g. GitHub Actions workflows
  - dependency/package files, e.g. `pyproject.toml`, `uv.lock`, `package.json`, lockfiles
  - deployment/runtime files, e.g. container file, compose file, Procfile, deploy configs
  - secret hygiene risks, e.g. `.env` tracked/present, likely secret filenames, obvious key/token-looking variable names in config files; do not print secret values
  - maintainability risks, e.g. very large source files, TODO/FIXME counts, missing README
  - CES-specific signals, e.g. `.ces/verification-profile.json`, `.ces/config.yaml`, `.ces/state.db`
- The report must include:
  - summary
  - detected project signals
  - strongest evidence
  - risk findings ordered by severity
  - missing production-readiness signals
  - recommended next CES actions, such as `ces profile detect --write`, `ces doctor`, `ces build`, `ces verify`, or future placeholder actions clearly marked as not-yet-implemented if needed
- JSON output must be deterministic and machine-readable.
- Markdown output must be concise and readable in a terminal or PR comment.
- Missing files or unknown project types should degrade gracefully, not crash.

## Stopping condition

Stop only when all of these are true:

1. `ces mri --format markdown` works on the CES repo.
2. `ces mri --format json` works on the CES repo and returns valid JSON.
3. `ces mri --project-root <temporary test repo> --format markdown` works on a small synthetic repo.
4. Unit tests cover markdown mode, JSON mode, `--project-root`, non-mutating behavior, and at least three risk/signal detections.
5. Relevant docs mention the command in the appropriate user-facing places.
6. The relevant validation commands pass locally:
   - focused unit tests for the new command and any detector logic
   - `uv run ruff check` on changed Python files/tests
   - `uv run ruff format --check` on changed Python files/tests
   - `uv run mypy` on changed source files or the relevant `src/ces` package scope if practical
   - any package/docs contract tests affected by README/docs changes
7. A short progress log exists describing checkpoints, changed files, validations, remaining risks, and follow-up ideas.

## Checkpoint-based work

Work in checkpoints and validate after each meaningful checkpoint:

- Checkpoint 1: inspect context and write a short implementation note before editing.
- Checkpoint 2: design the data model/report shape and add focused tests or test skeletons.
- Checkpoint 3: implement the scanner and CLI command with minimal scoped changes.
- Checkpoint 4: update docs and examples.
- Checkpoint 5: run validations, fix failures, and produce the final progress log.

## Progress log requirement

Create or update `docs/plans/CES_MRI_Progress_Log.md` with:

- objective
- files inspected
- checkpoint summaries
- changed files
- commands run
- validation results
- known limitations
- risks and follow-up work

## Constraints and things not to change

- Do not tag, publish, release, bump versions, or modify PyPI/GitHub release workflows.
- Do not make network calls.
- Do not add hosted services or external dependencies unless absolutely necessary; prefer the Python standard library and existing dependencies.
- Do not change existing public CLI behavior, command names, schemas, local-store migrations, evidence schemas, verification-profile schema, or approval semantics unless directly required for `ces mri`.
- Do not rewrite broad CLI architecture.
- Do not alter frontend dependencies or introduce a UI.
- Do not mutate `.ces/` project state from `ces mri`.
- Do not print secret values.
- Do not commit generated caches, virtualenvs, build artifacts, coverage files, or local dogfood output.
- Preserve existing public contracts and backwards compatibility.

## Engineering guidance

Prefer simple, deterministic, maintainable heuristics over clever scoring. Keep functions small, typed, and testable. Reuse existing project/verification detection patterns where appropriate, but avoid coupling the MRI command to approval gates. Make minimal, scoped changes. If you find a tempting larger roadmap idea, record it as follow-up in the progress log instead of implementing it.

Keep working until the stopping condition is reached unless blocked by missing information, failing credentials, destructive-risk changes, or a product decision that cannot be made safely from the existing context. At the end, document exactly what changed, what was validated, what remains, and any risks.
