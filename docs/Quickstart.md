# 5-Minute Quickstart

Get from zero to a governed AI build in under 5 minutes. CES is a local
builder-first tool: no Docker, no Postgres, and no hosted control plane.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (install: `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- A supported local runtime: Codex CLI or Claude Code

## 1. Install CES

From source:

```bash
git clone https://github.com/chrisduvillard/controlled-execution-system.git
cd controlled-execution-system
uv sync
```

Or from PyPI once published:

```bash
uv tool install controlled-execution-system
```

## 2. Run your first governed build

```bash
mkdir my-project && cd my-project
ces build "Add a healthcheck endpoint that returns JSON status" --yes
```

CES will:
1. Auto-create `.ces/` with local project state
2. Gather the missing constraints and acceptance criteria
3. Draft the manifest and governance context
4. Execute the change through a local runtime
5. Show the review result and next step

## 3. Check your project status

```bash
ces status
```

This shows the current builder session, evidence, and next action.

## 4. Verify your runtime

```bash
ces doctor
```

`ces build` and `ces execute` require a supported local runtime. `CES_DEMO_MODE=1`
only affects optional LLM-backed helper steps; it does not replace Codex CLI or
Claude Code for local execution.

## What just happened?

CES created a `.ces/` directory in your project with:
- `config.yaml` — project metadata and preferred runtime
- `state.db` — SQLite database storing manifests, audit entries, and session state

Everything is local. No Postgres, Redis, or external services were needed.

## Next steps

- **Resume a session:** `ces continue --yes`
- **Explain the latest state:** `ces explain`
- **Read the fuller setup guide:** [Getting Started](Getting_Started.md)
- **Read the workflow boundary guide:** [Operator Playbook](Operator_Playbook.md)
