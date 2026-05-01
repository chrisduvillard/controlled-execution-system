# GNHF Trial Guide

Use this guide when you want to use [`gnhf`](https://github.com/kunchenguid/gnhf) to help develop CES.

This is an external development workflow only. `gnhf` is not part of CES, CES does not depend on it, and no CES release process should assume it exists.

Use CES's own builder-first and expert workflows when you are operating delivery requests through CES. Use `gnhf` only for contributor-side changes to this repository, from a clean sibling worktree or clean clone.

## Goal

Use `gnhf` only if it improves **safe productivity**:

- faster delivery on scoped tasks
- lower review effort than doing the work manually
- no drift into CES governance-sensitive code
- no increase in regressions or cleanup churn

If a run produces plausible-looking changes that cost more to review or repair than they save, treat that as a failed trial.

## Good CES Trial Targets

Start with work that is narrow, reviewable, and already covered by tests:

- docs and contributor guidance
- unit-test expansion or fixture cleanup
- CLI copy and UX polish in builder-facing commands
- mechanical refactors with no behavior change
- small brownfield or status/reporting improvements outside governance-critical logic

Good first examples:

- improve `ces status` wording plus matching tests
- add missing tests around a stable CLI surface
- tighten docs around builder-first versus expert workflow

## Do Not Use GNHF On These Areas

Do not use `gnhf` unsupervised on code that defines CES governance guarantees:

- `src/ces/control/`
- manifest lifecycle or `src/ces/control/models/manifest.py`
- policy decision logic under `src/ces/control/`
- approval, triage, review, or trust-tier decision logic
- audit-ledger and tamper-evidence paths
- kill switch and emergency enforcement logic
- `src/ces/execution/agent_runner.py`
- runtime-boundary code under `src/ces/execution/`

If a run touches those areas unintentionally, stop and discard or isolate the work before review.

## Recommended Trial Workflow

1. Start from a clean checkout.
2. Create an isolated sibling worktree with the helper:

   ```bash
   ./scripts/gnhf_trial.sh status-copy-polish
   ```

3. Change into the printed worktree path.
4. Install `gnhf` separately if needed:

   ```bash
   npm install -g gnhf
   ```

5. Run one bounded objective with a small iteration cap:

   ```bash
   gnhf --agent codex --max-iterations 4 \
     "Improve CES status command copy and tests. Stay within src/ces/cli/status_cmd.py \
     and tests/unit/test_cli/. Do not touch src/ces/control/, src/ces/execution/, \
     approval, triage, review, manifest, audit, kill switch, or runtime-boundary logic. \
     Add or update tests for any behavior change."
   ```

6. Review the resulting branch manually.
7. Integrate only by `git cherry-pick` or manual porting into your real working branch.

Do not point `gnhf` at the checkout you are actively using for CES development. It expects a clean Git tree and is optimized for autonomous iteration, not for coexisting with an in-flight human branch.

## Prompt Rules

Every `gnhf` objective should state all of these explicitly:

- the single task to complete
- the exact allowed files or directories
- the exact no-go paths
- the required tests to run or update
- that behavior must not expand beyond the stated scope

Prefer prompts that look like this:

```text
Add tests for the runtime adapter transcript path behavior.
Only edit tests/unit/test_execution/ and the adapter test helpers needed for that case.
Do not modify runtime-boundary, manifest, audit, approval, triage,
review, policy, or kill-switch code.
Keep the change mechanical and test-backed.
```

## Review Checklist

Review every `gnhf` branch against this checklist:

- scope stayed inside the stated files and intent
- commits are incremental and understandable
- tests meaningfully cover the change
- no governance-sensitive files changed by accident
- the result needs less cleanup than writing the change manually

Reject the trial output if any of these repeat:

- drift into excluded CES surfaces
- superficial tests
- noisy churn commits
- plausible-but-wrong code that costs heavy reviewer time

## Success Scorecard

Keep `gnhf` in your CES workflow only if most runs meet all of these:

- review time is lower than a normal manual pass
- test pass rate is at least as good as your normal workflow
- no unintended edits land in excluded paths
- at least one medium-risk CLI or docs task ships with minimal rewrite

If you want multiple agents in parallel, prefer multiple clean CES worktrees or a dedicated clean base checkout. Use `gnhf --worktree` only from a clean non-`gnhf/` branch when you explicitly want `gnhf` to manage its own worktree fan-out.
