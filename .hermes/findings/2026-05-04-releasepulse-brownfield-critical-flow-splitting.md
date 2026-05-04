# RP-CES-013 — Brownfield critical-flow review splits comma-rich workflows into bogus behaviors

- **Wave:** ReleasePulse post-PR21 greenfield → brownfield dogfood
- **Severity:** Medium
- **Status:** Fix implemented in branch `fix/releasepulse-brownfield-report-entry-count`
- **Area:** Brownfield review UX / behavior inventory fidelity

## Reproduction

After PR #21 was merged, a fresh ReleasePulse greenfield build was approved/green. The deferred brownfield wave then ran:

```bash
CES_RUNTIME_TIMEOUT_SECONDS=600 /home/chris/.Hermes/workspace/controlled-execution-system/.venv/bin/ces build \
  "Improve the existing releasepulse CLI by adding a version command that prints 0.1.0." \
  --runtime codex \
  --brownfield \
  --yes \
  --accept-runtime-side-effects \
  --source-of-truth "Existing releasepulse CLI package, tests, pyproject.toml, README, and reviewed legacy behavior OLB-095836dc0cab must be preserved unless explicitly changed." \
  --critical-flow "python -m releasepulse ping prints pong and exits 0." \
  --critical-flow "python -m releasepulse summary sample_changelog.txt prints markdown containing Launch, Fixes, and Docs and exits 0." \
  --critical-flow "python -m releasepulse unknown exits non-zero and prints a helpful unknown command error." \
  --acceptance "Running pytest passes." \
  --acceptance "python -m releasepulse version prints 0.1.0 and exits 0." \
  --acceptance "python -m releasepulse ping still prints pong and exits 0." \
  --acceptance "python -m releasepulse summary sample_changelog.txt still prints markdown containing Launch, Fixes, and Docs and exits 0." \
  --acceptance "python -m releasepulse unknown still exits non-zero with a helpful unknown command error." \
  --constraint "Keep the implementation small and dependency-light." \
  --must-not-break "The README remains present." \
  --full
```

Target:

```text
/tmp/ces-releasepulse-post-pr21-greenfield-20260504-155241
```

The product and CES governance completed green:

```text
pytest: 4 passed
python -m releasepulse version: 0.1.0, exit 0
python -m releasepulse ping: pong, exit 0
python -m releasepulse summary sample_changelog.txt: Launch/Fixes/Docs markdown, exit 0
python -m releasepulse unknown: exit 1, helpful error
ces status: stage=completed, review_state=approved, triage_color=green, verification_findings=[]
```

However, the brownfield review inventory contained bogus behavior entries created by splitting a single comma-rich critical flow:

```text
Critical flow remains intact: python -m releasepulse summary sample_changelog.txt prints markdown containing Launch
Critical flow remains intact: Fixes
Critical flow remains intact: and Docs and exits 0.
```

`ces report builder` then reported:

```text
Brownfield progress: 9 behaviors reviewed, 0 behaviors remaining
```

That was technically consistent with the polluted inventory, but operator-hostile: the user supplied three repeated `--critical-flow` values, not separate behaviors named `Fixes` or `and Docs and exits 0.`.

## Expected Behavior

Repeated `--critical-flow` values should be treated as atomic workflow descriptions, even when a workflow contains commas. Semicolons can remain the compact inline separator for prompt-mode multi-entry text.

## Root Cause

`_split_flows(...)` normalized newlines to commas and split on every comma. This corrupted command-line `--critical-flow` values because the CLI joins repeated options with newlines before parsing.

## Fix

- Updated `_split_flows(...)` to preserve newline-delimited values as atomic items, matching `_split_list(...)` behavior for acceptance criteria.
- Kept semicolons as the compact inline separator.
- Added regression coverage for comma-rich `--critical-flow` options.
- Added defensive report-count coverage for persisted snapshots where entry IDs are available only in checkpoint state.

## Validation

RED:

```bash
uv run pytest tests/unit/test_builder_flow.py::TestUnattendedBrief::test_collect_brief_preserves_comma_rich_critical_flow_options -q
# failed: comma-rich flow split into Launch / Fixes / Docs fragments
```

GREEN:

```bash
uv run pytest \
  tests/unit/test_builder_flow.py::TestUnattendedBrief::test_collect_brief_preserves_comma_rich_critical_flow_options \
  tests/unit/test_cli/test_builder_report_cmd.py::test_builder_report_uses_checkpoint_entry_ids_when_snapshot_entry_ids_are_empty \
  -q
# 2 passed
```

## Impact

Medium severity. The runtime/product succeeded, recovery was not blocked, and CES status was green. But the brownfield behavior inventory became noisy and misleading, which weakens trust in brownfield preservation review and can confuse real operators during 0→100→improve workflows.
