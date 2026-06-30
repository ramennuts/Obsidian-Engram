# Durable memory — the note format

Layer 1 (durable memory) lives in a `memory/` directory: **one fact per file**, plus a
single `MEMORY.md` index that lists them. The agent reads the index every session and
opens individual notes on demand. This is the convention Engram uses; the
`memory-template/` directory is a ready-to-copy starting point.

> If you're on Claude Code, this pairs with its built-in file-based memory — these are
> the *conventions and tooling* that keep that memory sharp instead of sprawling.

## One fact per file

Each note captures a single durable fact and carries frontmatter:

```markdown
---
name: <short-kebab-case-slug>          # also the filename, minus .md
description: <one-line summary>         # used to judge relevance from the index
type: user | feedback | project | reference
scope: core | <context>                # optional; for multi-context recall
---

<the fact. For feedback/project, follow with **Why:** and **How to apply:** lines.
Link related notes with [[their-slug]].>
```

## The four types

| Type | Holds | Example |
|------|-------|---------|
| **user** | who the person is — role, expertise, preferences, how they work | "Senior backend dev; prefers terse answers; deploys on Fridays." |
| **feedback** | guidance on *how the agent should work* — corrections and confirmed approaches, **with the why** | "Don't refactor unrelated code in a PR. **Why:** review noise. **How to apply:** keep diffs scoped." |
| **project** | ongoing work/goals/constraints not derivable from the code | "Migrating the monolith to services; auth first; Q2 target." |
| **reference** | pointers to external resources or stable facts | "Staging dashboard: <url>. Deploy runbook: <path>." |

## The index (`MEMORY.md`)

One line per note, grouped by scope. This file is what's loaded every session, so keep
it tight — it's a table of contents, never the content itself.

```markdown
## Core — how we work (loaded everywhere)
- [User: who I am](user_me.md) — role, prefs, working style.
- [Feedback: scoped diffs](feedback_scoped_diffs.md) — keep PRs focused; why + how.

## Project X
- [Project: service migration](project_migration.md) — monolith → services, auth first.
```

## Scope (optional, for multi-context recall)

If you use the agent across several unrelated contexts (different clients, projects,
side ventures), tag each note with a `scope` and group the index by it. Recall defaults
to **core + the one active context**, so a side-project's notes don't bleed into
unrelated work. For a single context, ignore scope entirely.

## Discipline (what keeps it sharp)

- **Update, don't duplicate.** Before adding a note, check whether one already covers
  it — edit that instead. Two notes on one topic drift apart.
- **Prune the wrong ones.** A fact that turns out false gets deleted, not left to
  mislead. Closed decisions that still serve as "don't re-open this" guardrails stay.
- **Consolidate periodically.** Merge overlaps, fix stale facts, keep the index lean.
  Run `scripts/memory_lint.py` to catch orphans (files missing from the index) and
  dangling `[[wikilinks]]`.
- **Link liberally.** `[[other-slug]]` ties the graph together; a link to a note that
  doesn't exist yet just marks one worth writing.
- **Don't save what's already recorded elsewhere** — code structure, git history, or
  the README. Save what was *non-obvious*.

See `memory-template/` for filled-in examples of each type and a starter index.
