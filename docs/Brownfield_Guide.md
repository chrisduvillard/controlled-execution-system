# Brownfield Guide: Applying CES to Existing Codebases

CES supports brownfield projects — existing codebases where legacy behavior must be preserved while making changes. This guide explains how CES detects, captures, and governs changes to existing systems.

Default posture: start read-only with `ces mri`, `ces next`, and `ces next-prompt`; run `ces build` only after the scope, acceptance criteria, and must-not-break behavior are explicit. Use expert brownfield commands only when you need to register, review, or promote specific legacy behaviors yourself.

Use the [Operator Playbook](Operator_Playbook.md) when you need the broader builder-first versus expert workflow boundary for a single request. This guide focuses on the brownfield-specific legacy-behavior path within that workflow.

## How Brownfield Detection Works

When you run `ces build`, CES automatically detects whether the project is greenfield or brownfield:

- **Greenfield**: empty directory (no source files outside `.ces/`, `.git/`, etc.)
- **Brownfield**: directory contains existing source files

```bash
# Read-only diagnosis before runtime execution
cd my-existing-project
ces mri
ces next
ces next-prompt "Add input validation to the API" \
  --acceptance "Invalid payloads return documented 4xx errors." \
  --must-not-break "Existing successful API requests and response schemas."

# Governed execution after the scope is explicit
ces build "Add input validation to the API"
ces verify
ces proof
```

CES will ask additional questions in brownfield mode:
- "What best reflects today's behavior?" — point CES to the source of truth
- "Which workflows matter most to keep working?" — identify critical flows that must not break

### Override Detection

```bash
# Force brownfield mode (useful for repos with only config files)
ces build "Add monitoring" --brownfield

# Start a new project from an empty folder instead of rewriting an existing repo
mkdir ../replacement-project && cd ../replacement-project
ces build --from-scratch "Create the replacement project"
```

## The Brownfield Review Flow

During a brownfield build, CES automatically:
1. Detects existing files and infers project structure
2. Asks about critical flows and the source of truth
3. Includes "must not break" constraints in the manifest
4. Reviews changes against existing behavior

If CES pauses for grouped brownfield review, use `ces continue` to resume the same builder session instead of starting over. Use `ces explain --view brownfield` when you want the current brownfield summary without opening the local store manually.

## Expert Brownfield Commands

For more granular control over legacy behavior, use the expert brownfield commands directly.

### Register Legacy Behaviors

Capture specific behaviors you want CES to track and preserve:

```bash
# Register an observed behavior
ces brownfield register \
  --system "billing-api" \
  --description "CSV export uses semicolons as delimiters for EU locale"
```

### List Pending Behaviors

```bash
# See all registered behaviors awaiting review
ces brownfield list
```

### Review and Decide

For each registered behavior, decide its disposition:

```bash
# Review a specific entry and choose one CLI-supported disposition.
ces brownfield review OLB-<entry-id> --disposition preserve
```

Dispositions:
- **preserve**: behavior must be maintained exactly as-is
- **change**: behavior will be updated as part of the change
- **retire**: behavior is intentionally being retired
- **new**: behavior is a newly accepted requirement
- **under_investigation**: behavior needs more review before promotion or retirement

### Promote to PRL

When a reviewed behavior should become a formal Product Requirements Ledger item:

```bash
# Promote a reviewed behavior to PRL
ces brownfield promote OLB-<entry-id>
```

This creates a PRL item with acceptance criteria derived from the legacy behavior description.

### Discard

When a registered behavior is no longer relevant:

```bash
# Remove a legacy behavior entry
ces brownfield discard OLB-<entry-id>
```

## Recommended Workflow

### First time applying CES to an existing repo

```bash
# 1. Start read-only. Understand the repo and generate a bounded contract.
cd my-existing-project
ces mri
ces next
ces next-prompt "Add feature X" \
  --acceptance "The feature has focused tests and documented run instructions." \
  --must-not-break "Existing public CLI/API behavior."

# 2. Run the governed build only after the boundaries are explicit.
ces build "Add feature X"
ces verify
ces proof

# 3. Resume the same builder-first request if CES paused for grouped review.
ces continue

# 4. Use expert workflow commands only for critical behaviors CES should track explicitly.
ces brownfield register --system "auth" --description "Session tokens expire after 30 minutes"
ces brownfield register --system "api" --description "Rate limit is 100 req/min per API key"

# 5. Review and promote the important ones.
ces brownfield list
ces brownfield review OLB-<entry-id> --disposition preserve
ces brownfield promote OLB-<entry-id>

# 6. Future builds will include these as constraints.
ces build "Change session handling"
```

### How to know brownfield protection worked

After a brownfield run, check:

```bash
ces explain --view brownfield
ces verify
ces proof
```

Look for:

- source-of-truth files or docs captured in the contract
- critical flows and must-not-break behaviors listed
- changed files inside the declared scope
- behavior deltas marked `added`, `modified`, `removed`, or `preserved`
- no unresolved `unknown` behavior deltas before approval
- `ces proof` status `proven` with recommendation `safe-to-review`
- `ces proof --json` reports `review_summary.binding_status == "matched"`

If you change the objective, source of truth, critical flows, must-not-break list, behavior dispositions, or verification commands after running `ces verify`, old proof is no longer reusable. `ces proof` will report `stale-objective`, `missing-binding`, or `mismatched`; rerun `ces verify --json` and then `ces proof` before approval.

### Ongoing brownfield governance

- Use `ces build` for day-to-day changes — brownfield mode is automatic
- Use `ces continue` when CES pauses during grouped brownfield review
- Use `ces brownfield register` when you discover undocumented behavior
- Use `ces brownfield review ... --disposition <preserve|change|retire|new|under_investigation>` for explicit expert decisions
- Use `ces brownfield promote` when behavior should become a formal requirement
- Use `ces explain --view brownfield` to see brownfield context for the current session

## What CES Preserves

In brownfield mode, CES adds extra governance:
- **Must-not-break constraints** flow into the manifest
- **Legacy behaviors** are visible to the review pipeline
- **Grouped review checkpoints** surface when changes touch registered behaviors
- **Evidence packets** include brownfield context for audit

This ensures AI agents cannot silently break existing functionality — every change is evaluated against documented behavior.
