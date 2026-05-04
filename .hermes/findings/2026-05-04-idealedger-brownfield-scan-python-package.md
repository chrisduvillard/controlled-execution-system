# IL-CES-001 — Brownfield scan misses simple Python packages without pyproject

- Date: 2026-05-04
- Wave: Idea Ledger A→Z greenfield → brownfield dogfood
- Severity: Medium
- Area: brownfield scan/register onboarding
- Target: `/tmp/ces-idealedger-a2z-20260504-162837`
- CES baseline before fix: `ae5cb16ce7803e8023daa20809c3a27e8af9758c`

## Summary

A CES-generated greenfield Python package (`idea_ledger/`) had no `pyproject.toml`. The product itself worked and was approved, but `ces scan --root .` reported `modules: 0`, so `ces brownfield register --from-default-scan` said `No modules in scan — nothing to register.`

This forced a manual `ces brownfield register --system ... --description ...` workaround before the brownfield improvement could proceed.

## Expected

For a runnable local Python package with package files such as:

```text
idea_ledger/__init__.py
idea_ledger/__main__.py
idea_ledger/cli.py
idea_ledger/storage.py
tests/test_cli.py
```

`ces scan --root .` should inventory at least one Python module so `ces brownfield register --from-default-scan` can draft a review entry.

## Actual

Initial scan output on the generated Idea Ledger project:

```text
modules:         0
generated files: 0
codeowners:      0
```

Then:

```text
No modules in scan — nothing to register.
```

## Why it matters

The A→Z workflow remained recoverable, but it introduced unnecessary manual guesswork exactly at the greenfield→brownfield handoff. A real user who just created a simple Python CLI with CES should not have to know how to manually register legacy behavior before asking CES to improve it.

## Root cause

`src/ces/cli/scan_cmd.py` detected modules only from manifest files:

- `pyproject.toml`
- `package.json`
- `go.mod`
- `Cargo.toml`

It did not detect simple runnable Python package directories when packaging metadata was absent.

## Fix

- Added deterministic package-root detection for Python directories containing `__init__.py` plus at least one additional `.py` file.
- Skips test/package-cache/vendor directories via existing scan skip rules.
- Keeps manifest-based detection unchanged and deduplicates package/manifest module keys.

## Regression

Added:

```text
tests/unit/test_cli/test_scan_cmd.py::TestCesScan::test_detects_python_package_without_pyproject
```

RED before fix:

```text
AssertionError: ... in []
```

GREEN after fix:

```text
1 passed, 1 warning
```

## Live validation

Against the actual Idea Ledger dogfood target, using the source checkout fix:

```text
ces scan --root .
modules: 1
```

Scan JSON now includes:

```json
{"path": "idea_ledger/__init__.py", "type": "python", "name": "idea_ledger"}
```
