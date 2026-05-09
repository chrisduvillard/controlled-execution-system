# Verification profiles

Verification profiles let CES adapt its completion gates to the project it is governing while keeping the approval boundary explicit.

A profile lives at:

```text
.ces/verification-profile.json
```

It tells CES which verification artifacts are **required**, which are **optional/advisory**, and which tools are **unavailable** for the current project. This prevents a small project from being blocked by missing checks it does not use, without letting an agent silently downgrade real project requirements.

## When to use a profile

Use a verification profile when a repository has a known verification shape:

- Python package with `pytest`, `ruff`, and `mypy` configured.
- Small script project with linting but no test framework yet.
- Brownfield repository where coverage exists but should be advisory during adoption.
- Generated or throwaway project where only a subset of checks is meaningful.

If no profile exists, CES keeps the legacy strict behavior. Existing completion-gate expectations continue to apply for backward compatibility.

## Quick start

From the project root:

```bash
# Preview inferred checks without writing anything.
ces profile detect

# Persist the profile.
ces profile detect --write

# Show the saved profile.
ces profile show

# Explain required versus non-blocking checks.
ces profile doctor
```

`ces profile detect` is intentionally non-mutating unless `--write` is passed. The command prints `(not written; use --write to persist)` so operators can distinguish discovery from policy changes.

## Profile format

A profile is JSON with a version and one entry per known verification check:

```json
{
  "version": 1,
  "checks": {
    "pytest": {
      "status": "required",
      "configured": true,
      "reason": "pytest configuration detected"
    },
    "ruff": {
      "status": "required",
      "configured": true,
      "reason": "ruff configuration detected"
    },
    "mypy": {
      "status": "required",
      "configured": true,
      "reason": "mypy configuration detected"
    },
    "coverage": {
      "status": "advisory",
      "configured": true,
      "reason": "coverage configuration detected"
    }
  }
}
```

Supported statuses:

| Status | Meaning | Missing-artifact effect |
|---|---|---|
| `required` | CES should expect the artifact. | Missing evidence blocks approval. |
| `optional` | CES should surface the result when present, but absence should not block approval by itself. | Non-blocking when missing. |
| `advisory` | CES should surface the result when present, but absence should not block approval by itself. | Non-blocking when missing. |
| `unavailable` | CES should not require this check for the current project. | Non-blocking when missing. |

A profile relaxes missing-artifact handling. It does **not** turn a present failing result into a pass. If an advisory or optional check is explicitly run and reports a failure, CES may still surface or block on that failure through sensor/risk policy rather than pretending the evidence is clean.

Known check names include `pytest`, `ruff`, `mypy`, and `coverage`.

## Detection rules

CES detects configured tools from explicit project signals in `pyproject.toml`, including tool sections and dependency metadata.

Important guardrail: a `tests/` directory alone does **not** make `pytest` required. A project must explicitly configure or depend on pytest before CES classifies pytest as configured. This avoids false blockers in repositories that have example files, historical tests, or non-pytest test layouts. Standalone config files such as `pytest.ini`, `ruff.toml`, or `mypy.ini` are not currently detection inputs unless their equivalent settings also appear in `pyproject.toml`.

## How profiles affect completion evidence

When a builder run reaches completion, CES evaluates configured verification artifacts with the profile in mind:

| Check status | Missing artifact | Present failing artifact | Passing artifact |
|---|---|---|---|
| `required` | Blocks approval | Blocks approval | Satisfies the check |
| `optional` | Does not block by missing-artifact policy | May still fail or block as a real sensor result | Recorded as supporting evidence |
| `advisory` | Does not block by missing-artifact policy | May still fail or block as a real sensor result | Recorded as supporting evidence |
| `unavailable` | Ignored as unavailable when missing | May still be reported if explicitly present | Recorded as extra evidence |

For example, if `ruff` is required, CES expects a deterministic `ruff-report.json` artifact. If coverage is advisory, missing `coverage.json` should not block approval by itself, but a present low-coverage result remains visible and may still be treated as a failing sensor result.

## Trust and same-run profile changes

The profile is a governance policy file. If `.ces/verification-profile.json` changes in the same run being reviewed, CES treats the new profile as **untrusted for that run**.

That means an agent cannot include a change like this and immediately benefit from it:

```diff
- "ruff": { "status": "required", ... }
+ "ruff": { "status": "advisory", ... }
```

CES should fail closed and require the stricter existing expectations until the operator has separately reviewed and accepted the profile change. Path comparisons are normalized so variations such as `./.ces/verification-profile.json` cannot bypass this rule.

Recommended workflow for policy changes:

1. Review and merge the profile change separately.
2. Start the governed implementation run from the updated base.
3. Let CES use the now-trusted profile for future completion gates.

## CES repository profile

The CES repository carries its own profile at `.ces/verification-profile.json`:

- `pytest`: required
- `ruff`: required
- `mypy`: required
- `coverage`: advisory

This matches the project’s CI posture: tests, linting, formatting, typechecking, build metadata, dependency audit, and CodeQL remain release-quality gates; coverage is visible but not the only source of approval truth.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ces profile show` exits with “No verification profile found” | No persisted profile exists. | Run `ces profile detect --write` if you want to create one. |
| `ces profile detect` shows a profile but no file appears | Detection is preview-only by default. | Re-run with `--write`. |
| Pytest is not required despite a `tests/` directory | No explicit pytest config/dependency was detected. | Add pytest configuration or dependency if pytest is part of the project contract. |
| A profile downgrade does not affect the current run | The profile changed in the same reviewed diff and is untrusted for that run. | Merge the profile change separately, then rerun from the updated base. |
| A required check blocks approval because the artifact is missing | The profile says the check is mandatory. | Run the verification command and attach the expected artifact, or separately review whether the profile should change. |
| An advisory check still appears as failed | The profile only relaxes missing-artifact blocking; present failed evidence remains a real sensor result. | Fix the check, remove bad evidence, or consciously handle the failure in review rather than assuming advisory means ignored. |

## Operator rule of thumb

Profiles can reduce false positives, but they are not a shortcut around evidence. Required checks should reflect the project’s real verification contract; advisory checks should still be treated as useful signal during review.
