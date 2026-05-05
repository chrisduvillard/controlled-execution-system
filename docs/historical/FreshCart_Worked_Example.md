# FreshCart — Complete Worked Example

> A full lifecycle walkthrough of the Agent-Native Software Delivery Operating Model v4.
> Traces a grocery delivery platform from opportunity framing through post-launch, covering greenfield, brownfield, and emergency scenarios.
>
> **Note:** FreshCart is the *user's hypothetical app* — a worked example
> CES governs. The Java/Spring Boot/Postgres stack referenced below is
> FreshCart's, not CES's. CES itself runs locally as a Python CLI against
> `.ces/state.db` (SQLite); see `pyproject.toml` for the actual shipped
> runtime dependencies.

---

## The team

| Person | Roles | Key constraint |
|---|---|---|
| **Alex** | Product Owner + Design Approver | May not classify their own PRL items |
| **Jordan** | Architecture Approver + Classification Authority | May not approve their own architecture proposals |
| **Sam** | Ops Approver + Migration Approver | May not approve deployments of code they implemented |
| **Riley** | Part-time Design Approver (shared with Alex) | Available 3 days/week |

This is a 4-person team operating at **minimum deployable** adoption level. They use GitHub for version control, GitHub Actions for CI/CD, and Claude + GPT-4 for agent execution.

---

# Part A: Greenfield — Building the Order System

## Phase 1: Opportunity Framing

Alex triggers `/bootstrap`. The Bootstrap Agent runs the **Intake Interview** (§ 7.0), asking questions one at a time:

> **Agent [P1-Q-001, mandatory]:** What are you building? Describe the product in 1-2 sentences.
> **Alex:** A grocery delivery app for urban professionals and families. Fast delivery, real inventory, no surprise substitutions.

> **Agent [P1-Q-002, mandatory]:** Who are the target users? Describe 1-3 user segments.
> **Alex:** Busy professionals wanting 2-hour delivery, and families doing weekly shops who hate going to the store.

> **Agent [P1-Q-003, mandatory]:** What are your hard constraints? (Regulatory, legal, organizational, budget)
> **Alex:** PCI-DSS for payments, GDPR for EU data. Budget is seed-stage, 4-person team.

> **Agent [P1-Q-004, mandatory]:** What would make you kill this project? Define 1-3 measurable kill criteria.
> **Alex:** No logistics partner within 3 months, or CAC over $50 after pilot.

> **Agent [P1-Q-005, mandatory]:** What is the project mode? (Greenfield / Brownfield / Hybrid)
> **Alex:** Greenfield.

> **Agent [P1-Q-006, conditional, triggered by "payments"]:** You mentioned payments. Does the app handle refunds, partial refunds, or disputes?
> **Alex:** Yes, full and partial refunds. Disputes go through Stripe.

> **Agent [Completeness check]:** Here's what I know: grocery delivery platform, 2 user segments, PCI-DSS + GDPR, 4-person team, greenfield, kill criteria defined, refunds via Stripe. Is there anything else I should know before I draft the Vision Anchor?
> **Alex:** Substitution flow is critical — users must approve before we substitute.

The Bootstrap Agent then drafts the Vision Anchor:

```yaml
schema: vision_anchor
version: 1

required_fields:
  anchor_id: VA-freshcart-001
  version: 1
  target_users:
    - segment: urban_professionals
      description: "Busy professionals who want groceries delivered within 2 hours"
    - segment: families
      description: "Families doing weekly grocery shops who want to avoid the store"
  problem_statement: >
    Ordering groceries online is slow (next-day delivery), expensive (high fees),
    and unreliable (substitutions without consent). Users want fast, transparent,
    reliable grocery delivery.
  intended_value: >
    2-hour delivery with real-time inventory visibility, no surprise substitutions,
    and transparent pricing.
  non_goals:
    - "Restaurant or prepared food delivery"
    - "Wholesale or B2B ordering"
    - "In-store pickup (out of scope for v1)"
  experience_expectations:
    - "Browsing and ordering should feel instant (sub-200ms interactions)"
    - "Delivery tracking should update in real time, not on a 5-minute lag"
    - "Substitution proposals should arrive before the order is packed, not after"
  hard_constraints:
    - constraint: "PCI-DSS compliance for payment processing"
      source: "Legal requirement for handling credit card data"
    - constraint: "GDPR compliance for EU customer data"
      source: "Legal requirement for operating in EU markets"
  kill_criteria:
    - criterion: "Unable to secure a logistics partner within 3 months"
      measurement: "No signed LOI with a delivery partner by month 3"
    - criterion: "Customer acquisition cost exceeds $50 per user after pilot"
      measurement: "Marketing spend / new users > $50 over 30-day pilot"
  owner: Alex
  created_at: 2026-04-07T09:00:00Z
  last_confirmed: 2026-04-07T09:00:00Z
  status: draft
  signature: null
```

