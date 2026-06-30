---
title: "LIVE STATE — verified ground truth (read this before trusting older docs)"
type: live-state
last_verified: 2025-01-15
tags: [source-of-truth]
---

# LIVE STATE — verified ground truth

**Purpose:** the short, verified snapshot of what is ACTUALLY live. Older docs (the
queue's history, old handoffs, design notes) drift; each fact here was checked
against the running system on the date shown, not inferred from a doc. **When an
older doc disagrees with this file, verify against the live system (logs / the URL /
the config) before acting.** A periodic reconcile-to-live pass is cheaper than
rediscovering drift mid-task.

> This is a TEMPLATE. Replace the example sections below with your own. The Engram
> SessionStart hook injects a *table of contents* of these `##` headers plus the
> "read before trusting older docs" pointer — so keep the section titles meaningful.

---

## Services / deployments (verified 2025-01-15)
- `api` — deployed to prod, healthy (`/health` = 200). Region: us-east.
- `web` — deployed to prod. Last deploy: 2025-01-14.
- `worker` — running; processes the jobs queue every 60s.

## Config / feature flags (verified 2025-01-15)
| Flag | Value | Meaning |
|------|-------|---------|
| `NEW_CHECKOUT` | true | New checkout flow is live for all users |
| `EMAIL_DIGEST` | false | Weekly digest still in shadow |
| `RATE_LIMIT` | 100/min | Per-user API ceiling |

## Current capabilities (durable facts; detail in the linked handoff)
- **Auth** — email + OAuth (Google) live since 2024-12.
- **Billing** — Stripe subscriptions live; webhooks verified end-to-end.
- **Search** — full-text live; semantic search is built but behind `SEMANTIC_SEARCH` (off).

## Change log (compressed — full detail in each handoff)
- **2025-01-15** — Migrated jobs queue from cron to the worker; added health checks.
- **2025-01-10** — Shipped the new checkout flow; retired the legacy one.
- **2025-01-03** — OAuth (Google) added.

## Drift log (the lesson — why this file exists)
1. Old README: "search is TODO." → Full-text search has been live for weeks.
2. A handoff claimed "billing webhooks failing" → it was a stale signing secret, since fixed.
**Lesson:** reconcile-to-live (this file) beats rediscovering drift mid-task; refresh it when big things ship.
