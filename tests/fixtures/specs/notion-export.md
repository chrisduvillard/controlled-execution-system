# Healthcheck Endpoint (PRD)

## The Problem We're Solving
Operators need a probe endpoint.

## Who It's For
Ops engineers and platform teams.

## What Success Looks Like
- Route returns 200 under normal load
- p95 latency under 50ms

## Rolling Back
Revert the PR.

## User Stories

### Story: Add route
- **id:** ST-01
- **size:** S
- **description:** Wire HTTP route.
- **acceptance:**
  - Returns 200
