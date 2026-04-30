# CES Post-v1.0 Roadmap

> Historical roadmap snapshot. CES is currently published as a local builder-first CLI. Items below that reference Docker, API routers, Redis, Celery, dashboards, or shared control-plane infrastructure are no longer the active product roadmap.

## Current State (v1.0 — shipped 2026-04-08)

- **133/133** PRD requirements delivered across 10 phases, 46 plans
- **2,070 tests**, 91.36% coverage, 19,080 LOC across 149 modules
- **22 services** integrated, 16 CLI commands, 6 API routers
- All 7 sensor packs have real static analysis (no more stubs)
- Docker images build successfully, PostgreSQL + Redis infrastructure working

### What v1.0 Delivers
Complete single-repository governance: manifest lifecycle, deterministic classification, adversarial review triads, triage with auto-approval, kill switch, trust lifecycle, knowledge vault, brownfield register, emergency hotfix path, audit ledger with HMAC integrity, 7 engineering practice sensors, guide pack assembly, and chain-of-custody tracking.

---

## Critical Production Blockers (Fix Before Any Deployment)

These must be resolved before any team can use CES in production:

### 1. Missing Database Migrations
- `api_keys` table: `APIKeyRow` ORM class exists but no Alembic migration creates the table
- `trust_events` table: `TrustEventRow` defined but not in any migration
- **Impact:** API auth and trust lifecycle will crash with "no such table"

### 2. No E2E Integration Tests
- All CLI tests use mocked services
- Docker sandbox never tested with real containers
- LLM providers never tested with real API calls
- Celery tasks never executed against a running Redis broker
- **Impact:** No confidence that `docker compose up` + real usage works

### 3. No CI/CD Pipeline
- No `.github/workflows/`, `Jenkinsfile`, or equivalent
- No automated lint/test/build/deploy cycle
- **Impact:** Manual testing only; regressions caught late

---

## Milestone v1.1: Production Readiness (2-3 weeks)

**Goal:** Make CES safe and reliable for a real team to deploy and use.

### Phase 11: Complete Missing Infrastructure

| ID | Task | Effort | Files |
|----|------|--------|-------|
| INFRA-05 | Add Alembic migration for `api_keys` table | S | `alembic/versions/006_api_keys.py` |
| INFRA-06 | Add Alembic migration for `trust_events`, `kill_switch_states` tables | S | `alembic/versions/007_harness_tables.py` |
| INFRA-07 | Add Alembic migration for knowledge tables (`vault_notes`, `intake_sessions`, `legacy_behaviors`) if not already covered | S | Verify `005_knowledge_tables.py` completeness |
| INFRA-08 | Add admin CLI command `ces admin create-api-key` | M | `src/ces/cli/admin_cmd.py` |
| INFRA-09 | Add Celery worker health check in docker-compose | S | `docker-compose.yml` |
| INFRA-10 | Validate required secrets at startup (fail fast if missing) | S | `src/ces/shared/config.py` |

### Phase 12: E2E Integration Tests

| ID | Task | Effort | Files |
|----|------|--------|-------|
| TEST-01 | Docker sandbox integration test (real container, network=none) | M | `tests/integration/test_docker_sandbox.py` |
| TEST-02 | Celery task round-trip test (enqueue → Redis → dequeue → result) | M | `tests/integration/test_celery_roundtrip.py` |
| TEST-03 | API auth E2E test (create key → authenticate → access endpoint) | M | `tests/integration/test_api_auth_e2e.py` |
| TEST-04 | Full pipeline E2E test (manifest → execute → review → approve) with real DB | L | `tests/integration/test_full_pipeline_e2e.py` |
| TEST-05 | CLI-backed provider smoke test (real `claude`/`codex` invocation, skipped without runtime) | S | `tests/unit/test_providers/test_cli_provider.py` |

### Phase 13: CI/CD Pipeline

| ID | Task | Effort | Files |
|----|------|--------|-------|
| CI-01 | GitHub Actions: lint (ruff) + type check (mypy) + unit tests | M | `.github/workflows/ci.yml` |
| CI-02 | GitHub Actions: integration tests with Docker Compose services | M | `.github/workflows/integration.yml` |
| CI-03 | GitHub Actions: Docker image build + push to GHCR | S | `.github/workflows/build.yml` |
| CI-04 | Coverage gate (fail if below 90%) | S | In CI-01 workflow |

### Phase 14: Operational Documentation

| ID | Task | Effort | Files |
|----|------|--------|-------|
| OPS-01 | Production deployment guide (Docker, systemd, K8s options) | M | `docs/Production_Deployment_Guide.md` |
| OPS-02 | Operations runbook (emergency procedures, kill-switch playbook) | M | `docs/Operations_Runbook.md` |
| OPS-03 | Secrets management guide (key rotation, credential injection) | S | `docs/Secrets_Management.md` |
| OPS-04 | Database backup/recovery procedures | S | `docs/Database_Operations.md` |

### Phase 15: FreshCart Real E2E

