# Codex Scratch Project E2E

These smoke tests create external testing projects and drive CES through the
local-first builder path as a user would. They do not add scratch projects to
the CES package or require Postgres, Redis, or a hosted control plane.

## Fresh-Project Codex Run

Run from the CES checkout:

```bash
uv run python scripts/run_codex_scratch_e2e.py --runtime codex
```

The default mode uses the installed `codex` CLI twice:

- to answer every CES interactive prompt non-interactively from the current
  project/request context;
- to execute the governed builder task through CES's normal `codex` runtime
  adapter.

The harness creates a temporary git repo under `/tmp`, initializes `.ces/`
with `ces init`, plants a tiny Python app with a failing pytest, runs
interactive `ces build`, then checks `ces status`, `ces explain`,
`ces report builder`, target-project `git diff`, and final pytest output.

## Brownfield Codex Run

Run the two-task brownfield proof from the CES checkout:

```bash
uv run python scripts/run_codex_brownfield_e2e.py --runtime codex
```

The brownfield harness creates a fresh external repo, runs an initial governed
calculator fix through CES, commits that accepted baseline inside the scratch
repo, then runs a second governed brownfield task on the same existing project.
The second task adds `subtract`, `multiply`, and `divide`, preserves `add`, adds
pytest coverage, and verifies direct calculator use.

The summary records separate `baseline_manifest_id` and `brownfield_manifest_id`
values from the corresponding build command outputs. Post-merge `ces review`
and `ces approve` are also probed: they should refuse to reopen a merged
manifest and direct users to `ces report builder`, `ces status`, and `ces audit`.

## Fallback CI Run

Use fallback mode where real Codex is unavailable:

```bash
uv run python scripts/run_codex_scratch_e2e.py --mode fallback --runtime codex
uv run python scripts/run_codex_brownfield_e2e.py --mode fallback --runtime codex
```

Fallback mode still runs the CES CLI as subprocesses against an external scratch
project. It uses deterministic prompt answers and prepends a tiny fake `codex`
executable to `PATH` so CI can validate harness mechanics without network or
model access.

## Evidence

Each run writes an evidence directory, printed at the end. Fresh-project runs
include:

- `command-transcript.txt`
- `codex-prompt-answers.jsonl`
- `target-project.diff`
- `scratch-test-output.txt`
- `builder-report/`
- `summary.json`

Brownfield runs include the same files plus:

- `direct-calculator-smoke.txt`
- `baseline_manifest_id` and `brownfield_manifest_id` in `summary.json`
- post-merge review/approve return codes in `summary.json`

On failure, the scratch project is preserved and its path is printed. On pass,
temporary scratch projects are cleaned by default; pass `--keep` to preserve
the project for inspection. Evidence is not removed by cleanup.

Direct module smoke uses `PYTHONPATH=src` because `pyproject.toml` pytest
configuration applies to pytest, not plain `python -c` imports.

Useful overrides:

```bash
uv run python scripts/run_codex_scratch_e2e.py \
  --runtime codex \
  --project-dir /tmp/my-ces-scratch-project \
  --evidence-dir /tmp/my-ces-scratch-evidence \
  --keep
```

The brownfield script accepts the same overrides.
