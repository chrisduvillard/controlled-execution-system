# ReleasePulse Re-Dogfood Finding — Runtime Timeout Recovery

Date: 2026-05-04
Wave: ReleasePulse final re-dogfood gate after PR E-H merge
Finding ID: `RP-CES-008`
Severity: High
Status: Fix implemented in branch `fix/releasepulse-runtime-timeout-recovery`

## Summary

A fresh greenfield CES run using Codex could remain in `running` / `in_flight` indefinitely when the runtime subprocess did not return. CES invoked the runtime through `subprocess.run(...)` without a timeout, so a stuck Codex process left users with no bounded failure, no automatic recovery transition, and no clear retry path.

## Reproduction

Target project:

```text
/tmp/ces-releasepulse-redogfood-20260504-141737
```

Command:

```bash
uv run ces build \
  --project-root /tmp/ces-releasepulse-redogfood-20260504-141737 \
  --runtime codex \
  --greenfield \
  --yes \
  --accept-runtime-side-effects \
  --gsd "Build a tiny Python CLI named releasepulse ..." \
  --acceptance "Running pytest passes." \
  --acceptance "python -m releasepulse ping prints pong and exits 0." \
  --acceptance "python -m releasepulse unknown exits non-zero and prints a helpful unknown command error." \
  --constraint "Use only local files in the target project." \
  --constraint "Keep the implementation small and dependency-light." \
  --must-not-break "The README remains present." \
  --full
```

Observed after more than 10 minutes:

- CES process still running.
- Runtime transcript file existed but was empty.
- Target project contained only seed files plus `.ces/` state; no product files had been created.
- `ces status --project-root ... --json` showed:
  - `builder_run.stage == "running"`
  - `builder_run.review_state == "in_flight"`
  - `builder_run.latest_outcome == "manifest_ready"`
  - `builder_run.next_step == "Review the evidence and decide whether to ship the change."`
- That next-step text was misleading because there was no evidence to review while the runtime was still stuck.

## Root Cause

`CodexRuntimeAdapter.run_task()` and `ClaudeRuntimeAdapter.run_task()` called `subprocess.run(...)` without a timeout. If the CLI runtime hung, CES had no fail-closed runtime result and could not transition the builder session into a bounded blocked/retry state.

Relevant file:

```text
src/ces/execution/runtimes/adapters.py
```

## Fix

Implemented a bounded runtime timeout for local CLI adapters:

- Added `CES_RUNTIME_TIMEOUT_SECONDS` override.
- Added default runtime timeout of 1800 seconds.
- Added timeout handling for Codex and Claude adapters.
- On timeout, adapters return exit code `124` with actionable stderr instead of hanging indefinitely.
- Existing runtime failure handling then stores diagnostics and moves builder status to a retryable blocked state.

Regression tests:

```text
tests/unit/test_execution/test_runtime_adapters.py::TestRuntimeAdapterEnvScrubbing::test_runtime_adapters_pass_configured_timeout_to_subprocess
tests/unit/test_execution/test_runtime_adapters.py::TestRuntimeAdapterEnvScrubbing::test_codex_runtime_timeout_returns_actionable_failure
```

## Verification

RED:

```bash
uv run pytest \
  tests/unit/test_execution/test_runtime_adapters.py::TestRuntimeAdapterEnvScrubbing::test_runtime_adapters_pass_configured_timeout_to_subprocess \
  tests/unit/test_execution/test_runtime_adapters.py::TestRuntimeAdapterEnvScrubbing::test_codex_runtime_timeout_returns_actionable_failure \
  -q
```

Observed: `2 failed` because no timeout was passed to `subprocess.run(...)` and timeout exceptions were not handled.

GREEN:

```bash
uv run pytest \
  tests/unit/test_execution/test_runtime_adapters.py::TestRuntimeAdapterEnvScrubbing::test_runtime_adapters_pass_configured_timeout_to_subprocess \
  tests/unit/test_execution/test_runtime_adapters.py::TestRuntimeAdapterEnvScrubbing::test_codex_runtime_timeout_returns_actionable_failure \
  -q
```

Observed: `2 passed`.

Live timeout smoke:

```bash
CES_RUNTIME_TIMEOUT_SECONDS=3 uv run ces build \
  --project-root /tmp/ces-runtime-timeout-smoke-20260504-143132 \
  --runtime codex \
  --greenfield \
  --yes \
  --accept-runtime-side-effects \
  --gsd "Build a tiny CLI that intentionally can be interrupted for timeout smoke." \
  --acceptance "README remains present." \
  --constraint "Keep it tiny." \
  --must-not-break "README remains present." \
  --brief
```

Observed:

- CLI exited with code `2` after runtime timeout handling rather than hanging.
- Runtime panel showed `Exit code: 124`.
- Diagnostics path was emitted under `.ces/runtime-diagnostics/`.
- `ces status --project-root ... --json` showed:
  - `builder_run.stage == "blocked"`
  - `builder_run.latest_outcome == "runtime_failed"`
  - `builder_run.next_step == "Retry the last runtime execution with `ces continue`."`

## Follow-up Risk

The original full greenfield build was interrupted manually after the unbounded runtime hang. After this fix, a longer real re-dogfood should be rerun with the default timeout to determine whether Codex eventually completes the product or whether a separate prompt/runtime invocation issue remains.
