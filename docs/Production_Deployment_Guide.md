# CES Production Deployment Guide

CES is deployed as a local workstation tool, not as a shared API or worker
platform. “Production deployment” therefore means rolling CES out to developer
machines or CI environments with a consistent local runtime contract.

## Recommended Install

```bash
uv tool install controlled-execution-system
```

Or for repository development:

```bash
git clone <repo-url> && cd controlled-execution-system
uv sync
```

## Runtime Contract

Each CES operator needs:
- Python 3.12+
- `uv`
- `codex` or `claude` available on PATH
- A writable project checkout where CES can create `.ces/`

CES stores operational state locally in `.ces/state.db`. It does not require
Postgres, Redis, Celery, FastAPI, or Docker for supported usage.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CES_AUDIT_HMAC_SECRET` | Optional | dev default | HMAC secret for local audit chain integrity. Set a unique value in managed environments. |
| `CES_LOG_LEVEL` | Optional | `INFO` | Logging verbosity |
| `CES_LOG_FORMAT` | Optional | `json` | Log output format |
| `CES_DEMO_MODE` | Optional | `0` | Demo helper responses for optional LLM-backed flows when a CLI-backed provider is unavailable |
| `CES_DEFAULT_RUNTIME` | Optional | `codex` | Preferred local runtime if project config does not override it |

## Rollout Checklist

- [ ] `uv tool install controlled-execution-system` or `uv sync` succeeds
- [ ] `ces --help` and `ces doctor` run successfully
- [ ] `codex` or `claude` is available on PATH
- [ ] `CES_AUDIT_HMAC_SECRET` is set deliberately in managed environments
- [ ] A sample repo can complete `ces build`, `ces continue`, `ces review`, and `ces approve`

## CI and Automation

Supported automation is still local-style automation:
- run CES inside a checked-out repository
- keep `.ces/` as workspace state, not source
- invoke CLI commands directly
- use `--json` where machine-readable output is needed

Do not build new workflows around the removed shared-service surfaces.
