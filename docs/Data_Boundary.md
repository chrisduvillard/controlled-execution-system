# CES Data and Credential Boundary

CES is a local-first governance CLI. It stores project evidence locally, launches a selected local runtime, and relies on that runtime's own account and network behavior.

## What CES Stores Locally

CES writes project-local state under `.ces/`:

| Path | Contents |
|---|---|
| `.ces/state.db` | manifests, builder sessions, runtime execution excerpts, evidence summaries, approvals, and audit entries |
| `.ces/keys/` | project-local manifest signing keys and audit HMAC secret |
| `.ces/runtime-transcripts/` | full redacted runtime transcripts and runtime diagnostic artifacts |
| `.ces/artifacts/` and `.ces/exports/` | proof cards, diagnostics, reports, and exported evidence |

`.ces/` is ignored by default. Treat it as sensitive local project state unless you intentionally export a redacted artifact.

## What Goes to the Runtime

When `ces build` launches Codex CLI or Claude Code, the runtime receives:

- the task prompt and completion contract over stdin, not subprocess argv
- the selected project working directory
- runtime-specific auth/config environment variables required by that CLI
- the repository files that the runtime reads through its own tools

The runtime provider may receive prompt content, repository snippets, command output, and tool results according to that runtime's normal behavior. CES does not proxy or host those calls.

## Environment Variables

CES builds a restricted subprocess environment. It strips unrelated host secrets such as AWS credentials, database URLs, generic GitHub tokens, and unrelated API keys.

Runtime-specific variables still pass through:

| Runtime | Examples |
|---|---|
| Codex | `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_ORG_ID`, `OPENAI_PROJECT`, `CODEX_HOME`, sandbox settings |
| Claude | `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `CLAUDE_CODE` |
| Shared runtime needs | `PATH`, `HOME`, locale, selected proxy/TLS variables after credential stripping |

Use isolated runtime credentials for sensitive work. Do not assume CES can prevent a runtime CLI from sending data to its configured provider.

## Redaction Before Persistence

CES redacts known secret-like values before writing runtime stdout/stderr excerpts, evidence payloads, review artifacts, and transcripts. Covered examples include:

- OpenAI-style `sk-` tokens
- GitHub `ghp_`, `ghs_`, and `github_pat_` tokens
- GitLab `glpat-` tokens
- Slack `xoxb-`, `xoxp-`, `xoxc-`, `xoxa-`, `xoxr-`, `xoxs-`, and `xapp-` tokens
- AWS access-key IDs
- JWT-looking values
- credential-bearing URLs such as `scheme://user:password@host`
- Google service-account private key fields
- PEM private key blocks
- secret/key/token/password assignment values

Redaction is a defense-in-depth control, not a guarantee that every possible secret format is recognized. CI also runs gitleaks using `.gitleaks.toml`; operators should run full-history scans before public release.

## What CES Does Not Guarantee

- CES is not an OS sandbox.
- CES is not a hosted control plane.
- CES does not manage runtime accounts or provider-side retention.
- CES does not guarantee a runtime cannot read files outside the intended task if that runtime's own sandbox allows it.
- CES does not make raw runtime output safe to share without operator review.

Use `ces doctor --runtime-safety`, inspect workspace deltas, run `ces verify`, and review `ces proof` before approving work.
