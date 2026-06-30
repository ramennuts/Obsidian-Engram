# Engram — the two-layer memory architecture

Engram models an agent's memory as **two layers** with different jobs. Most "agent
memory" projects collapse these into one bucket; keeping them separate is what makes
recall sharp and the context lean.

```
┌─────────────────────────────────────────────────────────────────────┐
│ LAYER 1 — DURABLE MEMORY  (memory/)                                   │
│ Facts that are true across ALL sessions. Slow-changing.              │
│ Who you are · your preferences · how you want the agent to work ·    │
│ project context · references. Indexed by MEMORY.md, loaded every     │
│ session.                                                             │
├─────────────────────────────────────────────────────────────────────┤
│ LAYER 2 — WORKING MEMORY  (the vault)                                │
│ The state of the work RIGHT NOW. Fast-changing.                     │
│ LIVE-STATE.md (ground truth) · build-queue.md (active work) ·        │
│ handoffs/ (session pickup briefs). Injected lean at session start.   │
└─────────────────────────────────────────────────────────────────────┘
```

## Why two layers

A single "memory pile" forces a bad trade-off: include everything and the context
balloons and goes stale, or trim aggressively and lose durable facts. Splitting by
**rate of change** fixes it:

| | Durable memory | Working memory |
|---|---|---|
| **Holds** | identity, preferences, project facts, references | current state, the work queue, session handoffs |
| **Changes** | rarely (you correct it; it accretes slowly) | constantly (every session) |
| **Loaded** | the `MEMORY.md` index every session; full notes on demand | a lean bootstrap at session start (the SessionStart hook) |
| **Lifecycle** | written when you learn something durable; pruned/consolidated periodically | written as work happens; archived when finished |
| **Lives in** | `memory/` (see [memory-format.md](memory-format.md)) | the Obsidian vault (see the README) |

The rule of thumb: **"would this still be true and useful three months from now, in an
unrelated session?"** Yes → durable memory. "Is this about what we're doing right
now?" → working memory.

## How they work together in one session

1. **Session starts.** The `MEMORY.md` index (durable) is in context, and the
   SessionStart hook injects a lean bootstrap of working memory (latest handoff +
   active queue + ground-truth TOC). The agent resumes grounded on both *who you are*
   and *where the work is*.
2. **During the session.** Working memory is updated as state changes
   (`LIVE-STATE.md`, the queue). If the agent learns something **durable** — a
   preference, a project fact, a gotcha that will recur — it writes a durable note.
3. **Session ends.** `/handoff` writes a working-memory handoff. Durable facts are
   *not* duplicated into it — they already live in Layer 1.

## What goes where (worked examples)

| Observation | Layer | Why |
|---|---|---|
| "Prefer SI units in all output." | Durable (`feedback`) | A standing preference, true every session. |
| "The auth service is mid-migration to OAuth, soaking." | Working (`LIVE-STATE.md`) | Current state; changes soon. |
| "Decided to use cursor pagination on `created_at`, not `id`." | Durable (`project` or a note) + referenced in the handoff | The decision + reason is durable; the *task* is working memory. |
| "Today I migrated the jobs queue." | Working (handoff) | A session event. |
| "The CI token needs the `workflow` scope or pushes fail." | Durable (`reference`/gotcha) | A trap that will recur. |

## Anti-patterns (don't)

- **Don't dump durable facts into every session's context manually.** That's what the
  `MEMORY.md` index is for — one line per fact, full note on demand.
- **Don't let working memory accrete forever.** Archive finished queue items; the
  ground-truth board overrides stale handoffs.
- **Don't write the same fact in both layers.** Durable lives in `memory/`; the handoff
  points to it. Duplication drifts.

See [memory-format.md](memory-format.md) for the durable-note spec and
[principles.md](principles.md) for the operating rules both layers share.
