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
- **Runtime execution boundary** — Runtime adapters pass an `--allowedTools` allowlist to the Claude CLI (default: `Read Grep Glob Edit Write`) and do **not** run with `acceptEdits`. `Bash` and `WebFetch` require explicit opt-in via `TaskManifest.allowed_tools`.
- **Runtime boundary disclosure** — Codex is invoked with `--sandbox danger-full-access` by default in this local deployment; CES records this as not workspace-scoped and not manifest-tool-allowlist-enforced, because the Codex adapter does not enforce `TaskManifest.allowed_tools`. Operators can explicitly set `CES_CODEX_SANDBOX=read-only` or `workspace-write`; invalid explicit sandbox values fail closed to `read-only` instead of expanding back to full-host access.
- **Evidence-gated builder flow** — Governed builder runs require a `ces:completion` claim, persist actual workspace deltas, and block unattended approval when completion evidence, manifest scope, or risk-aware sensor policy fails.
- **No secrets in task packages** — Secrets are never included in manifests, guide packs, or evidence packets. Subprocess stdout/stderr are scrubbed (regex on known secret prefixes and `KEY=VALUE` assignments) before persistence to `.ces/state.db` and before inclusion in evidence.
- **Kill switch** — CES LLM-dispatch paths are designed to check `kill_switch.is_halted()` before dispatch. Treat the kill switch as a fail-closed project control for CES-managed work, not as an operating-system process killer for already-running external runtime CLIs.
- **Adversarial review diversity** — Tier A review is strongest when the STRUCTURAL/SEMANTIC/RED_TEAM triad uses distinct underlying models. When fewer distinct providers are configured, the `degraded_model_diversity` flag is set on the aggregated review so evidence packets surface the degraded guarantee rather than silently trusting a non-adversarial result.

For the archival threat matrix, see [docs/Security_Audit.md](docs/Security_Audit.md).

---

## Threat Model

### What CES defends against

| Threat | Mitigation |
|--------|------------|
| Unauthorized modification of approved manifests | Ed25519 signature + on-disk public key; `ManifestManager.verify_manifest` returns `False` for tampered content. |
| Tampering with the audit ledger after the fact | HMAC-SHA256 chain with timing-safe comparison; forged entries fail internal ledger integrity verification. There is not yet a public `ces audit verify` command. |
| Host command execution via prompt-injected repo content (hostile README/comment/issue body steering the agent to run `rm -rf ~`) | Claude runs with `--allowedTools` dropping `Bash`/`WebFetch` by default and `--permission-mode default`; Codex defaults to `--sandbox danger-full-access` for this local deployment, so CES compensates by requiring explicit runtime side-effect acceptance, persisting the workspace delta, and surfacing runtime-boundary disclosures. Operators can explicitly set `CES_CODEX_SANDBOX=read-only` or `workspace-write`; invalid explicit values fail closed to `read-only`. |
| Secret exfiltration via LLM output (agent reads `.env` and echoes it) | Regex scrubber (`scrub_secrets_from_text`) redacts known prefixes (`sk-`, `AKIA`, `ghp_`, `xoxb-`) and `KEY=VALUE` assignments before persisting runtime output. |
| Environment secret leakage to LLM subprocesses | Allowlisted env filter (`build_subprocess_env`) strips non-runtime env vars before spawning `claude`/`codex`. |
| World-readable state on shared hosts | `.ces/keys/` is `0o700`; all key files and `.ces/state.db` are `0o600`. Verifiable via `ces doctor --security`. |
| Reviewer-model collusion (one model approving its own output) | Model-diversity validator; builder model excluded from reviewer roster; `degraded_model_diversity` flag when diversity can't be met. |
| In-flight emergencies | Kill switch halts CES-managed LLM dispatch before new work starts; it is not an operating-system process killer for already-running external runtime CLIs. |

### What CES does NOT defend against

These are **inherent limitations** of any governance layer that uses LLMs. Adopters should plan around them; CES does not claim to mitigate them:

