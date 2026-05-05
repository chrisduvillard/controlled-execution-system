# CES Secrets Management Guide

CES is a local builder-first tool. For supported usage, the only secrets you
need to manage are the local audit secret, manifest-signing keys, and whatever
credential material your chosen local runtime (`codex` or `claude`) already
uses on your machine.

## Secrets Inventory

| Secret | Location | Rotation Frequency | Impact if Compromised |
|--------|----------|-------------------|----------------------|
| `CES_AUDIT_HMAC_SECRET` | Environment variable | Yearly | Audit ledger integrity |
| Ed25519 private key | `.ces/keys/ed25519_private.key` | Yearly | Manifest signing |
| CLI auth material for `claude` / `codex` | Runtime-specific config | Per provider policy | Runtime account or subscription exposure |

## Secret Injection Methods

### Local shell

```bash
export CES_AUDIT_HMAC_SECRET=<unique-local-value>
export CES_DEMO_MODE=0
```

### Direnv or shell profile

Keep secrets out of the repo and load them from your shell environment:

```bash
export CES_AUDIT_HMAC_SECRET=<unique-local-value>
```

### External secret stores

If you run CES in CI or a managed workstation image, inject
`CES_AUDIT_HMAC_SECRET` through your platform's standard secret mechanism:

- AWS Secrets Manager
- HashiCorp Vault
- Azure Key Vault
- GitHub Actions / GitLab CI encrypted secrets

## Rotation Procedures

### Audit HMAC Secret Rotation

1. Record the current secret in your secure secret store.
2. Set `CES_AUDIT_HMAC_SECRET` to a new value.
3. Start a new CES session or rerun the relevant CES command.
4. Keep the old value available if you need to verify older audit chains during migration.

### Ed25519 Key Rotation

Move the old `.ces/keys/` directory to a secure backup location, then run
`ces init` again in the project root. CES will generate a new local keypair
under `.ces/keys/`. Keep the backup if you need to verify older manifest
signatures.

## Security Controls

- **No secrets in task packages**: runtime subprocess environments are allowlist-filtered by default.
- **No secrets in guide packs**: `GuidePackBuilder` does not embed runtime credentials.
- **No secrets in evidence packets**: evidence models do not carry secret fields.
- **Audit HMAC default detection**: `ces doctor` warns when development defaults are still in use.

## Legacy Note

Older CES revisions documented API keys, Redis passwords, and server-side secret
rotation. Those server-style deployment surfaces are no longer part of the
supported public product.