**Gate decision (HYBRID gate — Tier C/BC1 Trusted not yet established, so HUMAN for bootstrap):**
- **Approver:** Alex (Product Owner)
- **Criteria check:** Problem statement exists and is specific. Kill criteria are defined with measurements. Project mode: greenfield. Preliminary risk: Tier A for payments, Tier B for order flow, Tier C for catalog browsing. Intake interview complete (no BLOCK questions unanswered).
- **Decision:** Proceed. Alex signs the Vision Anchor. Status changes to `approved`.

---

## Phase 2: Discovery

Greenfield discovery is lightweight — no legacy code to analyze. The Discovery Agent scans the planned tech stack (TypeScript, Next.js, PostgreSQL, Stripe API) and produces:

**Harnessability assessment:**

| Domain | Harnessability | Rationale |
|---|---|---|
| Catalog / browsing | High | Strongly typed, stateless reads, easy to test |
| Cart management | High | Clear state model, deterministic behavior |
| Order processing | Medium | State machine with multiple transitions, needs careful testing |
| Payment processing | Medium-Low | External API dependency (Stripe), PCI scope, retry logic |
| Delivery tracking | Medium | Real-time updates, external logistics API, eventual consistency |

**Gate decision:**
- **Approver:** Jordan (Architecture Approver)
- **Criteria:** Harnessability scored per domain. Service-class mapping proposed: 3 service classes (catalog, order, delivery).
- **Decision:** Proceed. Payment processing flagged as Tier A by default due to PCI scope and external API.

---

## Phase 3: PRL Authoring

Alex uses the `/prl` skill (§ 5.1, PRL Co-Author Agent). Given a feature description, the agent drafts PRL items. Alex reviews and approves.

**Example PRL items:**

```yaml
# PRL item 1: High-risk, well-specified
- prl_id: PRL-0012
  title: "Process payment with retry logic"
  description: >
    When a customer submits an order, charge their payment method via Stripe.
    If the charge fails due to a transient error, retry up to 3 times with
    exponential backoff (1s, 2s, 4s). If all retries fail, mark the order
    as payment_failed and notify the customer.
  acceptance_criteria:
    - "Successful charge creates a Stripe PaymentIntent with status 'succeeded'"
    - "Transient failures (network timeout, 500) trigger retry with backoff"
    - "Non-transient failures (card_declined, insufficient_funds) do not retry"
    - "After 3 failed retries, order status is 'payment_failed'"
    - "Customer receives notification within 30 seconds of final failure"
    - "All payment attempts are logged with Stripe request IDs for audit"
  negative_examples:
    - "Must NOT retry on card_declined — that is not a transient error"
    - "Must NOT charge the customer twice — idempotency key required on every attempt"
    - "Must NOT store raw card numbers — use Stripe tokens only"
  behavior_confidence_class: BC2
  priority: critical
  status: approved
  owner: Alex
  legacy_disposition: null
  dependencies: [PRL-0010]
  content_hash: sha256:a1b2c3...

# PRL item 2: Low-risk, well-specified
- prl_id: PRL-0005
  title: "Add item to cart"
  description: >
    Customer can add a product to their cart. The cart updates immediately.
    Quantity defaults to 1 and can be adjusted.
  acceptance_criteria:
    - "Adding an item shows it in the cart within 200ms"
    - "Default quantity is 1"
    - "Quantity can be adjusted from 1 to 99"
    - "Adding the same item again increments quantity, not duplicates"
  negative_examples:
    - "Must NOT allow quantity of 0 — use remove instead"
    - "Must NOT allow quantity above 99"
  behavior_confidence_class: BC1
  priority: standard
  status: approved
  owner: Alex
  legacy_disposition: null
  dependencies: []
  content_hash: sha256:d4e5f6...

# PRL item 3: Under investigation
- prl_id: PRL-0018
  title: "Substitution proposal flow"
  description: >
    When an item is out of stock, propose a substitution to the customer
    before packing.
  acceptance_criteria:
    - "Substitution proposed within 5 minutes of stock-out detection"
    - "Customer can accept, reject, or choose alternative"
  negative_examples:
    - "Must NOT auto-substitute without customer consent"
  behavior_confidence_class: BC3
  priority: important
  status: under_investigation
  owner: Alex
  notes: "UX flow unclear — Riley needs to design the notification experience"
```

**Gate decision:**
- **Approver:** Alex (Product Owner)
- **Criteria:** Required journeys represented. Acceptance criteria testable. PRL-0018 is explicitly "under investigation" with assigned resolution owner (Riley).
- **Decision:** Proceed. PRL-0018 cannot be manifested until resolved.

---

## Phase 4: Architecture and Harness Design

Jordan uses the `/architecture` skill (§ 5.13, Architecture Oracle). The oracle reads the PRL, harnessability assessment, and tech constraints, then proposes two options:

