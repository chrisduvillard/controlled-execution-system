# Release runbook

Checklist for cutting a CES release. Every release in this session hit a
trap that this runbook would have caught — treat the preflight list as
non-negotiable rather than advisory.

## One-time PyPI setup

Before the **first** release of a given package name, register a pending
trusted publisher on PyPI so the `Publish to PyPI` workflow's OIDC
exchange succeeds. Subsequent releases inherit the config.

1. Sign in to <https://pypi.org/manage/account/publishing/>.
2. **Add a new pending publisher** with:
   - **PyPI Project Name:** `controlled-execution-system`
   - **Owner:** `chrisduvillard`
   - **Repository:** `controlled-execution-system`
   - **Workflow:** `publish.yml`
   - **Environment:** `pypi`
3. On GitHub, confirm `Settings → Environments` has an environment named
   exactly `pypi`. Public environment, no protection rules required;
   `publish.yml` uses `id-token: write` for the OIDC exchange.

If the first publish fails with `invalid-publisher`, the claims rendered
in the error log tell you which of these four fields is mismatched.

## Per-release checklist

### 1. Preflight on master

```bash
# On a clean master checkout, confirm no pending work:
git status            # clean
git fetch             # no remote drift
gh run list --workflow=ci.yml --limit 1 --branch master   # latest CI run must be green
gh run list --workflow=codeql.yml --limit 1 --branch master # latest CodeQL run must be green

# Tests must pass locally at the enforced local-first gate:
uv run pytest tests/ -m "not integration" --cov=ces --cov-fail-under=90 -q -W error
uv run ruff check . && uv run ruff format --check .
```

### 2. Bump the version

**This is the step that bit us most often.** Two artefacts must move in
lockstep; a one-line patch has to hit both or the publish builds an old
wheel and PyPI rejects it as "file already exists":

```bash
# 2a. pyproject.toml
#     Change:   version = "0.1.X"
#     To:       version = "0.1.Y"
$EDITOR pyproject.toml

# 2b. CHANGELOG.md
#     Add a new '## [0.1.Y] - YYYY-MM-DD' header under [Unreleased].
#     Move any pending items from [Unreleased] to [0.1.Y].
#     Keep [Unreleased] as an empty header for the next cycle.
$EDITOR CHANGELOG.md

# Sanity-check both match before you tag:
grep -E '^version =' pyproject.toml
grep '^## \[' CHANGELOG.md | head -3
```

### 3. Commit and push

```bash
git add pyproject.toml CHANGELOG.md uv.lock
git commit -m "Bump version 0.1.X -> 0.1.Y"
git push
gh run watch --exit-status   # CI must go green
```

### 4. Tag

The tag points at the version-bump commit, not at any earlier one.

```bash
# Body can be CHANGELOG-lifted or a short summary:
git tag -a v0.1.Y -m "v0.1.Y: <one-line summary>" \
  -m "" \
  -m "<3-5 line highlights>"
git push origin v0.1.Y
```

Pushing the tag triggers `.github/workflows/publish.yml` →
unit tests → FreshCart E2E smoke → `uv build` → `twine check` →
installed-CLI smoke → trusted-publish → PyPI upload.

### 5. Watch the publish

```bash
# Find the triggered run:
gh run list --limit 1 --workflow=publish.yml

# Watch it to completion:
gh run watch <run-id> --exit-status
```

**Known gotcha:** `gh run watch --exit-status` returns 0 even when the
publish workflow's final "Publish to PyPI" step fails (it only cares
about the overall run status in some modes). **Always** cross-check:

```bash
gh run view <run-id>    # the final job must show ✓ publish, not X

# And confirm PyPI actually has the new version:
curl -sS https://pypi.org/pypi/controlled-execution-system/json \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['info']['version'])"
# → 0.1.Y
```

### 6. Install smoke test

```bash
python3.12 -m venv /tmp/ces-smoke
/tmp/ces-smoke/bin/pip install --no-cache-dir controlled-execution-system==0.1.Y
/tmp/ces-smoke/bin/ces --help           # renders
mkdir -p /tmp/smoke-proj
cd /tmp/smoke-proj
/tmp/ces-smoke/bin/ces init smoke-proj
ls -la /tmp/smoke-proj/.ces/keys/       # three files, mode 0600
/tmp/ces-smoke/bin/ces doctor --security # exits 0 when run inside a project
```

PyPI CDN propagation can take 30–60 s after the workflow turns green.
If `pip install` reports `No matching distribution`, wait and retry
rather than republishing.

### 7. GitHub Release

The canonical way to make the release discoverable on the repo sidebar
and downstream tooling (Dependabot, mise, pip changelog viewers):

```bash
# Extract the 0.1.Y section from the CHANGELOG as the Release body:
awk '/^## \[0\.1\.Y\]/{flag=1; next} /^## \[/{flag=0} flag' CHANGELOG.md \
  > /tmp/release-body.md

gh release create v0.1.Y \
  --title "v0.1.Y — <same one-line summary as tag>" \
  --notes-file /tmp/release-body.md \
  --latest \
  dist/controlled_execution_system-0.1.Y-py3-none-any.whl \
  dist/controlled_execution_system-0.1.Y.tar.gz
```

### 8. Post-release

- Cross-check the Releases page renders correctly:
  <https://github.com/chrisduvillard/controlled-execution-system/releases>
- If sharing in community channels, quote the 0.1.Y CHANGELOG section
  directly — it's written for that audience.
- Open a follow-up issue for any "Known follow-ups" you deferred from
  this release so the next cycle has concrete work queued.

## Lessons from 0.1.2 and 0.1.3 (for memory)

| # | What bit us | How to catch it next time |
|---|-------------|---------------------------|
| 1 | PyPI trusted-publisher not registered → first publish failed `invalid-publisher` | One-time setup section above; register for a project **before** its first tag push. |
| 2 | CHANGELOG `[Unreleased]` → `[0.1.Y]` done, but `pyproject.toml` version left at 0.1.X → publish tried to upload a wheel of the **previous** version, PyPI rejected as `file already exists` | Step 2's `grep -E '^version =' pyproject.toml` check is the preflight fence for this. Two artefacts, one commit, verified before tag. |
| 3 | `gh run watch --exit-status` exited 0 on a failed publish | Step 5's explicit `gh run view <id>` + PyPI JSON cross-check. |

## Rollback

If a published version is broken (crash on import, wrong payload):

1. **Yank, don't delete.** PyPI's `delete` is a one-way action that
   frees the version number for typosquatting. Instead: open the
   release in the PyPI web UI, mark it as **yanked** with a reason.
   `pip install controlled-execution-system` will skip yanked
   versions unless the user pins the exact yanked version.
2. Publish a fixed `0.1.Y.post1` (for packaging-only fixes) or
   `0.1.Y+1` (for real code fixes). **Do not re-use the same version
   number** — PyPI will reject it (file-already-exists) and yanking
   doesn't reopen the slot.
3. If the failure is a security issue affecting already-installed
   users, open a GitHub Security Advisory at
   `Security → Advisories → New draft`. PyPI will surface the
   advisory next to the yanked version.