| ID | Task | Effort | Files |
|----|------|--------|-------|
| DEMO-01 | Seed database with FreshCart truth artifacts (PRL, architecture, contracts) | M | `examples/freshcart/seed_data.py` |
| DEMO-02 | Make `run_e2e.py` work against real services (not mocked) | L | `examples/freshcart/run_e2e.py` |
| DEMO-03 | Document FreshCart walkthrough as "Getting Started" guide | M | `docs/Getting_Started.md` |

---

## Milestone v1.2: Multi-Project Support (4 weeks)

**Goal:** Support 2-50 person teams with multiple concurrent projects.

| ID | Task | Description |
|----|------|-------------|
| MULTI-01 | Project isolation | Add `project_id` to all governance tables, scoped queries |
| MULTI-02 | RBAC | Project-scoped permissions (Admin/Approver/Implementer per project) |
| MULTI-03 | CLI project context | `ces project switch`, `ces project list`, `ces project create` |
| MULTI-04 | Audit segregation | No cross-project data leakage in audit ledger |
| MULTI-05 | Harness profile templates | Site-wide trust profile templates shared across projects |
| MULTI-06 | API project scoping | All API endpoints require project context |

**Prerequisite:** v1.1 complete (stable single-project deployment).

---

## Milestone v2.0: Polyrepo + Dashboard (8-10 weeks)

**Goal:** Multi-repository governance with visual observability.

### Polyrepo Coordination (PRD §15B)

| ID | Task | Description |
|----|------|-------------|
| POLY-01 | Federated manifests | Cross-repo file refs via interface contracts |
| POLY-02 | Message bus | Invalidation events via webhook/Kafka/RabbitMQ |
| POLY-03 | Downstream subscription | Repos subscribe to upstream invalidation feeds |
| POLY-04 | Release coordination | Orchestrator above per-repo merge controllers |
| POLY-05 | Shared control plane | Centralized harness profiles, trust, audit (optional) |

### Dashboard UI

| ID | Task | Description |
|----|------|-------------|
| UI-01 | Active manifests view | Status, timeline, dependencies |
| UI-02 | Approval dashboard | Triage queue, review assignments, pending decisions |
| UI-03 | Audit timeline | Escape analysis, decision history, drift events |
| UI-04 | Trust trends | Promotion/demotion tracking, harness health |
| UI-05 | Cost/throughput metrics | Token usage, tasks/day, review capacity |

### Observability Integration

| ID | Task | Description |
|----|------|-------------|
| OBS-01 | Prometheus metrics | API latency, task throughput, sensor pass rates |
| OBS-02 | OpenTelemetry tracing | Distributed traces across CLI → API → Celery → LLM |
| OBS-03 | Alert routing | Kill-switch triggers, SLA breaches, escape rate spikes |
| OBS-04 | Grafana dashboards | Pre-built dashboards for governance health |

---

## Milestone v2.1: Extended Provider Support (3 weeks)

**Goal:** Broader LLM model diversity for adversarial reviews.

| ID | Task | Description |
|----|------|-------------|
| PROV-01 | Claude 3.5 Sonnet/Opus rotation | Multiple Claude models for review diversity |
| PROV-02 | Anthropic Batch API | Cost reduction for bulk review operations |
| PROV-03 | OpenAI o1/o3-mini reasoning models | For BC3 (unpredictable) work review |
| PROV-04 | Local LLM adapter | Ollama/vLLM integration for self-hosted models |
| PROV-05 | Custom model registry | Teams add their own model endpoints |

**Note:** Provider protocol (`LLMProviderProtocol`) already supports extension — each provider is ~100 LOC.

---

## Milestone v2.2: Advanced Harness Features (6 weeks)

**Goal:** Higher-fidelity quality controls.

| ID | Task | Description |
|----|------|-------------|
| ADV-01 | PRL Co-Author Agent | Auto-draft structured PRL items from feature descriptions |
| ADV-02 | Semantic Invalidation Analyzer | Reduce false invalidations (currently hash-based = conservative) |
| ADV-03 | Adversarial challenger v2 | Deeper semantic review with multi-turn questioning |
| ADV-04 | Failure pattern detection | Recurring failure loop acceleration |
| ADV-05 | Hidden check library | Domain-specific edge case libraries (1000+ checks) |

---

## Timeline Summary

```
Apr 2026       v1.1  Production Readiness     2-3 weeks
May 2026       v1.2  Multi-Project Support    4 weeks
Jun-Aug 2026   v2.0  Polyrepo + Dashboard     8-10 weeks
Sep 2026       v2.1  Extended Providers       3 weeks
Oct-Nov 2026   v2.2  Advanced Harness         6 weeks
```

**Recommended path:** Ship v1.1 first (2-3 weeks), validate with a real team, then decide v1.2 vs v2.0 based on demand.

---

## Decision Log

| Decision | Rationale |
|----------|-----------|
| v1.1 before v1.2 | Can't support multi-project until single-project is production-stable |
| Missing migrations are P0 | Runtime crashes are unacceptable; must fix before any deployment |
| CI/CD in v1.1 not v1.0 | v1.0 was about feature completeness; v1.1 adds operational maturity |
| Dashboard deferred to v2.0 | CLI-first by PRD design; dashboard adds value but isn't blocking |
| Polyrepo in v2.0 not v1.x | Requires architectural decisions (message bus, federation model) |