**Option A: Modular monolith**
- Single deployment unit with clear module boundaries
- Harnessability: High (shared type system, easy to test across modules)
- Tradeoff: Harder to scale independently, but simpler to operate at launch

**Option B: Microservices from day 1**
- Separate services: catalog, order, payment, delivery
- Harnessability: Medium (requires interface contracts, distributed testing)
- Tradeoff: More complex to operate, but scales independently

Jordan selects **Option A** (modular monolith) because the 4-person team cannot sustain microservice operational overhead. The oracle notes this is the higher-harnessability option.

**Harness profile assignment:**

| Service class | Harness profile | Trust status |
|---|---|---|
| Catalog (browsing, search) | HP-catalog-v1 | Candidate |
| Order (cart, checkout, payment) | HP-order-v1 | Candidate |
| Delivery (tracking, logistics) | HP-delivery-v1 | Candidate |

All profiles start as Candidate. They will be promoted to Trusted after calibration (Phase 6).

**Gate decision:**
- **Approver:** Jordan (Architecture Approver)
- **Criteria:** Blueprint covers all components. Interface contracts defined (internal module boundaries). Harness profiles assigned. Low-harnessability domains identified (payment = medium-low, with compensating controls: mandatory security sensor pack, mandatory inferential review).
- **Decision:** Proceed.

---

## Phase 5: Planning and Decomposition

Jordan uses the `/classify` skill (§ 5.3) and `/manifest` skill (§ 5.9) to classify and manifest tasks.

**Classification examples:**

| Task | Risk tier | BC | Change class | Rationale |
|---|---|---|---|---|
| PRL-0005: Add item to cart | Tier C | BC1 | Class 1 | Local, stateless, well-specified |
| PRL-0012: Process payment with retry | Tier A | BC2 | Class 1 | PCI scope, external API, money |
| PRL-0007: Display product catalog | Tier C | BC1 | Class 1 | Read-only, no state changes |
| PRL-0010: Create order from cart | Tier B | BC2 | Class 1 | State machine, but bounded |

**Gate decision (AGENT gate for Tier C/BC1 tasks; HUMAN for Tier A/BC2 tasks):**

For the Tier C tasks (add-to-cart, catalog display), the Classification Oracle confidence is 94% (HIGH). The gate agent (a different model from the planning agent) evaluates:

```yaml
schema: gate_evidence_packet
gate_id: GATE-P5-2026-04-09-001
phase: 5
gate_type: agent
gate_agent_model: gpt-4.1-2025-04-14
work_agent_models: [claude-opus-4-20250514]
classification:
  risk_tier: TierC
  behavior_confidence_class: BC1
  classification_confidence: 0.94
trust_status: candidate   # first project, not yet Trusted
gate_criteria:
  - criterion: "Decomposition passes semantic tests"
    evidence: "All 4 tasks pass boundary, overlap, and completeness tests"
    met: true
  - criterion: "Classifications validated"
    evidence: "Oracle confidence 94% for Tier C items, 87% for Tier B"
    met: true
  - criterion: "No concurrency conflicts"
    evidence: "No overlapping file authority across tasks"
    met: true
decision: pass
concerns: ["PRL-0010 (create order) has medium Oracle confidence (87%); elevated to HYBRID gate per §16.7.6"]
```

For Tier A tasks (payment processing), the gate is HUMAN. Jordan reviews and approves the classification.

- **Decision:** Proceed to calibration.

---

## Phase 6: Calibration

The team runs 3 probe tasks under real constraints:

1. **Probe 1** (highest risk): PRL-0012 "Process payment" — Tier A / BC2
2. **Probe 2** (most complex dependency): PRL-0010 "Create order" — Tier B / BC2
3. **Probe 3** (routine): PRL-0005 "Add item to cart" — Tier C / BC1

**Results:**

| Probe | Functional correct? | Boundary compliant? | Hallucination? | Cost (tokens) | Time |
|---|---|---|---|---|---|
| Probe 1 (payment) | Yes | Yes | No | 45K | 8 min |
| Probe 2 (order) | Yes, with 1 self-correction | Yes | No | 32K | 5 min |
| Probe 3 (cart) | Yes | Yes | No | 12K | 2 min |

- 0 significant issues: **proceed**
- Token baselines established: Tier A budget = 45K x 2.0 = 90K. Tier C budget = 12K x 1.5 = 18K.
- All three harness profiles remain Candidate (need 10 tasks with 0 escapes before Trusted).

**Gate decision:**
- **Approver:** Jordan (Architecture Approver)
- **Criteria:** All probes pass. Model fit confirmed. Cost within budget.
- **Decision:** Proceed to execution.

---

## Phase 7: Execution

### Track 1: Tier C / BC1 — "Add item to cart" (autonomous path, § 16.5)

