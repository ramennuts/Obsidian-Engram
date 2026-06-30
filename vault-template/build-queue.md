---
title: Build queue
type: build-queue
tags: [queue]
---

# Build queue

The work queue. Items live under `## Active items` (current work) and `## Blocked`
(waiting on something/someone). When an item is fully finished, **strike its `###`
header** (`~~like this~~`) and add a done/shipped/closed marker — the archiver
(`scripts/archive_finished_queue.py`, run weekly) then moves it to `## Auto-archived`.

The Engram SessionStart hook injects the `###` item HEADERS from `## Active items`
and `## Blocked` (one line each), so keep headers descriptive. It skips
`## Auto-archived` entirely.

## Active items
### Add pagination to the results list
- The list returns all rows; needs cursor pagination. Touch `api/results.py` + the web table.
- **Next:** decide page size (50?) with the team.

### Wire up the semantic-search flag
- Code is built behind `SEMANTIC_SEARCH` (off). Needs an eval pass before flipping.

### ~~Migrate jobs queue cron → worker~~ — **SHIPPED 2025-01-15**
- Moved the 3 cron jobs into `worker/jobs.py`; added health checks. Verified running.
- (This item is struck + has a completion marker + no open thread → the archiver will move it.)

## Blocked
### ~~Enable OAuth (Google)~~ — **DONE 2025-01-03**, but: still waiting on the Apple review
- Google OAuth is live. **Still to do:** Apple Sign-In is pending Apple's review — keep this here.
- (Struck + DONE, but the live thread "Still to do … pending review" keeps it OUT of the archive.)

### Upgrade the database — blocked on the infra team
- Needs a maintenance window from infra before we can run the migration.

## Auto-archived
_Auto-moved here by `scripts/archive_finished_queue.py` once an item was fully finished (struck header + a done/shipped/closed marker + no open thread). Newest at top. Anything still live — even if struck, superseded, or pushed-aside — stays put._
