# Security Audit Report - Phase 01: Foundation

**Audit Date:** 2026-04-06
**ASVS Level:** 1
**Block On:** critical
**Auditor:** GSD Security Auditor (automated)

## Summary

**Phase:** 01 -- Foundation
**Threats Closed:** 33/33
**Open Threats:** 0
**Result:** SECURED

This report is archival evidence for the Phase 01 foundation audit. It avoids
line-number-specific claims so the public documentation does not become stale
when implementation files move. Use [SECURITY.md](../SECURITY.md) for the
current security policy and reporting process.

---

## Threat Verification

### Plan 01 -- Core Models & Crypto

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-01-01 | Tampering | mitigate | CLOSED | `src/ces/shared/crypto.py` uses Ed25519 primitives from `cryptography` and timing-safe HMAC comparison. |
| T-01-02 | Information Disclosure | mitigate | CLOSED | `.gitignore` excludes `.env` while preserving `.env.example`, which contains only placeholder development values. |
| T-01-03 | Information Disclosure | mitigate | CLOSED | `.gitignore` excludes private key files and CES key directories. |
| T-01-04 | Tampering | mitigate | CLOSED | `canonical_json` in `src/ces/shared/crypto.py` serializes with sorted keys and stable separators; `tests/unit/test_crypto.py` verifies determinism. |
| T-01-05 | Spoofing | mitigate | CLOSED | `GovernedArtifactBase` rejects approved artifacts that do not carry a signature. |

### Plan 02 -- Schema Models

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-02-01 | Tampering | mitigate | CLOSED | Domain models use Pydantic v2 strict/frozen base configuration plus typed constraints such as bounds and literal discriminators. |
| T-02-02 | Elevation of Privilege | mitigate | CLOSED | Truth artifact models extend `GovernedArtifactBase`, which enforces signatures for approved artifacts. |
| T-02-03 | Information Disclosure | accept | CLOSED | Accepted risk. Optional audit fields such as `cost_impact` and `model_version` may contain operational data, but audit entries are internal-only. |
| T-02-04 | Tampering | mitigate | CLOSED | Truth artifact unions use `schema_type` discriminators with unique literal values per artifact model. |

### Plan 03 -- Intake Models

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-03-01 | Elevation of Privilege | mitigate | CLOSED | `TaskManifest` validates file and tool scopes with typed lists, positive token budgets, and MANIF-07 downgrade prevention in the manifest manager. |
| T-03-02 | Spoofing | mitigate | CLOSED | `TaskManifest` enforces independent classification and rejects manifests where the implementer is the sole classifier. |
| T-03-03 | Tampering | mitigate | CLOSED | Intake models reject material `FLAG` assumptions; material questions must use the blocking category. |
| T-03-04 | Denial of Service | accept | CLOSED | Accepted risk. Token budget upper bounds are enforced at the service layer rather than the model layer. |

### Plan 04 -- Database

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-04-01 | Tampering | mitigate | CLOSED | Local audit writes go through append-only repository methods; `AuditLedgerService` computes an HMAC chain and the compatibility Postgres path retains an audit-modification trigger. |
| T-04-02 | Injection | mitigate | CLOSED | Local audit writes use parameterized SQLite statements; compatibility SQLAlchemy repositories use ORM statements instead of raw SQL. |
| T-04-03 | Information Disclosure | mitigate | CLOSED | `.gitignore` excludes `.env`; the published local-first runtime does not open a network database. Compatibility-only development database defaults are not used by the wheel. |
| T-04-04 | Tampering | accept | CLOSED | Accepted risk for compatibility migrations. The supported local-first product writes to `.ces/state.db`, and local-store initialization tightens file permissions. |

### Plan 05 -- Classification

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-05-01 | Elevation of Privilege | mitigate | CLOSED | Classification uses exact deterministic rule lookup in `src/ces/control/services/classification.py`; control-plane code does not call LLM APIs. |
| T-05-02 | Tampering | mitigate | CLOSED | Invalidation uses SHA-256 hashing through `src/ces/shared/crypto.py` with deterministic canonical JSON input. |
| T-05-03 | Repudiation | mitigate | CLOSED | Classification rules are immutable dataclass records and classification decisions are written to the audit ledger by `ManifestManager`. |

