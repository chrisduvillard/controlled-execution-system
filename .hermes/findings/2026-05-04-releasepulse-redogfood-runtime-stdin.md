# RP-CES-009 — Runtime adapter inherits stdin and blocks Codex exec

- **Wave:** ReleasePulse final re-dogfood after PR #18 merge
- **Severity:** High
- **Status:** Fix implemented in branch `fix/releasepulse-runtime-stdin-devnull`
- **Area:** Runtime execution / recovery / non-interactive CLI reliability

## Summary

After PR #18 bounded runtime execution, a fresh greenfield re-dogfood run no longer hung indefinitely. Instead it reliably timed out with actionable diagnostics. The timeout exposed a second runtime-boundary bug: the Codex CLI was still trying to read inherited stdin even though CES passed the prompt as an argument.

When CES is run from a shell pipeline or background process, the runtime adapter should not let child runtimes inherit the parent stdin. Codex detects piped/inherited stdin and appends it as additional input, printing `Reading additional input from stdin...`; in the observed dogfood run, that read never completed and the task only recovered because PR #18's timeout fired.

## Reproduction

Target:

```text
/tmp/ces-releasepulse-redogfood-after-pr18-20260504-144426
```

Command shape:

```bash
CES_RUNTIME_TIMEOUT_SECONDS=300 uv run ces build \
  --project-root "$TARGET" \
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
  --full 2>&1 | tee "$LOG"
```

## Observed behavior

- CES reached runtime execution and then timed out after 300 seconds.
- Diagnostics were correctly written by the PR #18 timeout path.
- Runtime stderr included:

```text
Reading additional input from stdin...

codex runtime timed out after 300 seconds. The run was stopped so CES can recover instead of hanging indefinitely; inspect the runtime transcript, then retry with `ces continue` or set CES_RUNTIME_TIMEOUT_SECONDS to a larger positive value if this task legitimately needs more time.
```

- `ces status --json` showed the run was now bounded and retryable rather than indefinitely running:
  - `stage=blocked`
  - `review_state=in_flight`
  - `latest_outcome=runtime_failed`
  - `next_step=Retry the last runtime execution with `ces continue`.`
- Retrying with `ces continue` reproduced the same stdin-read symptom until the process was killed during investigation.

Evidence paths:

```text
/tmp/ces-redogfood-after-pr18-20260504-144426.log
/tmp/ces-redogfood-after-pr18-continue-20260504-144955.log
/tmp/ces-releasepulse-redogfood-after-pr18-20260504-144426/.ces/runtime-diagnostics/M-7617349ed3b1-codex-219be256fb27.txt
/tmp/ces-releasepulse-redogfood-after-pr18-20260504-144426/.ces/runtime-transcripts/codex-219be256fb27-jl5udvqj.txt
```

The runtime transcript was empty.

## Expected behavior

CES should invoke non-interactive local runtimes with closed stdin when the prompt is already supplied via command arguments/options. Child runtime CLIs should not read from the operator's terminal, Hermes process, pipeline, or background process stdin.

## Why this matters

PR #18 made this failure recoverable, but users would still hit a guaranteed 30-minute delay by default in common non-interactive executions. For real 0→100 greenfield projects, that feels like CES is stuck and undermines the recovery guarantee.

## Root cause

`CodexRuntimeAdapter` and `ClaudeRuntimeAdapter` called `subprocess.run(...)` without specifying `stdin`. The child process inherited CES's stdin. Codex treats available stdin as additional prompt input even when a prompt argument is provided.

Codex help confirms the behavior:

```text
If stdin is piped and a prompt is also provided, stdin is appended as a <stdin> block
```

## Fix

Pass `stdin=subprocess.DEVNULL` to local runtime subprocess invocations so non-interactive adapters do not inherit parent stdin.

Applied to:

- `CodexRuntimeAdapter.run_task(...)`
- `ClaudeRuntimeAdapter.run_task(...)`

## Regression coverage

Added unit regression:

```text
tests/unit/test_execution/test_runtime_adapters.py::TestRuntimeAdapterEnvScrubbing::test_runtime_adapters_do_not_inherit_stdin
```

It failed before the fix with `KeyError: 'stdin'` and passes after the fix.

## Post-fix live validation

Fresh target:

```text
/tmp/ces-releasepulse-redogfood-after-stdin-fix-20260504-145642
```

Command shape:

```bash
CES_RUNTIME_TIMEOUT_SECONDS=600 .venv/bin/ces build \
  --project-root "$TARGET" \
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
  --full 2>&1 | tee "$LOG"
```

Observed after the fix:

- CES completed the greenfield build with exit code 0.
- Build review outcome was `ready to ship`.
- `ces status --project-root "$TARGET" --json` reported:
  - `stage=completed`
  - `review_state=approved`
  - `latest_outcome=approved`
- No `Reading additional input from stdin...` symptom appeared in the build log or runtime diagnostics.
- Independent product verification passed:
  - `python -m pytest -q` → `2 passed`
  - `python -m releasepulse ping` → `pong`, exit 0
  - `python -m releasepulse unknown` → exit 1, `Unknown command: unknown. Expected: ping`

## Follow-ups

- Continue ReleasePulse dogfood through a brownfield improvement pass after this PR lands.
- Consider surfacing the timed-out runtime's stderr hint more prominently in `ces why` if `Reading additional input from stdin...` appears in diagnostics.