This shows the full autonomous pipeline for low-risk work:

**Step 1 — Manifest:**
```yaml
task_id: TASK-0005-v1
prl_refs: [PRL-0005]
prl_hashes: {PRL-0005: "sha256:d4e5f6..."}
risk_tier: TierC
behavior_confidence_class: BC1
change_class: Class1
harness_profile: HP-catalog-v1
model_assignment: fast
allowed_files: ["src/cart/**", "tests/cart/**"]
forbidden_files: ["src/payment/**", "src/delivery/**"]
token_budget: 18000
max_retries: 2
spawn_budget: 0
computational_checks_required: [unit_tests, lint, typecheck, contract_validation]
review_policy: standard
ttl_hours: 336  # 2 weeks for Tier C
```

**Step 2 — Execution:** Builder Agent invokes the configured local runtime (Codex or Claude Code) and records the manifest, expected scope, evidence, and workspace delta.

**Step 3 — Sensors pass:** All tests green. Lint clean. Types check. No security sensor pack required (internal, no auth/data).

**Step 4 — Evidence synthesis:** Evidence Synthesizer produces:
```
DECISION VIEW:
Change: Add item to cart (PRL-0005)
Scope: src/cart/addToCart.ts, tests/cart/addToCart.test.ts
Risk: Tier C / BC1 / Class 1
Tests: 8 passed, 0 failed, 0 skipped
Sensors: All green. No hidden checks triggered (Candidate profile = every task).
Hidden check result: Passed (edge case: quantity 100 correctly rejected)
Retries: 0
Assumptions: None
Unknowns: None
Recommended decision: APPROVE
```

Adversarial Challenger (GPT-4, different model): "No concerns. Implementation matches PRL-0005 acceptance criteria. Edge cases handled."

**Step 5 — Triage:** Approval Triage Agent (Claude Sonnet, different from both builder and synthesizer) triages as **GREEN**.

**Step 6 — Auto-merge.** Merge Controller merges.

**Step 7 — Meta-review:** This is task #3 under HP-catalog-v1 (Candidate profile), so 100% meta-review applies (first 50 rule).

**Step 8-10 — Auto-deploy:** Staging → canary (1 hour, latency p99 < 200ms, error rate < 0.1%) → production.

**Agent chain of custody:**
```yaml
agent_chain_of_custody:
  - step: implementation
    agent_model: claude-haiku-4-5-20251001
    agent_role: builder
    timestamp: 2026-04-14T10:15:00Z
  - step: evidence_synthesis
    agent_model: claude-sonnet-4-6-20250514
    agent_role: synthesizer
    timestamp: 2026-04-14T10:18:00Z
  - step: adversarial_challenge
    agent_model: gpt-4.1-2025-04-14
    agent_role: challenger
    timestamp: 2026-04-14T10:18:30Z
  - step: approval_triage
    agent_model: claude-sonnet-4-6-20250514
    agent_role: triage
    timestamp: 2026-04-14T10:19:00Z
```

**Total time: ~12 minutes from manifest to production.** Zero human intervention.

---

### Track 2: Tier A / BC2 — "Process payment with retry logic" (governed path, § 16.6)

**Step 1 — Manifest:**
```yaml
task_id: TASK-0012-v1
prl_refs: [PRL-0012]
prl_hashes: {PRL-0012: "sha256:a1b2c3..."}
risk_tier: TierA
behavior_confidence_class: BC2
change_class: Class1
harness_profile: HP-order-v1
model_assignment: reasoning
allowed_files: ["src/payment/**", "tests/payment/**"]
forbidden_files: ["src/cart/**", "src/delivery/**", "infrastructure/**"]
token_budget: 90000
max_retries: 2
spawn_budget: 0
computational_checks_required:
  - unit_tests
  - integration_tests
  - lint
  - typecheck
  - contract_validation
  - security_sensor_pack    # mandatory for Tier A
  - resilience_sensor_pack  # recommended for external API
review_policy: adversarial
reviewer_diversity_required: true
ttl_hours: 48  # Tier A
```

**Step 2 — Execution:** Builder Agent (Claude Opus, reasoning model) implements the payment module. Uses 1 self-correction (initial version did not include idempotency key on Stripe calls — sensor caught it).

**Step 3 — Sensors:**
- Unit tests: 14 passed, 0 failed
- Integration tests (Stripe test mode): 6 passed, 0 failed
- Security sensor pack: SAST clean, secrets scan clean, no hardcoded keys
- Resilience sensor pack: idempotency verified, retry backoff correct, timeout configured (30s)
- Hidden check: Passed (injected Stripe 500 error — agent correctly retried)

**Step 4 — Adversarial Review Triad:**

Three independent reviewer roles are dispatched, each receiving PRL-0012 and the implementation independently:

