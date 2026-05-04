# RP-CES-010 — Approved builder status keeps stale red diagnostics active

- **Wave:** ReleasePulse greenfield → brownfield re-dogfood after PR #19 merge
- **Severity:** Medium
- **Status:** Fix implemented in branch `fix/releasepulse-approved-status-diagnostics`
- **Area:** Builder status/report diagnostics

## Summary

After PR #19, a full greenfield build and brownfield improvement both completed successfully with Codex. The brownfield product was approved and independently verified, but `ces status --json` still reported stale red diagnostics as if they were active blockers.

This did not block the run because `ces why` correctly said there was no active blocker. However, machine consumers and operators reading JSON saw contradictory fields:

- `stage=completed`
- `review_state=approved`
- `latest_outcome=approved`
- `independent_verification_passed=true`
- but also `triage_color=red`
- `evidence_quality_state=failed`
- active `verification_findings` containing expected-negative command and missing-artifact diagnostics

## Reproduction

Target:

```text
/tmp/ces-releasepulse-redogfood-after-stdin-fix-20260504-145642
```

Brownfield build command shape:

```bash
CES_RUNTIME_TIMEOUT_SECONDS=600 /home/chris/.Hermes/workspace/controlled-execution-system/.venv/bin/ces build \
  "Improve the existing releasepulse CLI by adding a version command ..." \
  --runtime codex \
  --brownfield \
  --yes \
  --accept-runtime-side-effects \
  --source-of-truth "Existing releasepulse CLI package, tests, pyproject.toml, README, and reviewed legacy behavior OLB-286cfea2fdb3 must be preserved unless explicitly changed." \
  --critical-flow "python -m releasepulse ping prints pong and exits 0." \
  --critical-flow "python -m releasepulse unknown exits non-zero and prints a helpful unknown command error." \
  --acceptance "Running pytest passes." \
  --acceptance "python -m releasepulse version prints 0.1.0 and exits 0." \
  --acceptance "python -m releasepulse ping still prints pong and exits 0." \
  --acceptance "python -m releasepulse unknown still exits non-zero with a helpful unknown command error." \
  --constraint "Keep the implementation small and dependency-light." \
  --must-not-break "The README remains present." \
  --full
```

## Observed before fix

`ces status --project-root "$TARGET" --json` reported:

```text
project_mode=brownfield
stage=completed
review_state=approved
latest_outcome=approved
workflow_state=merged
triage_color=red
evidence_quality_state=failed
independent_verification_passed=True
verification_findings=[...]
```

Findings included:

```text
Verification command failed with exit code 1: python -m releasepulse unknown
[test_pass] Required verification artifact is missing: pytest-results.json @ pytest-results.json
[lint] Required verification artifact is missing: ruff-report.json @ ruff-report.json
[typecheck] Required verification artifact is missing: mypy-report.txt @ mypy-report.txt
[coverage] Required coverage artifact is missing: coverage.json @ coverage.json
```

Independent product verification still passed:

```text
python -m pytest -q                     # 3 passed
python -m releasepulse version          # 0.1.0, exit 0
python -m releasepulse ping             # pong, exit 0
python -m releasepulse unknown          # exit 1, helpful error
```

## Expected behavior

When a builder run is approved and independent verification passed, old runtime/gate diagnostics should not remain active red blockers in status/report JSON. They should move to `superseded_verification_findings` for auditability, while current active fields reflect the approved state.

## Fix

`build_builder_run_report(...)` now treats `approval_decision == "approved"` plus `independent_verification_passed is True` as authoritative for operator-facing current status:

- `verification_findings=()`
- old current `verification_result` findings are retained under `superseded_verification_findings`
- `triage_color="green"`
- `evidence_quality_state="passed"`

This preserves the audit trail without presenting stale red diagnostics as current blockers.

## Regression coverage

Added:

```text
tests/unit/test_cli/test_builder_report_cmd.py::test_approved_builder_report_demotes_stale_runtime_findings_when_independent_verification_passed
```

RED result before fix:

```text
AssertionError: assert 'red' == 'green'
```

GREEN result after fix:

```text
1 passed
```

## Post-fix live validation

Against the same brownfield target, `ces status --project-root "$TARGET" --json` now reports:

```text
project_mode=brownfield
stage=completed
review_state=approved
latest_outcome=approved
workflow_state=merged
triage_color=green
evidence_quality_state=passed
independent_verification_passed=True
active verification_findings=[]
superseded_verification_findings count=5
```

Human `ces status` remains clean and `ces why` reports:

```text
No active blocker; the latest builder run is approved.
Product may be complete: True
```
