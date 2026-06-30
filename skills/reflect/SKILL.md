---
name: reflect
description: Periodic self-improvement reflection. Reviews recent sessions/handoffs/work, spots recurring friction and misses, and PROPOSES concrete improvements to the memory system + workflow — for the user to approve. Never self-applies. Use weekly, or when the user says "reflect", "retro", "how can we work better", or "review how it's going".
---

# Reflect — propose how to work better (don't self-apply)

A periodic pass that turns recent experience into concrete, durable improvements. The
goal is to make *next* week smoother by upgrading the memory and the workflow — not to
re-litigate the work itself.

**Hard rule: propose, never self-apply.** This skill outputs recommendations for the
user to approve. It does not silently edit memory, flip settings, or change behavior.
Approved changes are made deliberately afterward.

## Step 1 — Gather the evidence

Look across the recent window (default: the last week):
- The newest handoffs in the vault's `handoffs/` — what shipped, what stalled, what
  was a dead-end.
- `LIVE-STATE.md` and `build-queue.md` — drift, stale items, things that should've
  been archived.
- Any moments this period where you (the agent) were corrected, repeated a mistake,
  re-derived something you should have remembered, or guessed instead of checking.

## Step 2 — Find the patterns (not one-offs)

You're looking for *recurring* friction, the kind a durable change would fix:
- **Repeated misses** — the same wrong assumption or dead-end more than once.
- **Memory gaps** — a fact you needed wasn't written down (→ a new durable note), or a
  durable note was stale/misleading (→ fix or prune it).
- **Workflow friction** — a manual ritual that should be a hook/skill, or a noisy
  injection that should be leaner.
- **Drift** — `LIVE-STATE.md` disagreeing with reality; handoffs that were too thin to
  resume from.

## Step 3 — Propose concrete, specific changes

For each, write a 1–3 line proposal: **what to change, why, and the cost/risk.** Prefer
durable fixes over reminders. Examples of good proposals:
- "Add a `feedback` note: *always check the migration status before touching the auth
  service* — we hit this twice this week."
- "The handoff template's 'dead-ends' section keeps getting skipped — add a one-line
  prompt for it."
- "`LIVE-STATE.md`'s cron table drifted; re-verify against the live system and update."
- "Three closed items are still cluttering the queue — run the archiver."

## Step 4 — Hand it to the user

Present the proposals as a short list and ask which to apply (yes / no / defer). Only
on a yes do you make the change, using the normal deliberate path. Defer the rest to
the queue with a reason. Nothing here happens automatically.

## Guardrails

- **No reward-hacking.** Don't propose changes that just make the agent *look* better
  (e.g. relaxing a check). Improvements must be real.
- **Cite the evidence.** Each proposal points at the handoff/log/moment that motivates
  it, so the user can judge it.
- **Small and durable beats big and vague.** "Add this one note" lands; "be more
  careful" doesn't.