**Agent 1 (Structural Reviewer):**
> "Boundaries respected. No writes outside allowed_files. Contract with Stripe client matches interface spec. Types correct. No issues found."

**Agent 2 (Semantic Reviewer):**
> "PRL-0012 acceptance criteria met. Retry logic correctly distinguishes transient vs. non-transient errors. Idempotency key uses order_id + attempt_number. One concern: the notification to the customer after payment_failed uses a fire-and-forget pattern — if the notification service is down, the customer is never informed. Suggest: add a dead-letter queue or retry mechanism for the notification."

**Agent 3 (Red Team Reviewer):**
> "Attempted to break the retry logic. Found: if the Stripe API returns a 429 (rate limit) during the retry window, the current implementation treats it as a transient error and retries immediately. This could cause a retry storm against Stripe's rate limiter. Suggest: add Stripe's Retry-After header handling to the backoff logic."

**Step 5 — Quorum evaluation (§ 10.9.4):**
- Agent 1: zero findings
- Agent 2: one concern (notification reliability)
- Agent 3: one concern (rate limit handling)
- Result: 2-of-3 found issues. Both issues escalated to human with specific disagreement framed.

**Step 6 — Evidence packet:**
```
DECISION VIEW:
Change: Process payment with retry logic (PRL-0012)
Scope: src/payment/processPayment.ts, src/payment/stripeClient.ts, tests/payment/**
Risk: Tier A / BC2 / Class 1
Tests: 20 passed, 0 failed, 0 skipped
Hidden check: Passed (Stripe 500 injection)
Security: SAST clean, secrets clean, no PCI violations
Retries: 1 (missing idempotency key, self-corrected)

ADVERSARIAL HONESTY:
- retries_used: 1
- skipped_checks: []
- flaky_checks: []
- context_summarized: false
- review_disagreements:
    - "Semantic reviewer: notification fire-and-forget could lose failure alerts"
    - "Red team reviewer: Stripe 429 handling missing, risk of retry storm"
- recommended_decision: APPROVE with conditions (fix both findings)

ADVERSARIAL COUNTER-BRIEF:
"The Synthesizer's 'approve with conditions' is reasonable. Both findings are
real but neither is a security risk. The notification issue is a reliability
gap, not a correctness bug. The 429 issue is a resilience gap that would only
manifest under load. Suggest: fix both before merge, not after."
```

**Step 7 — Human approval:**
Sam reviews the evidence packet (2-minute read). Sees the two findings and the counter-brief.
- **Decision:** Approve with conditions. Both findings must be fixed before merge.
- The Builder Agent fixes both issues (adds dead-letter queue for notifications, adds Retry-After header handling). A second sensor run confirms fixes.

**Step 8 — Meta-review:** 100% for Tier A. Jordan meta-reviews Sam's approval: evidence was read, decision quality is credible.

**Step 9 — Merge.** Merge Controller merges after human approval recorded.

**Steps 10-13 — Deploy:** Human gate for staging (Sam authorizes). Integration testing. Human gate for production (Sam authorizes after rollback plan verified). Production deploy with canary.

**Total time: ~2 hours from manifest to production.** Human involvement: ~15 minutes (evidence review + two approval gates).

---

## Phase 8: Integration and Hardening

After all order-system tasks merge, the Phase 8 gate is a **HYBRID gate** (per § 16.7.2 — the profile is still Candidate at this point, and Tier A tasks are in the slice).

The gate agent evaluates:
- Structural coverage: all 4 planned tasks merged ✓
- Journey completeness: end-to-end flows pass (browse → cart → order → payment) ✓
- Contract compatibility: no interface regression ✓

The gate agent produces a **recommendation: PASS** with confidence 0.91 and one concern: "Payment retry logic was reviewed by the Triad, but the reassembly-level interaction between retry and cart timeout was not explicitly tested."

Jordan (Reassembly Authority for this slice) reviews the recommendation and decides:
- Does the cart flow correctly into the order flow? Yes.
- Does the payment flow correctly handle all order states? Yes.
- Are interface contracts between modules consistent? Yes.
- The concern about retry/timeout interaction? Jordan confirms: "The end-to-end test covers this — the test creates a cart, waits past timeout, and verifies the payment retry path." Override: no.

**Decision:** Accept agent recommendation. PASS. Reassembly proof recorded.

---

## Phase 9: Release

The Phase 9 gate is also a **HYBRID gate**. The Deploy Controller runs a quick **Intake Interview** (§ 7.0):

> **Agent [P9-Q-001, mandatory]:** What is the maximum acceptable downtime during deployment?
> **Sam:** Zero. Rolling deployment only.

> **Agent [P9-Q-002, mandatory]:** What canary metric thresholds should trigger auto-rollback?
> **Sam:** Error rate > 1%, latency p99 > 2s, payment success rate < 98%.

