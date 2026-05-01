# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in CES, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, please use [GitHub's private vulnerability reporting](https://github.com/chrisduvillard/controlled-execution-system/security/advisories/new) to submit your report.

You should receive a response within 72 hours. We will work with you to understand the issue and address it promptly.

---

## Security Model

CES is a local-first governance layer between "an AI wrote this code" and "this code is in production." It enforces governance through deterministic controls backed by cryptographic primitives:

- **Manifest signing** — Ed25519 signatures on task manifests (D-13). Keys are generated and persisted per-project in `.ces/keys/` at `ces init` time and loaded from disk on every CLI invocation, so signatures produced by one command can be verified by later commands.
- **Audit chain integrity** — HMAC-SHA256 hash chain on the append-only audit ledger (T-06-02). Each project gets a 32-byte random HMAC secret at `ces init`, stored mode `0600` under `.ces/keys/audit.hmac`.
- **Sandboxed execution** — Runtime adapters pass an `--allowedTools` allowlist to the Claude CLI (default: `Read Grep Glob Edit Write`) and do **not** run with `acceptEdits`. `Bash` and `WebFetch` require explicit opt-in via `TaskManifest.allowed_tools`.
- **Runtime boundary disclosure** — Codex is invoked with `--sandbox workspace-write`; CES records this as workspace-scoped but not manifest-tool-allowlist-enforced, because the Codex adapter does not enforce `TaskManifest.allowed_tools`.
- **Evidence-gated builder flow** — Governed builder runs require a `ces:completion` claim, persist actual workspace deltas, and block unattended approval when completion evidence, manifest scope, or risk-aware sensor policy fails.
- **No secrets in task packages** — Secrets are never included in manifests, guide packs, or evidence packets. Subprocess stdout/stderr are scrubbed (regex on known secret prefixes and `KEY=VALUE` assignments) before persistence to `.ces/state.db` and before inclusion in evidence.
- **Kill switch** — Every LLM-calling service checks `kill_switch.is_halted()` before dispatch. Flipping the kill switch halts all in-flight and subsequent LLM work project-wide.
- **Adversarial review diversity** — Tier A review requires three distinct underlying models for the STRUCTURAL/SEMANTIC/RED_TEAM triad. When fewer distinct providers are installed, the `degraded_model_diversity` flag is set on the aggregated review so evidence packets surface the degraded guarantee rather than silently trusting a non-adversarial result.

For the archival threat matrix, see [docs/Security_Audit.md](docs/Security_Audit.md).

---

## Threat Model

### What CES defends against

| Threat | Mitigation |
|--------|------------|
| Unauthorized modification of approved manifests | Ed25519 signature + on-disk public key; `ManifestManager.verify_manifest` returns `False` for tampered content. |
| Tampering with the audit ledger after the fact | HMAC-SHA256 chain with timing-safe comparison; a forged entry breaks the chain on the next `audit verify`. |
| Host command execution via prompt-injected repo content (hostile README/comment/issue body steering the agent to run `rm -rf ~`) | Claude runs with `--allowedTools` dropping `Bash`/`WebFetch` by default and `--permission-mode default`; Codex runs under `--sandbox workspace-write`, and CES compensates by persisting the workspace delta and surfacing runtime-boundary disclosures. |
| Secret exfiltration via LLM output (agent reads `.env` and echoes it) | Regex scrubber (`scrub_secrets_from_text`) redacts known prefixes (`sk-`, `AKIA`, `ghp_`, `xoxb-`) and `KEY=VALUE` assignments before persisting runtime output. |
| Environment secret leakage to LLM subprocesses | Allowlisted env filter (`build_subprocess_env`) strips non-runtime env vars before spawning `claude`/`codex`. |
| World-readable state on shared hosts | `.ces/keys/` is `0o700`; all key files and `.ces/state.db` are `0o600`. Verifiable via `ces doctor --security`. |
| Reviewer-model collusion (one model approving its own output) | Model-diversity validator; builder model excluded from reviewer roster; `degraded_model_diversity` flag when diversity can't be met. |
| In-flight emergencies | Kill switch halts all LLM dispatch across control + harness services. |

### What CES does NOT defend against

These are **inherent limitations** of any governance layer that uses LLMs. Adopters should plan around them; CES does not claim to mitigate them:

