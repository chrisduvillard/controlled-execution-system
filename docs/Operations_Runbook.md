# CES Operations Runbook

Use builder-first commands (`ces build`, `ces continue`, `ces explain`, `ces explain --view brownfield`, `ces status`) for one active delivery request. Use the expert operations surfaces in this runbook when you need system-wide visibility, incident response, or audit inspection: `ces status --expert`, `ces status --expert --watch`, `ces audit --limit 20`, and `ces emergency declare "Security incident detected"`.

Use the [Operator Playbook](Operator_Playbook.md) when you need the builder-first versus expert workflow boundary for a single request, and the [Brownfield Guide](Brownfield_Guide.md) when the question is legacy-behavior governance rather than system-wide operations.

## Emergency Procedures

### Kill Switch Activation

The kill switch halts specific activity classes without shutting down the system.

```bash
# Via CLI (interactive confirmation)
ces emergency declare "Security incident detected" \
  --file src/payments/checkout.py

# Non-interactive form for automation or drills
ces emergency declare "Security incident detected" \
  --file src/payments/checkout.py \
  --yes

# If the CLI is unavailable, stop the local runtime process and preserve
# `.ces/state.db` plus `.ces/keys/` for post-incident audit reconciliation.
```

Avoid editing `.ces/state.db` directly during normal incidents. Direct database
changes bypass the normal emergency-service audit trail and should be treated as
manual forensic recovery, not the supported operator path.

**Activity classes:** `task_issuance`, `merges`, `deploys`, `spawning`, `tool_classes`, `truth_writes`, `registry_writes`

### Kill Switch Recovery

Kill switch recovery is human-only. CES currently exposes emergency declaration on the public CLI, but not a public `ces emergency resolve` command. Coordinate recovery through the operator-owned service path, then confirm the expected audit trail from the CLI:

```bash
# Watch the full expert status view during an active incident
ces status --expert --watch

# Confirm the declaration and recovery events after recovery
ces audit --event-type kill_switch --limit 20
ces audit --event-type recovery --limit 20
ces audit --event-type escalation --limit 20
```

Recovery should leave these compensating controls in the audit trail:
1. Kill switch recovery for the affected activity class
2. 24-hour review escalation
3. Retroactive evidence packet generation

### Audit Ledger Inspection

The public CLI currently supports audit inspection queries. End-to-end HMAC integrity verification remains a deployment/database procedure.

```bash
# Inspect recent audit activity around an incident window
ces audit --after "2026-04-08T00:00:00+00:00" --limit 100

# Filter down to the event stream you need
ces audit --event-type kill_switch --limit 20
ces audit --event-type recovery --limit 20
```

## Monitoring Alerts

| Alert | Condition | Action |
|-------|-----------|--------|
| Kill switch auto-triggered | Any of 5 auto-triggers fired | Check audit log, assess if genuine threat |
| SLA breach | Emergency task exceeds 15-minute SLA | Escalate to Ops Approver |
| High escape rate | Visible check pass rate rising while escapes increase | Activate anti-gaming detection |
| Audit chain broken | HMAC verification fails | Investigate potential tampering |

## Routine Operations

### Daily
- Review the full expert status view: `ces status --expert`
- During live incidents, tail the expert status view: `ces status --expert --watch`
- Review recent audit activity: `ces audit --limit 20`

### Weekly
- Review kill-switch and recovery events: `ces audit --event-type kill_switch --limit 20` and `ces audit --event-type recovery --limit 20`
- Review trust status trends: `ces status --expert`

### Monthly
- Review and update classification rules if needed
- Reconfirm workstation rollout guidance in the Production Deployment Guide
