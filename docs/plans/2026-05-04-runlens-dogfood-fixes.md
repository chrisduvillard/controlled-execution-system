# RunLens Dogfood Fixes Implementation Plan

> **For Hermes:** Implement with regression tests for each dogfood finding, then open a GitHub PR.

**Goal:** Turn RunLens dogfood findings F-001–F-007 into concrete CES CLI/governance improvements.

**Architecture:** Keep fixes in the existing CLI/service boundaries: init hygiene in `init_cmd.py`, runtime auth readiness in `doctor_cmd.py`, status labeling in `status_cmd.py`, manual reconciliation in `complete_cmd.py`, and greenfield governance/sensor policy in `run_cmd.py` + sensor policy helpers. Preserve conservative brownfield behavior while making greenfield builds recoverable and safe by default.

**Finding-to-fix coverage:**

| Finding | Fix |
|---|---|
| F-001 `ces init --yes` missing | Add `--yes/-y` no-op automation flag to `ces init`. |
| F-002 stale `ces doctor --verify-runtime` guidance | Add real `ces doctor --verify-runtime` option and update init guidance to point to it. |
| F-003 status shows project ID only | Show `project_name` in status panel and JSON, with project ID as secondary metadata. |
| F-004 greenfield empty scope rejects successful build | For greenfield manifests with empty scope, derive effective affected files from runtime workspace delta before completion verification and scope checks. |
| F-005 coverage blocks when not requested | Treat missing coverage artifacts as advisory; do not block greenfield auto-approval solely because `coverage.json` is missing. |
| F-006 `ces complete` crashes with real store | Remove invalid `findings=` kwarg and add real `LocalProjectStore` integration regression test. |
| F-007 `.ces/` not ignored | During `ces init`, append safe ignore entries to repo `.gitignore` or create one. Also write `.ces/.gitignore` as a defense-in-depth ignore-all marker. |

## Tasks

1. Add failing regression tests for init automation/hygiene and stale runtime guidance.
2. Add failing real-store regression test for `ces complete --evidence`.
3. Add failing regression tests for status project name display/JSON.
4. Add failing unit tests for greenfield effective scope and coverage missing-artifact advisory behavior.
5. Implement minimal code changes to satisfy tests.
6. Run targeted tests, then full unit suite, Ruff, and mypy.
7. Commit, push branch, open PR with findings-to-fixes mapping and verification evidence.
