# CES Scenario Matrix

This matrix tracks whether CES delivers a low-friction, evidence-first path for:

- **Greenfield** work (new project from scratch),
- **Brownfield** work (existing repo with behavior to preserve), and
- **Agent-quality controls** (anti-slop, bounded scope, proof-before-approval).

Use this document as the operator planning artifact before large workflow edits.

## Status legend

- **Supported**: flow works as documented with current guardrails.
- **Partially supported**: flow works but has known friction or reliability gaps.
- **Blocked**: cannot be validated in this environment without an external unblock.

## Greenfield scenarios

| Scenario | Expected user path | Commands / steps | Success criteria | Likely friction | Current support status | Improvements needed |
|---|---|---|---|---|---|---|
| User starts from an empty folder | Read-only planning first, then one governed mutating run | `ces create` -> `mkdir/cd` -> `ces ship` -> `ces build --from-scratch` -> `ces verify` -> `ces proof` | `.ces/` created in target folder, app scaffolded, verification evidence captured, proof is `proven` or explicitly blocked | Project-root confusion, runtime side-effect consent | Partially supported | Keep emphasizing explicit target folder/project-root patterns in docs and examples |
| User follows only README | Uses beginner map without jumping into advanced sections | “Beginner journey (10-minute map)” then Greenfield section | First run completes with bounded objective and reviewable evidence | Treating `create/start/ship` as mutating commands | Supported | Keep examples concise and keep pitfalls near quickstart |
| User has no CES internals knowledge | Uses mode decision first (greenfield vs brownfield) | Quick decision table + pitfalls checklist | User can explain why the selected mode is correct before running build | Misusing `--from-scratch` in an existing repo | Supported | Continue strict mode-selection framing and examples |

## Brownfield scenarios

| Scenario | Expected user path | Commands / steps | Success criteria | Likely friction | Current support status | Improvements needed |
|---|---|---|---|---|---|---|
| Existing repo with must-not-break behavior | Build a contract before runtime execution | `ces mri` -> `ces next` -> `ces next-prompt ... --must-not-break ... --acceptance ...` -> `ces build` -> `ces verify` -> `ces proof` | Contract captures bounded scope + must-not-break; edits stay scoped; proof reflects evidence freshness | Weak/generic acceptance criteria | Partially supported | Improve prompt generation for objective-specific acceptance/must-not-break defaults |
| Scoped improvement in a risky repo | Require checklist before mutating commands | Brownfield guardrails checklist in Getting Started | Operator checks objective bounds, acceptance criteria, and verification plan before run | Users skip checklist discipline | Supported | Keep checklist copy-paste ready for issue/PR templates |
| Real brownfield dogfood on Auralis | Validate CES against real-world codebase | Clone `https://github.com/chrisduvillard/auralis` and run brownfield path | End-to-end evidence-backed change loop on non-trivial repo | Environment/network restrictions can block clone | Blocked in this environment | Use local checkout/mirror/artifact bundle to complete mandatory dogfood trial |

## Agent-quality scenarios

| Scenario | Expected user path | Commands / steps | Success criteria | Likely friction | Current support status | Improvements needed |
|---|---|---|---|---|---|---|
| CES forces plan before code | Deliberation before execution contract | `ces deliberate` then `ces next-prompt` | Alternatives, risk critique, dissent, and blockers are visible before runtime work | Over-blocking terminology in challenge mode | Partially supported | Tune challenge-mode scoring and deduplicate blocker terms |
| CES enforces validation over claims | Proof gate must pass before approval | `ces verify` -> `ces proof` -> `ces approve` only when safe | Approvals are evidence-backed, not runtime-exit-backed | Humans may shortcut to approval | Supported | Continue emphasizing proof status and recommendation semantics |
| CES limits uncontrolled rewrites | Scope + must-not-break + evidence checks constrain runtime output | Contract + workspace delta checks + proof review | Out-of-scope edits detected and explained | Generic scope relevance can reduce precision | Partially supported | Improve objective-aware likely-file selection for `next-prompt` |

## Known blockers and dependencies

1. **External brownfield dogfood dependency**: Auralis clone access is required to complete the mandated real-project brownfield trial in this environment.
2. **Prompt quality dependency**: Contract quality still depends on acceptance/must-not-break specificity.
3. **Operator discipline dependency**: CES guardrails are strongest when users follow read-only-first and proof-before-approval sequences.

## Exit criteria linkage

This matrix is considered complete for a release when:

- README and Getting Started paths match these scenario flows,
- friction entries are logged for any failed or confusing step,
- greenfield trial evidence exists,
- brownfield trial evidence exists (or explicit environmental blocker is documented),
- and verification/proof checks are runnable and documented.
