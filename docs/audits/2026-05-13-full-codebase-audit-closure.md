# CES full-codebase audit closure — 2026-05-13

Generated: 2026-05-13T10:38:54Z  
Base reviewed: `master` @ `5c4056ef63a7`

## Executive conclusion

**Recommendation: codebase ready for normal release preparation; do not tag/publish without the separate version-bump and release approval flow.**

The 2026-05-13 audit follow-up is closed. The sequence fixed the package-artifact hygiene gap, confirmed and documented unsafe-runtime consent controls, hardened `.ces` state and manual evidence handling, made local SQLite access more tolerant of overlapping CLI invocations, lifted runtime/recovery coverage where the audit found risk concentration, and removed source-level dead-code findings in telemetry/provider paths.

No release-blocking audit findings remain open for the reviewed scope. One architectural risk remains accepted and intentionally disclosed: Codex still runs as a full-host local runtime boundary, so CES governance must keep explicit side-effect consent, runtime-boundary notices, workspace-delta evidence, and operator review in the loop.

## Original audit findings closure table

| Finding | Risk | Closure | PR / evidence | Status |
| --- | --- | --- | --- | --- |
| Local build packaging could include untracked/private example projects. | Dirty-tree local artifacts could contaminate sdists and undermine release trust. | Moved the unrelated `voice-to-text-mvp` project outside CES, hardened package contract tests, and kept source/wheel/sdist build checks in CI-parity verification. | [#91](https://github.com/chrisduvillard/controlled-execution-system/pull/91) | Fixed, merged |
| Codex runtime uses `--sandbox danger-full-access`. | Runtime cannot enforce manifest `allowed_tools` and can have host-side effects if accepted. | Existing unsafe-runtime consent gate was confirmed: `--yes` does not imply side-effect consent; execution paths require `--accept-runtime-side-effects` and docs/security notices disclose the boundary. After consent, Codex still has full-host runtime authority; CES controls are approval/detection/evidence controls, not sandbox enforcement. | [#42](https://github.com/chrisduvillard/controlled-execution-system/pull/42), docs/tests reconfirmed in this audit | Accepted residual risk, explicitly gated/disclosed |
| `ces init` could follow a symlinked `.ces` during profile-bootstrap init. | Local state/keys could be written outside the project root through a symlinked state directory. | Reject symlinked CES state directories before initialization and add adversarial unit coverage. | [#92](https://github.com/chrisduvillard/controlled-execution-system/pull/92) | Fixed, merged |
| `ces complete` manual evidence stored raw evidence text without cap or secret scrub. | Operators could persist very large files or credential-looking values into local state and downstream reports. | Scrub manual evidence, cap stored text, preserve evidence metadata/digest behavior, and add regression coverage for secret redaction and size limits. | [#93](https://github.com/chrisduvillard/controlled-execution-system/pull/93) | Fixed, merged |
| SQLite local store lacked explicit concurrency resilience settings. | Overlapping CLI readers/writers could hit avoidable `database is locked` failures. | Configure SQLite connections with a busy timeout and WAL-oriented local-first settings; added store hardening coverage. | [#94](https://github.com/chrisduvillard/controlled-execution-system/pull/94) | Fixed, merged |
| Runtime/recovery coverage was low relative to operational risk. | Runtime diagnostics and stale-session reconciliation could regress in failure modes not exercised by tests. | Added runtime diagnostics coverage for redaction/truncation/permissions and recovery lock edge coverage for mismatched, corrupt, and stale locks. | [#95](https://github.com/chrisduvillard/controlled-execution-system/pull/95) | Fixed, merged |
| Source-level dead-code scan found provider/observability cleanup candidates. | Small hygiene issues in telemetry/provider code could hide future drift. | Removed unreachable null-provider stream code and marked OpenTelemetry/structlog callback arguments intentionally unused. | [#96](https://github.com/chrisduvillard/controlled-execution-system/pull/96) | Fixed, merged |

## Verification performed locally

Final verification was run on the closure report branch rebased from post-fix `master` @ `5c4056ef63a7`.

```bash
uv run vulture src/ces --min-confidence 90
uv run pytest tests/unit/test_observability tests/unit/test_providers -q
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/ces/ --ignore-missing-imports
uv export --frozen --group ci --format requirements-txt --no-emit-project --no-hashes --output-file /tmp/ces-ci-requirements.txt
uv run pip-audit --strict -r /tmp/ces-ci-requirements.txt
uv run pytest tests/ -m "not integration" --cov=ces --cov-fail-under=90 --cov-report=term-missing -q -W error
rm -rf dist && uv build && uvx twine check dist/* && rm -rf dist
```

### Local verification results

- `vulture src/ces --min-confidence 90`: passed; no source-level findings emitted.
- Observability/provider targeted tests: **130 passed**.
- `ruff check`: passed.
- `ruff format --check`: passed; 532 files already formatted.
- `mypy`: passed; no issues in 243 source files.
- `pip-audit --strict`: no known vulnerabilities found.
- Non-integration pytest: **2791 passed, 319 deselected**, coverage gate met at **90.26%**.
- Package artifact hygiene regressions are covered by the non-integration test gate, including the release package contract tests added in [#91](https://github.com/chrisduvillard/controlled-execution-system/pull/91).
- Build: produced `controlled_execution_system-0.1.16.tar.gz` and `controlled_execution_system-0.1.16-py3-none-any.whl`.
- `twine check`: passed for both sdist and wheel.

## CI / PR evidence

| PR | Title | Merged | CI status |
| --- | --- | --- | --- |
| [#42](https://github.com/chrisduvillard/controlled-execution-system/pull/42) | fix(runtime): require unsafe runtime consent | 2026-05-06T08:18:31Z | Green before merge; pre-existing control reconfirmed by this audit |
| [#91](https://github.com/chrisduvillard/controlled-execution-system/pull/91) | test: harden release artifact package contract | 2026-05-13T10:07:04Z | Green before merge |
| [#92](https://github.com/chrisduvillard/controlled-execution-system/pull/92) | fix: reject symlinked CES state directories | 2026-05-13T10:13:16Z | Green before merge |
| [#93](https://github.com/chrisduvillard/controlled-execution-system/pull/93) | fix: scrub and cap manual completion evidence | 2026-05-13T10:20:08Z | Green before merge |
| [#94](https://github.com/chrisduvillard/controlled-execution-system/pull/94) | fix: configure sqlite for concurrent CLI access | 2026-05-13T10:25:07Z | Green before merge |
| [#95](https://github.com/chrisduvillard/controlled-execution-system/pull/95) | test: cover runtime diagnostics and recovery lock edges | 2026-05-13T10:30:50Z | Green before merge |
| [#96](https://github.com/chrisduvillard/controlled-execution-system/pull/96) | chore: clean dead code in provider and telemetry paths | 2026-05-13T10:38:31Z | Green before merge |

Latest `master` after PR #96:

- CI: success for `5c4056ef63a7` — https://github.com/chrisduvillard/controlled-execution-system/actions/runs/25793903553
- CodeQL: success for `5c4056ef63a7` — https://github.com/chrisduvillard/controlled-execution-system/actions/runs/25793903508

The closure PR itself should be merged only after its own CI/CodeQL checks are green.

## Accepted risks / non-blocking notes

1. **Codex full-host runtime boundary remains accepted, not removed.** CES blocks unsafe runtime launch until explicit `--accept-runtime-side-effects` is provided, documents the boundary, and records runtime evidence. After consent, Codex still has full-host runtime authority and manifest `allowed_tools` are not runtime-enforced by the adapter. Workspace-delta evidence and operator review are detective/approval controls, not sandbox enforcement.
2. **Integration tests remain intentionally excluded from the routine local non-integration gate** by the existing selector. The final local gate mirrors the repository CI lane; targeted integration/publish smokes remain part of release-specific workflows.
3. **Coverage still has risk-shaped pockets.** Overall coverage is above the 90% gate and runtime/recovery coverage improved, but large CLI/runtime modules remain below ideal per-module coverage. Treat this as ongoing hardening, not a release blocker.
4. **This closure does not authorize external publication.** Tagging and PyPI publishing are separate external actions requiring the normal release/version approval path.

## Release recommendation

**Proceed to a normal release-preparation PR when ready.**

Recommended next release sequence:

1. bump version/changelog/public install references;
2. open a release-prep PR;
3. require CI, CodeQL, latest-bounds, build, twine, audit, and installed-wheel smoke evidence;
4. after merge, request explicit approval before pushing the release tag;
5. only then let the publish workflow build and publish artifacts.
