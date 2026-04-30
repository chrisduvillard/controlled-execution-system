---
spec_id: SP-COMPLEX
title: Diamond deps
owner: a@b.c
created_at: 2026-04-21T10:00:00Z
status: draft
template: default
signals:
  primary_change_class: feature
  blast_radius_hint: module
  touches_data: false
  touches_auth: false
  touches_billing: false
---

## Problem
p

## Users
u

## Success Criteria
- s

## Non-Goals
- n

## Risks & Mitigations
- **Risk:** r
  **Mitigation:** m

## Stories

### Story: A (base)
- **id:** ST-A
- **size:** S
- **description:** base
- **acceptance:**
  - works

### Story: B (depends on A)
- **id:** ST-B
- **size:** S
- **depends_on:** [ST-A]
- **description:** b
- **acceptance:**
  - works

### Story: C (depends on A)
- **id:** ST-C
- **size:** S
- **depends_on:** [ST-A]
- **description:** c
- **acceptance:**
  - works

### Story: D (depends on B and C)
- **id:** ST-D
- **size:** S
- **depends_on:** [ST-B, ST-C]
- **description:** d
- **acceptance:**
  - works

## Rollback Plan
rb