### Plan 06 -- Audit Ledger

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-06-01 | Tampering | mitigate | CLOSED | Audit APIs expose append/read operations without update/delete paths; the compatibility database path also protects audit rows with a trigger. |
| T-06-02 | Tampering | mitigate | CLOSED | `AuditLedgerService` computes HMAC-SHA256 entry hashes and verifies the full chain with timing-safe comparison helpers from `src/ces/shared/crypto.py`. |
| T-06-03 | Repudiation | mitigate | CLOSED | `append_event` records event type, actor, actor type, timestamp, rationale, and hash-chain links on each ledger entry. |
| T-06-04 | Information Disclosure | mitigate | CLOSED | The ledger HMAC secret is held in service memory and never serialized into audit entries. |

### Plan 07 -- Workflow & Trust

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-07-01 | Elevation of Privilege | mitigate | CLOSED | `WorkflowEngine` defines explicit state-machine transitions and invalid transitions raise `TransitionNotAllowed`. |
| T-07-02 | Tampering | mitigate | CLOSED | Workflow transitions are logged to the audit ledger and state can be reconstructed from persisted workflow values. |
| T-07-03 | Elevation of Privilege | mitigate | CLOSED | `PolicyEngine` checks forbidden files/tools before allowlists and validates every proposed file/tool action. |
| T-07-04 | Spoofing | mitigate | CLOSED | Promotion validation rejects non-draft artifacts, empty approvers, and owner self-approval. |
| T-07-05 | Denial of Service | accept | CLOSED | Accepted risk. Retry transitions are bounded by `max_retries`, and cancellation paths exist. |

### Plan 08 -- Manifest Manager

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-08-01 | Spoofing | mitigate | CLOSED | `ManifestManager` signs manifests with Ed25519 and verifies signatures with the injected public key. |
| T-08-02 | Tampering | mitigate | CLOSED | Manifest creation hashes referenced truth artifacts and validation recomputes those hashes through the invalidation tracker. |
| T-08-03 | Elevation of Privilege | mitigate | CLOSED | Manifest validation rejects draft truth artifacts referenced by governed manifests. |
| T-08-04 | Spoofing | mitigate | CLOSED | Manifest classification rejects implementer-as-classifier both at the model layer and service layer. |
| T-08-05 | Repudiation | mitigate | CLOSED | Manifest creation, signing, classification, and invalidation events are recorded through the HMAC-backed audit ledger. |

---

## Accepted Risks Log

| Threat ID | Category | Component | Risk Description | Justification |
|-----------|----------|-----------|------------------|---------------|
| T-02-03 | Information Disclosure | AuditEntry optional fields | Optional fields such as `cost_impact` and `model_version` may contain operational data. | Low risk -- audit entries are internal-only and not exposed to external consumers. |
| T-03-04 | Denial of Service | token_budget | Budget is a positive integer with no upper bound at the model layer. | Upper bound enforcement deferred to service layer. Low risk -- only consumed by authorized agents. |
| T-04-04 | Tampering | Migration scripts | Alembic migrations run with elevated database privileges. | Standard practice. Migration files are committed to git for code review. |
| T-07-05 | Denial of Service | Retry exhaustion | Retry transitions are bounded but could be attempted up to `max_retries` times. | Retry guard limits retries to `max_retries` and cancellation paths exist. |

---

## Unregistered Flags

None. No `## Threat Flags` sections were found in any SUMMARY.md files for
Phase 01.

---

## Verification Methodology

- **ASVS Level:** 1 (standard)
- **Approach:** For each `mitigate` threat, searched implementation files for
  the declared mitigation pattern. For each `accept` threat, verified
  documentation in this accepted risks log.
- **Scope:** 33 threats across 8 plans (Plans 01-08 of Phase 01 Foundation).
- **Implementation files:** Read-only during the original audit.
- **Coverage:** All 29 `mitigate` threats verified with code evidence. All 4
  `accept` threats documented with justification.
