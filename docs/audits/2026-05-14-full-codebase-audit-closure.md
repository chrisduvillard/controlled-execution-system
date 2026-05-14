# CES full-codebase audit closure — 2026-05-14

Generated: 2026-05-14T10:27:45Z  
Base reviewed: `master` @ `1964e02bf5e8`

## Executive conclusion

**Recommendation: codebase ready for normal release preparation; do not tag/publish without the separate release approval flow.**

The 2026-05-14 audit sequence is closed. Four sequential hardening PRs fixed runtime/governance boundary issues, bound manifest verification to canonical content hashes, scrubbed persisted evidence recursively, strengthened release workflow guardrails, and removed bulky documentation media from published package artifacts.

No release-blocking audit findings remain open for the reviewed scope. The remaining release work is procedural: prepare the next version/changelog release PR, then tag/publish only through the guarded release workflow after explicit release approval.

## Original audit findings closure table

| Finding | Risk | Closure | PR / evidence | Status |
| --- | --- | --- | --- | --- |
| Runtime sandbox default and lifecycle mutation boundaries were too permissive. | Operator-intended governance could be bypassed by permissive runtime defaults or CLI lifecycle paths outside the central workflow engine. | Restricted runtime defaults, added explicit two-key override behavior, centralized lifecycle mutation through `WorkflowEngine`, and excluded `.ces` governance files from runtime/builder manifest scope. | [#114](https://github.com/chrisduvillard/controlled-execution-system/pull/114) | Fixed, merged |
| Manifest verification did not bind signatures tightly enough to canonical content. | A manifest/signature mismatch could allow content laundering if verification accepted detached or caller-supplied hash context. | Manifest signing and verification now compute the canonical signing payload and validate the stored content hash before signature verification. | [#115](https://github.com/chrisduvillard/controlled-execution-system/pull/115) | Fixed, merged |
| Persisted evidence scrubbing was not recursive across nested durable payloads. | Secret-looking values in nested evidence JSON could leak into local storage and downstream reports. | Added recursive scrubbing for strings, lists, and dictionaries before persisted evidence is saved or reloaded. | [#115](https://github.com/chrisduvillard/controlled-execution-system/pull/115) | Fixed, merged |
| Publish workflows had insufficient release guardrails. | A tag or manual publish path could run without enough ancestry, CI, or permission constraints. | Added explicit read-only CI permissions, full release test suites before publish, tag/version/changelog checks, and master-ancestry verification in publish workflows. | [#116](https://github.com/chrisduvillard/controlled-execution-system/pull/116) | Fixed, merged |
| Source distributions shipped bulky docs media. | Public artifacts were unnecessarily large and risked shipping non-runtime material. | Excluded `docs/assets` from distributions and added artifact inspection tests for wheel/sdist hygiene. | [#117](https://github.com/chrisduvillard/controlled-execution-system/pull/117) | Fixed, merged |

## Verification performed locally

Final verification was run on post-fix `master` @ `1964e02bf5e8`.

```bash
uv sync --frozen --group ci
python - <<'PY'
from pathlib import Path
import yaml
for path in Path('.github/workflows').glob('*.yml'):
    yaml.safe_load(path.read_text(encoding='utf-8'))
print('workflow yaml ok')
PY
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/ces
uv run pip-audit
uv run pytest tests/ -m "not integration" --cov=ces --cov-fail-under=90 --cov-report=term-missing -q -W error
uv build --out-dir <temp-dist-dir>
uv run twine check <temp-dist-dir>/*
python <artifact-inspection-script> <temp-dist-dir>
```

### Local verification results

- Workflow YAML parse: passed.
- `ruff check`: passed.
- `ruff format --check`: passed; **549 files already formatted**.
- `mypy src/ces`: passed; **no issues in 249 source files**.
- `pip-audit`: **no known vulnerabilities found**.
- Non-integration pytest: **2862 passed, 319 deselected**, coverage gate met at **90.16%**.
- Build: produced `controlled_execution_system-0.1.18.tar.gz` and `controlled_execution_system-0.1.18-py3-none-any.whl`.
- `twine check`: passed for both sdist and wheel.
- Artifact inspection on post-fix `master` before adding this docs-only report:
  - wheel: **501,442 bytes**, 263 entries, forbidden paths `[]`.
  - sdist: **692,908 bytes**, 316 entries, forbidden paths `[]`.
  - explicit forbidden-path scan covered tests, GitHub workflow internals, `.ces`, and local agent state paths; the docs-media scan separately confirmed bulky `docs/assets` media was absent.

## CI / PR evidence

| PR | Title | Merged | CI status |
| --- | --- | --- | --- |
| [#114](https://github.com/chrisduvillard/controlled-execution-system/pull/114) | fix: harden runtime governance boundaries | 2026-05-14T08:33:22Z | Green before merge |
| [#115](https://github.com/chrisduvillard/controlled-execution-system/pull/115) | fix: bind manifest hashes and scrub persisted evidence | 2026-05-14T09:20:33Z | Green before merge |
| [#116](https://github.com/chrisduvillard/controlled-execution-system/pull/116) | ci: harden release publish guardrails | 2026-05-14T09:28:35Z | Green before merge |
| [#117](https://github.com/chrisduvillard/controlled-execution-system/pull/117) | build: exclude bulky docs assets from artifacts | 2026-05-14T09:37:18Z | Green before merge |

Latest `master` after PR #117 (`1964e02bf5e8`):

- CI workflow: success — https://github.com/chrisduvillard/controlled-execution-system/actions/runs/25852991094
- CodeQL / Analyze Python: success — https://github.com/chrisduvillard/controlled-execution-system/actions/runs/25852991067
- UV graph update: success — https://github.com/chrisduvillard/controlled-execution-system/actions/runs/25852992500

The closure PR itself should be merged only after its own CI and CodeQL checks are green.

## Accepted risks / non-blocking notes

1. **This closure is not a release tag or PyPI publication.** It supports release preparation, but publishing remains an external action that should go through the guarded release workflow.
2. **Runtime authority is improved, not magically eliminated.** CES now defaults more restrictively and requires explicit dangerous-access override, but runtime adapters still need operator discipline and evidence review for host-side effects.
3. **Routine CI intentionally excludes marked integration tests.** The non-integration coverage gate mirrors the repository CI lane; release-specific installed-wheel and publish smokes belong in the release-prep/tag-publish flow.
4. **Package artifact tests build real distributions.** They add confidence but also add modest test runtime; keep them because public artifact hygiene was in audit scope.

## Release recommendation

**Proceed to a normal release-preparation PR when ready.**

Recommended next release sequence:

1. bump version/changelog/public install references;
2. open a release-prep PR;
3. require CI, CodeQL, latest-bounds, build, twine, audit, artifact inspection, and installed-wheel smoke evidence;
4. after merge, request explicit approval for the release tag;
5. let the guarded tag-triggered publish workflow build and publish artifacts;
6. verify the published package from a fresh installer environment.
