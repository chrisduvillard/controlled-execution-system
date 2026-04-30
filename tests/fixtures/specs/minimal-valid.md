---
spec_id: SP-01HXY
title: Healthcheck endpoint
owner: duvillard.c@gmail.com
created_at: 2026-04-21T10:00:00Z
status: draft
template: default
signals:
  primary_change_class: feature
  blast_radius_hint: isolated
  touches_data: false
  touches_auth: false
  touches_billing: false
---

## Problem
Operators need a probe.

## Users
Ops engineers.

## Success Criteria
- Route returns 200.

## Non-Goals
- No metrics.

## Risks & Mitigations
- **Risk:** Network flakiness
  **Mitigation:** Add retries

## Stories

### Story: Add /healthcheck route
- **id:** ST-01HXY
- **size:** S
- **risk:** C
- **depends_on:** []
- **description:** Wire HTTP route.
- **acceptance:**
  - Returns 200 with JSON body
  - p95 under 50ms

## Rollback Plan
Revert the PR.
