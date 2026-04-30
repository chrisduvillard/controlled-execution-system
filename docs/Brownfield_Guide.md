# Brownfield Guide: Applying CES to Existing Codebases

CES supports brownfield projects — existing codebases where legacy behavior must be preserved while making changes. This guide explains how CES detects, captures, and governs changes to existing systems.

Default posture: start with the builder-first flow (`ces build`, `ces continue`, `ces explain --view brownfield`) and only drop into the expert workflow brownfield commands when you need to register, review, or promote specific legacy behaviors yourself.

Use the [Operator Playbook](Operator_Playbook.md) when you need the broader builder-first versus expert workflow boundary for a single request. This guide focuses on the brownfield-specific legacy-behavior path within that workflow.

## How Brownfield Detection Works

When you run `ces build`, CES automatically detects whether the project is greenfield or brownfield:

- **Greenfield**: empty directory (no source files outside `.ces/`, `.git/`, etc.)
- **Brownfield**: directory contains existing source files

```bash
# Auto-detection: CES sees existing files and enters brownfield mode
cd my-existing-project
ces build "Add input validation to the API" --yes
```

CES will ask additional questions in brownfield mode:
- "What best reflects today's behavior?" — point CES to the source of truth
- "Which workflows matter most to keep working?" — identify critical flows that must not break

### Override Detection

```bash
# Force brownfield mode (useful for repos with only config files)
ces build "Add monitoring" --brownfield --yes

# Force greenfield mode (useful when you want to ignore existing code)
ces build "Rewrite from scratch" --greenfield --yes
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
# Review a specific entry — decide to preserve, migrate, or remove
ces brownfield review OLB-<entry-id> --disposition preserve
```

Dispositions:
- **Preserve**: behavior must be maintained exactly as-is
- **Migrate**: behavior will be updated as part of the change
- **Remove**: behavior is intentionally being retired

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
# 1. Start with a builder-first run — CES auto-detects brownfield
cd my-existing-project
ces build "Add feature X" --yes

# 2. Resume the same builder-first request if CES paused for grouped review
ces continue --yes

# 3. After the first run, use expert workflow commands for any critical
#    behaviors CES should track explicitly
ces brownfield register --system "auth" --description "Session tokens expire after 30 minutes"
ces brownfield register --system "api" --description "Rate limit is 100 req/min per API key"

# 4. Review and promote the important ones
ces brownfield list
ces brownfield review OLB-<entry-id> --disposition preserve
ces brownfield promote OLB-<entry-id>

# 5. Future builds will include these as constraints
ces build "Change session handling" --yes
```

### Ongoing brownfield governance

- Use `ces build` for day-to-day changes — brownfield mode is automatic
- Use `ces continue` when CES pauses during grouped brownfield review
- Use `ces brownfield register` when you discover undocumented behavior
- Use `ces brownfield review ... --disposition <preserve|migrate|remove>` for explicit expert decisions
- Use `ces brownfield promote` when behavior should become a formal requirement
- Use `ces explain --view brownfield` to see brownfield context for the current session

## What CES Preserves

In brownfield mode, CES adds extra governance:
- **Must-not-break constraints** flow into the manifest
- **Legacy behaviors** are visible to the review pipeline
- **Grouped review checkpoints** surface when changes touch registered behaviors
- **Evidence packets** include brownfield context for audit

This ensures AI agents cannot silently break existing functionality — every change is evaluated against documented behavior.
