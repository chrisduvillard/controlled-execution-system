# CES Local State Operations Guide

CES now operates as a local builder-first tool. The supported persistence model
is the local SQLite state file at `.ces/state.db`, along with `.ces/keys/` and
generated artifacts under `.ces/artifacts/`.

## Local State Overview

| Path | Purpose |
|------|---------|
| `.ces/state.db` | Local workflow, manifest, audit, and project state |
| `.ces/keys/` | Manifest-signing keypair |
| `.ces/artifacts/` | Generated reports and supporting outputs |

## Backup Strategy

### Simple file backup

```bash
cp .ces/state.db /safe/location/state-$(date +%Y%m%d-%H%M%S).db
cp -R .ces/keys /safe/location/ces-keys-$(date +%Y%m%d-%H%M%S)
```

### Full `.ces/` snapshot

```bash
tar -czf ces-state-$(date +%Y%m%d-%H%M%S).tar.gz .ces/
```

## Restore

```bash
cp /safe/location/state.db .ces/state.db
cp -R /safe/location/keys .ces/keys
```

If the restored state is older than your current working tree, rerun:

```bash
ces status --expert
```

to confirm manifest and audit state before continuing.

## Audit Ledger Integrity

Verify the local audit chain with:

```bash
ces audit --limit 20
```

There is not currently a public `ces audit --verify-integrity` command. Integrity
verification is an operator/database procedure for now; see the Operations
Runbook before making incident-response claims from raw database rows.

## Resetting Local State

If you intentionally want a fresh CES project, remove or archive `.ces/` and
reinitialize:

```bash
mv .ces .ces.backup.$(date +%Y%m%d-%H%M%S)
ces init
```

Do not delete `.ces/` if you still need prior audit history.

## Legacy Note

Older CES revisions documented PostgreSQL schemas, Alembic migrations, and
server-style restore procedures. Those database operations are no longer part
of the supported public workflow.
