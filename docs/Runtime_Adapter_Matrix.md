# Runtime Adapter Matrix

CES currently supports local execution through Codex CLI and Claude Code. Both are external CLIs; CES governs the workflow around them, not the provider itself.

| Boundary | Codex CLI | Claude Code |
|---|---|---|
| Prompt delivery | stdin pipe; prompt body is not passed in subprocess argv | stdin pipe with `-p`; prompt body is not passed in subprocess argv |
| Working directory | `-C <project-root>` | `--add-dir <project-root>` and subprocess cwd |
| Default tool boundary | Codex sandbox mode, default `workspace-write` | `--permission-mode default` plus allowed tools |
| Manifest tool allowlist | Not directly enforced by CES before subprocess launch | Passed through `--allowedTools`; default excludes `Bash` and `WebFetch` |
| Runtime side-effect consent | Required for unsafe unattended approval paths when boundary cannot be fully enforced | Still evidence-gated; tool allowlist is stronger |
| Runtime auth variables | OpenAI/Codex-specific variables only | Anthropic/Claude-specific variables only |
| Transcript handling | Full redacted transcript under `.ces/runtime-transcripts/`; capped stdout excerpt for CLI/SQLite | Capped stdout/stderr excerpts; no separate transcript path currently returned |
| Network behavior | Determined by Codex CLI/provider configuration | Determined by Claude Code/provider configuration |
| MCP support | Runtime-dependent; disclose unsupported grounding | Runtime-dependent; disclose unsupported grounding |

## Operator Guidance

Prefer Claude Code when a task requires a runtime-enforced tool allowlist. Prefer Codex only when you accept its disclosed sandbox behavior and will review the workspace delta before approval.

Before mutating work:

```bash
ces doctor --runtime-safety
```

Before approval:

```bash
ces verify
ces proof
```

Do not treat runtime exit code 0 as approval. CES approval is based on completion claims, independent verification, workspace deltas, sensor policy, and human review.
