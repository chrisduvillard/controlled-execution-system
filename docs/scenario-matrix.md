# CES Scenario Matrix

This matrix records the expected beginner and operator paths CES is meant to support. It was created during the production-readiness dogfood pass so claims stay tied to tested or explicitly scoped behavior.

## Greenfield scenarios

### Empty folder, new app from an idea

- **Expected user path:** `ces create "..."`, create the suggested folder, run `ces ship`, `ces build --from-scratch "..."`, `ces verify`, `ces proof`.
- **Success criteria:** CES treats the project as greenfield, creates local `.ces/` state during the mutating build, generates app files, captures a completion contract, and proof reports `proven` or a concrete evidence blocker.
- **Likely friction:** Codex requires `--accept-runtime-side-effects`; source-checkout use via `uv run --project` is noisy; `ces create` can suggest a nested folder when run from an already-created slug folder.
- **Current support status:** Tested to the runtime-consent boundary in a real outside folder under a local `ces-friction-tests/greenfield-quickstart-*` workspace.
- **Improvements made:** README and Quickstart now show explicit greenfield flow, Codex consent guidance, expected `ces create` output, and proof success criteria.

### User follows only the README

- **Expected user path:** Install first, choose Greenfield or Brownfield, follow copy-paste commands, use `ces verify` and `ces proof` before approval.
- **Success criteria:** No `ces: command not found` before install guidance; no hidden runtime assumption; explicit quality gates.
- **Likely friction:** Too many commands too early; install previously appeared after `ces` commands.
- **Current support status:** README revised with install-first quickstart, path chooser, explicit Greenfield and Brownfield sections.
- **Improvements made:** Added beginner path chooser and “Quality gates: how to know it worked.”

## Brownfield scenarios

### Existing real repo, scoped safe improvement

- **Expected user path:** `ces mri`, `ces next`, `ces next-prompt "..." --acceptance "..." --must-not-break "..."`, plain `ces build "..."`, `ces verify`, `ces proof`.
- **Success criteria:** CES identifies the repo as brownfield, preserves must-not-break behavior in the contract, changed files stay inside declared scope, and proof reports `proven` or names the blocker.
- **Likely friction:** Deliberation challenge can over-block common terminology; generated file areas may be too broad or too generic; `status` and `proof` report latest persisted task, not necessarily the latest read-only planning objective.
- **Current support status:** Tested read-only against the local Auralis checkout for a provider-capability panel objective.
- **Improvements made:** Brownfield docs now start read-only and emphasize explicit scope, verification, proof, and changed-file boundaries.

### Existing repo with agent-output risk

- **Expected user path:** Compile a strict Developer Intent Contract with scope, non-goals, anti-slop limits, must-not-break rules, and verification evidence before launching runtime work.
- **Success criteria:** Runtime output cannot auto-authorize out-of-scope changes or recommend approval based only on exit code.
- **Likely friction:** Post-runtime summaries can sound stronger than the evidence; brownfield runtime deltas can be mistaken for authorized scope.
- **Current support status:** Code paths reviewed and hardened in this pass.
- **Improvements made:** Runtime evidence summaries now explicitly say they are raw status only, and brownfield observed edits are no longer added to manifest scope as post-hoc authorization.

## Agent-quality scenarios

### Agent must plan before coding

- **Expected user path:** `ces deliberate` when approach needs pushback, then `ces next-prompt` to produce a Developer Intent Contract.
- **Success criteria:** The prompt includes scope, non-goals, anti-slop limits, verification commands, and `ces:completion` expectations.
- **Current support status:** Read-only dogfood confirmed useful shape on Auralis; file-scope precision remains an improvement area.

### Agent must prove instead of assert

- **Expected user path:** `ces build`, `ces verify`, `ces proof`; approval only after proof is `proven` and recommendation is `safe-to-review`.
- **Success criteria:** Completion claim, verification, changed-file scope, and behavior-delta evidence are fresh and consistent.
- **Current support status:** Existing CI and docs cover proof loop; docs now make the quality gate prominent.

### Independent critique and preserved dissent

- **Expected user path:** `ces deliberate` before risky work, `ces proof` and reports after runtime work.
- **Success criteria:** Alternatives, role critique, dissent, blockers, and next operator action are visible.
- **Current support status:** Supported by existing commands; challenge-mode overblocking should be tuned later.

## Out of scope for this pass

- Launching a real Codex or Claude runtime to completion in Auralis.
- Pushing or modifying Auralis.
- Building import adapters for external methodology frameworks.
- Claiming full integration-suite coverage in PR CI before a curated integration lane is designed.
