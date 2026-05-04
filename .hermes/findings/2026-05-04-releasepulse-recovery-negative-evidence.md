# RP-CES-011 / RP-CES-012 — Greenfield recovery blocked despite complete product

- **Wave:** ReleasePulse post-PR20 fresh greenfield dogfood
- **Severity:** High
- **Status:** Fix implemented in branch `dogfood/releasepulse-post-pr20-redogfood`
- **Area:** Completion verification and self-recovery

## Summary

A fresh ReleasePulse greenfield build completed product implementation successfully, but CES held the run as blocked/rejected. Independent product verification passed, but self-recovery initially could not complete the run.

Two root causes appeared together:

1. **RP-CES-011:** CompletionVerifier treated any non-zero verification command evidence as failure, even when the command was explicitly the expected-negative acceptance check (`python -m releasepulse unknown exits non-zero ...`).
2. **RP-CES-012:** `ces recover --auto-evidence --auto-complete` trusted the pre-runtime completion contract. The contract was written before product files existed, so it had `project_type="unknown"` and `inferred_commands=[]`; recovery ran zero commands and failed.

For a real user, this is a halfway-failure concern: the product was complete, but the builder state was blocked and the advertised recovery command did not recover it.

## Reproduction

CES baseline:

```text
f0d2fe0 Merge pull request #20 from chrisduvillard/fix/releasepulse-approved-status-diagnostics
```

Target:

```text
/tmp/ces-releasepulse-post-pr20-greenfield-20260504-152613
```

Command shape:

```bash
CES_RUNTIME_TIMEOUT_SECONDS=600 /home/chris/.Hermes/workspace/controlled-execution-system/.venv/bin/ces build \
  "Build ReleasePulse, a dependency-light Python CLI package for release readiness notes ..." \
  --runtime codex \
  --greenfield \
  --yes \
  --accept-runtime-side-effects \
  --acceptance "Running pytest passes." \
  --acceptance "python -m releasepulse ping prints pong and exits 0." \
  --acceptance "python -m releasepulse summary --title Launch --change Fixes --change Docs prints markdown containing Launch, Fixes, and Docs." \
  --acceptance "python -m releasepulse unknown exits non-zero with a helpful unknown command error." \
  --constraint "Use only the Python standard library unless packaging/test tooling already requires otherwise." \
  --constraint "Do not require network access at runtime." \
  --full
```

## Observed before fix

Build exited `0` but reported:

```text
Outcome: held for another pass
Blocking reasons:
- completion evidence failed verification: Verification command failed with exit code 2: python -m releasepulse unknown
- missing pytest-results.json / ruff-report.json / mypy-report.txt / coverage.json
Next: ces why
Next: ces recover --dry-run
```

`ces status --json`:

```text
project_mode=greenfield
stage=blocked
review_state=rejected
latest_outcome=rejected
workflow_state=rejected
triage_color=red
evidence_quality_state=missing_artifacts
verification_findings=[...]
```

Independent product verification passed:

```bash
python -m pytest -q
# 3 passed
python -m releasepulse ping
# pong, exit 0
python -m releasepulse summary --title Launch --change Fixes --change Docs
# markdown with Launch, Fixes, Docs; exit 0
python -m releasepulse unknown
# exit 2; stderr: releasepulse: error: unknown command: unknown
```

The completion claim correctly disclosed the expected-negative command:

```json
{
  "command": "python -m releasepulse unknown",
  "exit_code": 2,
  "summary": "Exited non-zero and printed 'releasepulse: error: unknown command: unknown'."
}
```

But verifier interpreted it as failure.

Then recovery failed:

```bash
ces recover --auto-evidence --auto-complete
```

Output before fix:

```text
Recovered Verification
# no command rows
Passed: False
Completed: False
Independent verification failed; builder session remains blocked.
```

The saved contract explained why:

```json
{
  "project_type": "unknown",
  "inferred_commands": []
}
```

## Expected behavior

- A non-zero verification command should be accepted when it is evidence for an acceptance criterion that explicitly expects non-zero/error behavior.
- Recovery should not get stuck on an empty pre-runtime contract after generated product files exist; it should refresh/re-infer independent verification commands from the current project tree.

## Fix

### RP-CES-011

`CompletionVerifier` now recognizes expected-negative verification command evidence when:

- command exit code is non-zero,
- the command appears in satisfied criterion/evidence text,
- the criterion/evidence/summary contains a negative-exit marker such as `non-zero`, `nonzero`, `should fail`, or expected error phrasing.

Unexpected non-zero commands still fail.

### RP-CES-012

`run_auto_evidence_recovery(...)` now refreshes a completion contract when it has no inferred commands. It rebuilds the contract against the current project tree while preserving the request, acceptance criteria, runtime name, and runtime metadata.

`detect_project_type(...)` now recognizes simple Python projects without `pyproject.toml` when tests or Python package/module files exist, allowing recovery to infer:

```text
python -m pytest -q
python -m compileall tests
```

## Regression coverage

RED before fix:

```bash
uv run pytest tests/unit/test_services/test_completion_verifier.py::TestVerifierSchemaChecks::test_expected_nonzero_command_evidence_satisfies_negative_criterion -q --tb=short
# AssertionError: assert False is True

uv run pytest tests/unit/test_recovery/test_recovery_executor.py::test_auto_evidence_refreshes_stale_empty_contract_after_greenfield_files_exist tests/unit/test_verification/test_project_detector.py::test_detects_python_package_from_tests_without_pyproject -q --tb=short
# recovery verification passed=False with commands=(); project detector returned 'unknown'
```

GREEN after fix:

```bash
uv run pytest \
  tests/unit/test_services/test_completion_verifier.py::TestVerifierSchemaChecks::test_expected_nonzero_command_evidence_satisfies_negative_criterion \
  tests/unit/test_services/test_completion_verifier.py::TestVerifierSchemaChecks::test_unexpected_nonzero_command_evidence_still_fails \
  tests/unit/test_recovery/test_recovery_executor.py::test_auto_evidence_refreshes_stale_empty_contract_after_greenfield_files_exist \
  tests/unit/test_verification/test_project_detector.py::test_detects_python_package_from_tests_without_pyproject -q
# 4 passed
```

## Live post-fix validation

Against the same blocked target:

```bash
ces recover --auto-evidence --auto-complete
```

Output after fix:

```text
Recovered Verification
python -m pytest -q        Exit 0 PASS
python -m compileall tests Exit 0 PASS
Self-Recovery Complete
Passed: True
Completed: True
Evidence packet: EP-recovery-34d3bcc729cd
Next: start_new_session
```

Post-recovery status:

```text
project_mode=greenfield
stage=completed
review_state=approved
latest_outcome=approved
workflow_state=approved
triage_color=green
evidence_quality_state=passed
independent_verification_passed=True
active verification_findings=[]
superseded_verification_findings count=5
```

`ces why`:

```text
No active blocker; the latest builder run is approved.
Product may be complete: True
```

## Follow-up

Brownfield continuation was intentionally deferred until this recovery blocker lands, because a user-facing greenfield blocked/recovery-failed state is more severe than proceeding to the next wave on an unmerged fix.
