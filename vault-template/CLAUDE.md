# Agent operating instructions for this vault

This Obsidian vault is your long-term memory. This file tells you how to use it.
(Engram auto-injects a lean bootstrap at session start; this is the full reference.)

## How to start a session

The Engram SessionStart hook already injects a summary of the three files below.
Read the full file when you need detail:

1. **`LIVE-STATE.md`** — the verified ground-truth board (services, config, current
   state). When an older doc disagrees with it, **verify against the live system
   before acting** — LIVE-STATE overrides older docs.
2. **Newest file in `handoffs/`** — the pickup brief from the last session.
3. **`build-queue.md`** — what's actively being worked (`## Active items`) and what's
   stuck (`## Blocked`).

## How to end a session

When the user says to wrap up (or `/handoff`), write a detailed handoff into
`handoffs/` using the `handoff` skill. If live state changed (a deploy, a flag, a
new capability), also update `LIVE-STATE.md`.

## Conventions

- **Frontmatter on every note** (`title`, `type`, `date`, `tags`) so queries work.
- **Strike + mark finished queue items** (`~~header~~ — **DONE**`) so the archiver
  can move them. Keep anything with an open thread un-struck or with the thread
  spelled out.
- **Cite the source.** If you make a claim, link the note or file that grounds it.
- **Surface contradictions.** If a request conflicts with a note saved earlier, stop
  and flag it rather than guessing.

## What goes where

- `LIVE-STATE.md` — current verified state (the board).
- `build-queue.md` — the work queue.
- `handoffs/` — dated session handoffs.
- Everything else — your own notes, organized however you like (Obsidian links tie
  them together regardless of folders).