| Non-goal | Why | What you can do |
|----------|-----|-----------------|
| **Prompt injection in reviewer prompts.** A diff that contains `"]}\nIgnore previous instructions..."` can steer a reviewer model to emit empty findings. | CES now labels review inputs as untrusted and treats malformed reviewer output as blocking, but LLMs can still be influenced by hostile content. | Lean on model diversity: Tier A requires three distinct models, each with different training. Watch the `degraded_model_diversity` flag on evidence packets. Do not ship Tier A changes without three real providers installed. |
| **Malicious code in the builder's output.** If a trusted builder intentionally writes backdoored code, nothing CES does will detect it. | CES is a governance layer, not a code scanner. It enforces *process* (classify → execute → review → approve), not *intent*. | Use review diversity + human approval gates for Tier A. Trust tier demotion (watch / constrained) on measured defect rate. |
| **Supply chain attacks on CES dependencies.** A malicious `pydantic` release could run arbitrary code at import time. | Python packaging does not have reliable reproducible-build guarantees. | Upper-bounded deps (`<N+2`) limit blast radius. Lockfile (`uv.lock`) pins exact versions. Use `uv sync --frozen` and audit `uv.lock` diffs in PRs. |
| **Physical/OS-level access to the developer machine.** If an attacker has shell on the box, they can read `.ces/keys/` regardless of mode. | POSIX permissions protect against other users on the same host, not against the host owner. | Encrypted disk, `ssh-agent` with short-lived keys, workplace MDM. Out of scope for CES itself. |
| **Network-level attacks on the LLM provider.** A MITM intercepting traffic to `api.anthropic.com` sees your prompts. | CES relies on the CLI provider's (Claude/Codex) TLS configuration. | Run CES behind a VPN for sensitive work; verify the CLI's `HTTPS_PROXY` trust chain; keep `SSL_CERT_FILE` pointed at your managed CA bundle. The `build_subprocess_env` allowlist preserves these vars. |
| **Runtime boundary gaps.** Different local CLIs expose different safety controls, and not every adapter can enforce manifest tool allowlists directly. | A governance layer still depends on the invoked runtime's boundary semantics. | Review `ces doctor --runtime-safety`, inspect persisted workspace deltas, and require explicit waivers for unattended approval when runtime-side effects cannot be fully enforced. |

### Adversarial-review diversity in depth

Tier A changes (highest risk per the classification engine) trigger a triad review: STRUCTURAL, SEMANTIC, and RED_TEAM reviewers, each with a distinct model. This is the primary mitigation for prompt injection in reviewer prompts:

- A hostile diff tuned to silence one model (say, Claude) still faces a reviewer running GPT, whose weights have not seen the same injection template verbatim.
- `bootstrap.register_cli_fallback` previously aliased one CLI to both `claude` and `gpt` prefixes when only one was installed, silently collapsing the triad to a single model. **0.1.2+ surfaces this via `AggregatedReview.degraded_model_diversity=True`** so the evidence packet records that the review was less adversarial than Tier A policy requires.

**Operator responsibility:** configure enough independent review providers for the risk tier you want to claim, then check `ces doctor` and the evidence packet. Do not approve a Tier A evidence packet whose `degraded_model_diversity` is `true` unless you have compensating controls (for example, mandatory human review).

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

Security-relevant changes are called out in [CHANGELOG.md](CHANGELOG.md) under `### Security` or the relevant Added/Changed/Fixed subsection. Notable past releases:

- **0.1.2** — B1/B2/B3 hardening: persistent signing keys, HMAC fail-closed, `acceptEdits` removed from the Claude runtime, stdout/stderr scrubbing, state DB permissions, kill-switch gap fixes, env allowlist for the CLI provider, `git diff` ref injection mitigation.
- **0.1.3** — `ces doctor --security` added; `ces init` now tightens `state.db` permissions at creation time.
- **0.1.6** — Public-maintenance guardrails added: Dependabot metadata, CodeQL analysis, localhost-only development compose ports, and refreshed public security documentation.
