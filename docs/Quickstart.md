# 5-Minute Quickstart

Get from zero to a governed AI build in under 5 minutes. CES is a local
builder-first tool with SQLite project state and no hosted control plane.

## Prerequisites

- Python 3.12 or 3.13
- [uv](https://docs.astral.sh/uv/) (install: `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- A supported local runtime: Codex CLI or Claude Code

## 1. Install CES

From source:

```bash
git clone https://github.com/chrisduvillard/controlled-execution-system.git
cd controlled-execution-system
uv sync
uv run ces --help
```

For day-to-day use, install the published package from PyPI:

```bash
uv tool install controlled-execution-system
```

If your default `python3` is Python 3.11, a direct `pip install controlled-execution-system` can stop with `No matching distribution` because CES requires Python 3.12 or 3.13. Use uv with an explicit supported interpreter, such as Python 3.13:

```bash
uv tool install --python 3.13 controlled-execution-system
```

## Before you start

CES governs a local AI runtime; it does not ship one. Make sure Codex CLI or
Claude Code is installed, authenticated, and available on `PATH` before running
`ces build`. If a runtime is missing or unauthenticated, CES will still preserve
local state and diagnostics, but the implementation step cannot complete.

Everything CES writes stays in your project under `.ces/`: SQLite state, audit
records, evidence, reports, runtime transcripts, and local keys. Keep `.ces/`
untracked unless you intentionally share an exported report.

## 2. Verify your runtime

```bash
ces doctor
ces doctor --runtime-safety
# Optional: may contact the runtime provider and consume a small request.
ces doctor --verify-runtime --runtime all
```

Bare `ces doctor` is a preflight check for Python, installed providers, extras,
and project setup. Use `--runtime-safety` to inspect runtime-boundary disclosures:
Claude should appear as allowlist-enforced when available; Codex appears as a
`NOTICE`, not a missing runtime, because CES intentionally discloses it as a
full-access adapter that requires explicit side-effect consent for execution.
Use `--verify-runtime` only when you deliberately want CES to probe Codex/Claude
authentication before a build.

`ces build` and `ces execute` require a supported local runtime. `CES_DEMO_MODE=1`
only affects optional LLM-backed helper steps; it does not replace Codex CLI or
Claude Code for local execution.

Codex is a full-access local runtime for CES purposes. If Codex is selected,
`ces build`, `ces continue`, and `ces execute` stop before subprocess launch
until you pass `--accept-runtime-side-effects`. That flag is explicit consent
for the runtime boundary; choose Claude Code when you need tool allowlist
enforcement before the agent starts.

## 3. Plan or start your project

For a brand-new app, start with the read-only guided front door:

```bash
mkdir my-task-app && cd my-task-app
ces start
# prompts: What do you want to build?
```

For copy/paste or automation, pass the objective directly:

```bash
ces start "Create a small task tracker app with add/list/complete tasks, tests, and a README"
ces ship "Create a small task tracker app with add/list/complete tasks, tests, and a README"
```

`ces start` and `ces ship` do not create `.ces/`, edit files, or launch Codex/Claude. `ces start` gives the beginner sequence: plan, build, verify, prove. `ces ship` explains the safest command sequence for the current project state. When you are ready to launch the local runtime, run the recommended greenfield command:

```bash
ces build --from-scratch "Create a small task tracker app with add/list/complete tasks, tests, and a README"
```

For an existing repo, use `ces mri` and `ces next` first, then run `ces build "Change ..."` for the bounded implementation step.

CES will:
1. Auto-create `.ces/` with local project state
2. Gather the missing constraints and acceptance criteria
3. Draft the manifest and governance context
4. Execute the change through a local runtime
5. Show the review result and next step

## 4. Check your project status

```bash
ces status
```

This shows the current builder session, evidence, and next action.

## 5. Use the Production Autopilot reports

Before asking an agent for more feature work, inspect the repo and generate the next bounded readiness prompt:

```bash
ces mri
ces next
ces next-prompt
ces passport
ces promote production-candidate
ces launch rehearsal
```

These report-style commands are local and read-only by default. They support `--project-root PATH` and `--format markdown|json`, so a CES source checkout can inspect a separate target project without creating `.ces/` state or launching a runtime.

## What just happened?

CES created a `.ces/` directory in your project with:
- `config.yaml` — project metadata and preferred runtime
- `state.db` — SQLite database storing manifests, audit entries, and session state

Everything is local. No Postgres, Redis, or external services were needed.

## Next steps

- **Resume a session:** `ces continue`
- **Explain the latest state:** `ces explain`
- **Read the fuller setup guide:** [Getting Started](Getting_Started.md)
- **Read the workflow boundary guide:** [Operator Playbook](Operator_Playbook.md)
