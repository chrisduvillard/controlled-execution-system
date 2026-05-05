# CES Secrets Management Guide

CES is a local builder-first tool. For supported usage, the secrets you manage
are the project-local audit secret, manifest-signing keys, and whatever
credential material your chosen local runtime (`codex` or `claude`) already uses
on your machine.

CES does **not** require server-style API keys, Redis passwords, Postgres
credentials, or a hosted secret manager for normal local operation.

## Secrets Inventory

| Secret | Default location | Rotation Frequency | Impact if Compromised |
|--------|------------------|-------------------|----------------------|
| Audit HMAC secret | `.ces/keys/audit.hmac` | Yearly or when operator access changes | Audit ledger integrity |
| Ed25519 private key | `.ces/keys/ed25519_private.key` | Yearly or when operator access changes | Manifest signing |
| CLI auth material for `claude` / `codex` | Runtime-specific config | Per provider policy | Runtime account or subscription exposure |

## Local Secret Creation

Run CES initialization in each project root:

```bash
ces init
```

`ces init` creates `.ces/keys/` and writes a random audit HMAC secret to
`.ces/keys/audit.hmac` with file permissions intended for local use. Keep
`.ces/keys/` out of source control.

The `CES_AUDIT_HMAC_SECRET` environment variable is an optional override, not the
normal local setup path. Use it only when a managed workstation image, CI job, or
other controlled environment must inject the audit secret externally instead of
using the project-local `.ces/keys/audit.hmac` file.

## Managed/CI Secret Injection

If you run CES in managed/CI environments, inject `CES_AUDIT_HMAC_SECRET` through
your platform's standard secret mechanism and keep it out of logs:

- AWS Secrets Manager
- HashiCorp Vault
- Azure Key Vault
- GitHub Actions / GitLab CI encrypted secrets

Example CI shape:

```bash
env CES_AUDIT_HMAC_SECRET=[REDACTED] ces doctor --security
```

Do not commit real values or paste them into issue reports, PR descriptions,
transcripts, or exported evidence. Replace credential-like values with
`[REDACTED]`.

## Rotation Procedures

### Audit HMAC Secret Rotation

For local projects using the default file-backed model:

1. Stop active CES operations for the project.
2. Move the current `.ces/keys/audit.hmac` to a secure backup location if older
   audit-chain verification must remain possible.
3. Write a new random value to `.ces/keys/audit.hmac` with owner-only file
   permissions, for example `chmod 0600 .ces/keys/audit.hmac` after writing it.
4. Run `ces doctor --security` before resuming work.

Do not expect `ces init` to regenerate keys inside an existing `.ces/` directory;
it is intentionally conservative when project state already exists.

For managed/CI environments that deliberately override with
`CES_AUDIT_HMAC_SECRET`:

1. Rotate the secret in the external secret store.
2. Restart the job, shell, or managed workstation profile so the new value is
   injected.
3. Keep the old value available only if you need to verify older audit chains
   during migration.

### Ed25519 Key Rotation

Move the old `.ces/keys/` directory to a secure backup location, write a new
keypair under `.ces/keys/`, and keep owner-only permissions on private key
material. If you prefer to let CES recreate all local key material, first back
up the full `.ces/` directory and remove project state deliberately; `ces init`
will not overwrite an existing `.ces/` directory. Keep the backup if you need to
verify older manifest signatures.

## Security Controls

- **No secrets in task packages**: runtime subprocess environments are
  allowlist-filtered by default.
- **No secrets in guide packs**: `GuidePackBuilder` does not embed runtime
  credentials.
- **No secrets in evidence packets**: evidence models do not carry secret fields.
- **Audit HMAC file checks**: `ces doctor --security` checks local key material
  and warns when an explicitly supplied `CES_AUDIT_HMAC_SECRET` override uses an
  unsafe value.

## Legacy Note

Older CES revisions documented API keys, Redis passwords, and server-side secret
rotation. Those server-style deployment surfaces are no longer part of the
supported public product.