| Non-goal | Why | What you can do |
|----------|-----|-----------------|
| **Prompt injection in reviewer prompts.** A diff that contains `"]}\nIgnore previous instructions..."` can steer a reviewer model to emit empty findings. | CES now labels review inputs as untrusted and treats malformed reviewer output as blocking, but LLMs can still be influenced by hostile content. | Lean on model diversity: Tier A requires three distinct models, each with different training. Watch the `degraded_model_diversity` flag on evidence packets. Do not ship Tier A changes without three real providers installed. |
| **Malicious code in the builder's output.** If a trusted builder intentionally writes backdoored code, nothing CES does will detect it. | CES is a governance layer, not a code scanner. It enforces *process* (classify → execute → review → approve), not *intent*. | Use review diversity + human approval gates for Tier A. Trust tier demotion (watch / constrained) on measured defect rate. |
| **Supply chain attacks on CES dependencies.** A malicious `pydantic` release could run arbitrary code at import time. | Python packaging does not have reliable reproducible-build guarantees. | Upper-bounded deps (`<N+2`) limit blast radius. Lockfile (`uv.lock`) pins exact versions. Use `uv sync --frozen` and audit `uv.lock` diffs in PRs. |
| **Physical/OS-level access to the developer machine.** If an attacker has shell on the box, they can read `.ces/keys/` regardless of mode. | POSIX permissions protect against other users on the same host, not against the host owner. | Encrypted disk, `ssh-agent` with short-lived keys, workplace MDM. Out of scope for CES itself. |
| **Network-level attacks on the LLM provider.** A MITM intercepting traffic to `api.anthropic.com` sees your prompts. | CES relies on the CLI provider's (Claude/Codex) TLS configuration. | Run CES behind a VPN for sensitive work; verify the CLI's `HTTPS_PROXY` trust chain; keep `SSL_CERT_FILE` pointed at your managed CA bundle. The `build_subprocess_env` allowlist preserves these vars. |
| **Agent sandbox escape.** Docker sandbox defaults (`network_mode="none"`, `read_only=True`, `mem_limit=512m`) follow defense-in-depth best practice but Docker itself is not a hardened sandbox. | Container breakout CVEs surface regularly. | Do not run CES on hosts that store other sensitive workloads. The kill switch (per-project) and manifest expiry (per-task) bound blast radius. |

### Adversarial-review diversity in depth

Tier A changes (highest risk per the classification engine) trigger a triad review: STRUCTURAL, SEMANTIC, and RED_TEAM reviewers, each with a distinct model. This is the primary mitigation for prompt injection in reviewer prompts:

- A hostile diff tuned to silence one model (say, Claude) still faces a reviewer running GPT, whose weights have not seen the same injection template verbatim.
- `bootstrap.register_cli_fallback` previously aliased one CLI to both `claude` and `gpt` prefixes when only one was installed, silently collapsing the triad to a single model. **0.1.2+ surfaces this via `AggregatedReview.degraded_model_diversity=True`** so the evidence packet records that the review was less adversarial than Tier A policy requires.

**Operator responsibility:** install two or more CLI providers (`claude` AND `codex`) before running Tier A reviews. Check `ces doctor` for provider availability. Do not approve a Tier A evidence packet whose `degraded_model_diversity` is `true` unless you have compensating controls (e.g. mandatory human review).

---

## Verifying your installation

Run `ces doctor --security` inside a CES project to verify the shipped posture:

```
ces doctor --security
```

The check confirms:

- `.ces/keys/` is `0o700`
- `.ces/keys/ed25519_private.key` and `.ces/keys/audit.hmac` exist and are `0o600`
- `.ces/keys/ed25519_public.key` exists
- `.ces/state.db` is `0o600`
- `CES_AUDIT_HMAC_SECRET` is not set to the hardcoded development default

Exit code is 0 on full pass, 1 otherwise. `ces --json doctor --security` emits the same result as machine-readable JSON for CI wiring.

---

## Operator responsibilities

CES's guarantees presume the operator takes four actions:

1. **Run `ces init` once per project.** This generates the signing keypair and HMAC secret. Do not copy `.ces/keys/` between projects; each project gets its own crypto material.
2. **Protect `.ces/keys/`.** Do not commit it (already in `.gitignore`), do not share the directory, do not re-use it across hosts. Rotation is a delete-and-re-init operation (note: this invalidates all prior signatures for that project).
3. **Install multiple CLI providers for Tier A.** Without distinct providers, adversarial diversity degrades to "the same model reviewing itself" and the `degraded_model_diversity` flag fires. Check `ces doctor` and the evidence packet.
4. **Keep the audit ledger append-only.** CES enforces this in code, but direct `.ces/state.db` edits bypass the enforcement. Treat the file like you would any cryptographic ledger.

---

## Changelog

Security-relevant changes are called out in [CHANGELOG.md](CHANGELOG.md) under a `### Security` subsection of each release. Notable past releases:

- **0.1.2** — B1/B2/B3 hardening: persistent signing keys, HMAC fail-closed, `acceptEdits` removed from the Claude runtime, stdout/stderr scrubbing, state DB permissions, kill-switch gap fixes, env allowlist for the CLI provider, `git diff` ref injection mitigation.
- **0.1.3** — `ces doctor --security` added; `ces init` now tightens `state.db` permissions at creation time.
- **0.1.6** — Public-maintenance guardrails added: Dependabot metadata, CodeQL analysis, localhost-only development compose ports, and refreshed public security documentation.
