# Public Release Checklist

Run this checklist before inviting broad public use.

## Repository Safety

- [ ] Run `gitleaks detect --source . --config .gitleaks.toml --redact` from a full clone to scan history.
- [ ] Confirm GitHub secret scanning is enabled.
- [ ] Confirm GitHub push protection is enabled.
- [ ] Confirm branch protection requires CI, CodeQL, dependency audit, tests, and secret scan.
- [ ] Confirm release tags are protected.
- [ ] Review `.gitleaks.toml` allowlists after any new fixture or docs changes.

## Release Environments

- [ ] Confirm PyPI trusted publishing is configured for the exact repository and workflow.
- [ ] Confirm TestPyPI trusted publishing is configured for the exact repository and workflow.
- [ ] Confirm PyPI/TestPyPI environments require the intended reviewer approvals.
- [ ] Confirm no long-lived PyPI tokens are stored in repository secrets.

## Supply Chain

- [ ] Review pinned GitHub Actions commit SHAs and refresh them only through a normal dependency-review PR.
- [ ] Review Dependabot updates and lockfile diffs.
- [ ] Run `uv sync --frozen --group ci`.
- [ ] Run `uv run pip-audit --strict` through the CI export command.

## CES Integrity

- [ ] Run `ces doctor --security` in the release smoke project.
- [ ] Run `ces audit verify` after smoke workflow activity.
- [ ] Preserve `.ces/keys/` only with the matching `.ces/state.db` when archiving audit evidence.

## Public Docs

- [ ] README, Quickstart, First 15 Minutes, Data Boundary, Runtime Adapter Matrix, Audit Integrity, Security Policy, and Release docs reflect the current commands.
- [ ] No docs claim CES is a sandbox, hosted control plane, deployment controller, or runtime credential manager.
- [ ] Beginner path uses one exact command sequence.
- [ ] Experienced-developer docs cover JSON output, CI wiring, audit verification, and runtime boundaries.
