# CES full-codebase audit closure — 2026-05-10

Generated: 2026-05-10T14:57:17Z  
Base reviewed: `master` @ `a814ac3`

## Executive conclusion

**Recommendation: ship after the normal tag/version bump.**

The original full-codebase audit findings are closed. The repository now has:

- clean public release artifacts with local/workspace artifacts excluded and tested;
- manifest governance fields preserved across persistence round trips;
- stable machine-readable JSON for handled CLI errors;
- a centralized subprocess lifecycle helper with process-tree cleanup, timeout, and cancellation coverage;
- representative CLI JSON contract matrix coverage;
- PyPI-safe README rendering and clearer runtime-safety wording;
- CI/publish guardrails that smoke the exact built wheel and JSON public contract before release.

No release-blocking audit findings remain open. The remaining accepted risk is architectural rather than blocking: Codex is explicitly disclosed as a full-access local runtime boundary because the Codex adapter does not enforce CES manifest tool allowlists.

## Original audit findings closure table

| Finding | Risk | Closure | PR | Status |
| --- | --- | --- | --- | --- |
| Release artifact leakage: `dogfood-output/`, local runtime files, and `env.sh` were present in sdist. | Public package could leak workstation paths/local artifacts and reduce release trust. | Added packaging exclusions, release packaging tests, and final artifact scans blocking local artifacts from public distributions. | [#68](https://github.com/chrisduvillard/controlled-execution-system/pull/68) | Fixed, merged |
| Manifest governance fields dropped on reload by `ManifestManager._row_to_manifest()`. | Completion gates and verification governance could silently disable after persistence. | Added regression coverage and restored full `TaskManifest` governance-field rehydration. | [#69](https://github.com/chrisduvillard/controlled-execution-system/pull/69) | Fixed, merged |
| CLI handled errors in JSON mode were inconsistent. | Automation/API consumers could receive Rich panels or non-parseable errors. | Normalized handled errors to stable JSON envelopes on stderr in JSON mode. | [#70](https://github.com/chrisduvillard/controlled-execution-system/pull/70) | Fixed, merged |
| Subprocess process-tree cleanup was decentralized and incomplete. | Timeouts/cancellations could leave orphaned child processes or hanging stream readers. | Added shared async/sync subprocess lifecycle helper and migrated CLI provider, verifier, and diff extractor call sites. | [#71](https://github.com/chrisduvillard/controlled-execution-system/pull/71) | Fixed, merged |
| CLI JSON contract lacked representative matrix coverage. | Future command changes could regress root `--json`, command-local `--json`, stdout/stderr split, or validation behavior. | Added CLI JSON contract matrix tests and hardened command validation paths. | [#72](https://github.com/chrisduvillard/controlled-execution-system/pull/72) | Fixed, merged |
| Docs/PyPI/runtime-safety wording was ambiguous. | PyPI README links/assets could render poorly; `doctor --runtime-safety` could imply Codex was missing instead of intentionally full-access. | Converted README links/assets to absolute public URLs; changed Codex runtime-safety table status to `NOTICE`; documented Codex vs Claude boundary. | [#73](https://github.com/chrisduvillard/controlled-execution-system/pull/73) | Fixed, merged |
| CI/release guardrails did not fully encode the audit public contract. | Release regressions could reappear after manual audit memory fades. | Added exact-wheel CI/publish smokes for help/version/init, JSON doctor, handled-error JSON, artifact metadata, and workflow contract tests. | [#74](https://github.com/chrisduvillard/controlled-execution-system/pull/74) | Fixed, merged |

## Verification performed locally

Final verification was run from `docs/final-audit-closure-report` rebased onto `master` @ `a814ac3`.

```bash
git checkout master
git pull --ff-only origin master
git checkout docs/final-audit-closure-report
git rebase master
git status --short --branch
uv run python -m compileall src tests scripts
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/ces/ --ignore-missing-imports
uv run pytest tests/ -m "not integration" --cov=ces --cov-fail-under=90 --cov-report=term-missing -q -W error
rm -rf dist && uv build && uvx twine check dist/*
uv export --frozen --group ci --format requirements-txt --no-emit-project --no-hashes --output-file /tmp/ces-ci-requirements.txt
uv run pip-audit --strict -r /tmp/ces-ci-requirements.txt
python3 - <<'PY'
import pathlib, tarfile, zipfile
bad_terms = ['dogfood-output', '.ces/', 'runtime-transcripts', 'state.db', '__pycache__', '.pyc', 'env.sh']
for p in sorted(pathlib.Path('dist').glob('*')):
    names = []
    if p.suffix == '.whl':
        with zipfile.ZipFile(p) as z:
            names = z.namelist()
    elif p.suffixes[-2:] == ['.tar', '.gz']:
        with tarfile.open(p) as t:
            names = t.getnames()
    bad = [name for name in names if any(term in name for term in bad_terms)]
    if bad:
        raise SystemExit(f'{p}: forbidden artifact members: {bad[:20]}')
    print(f'{p}: {len(names)} members clean')
PY
```

### Local verification results

- `compileall`: passed.
- `ruff check`: passed.
- `ruff format --check`: passed.
- `mypy`: passed, no issues in 224 source files.
- Non-integration pytest: **2658 passed, 319 deselected**, coverage gate met at **90.16%**.
- Build: produced `controlled_execution_system-0.1.15.tar.gz` and `controlled_execution_system-0.1.15-py3-none-any.whl`.
- `twine check`: passed for sdist and wheel.
- `pip-audit --strict`: no known vulnerabilities found.
- Artifact hygiene scan: wheel and sdist clean of forbidden terms (`dogfood-output`, `.ces/`, `runtime-transcripts`, `state.db`, `__pycache__`, `.pyc`, `env.sh`).

## CI / PR evidence

| PR | Title | Merged | CI status |
| --- | --- | --- | --- |
| [#68](https://github.com/chrisduvillard/controlled-execution-system/pull/68) | fix: block local artifacts from release sdist | 2026-05-10T12:24:27Z | Green before merge |
| [#69](https://github.com/chrisduvillard/controlled-execution-system/pull/69) | fix: preserve manifest governance fields on reload | 2026-05-10T12:32:31Z | Green before merge |
| [#70](https://github.com/chrisduvillard/controlled-execution-system/pull/70) | fix: emit JSON for CLI handled errors | 2026-05-10T12:39:51Z | Green before merge |
| [#71](https://github.com/chrisduvillard/controlled-execution-system/pull/71) | fix: centralize subprocess lifecycle cleanup | 2026-05-10T14:10:47Z | Green before merge |
| [#72](https://github.com/chrisduvillard/controlled-execution-system/pull/72) | fix: harden CLI JSON contract matrix | 2026-05-10T14:27:47Z | Green before merge |
| [#73](https://github.com/chrisduvillard/controlled-execution-system/pull/73) | docs: polish PyPI README and runtime safety guidance | 2026-05-10T14:38:09Z | Green before merge |
| [#74](https://github.com/chrisduvillard/controlled-execution-system/pull/74) | ci: smoke public release contracts | 2026-05-10T14:55:14Z | Green before merge |

Latest `master` after PR #74:

- CI: success — https://github.com/chrisduvillard/controlled-execution-system/actions/runs/25631832671
- CodeQL: success — https://github.com/chrisduvillard/controlled-execution-system/actions/runs/25631832669

## Accepted risks / non-blocking notes

1. **Codex runtime boundary** — accepted and disclosed. Codex is invoked as a full-access local runtime; CES does not enforce manifest `allowed_tools` inside the Codex adapter. The product now labels this as `NOTICE`, documents it, requires explicit side-effect acceptance on relevant execution paths, and keeps it visible in `ces doctor --runtime-safety` JSON/table output.
2. **Integration tests remain intentionally deselected from the local release gate** unless explicitly invoked. CI/publish workflows still include targeted integration and installed-wheel smokes for public-release confidence.
3. **Future version bump still required before publishing** if releasing a new package. The codebase is audit-clean, but publishing should follow the existing tag/version/changelog agreement workflow.

## Release recommendation

**Ship after tag/version bump.**

The codebase is hard-publication-clean relative to the original audit scope. The normal release process should now be:

1. bump package version and changelog;
2. open the version-bump PR;
3. require CI/CodeQL green;
4. tag `v<version>` only after merge;
5. let the publish workflow validate tag/version/changelog, run strict tests, build, twine-check, exact-wheel smoke, then publish.
