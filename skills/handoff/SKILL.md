---
name: handoff
description: Write a VERY detailed end-of-session handoff into your Obsidian vault so the next session resumes with zero context loss. Use when wrapping up a session, when the user says "/handoff", "write a handoff", "wrap it up", "hand off", or "end of session". Produces a dense, technical handoff (what shipped, why, dead-ends, open threads, gotchas, exact paths/commits, resume command) at $ENGRAM_VAULT/handoffs/ — which the Engram SessionStart hook auto-loads next time.
---

# Write a detailed session handoff

You are writing the pickup brief the NEXT session will rely on. Engram's SessionStart
hook auto-injects the newest handoff at session start, so its quality directly
determines how well the next session resumes. **Bias hard toward completeness** — a
handoff that's too detailed costs a few tokens; one that's too thin costs a
re-derivation, a repeated dead-end, or a silent regression. When unsure whether a
detail belongs, include it.

This is an INTERNAL technical document. Be dense and precise — exact paths, commit
hashes, line numbers, flag names, and command lines.

## Step 1 — Reconstruct the WHOLE session (don't skim the last few turns)

Scan back over the entire conversation and extract, exhaustively:

- **Everything that changed** — every file created/edited (full path), every
  script/config/flag touched, every command/commit run (hash + message), every
  external system affected.
- **What was decided and WHY** — capture the reasoning and the options rejected.
  "Chose X over Y because Z" beats "did X."
- **Dead-ends / things that did NOT work** — anything tried that failed or was
  reverted, with symptom + root cause. This is the highest-value content: it stops
  the next session repeating it.
- **Verified vs. assumed** — for anything touching a live system, state how it was
  checked and what's still unverified.
- **Open threads + owners** — every loose end, what it's waiting on, the next
  concrete action.
- **Gotchas** — non-obvious traps that bit you and would bite again.
- **Rollback** for anything risky that shipped.

## Step 2 — Pick the path

Write to: `$ENGRAM_VAULT/handoffs/<YYYY-MM-DD>-<slug>-handoff.md`
(`<slug>` = 3–6 kebab-case words naming the session's main threads). The hook picks
the newest file by modified time, so a correct date keeps selection right.

## Step 3 — Use this structure

```markdown
---
title: "Session handoff — <YYYY-MM-DD> (<clause> · <clause>)"
type: session-handoff
date: <YYYY-MM-DD>
tags: [handoff, <topic>, ...]
---

# Session handoff — <YYYY-MM-DD>

<1–3 sentence orientation: the most important thing that changed, and what to read FIRST.>

---

## Headlines
### A) <Biggest change — short title>
<Dense paragraph + bullets. Exact paths, commits, flags. Current state. **ROLLBACK:** how to undo.>
### B) <Next change>
...

## What did NOT work / dead-ends
<Everything abandoned, with symptom + root cause.>

## Open items / next steps
- <Concrete next action> — <waiting on / owner / where it picks up>

## Pending decisions (carried)
- <Decision not yet made + what it's waiting on>

## Gotchas (don't relearn)
- <Non-obvious trap + the rule to follow instead>

## Verification status
- ✅ Confirmed live: <what + how>
- ⚠️ Assumed / NOT verified: <what + how to verify next session>

## Key files / docs
- <paths touched>

## Resume command
<A short paragraph the next session can act on: what to read, what to run, the top 1–3 prioritized actions.>
```

## Step 4 — Depth bar

- Never write "updated X" without the path and what specifically changed.
- Always include rollback for anything that touched a live system.
- Always include the "why," not just the "what."
- Prefer specifics to summaries.
- If the session changed live state, ALSO update `LIVE-STATE.md` (the ground-truth
  board the hook injects a table-of-contents of). The handoff narrates the change;
  LIVE-STATE records the new steady state.

## Step 5 — Close the loop

After writing, tell the user the exact path, a one-line summary, whether you updated
LIVE-STATE, and confirm it will auto-load next session.