> **Agent [Completeness check]:** Deployment type: rolling. Rollback triggers defined. Canary observation: 30 min per stage. Anything else?
> **Sam:** Notify me if cart abandonment rate spikes above 15%.

Sam (Ops Approver) reviews the deployment packet:
- Rollback plan: database migration is backwards-compatible (additive only). Code rollback restores previous version.
- Canary metrics: latency p99, error rate, payment success rate, cart abandonment rate.
- Staged rollout: 10% traffic → 30 min observation → 50% → 30 min → 100%.

**Decision:** Approve. Deploy.

---

## Phase 10: Post-Launch

### Severity 2 escape detected

Two days after launch, a customer reports they were charged twice for the same order. Investigation reveals: when a user double-clicks the "Pay" button within 100ms, two payment requests reach Stripe before the idempotency check takes effect (race condition in the frontend, not the backend).

**Escape analysis:**

| Layer | Should have caught it? | Did it? | Category |
|---|---|---|---|
| Computational sensors | Maybe (frontend race condition) | No | Sensor gap |
| Adversarial Review Triad | Possibly (Red Team tried to break it) | No | Review-framing gap (tested backend only) |
| Hidden checks | Maybe | No | Hidden check gap (no frontend interaction testing) |
| Canary monitoring | No (canary doesn't simulate double-clicks) | N/A | Harnessability limit |

**Severity:** Severity 2 (functional defect affecting users, financial impact).
**Contraction:** HP-order-v1 demoted from Candidate to Watch.
**Harness improvement:** Add frontend interaction sensor (debounce verification). Add hidden check: rapid double-submission test. Update Red Team Reviewer guide to include frontend interaction testing.

**Vault write (§ 15A):** The Monitoring Agent writes an escape analysis note to the Project Knowledge Vault:

```markdown
---
id: KV-escape-001
title: Double-charge race condition on rapid Pay button clicks
category: escape
tags: [payment, frontend, race-condition, stripe, tier-a, sev-2]
trust_level: verified
created: 2026-04-11T14:30:00Z
created_by: monitoring-agent-claude-opus-4
last_verified: 2026-04-11T14:30:00Z
last_verified_by: jordan (Architecture Approver)
depends_on_artifacts: [PRL-0012]
linked_notes: [KV-pattern-001]
---

## Summary
Rapid double-click on the Pay button (within 100ms) creates two
payment requests that reach Stripe before the frontend idempotency
check takes effect. Backend idempotency is correct; the gap is in
frontend event handling.

## Detail
Root cause: the checkout component dispatches a Stripe PaymentIntent
on each click event. The idempotency key is generated per-click
(not per-order). Fix: add 500ms debounce to the Pay button +
generate idempotency key from order_id (not click event).

## Context
Any future agent working on payment UI or checkout flow must be
aware of this. The Red Team Reviewer guide has been updated to
include frontend interaction testing for payment flows.

## Evidence
- Escape trace: AUDIT-2026-04-11-003
- Fix commit: abc1234
- Steering Backlog: SB-007 (frontend interaction sensor)
```

This note will now appear in Guide Packs for any future task touching payment UI or checkout flow, preventing agents from re-introducing the same vulnerability.

---

# Part B: Brownfield — Integrating the Legacy Inventory System

FreshCart grows. They need real-time inventory from a partner grocery store that runs a legacy inventory system (Java monolith, PostgreSQL, REST API, minimal test coverage).

## Phase 2: Discovery (brownfield)

Discovery Agent inventories the legacy system:

```
DISCOVERY PACKET:
- Components: 1 monolith (Java Spring Boot), 1 PostgreSQL database
- API: 23 REST endpoints, partial OpenAPI spec (covers 15 of 23)
- Test coverage: 34% line coverage, mostly unit tests on utility classes
- State machines: inventory_item (in_stock → reserved → sold → returned)
- Harnessability: LOW
  - Weak typing (Java Object used extensively)
  - Implicit behavior (business rules in stored procedures)
  - Minimal contract documentation
  - No golden-master tests
```

**Harnessability assessment:** LOW. Compensating controls needed: mandatory inferential review, conservative concurrency, elevated hidden checks.

## Phase 3: PRL (brownfield)

The PRL Co-Author derives items from existing tests and API documentation:

```yaml
- prl_id: PRL-0042
  title: "Inventory lookup by product SKU"
  description: "Return current stock level for a given SKU"
  acceptance_criteria:
    - "Returns stock count for valid SKU"
    - "Returns 0 for valid SKU with no stock"
    - "Returns 404 for unknown SKU"
  legacy_disposition: preserve
  source: "Inferred from GET /api/inventory/{sku} endpoint and 3 existing tests"
  confidence: medium
  notes: "Stored procedure applies a 'safety buffer' of -5 units. Unclear if intentional."

- prl_id: PRL-0043
  title: "Reserve inventory for order"
  description: "Decrement available stock when order is placed"
  acceptance_criteria:
    - "Stock decremented atomically (no double-sell)"
    - "Reservation expires after 30 minutes if order not confirmed"
  legacy_disposition: change
  source: "Inferred from POST /api/inventory/reserve endpoint. No existing tests."
  confidence: low
  notes: "Current implementation has no reservation expiry. This is a known bug being fixed in migration."
```

## Phase 4: Architecture (hybrid)

Jordan selects a migration approach: extract inventory lookup into a new service, with the legacy system remaining as the source of record during migration.

**Migration Control Pack skeleton:**

```yaml
schema: migration_control_pack
version: 1

current_state_inventory:
  - system: legacy-inventory-monolith
    role: "Source of record for all inventory data"
    database: PostgreSQL 12
    api_endpoints: 23

disposition_decisions:
  - component: "Inventory lookup (GET /api/inventory/{sku})"
    disposition: migrate
    rationale: "New service will provide real-time inventory to FreshCart"
  - component: "Inventory reservation (POST /api/inventory/reserve)"
    disposition: change
    rationale: "Add reservation expiry. Fix known double-sell risk."
  - component: "Inventory admin (PUT/DELETE endpoints)"
    disposition: preserve
    rationale: "Partner team manages. Not in FreshCart scope."

source_of_record:
  - domain: inventory_data
    current_owner: legacy-inventory-monolith
    future_owner: new-inventory-service
    transition_rule: "Legacy remains SoR until reconciliation passes for 1 week"

golden_master_traces:
  - trace_id: GM-001
    description: "100 SKU lookups captured from production"
    captured_at: 2026-05-01
    format: request_response_pairs

reconciliation_rules:
  - rule: "New service must return identical stock levels as legacy for all GM-001 traces"
  - rule: "Reservation behavior must match legacy for all non-expiry scenarios"

coexistence_plan:
  duration: "4 weeks"
  routing: "Feature flag: 10% → 50% → 100% traffic to new service"

cutover_plan:
  - step: "Route 10% traffic to new service"
  - step: "Monitor for 1 week"
  - step: "Route 50% traffic"
  - step: "Monitor for 1 week"
  - step: "Route 100% traffic"
  - step: "Decommission legacy API proxy after 2 weeks at 100%"

rollback_matrix:
  - scenario: "New service returns wrong stock levels"
    action: "Revert feature flag to 0%. Legacy resumes immediately."
    data_risk: "None — legacy was never modified"
  - scenario: "New service is down"
    action: "Feature flag to 0%. Legacy serves all traffic."
    data_risk: "None"

exit_criteria:
  - "All GM-001 traces pass on new service for 7 consecutive days"
  - "Error rate on new service < 0.1% for 7 consecutive days"
  - "No Severity 1 or 2 escapes during coexistence"
```

## Phase 7: Execution — Class 4 migration task

**Manifest for "Extract inventory lookup":**

```yaml
task_id: TASK-0042-v1
prl_refs: [PRL-0042]
risk_tier: TierA
behavior_confidence_class: BC2
change_class: Class4  # migration
harness_profile: HP-inventory-migration-v1
model_assignment: reasoning
computational_checks_required:
  - unit_tests
  - integration_tests
  - lint
  - typecheck
  - security_sensor_pack
  - database_migration_sensor_pack  # mandatory for schema changes
  - reconciliation_validation       # golden-master comparison
review_policy: adversarial
reviewer_diversity_required: true
```

**Database migration sensor pack in action:**
- Reversibility: down-migration script exists and passes ✓
- Online-migration safety: no table locks, additive schema change only ✓
- Data loss detection: no columns dropped ✓
- Referential integrity: FK constraints maintained ✓

**Reconciliation validation:**
- 100 golden-master traces (GM-001) compared
- 98 match exactly
- 2 discrepancies: legacy returns stale cached values, new service returns real-time values
- **Diagnosis:** Legacy has a 5-minute cache. New service queries directly. The "discrepancy" is the new service being more correct.
- **Decision:** Jordan reviews and accepts. The 2 discrepancies are documented as expected improvements.

## Phase 9: Cutover

Traffic routing: 10% → (1 week, no issues) → 50% → (1 week, no issues) → 100%.

**Reconciliation failure scenario:** At 50% traffic, a reconciliation check detects that the new service returns stock=0 for SKU-7734, while legacy returns stock=12.

1. **Halt.** Migration Approver (Sam) halts further traffic increase.
2. **Diagnose.** Root cause: the new service reads from a replica database that is 3 minutes behind the primary. The legacy system reads from the primary.
3. **Route:** This is a data issue (b), not a behavioral divergence. Fix: point the new service to the primary database for stock queries.
4. **Re-gate.** Fix deployed. Reconciliation re-runs. All 100 traces match. Sam authorizes resumption at 50%.

**Coexistence window:** 2 weeks at 100% with legacy available for instant rollback. After 2 weeks with all exit criteria met, Sam authorizes legacy retirement.

---

# Part C: Emergency Hotfix (§ 12.5)

It's Tuesday at 11 PM. Sam's phone rings: payment processing is failing for all orders. Error rate spiked from 0.1% to 95% in the last 5 minutes.

**Step 1 — Declare emergency.** Sam declares via Slack. Logged in Audit Ledger:
```yaml
event_type: emergency_declared
actor: Sam
scope: "payment processing — all orders failing"
timestamp: 2026-05-20T23:05:00Z
```

**Step 2 — Diagnose.** Sam and Jordan investigate. Root cause: Stripe updated their API version. A previously optional field (`payment_method_options`) is now required. The change was not in Stripe's changelog (Stripe's bug, but FreshCart's problem).

**Step 3 — Simplified manifest:**
```yaml
task_id: HOTFIX-001
scope: "Add payment_method_options to Stripe PaymentIntent creation"
affected_files: ["src/payment/stripeClient.ts"]
rollback_plan: "Revert commit. Previous version works with old API behavior."
classification: TierA  # emergency default
```

**Step 4 — Fix.** Jordan implements the 3-line fix (adds the required field).

**Step 5 — Minimum sensors:** Tests pass (including the Stripe test-mode integration test). Lint clean. Type check passes.

**Step 6 — Expedited review.** Sam reviews the 3-line diff. Confirms: fix addresses the issue, no regressions, rollback plan viable. Approval time: 4 minutes.

**Step 7 — Emergency approval.** Sam approves unilaterally. Logged.

**Step 8 — Deploy.** Direct to production. Heightened monitoring: all payment metrics at 1-minute intervals.

**Result:** Error rate drops from 95% to 0.2% within 3 minutes. Emergency stabilized.

**Post-incident (within 24 hours):**
1. Full evidence packet assembled retroactively
2. Fix re-reviewed under normal Tier A procedures — Jordan and Sam confirm the fix is correct
3. Escape analysis: this is NOT a code escape (FreshCart's code was correct). It's an external dependency change. Harness improvement: add a sensor that monitors Stripe API changelog and alerts on breaking changes.
4. Emergency closed in Audit Ledger:
```yaml
event_type: emergency_closed
root_cause: "Stripe API breaking change (undocumented)"
fix: "Added payment_method_options field"
controls_waived: ["Adversarial Review Triad", "hidden checks", "canary observation"]
justified: true
```

---

# Summary: What This Example Demonstrates

| Concept | Where demonstrated |
|---|---|
| Vision Anchor schema | Phase 1 |
| PRL items with acceptance criteria and negative examples | Phase 3 |
| "Under investigation" status blocking manifesting | Phase 3 (PRL-0018) |
| Architecture Oracle generating options | Phase 4 |
| Classification decision table in action | Phase 5 |
| Calibration with probe tasks and thresholds | Phase 6 |
| Full autonomous path (Tier C/BC1, § 16.5) | Phase 7, Track 1 |
| Full governed path (Tier A/BC2, § 16.6) | Phase 7, Track 2 |
| Adversarial Review Triad with quorum evaluation | Phase 7, Track 2 |
| Evidence packet with adversarial honesty | Phase 7, Track 2 |
| Agent chain of custody | Phase 7, Track 1 |
| Reassembly and integration review | Phase 8 |
| Canary deployment and staged rollout | Phase 9 |
| Escape analysis with severity classification | Phase 10 |
| Trust status contraction (Candidate → Watch) | Phase 10 |
| Brownfield discovery and harnessability assessment | Part B, Phase 2 |
| Migration Control Pack with golden masters | Part B, Phase 4 |
| Database migration sensor pack | Part B, Phase 7 |
| Reconciliation validation and failure response | Part B, Phase 9 |
| Cutover with coexistence and rollback | Part B, Phase 9 |
| Emergency hotfix path (§ 12.5) | Part C |
| Post-incident review and harness improvement | Part C |
| Intake Interview Protocol (§ 7.0) — sequential questions | Phase 1 |
| Conditional question triggered by prior answer | Phase 1 (refund question triggered by "payments") |
| Completeness check at end of intake | Phase 1 |
| Agent Gate with gate evidence packet (§ 16.7) | Phase 5 (Tier C tasks) |
| Classification Oracle confidence feeding gate type | Phase 5 (94% HIGH → AGENT gate) |
| Hybrid Gate with agent recommendation + human decision | Phase 8 |
| Intake Interview at deployment phase (§ 7.0) | Phase 9 |
| Project Knowledge Vault escape analysis note (§ 15A) | Phase 10 |
| Vault note format with frontmatter, trust level, artifact links | Phase 10 |
| Vault feeding future Guide Packs | Phase 10 (explained in note context) |
