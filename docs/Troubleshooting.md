# Troubleshooting

Common issues and how to resolve them.

## "Not inside a CES project"

**Error:**
```
Not inside a CES project. Run `ces init <name>` first or use `ces build` to auto-create one.
```

**Cause:** You ran a command that requires a `.ces/` directory, but none exists in the current directory or any parent.

**Fix:** Use `ces build` — it auto-creates `.ces/` on first run. Or explicitly run `ces init <name>` first.

---

## "No LLM provider configured"

**Error:**
```
RuntimeError: No LLM provider configured. Configure a local `claude` or `codex`
CLI, or enable CES_DEMO_MODE=1.
```

**Cause:** You used an LLM-assisted helper flow (for example `ces manifest --auto`) but CES could not find a CLI-backed provider and demo mode is off.

**Fix (option A):** Install/authenticate a supported CLI:
```bash
claude --version
# or
codex --version
```

**Fix (option B):** Use demo mode for dry-run without a real provider:
```bash
CES_DEMO_MODE=1 ces doctor
```

**Fix (option C):** Skip `--auto` — CES works without helper LLM access for most operations. Classification is deterministic (no LLM needed) and local runtime execution delegates to Codex CLI or Claude Code.

---

## "No supported runtime detected"

**Cause:** `ces build` could not find a local agent runtime (Codex CLI or Claude Code). `CES_DEMO_MODE` does not replace this requirement.

**Fix:** Install one of the supported runtimes:
- **Codex CLI**: install and authenticate `codex` so it is on `PATH`
- **Claude Code**: install and authenticate `claude` so it is on `PATH`

You can verify which runtime CES detects with:
```bash
ces doctor
```

---

## `ces doctor --runtime-safety` shows Codex as NOTICE

**Cause:** Codex is installed, but CES discloses it as a full-access local runtime boundary. This is not a missing runtime. It means the Codex adapter does not enforce manifest tool allowlists before subprocess launch.

**Fix:** Choose the boundary you want:
- Use Claude Code when you need CES to pass an explicit `--allowedTools` allowlist before the agent starts.
- Use Codex when you accept the full-access local runtime boundary, and pass `--accept-runtime-side-effects` for `ces build`, `ces continue`, or `ces execute` when prompted.
- Use `ces doctor --verify-runtime --runtime codex` only when you also want to probe Codex authentication.

---

## Legacy server-mode config detected

**Error:**
```
CES server mode is no longer supported.
```

**Cause:** Your `.ces/config.yaml` still contains `execution_mode: server` from an older CES setup.

**Fix:** Remove the legacy mode switch and keep only local project metadata:

```yaml
project_id: proj-...
preferred_runtime: codex
```

Then rerun `ces doctor` and `ces build`.

---

## Import errors after `pip install`

**Cause:** You are trying to use legacy or unsupported code paths from an older CES revision.

**Fix:** Reinstall the supported local CLI surface:

```bash
pip install controlled-execution-system
```

Core commands (`ces build`, `ces init`, `ces status`, `ces classify`, `ces manifest`) do not require server packages.

---

## Windows-specific issues

### Line ending warnings

```
warning: in the working copy of 'file.py', LF will be replaced by CRLF
```

**Fix:** This is a Git autocrlf warning, not a CES issue. It is safe to ignore, or configure Git:
```bash
git config core.autocrlf true
```

### Path length issues

If you see errors about paths being too long, enable long paths in Git:
```bash
git config core.longpaths true
```

---

## Tests failing with coverage below 90%

**Cause:** The CI enforces the 90% coverage floor, so new code without tests
will still drop coverage below the threshold.

**Fix:** Add tests for all new code. Run locally to check before pushing:
```bash
uv run pytest tests/ -m "not integration" --cov=ces --cov-fail-under=90 -q
```

---

## Still stuck?

- Check the [Getting Started guide](Getting_Started.md) for full setup instructions
- Check the [Operator Playbook](Operator_Playbook.md) for workflow guidance
- Open an issue at [GitHub Issues](https://github.com/chrisduvillard/controlled-execution-system/issues)
