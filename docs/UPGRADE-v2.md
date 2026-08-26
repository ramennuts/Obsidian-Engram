# Engram v2 — cutover runbook

Written after the 5-agent review board of 2026-08-24 (record:
`~/vault/machine/memory-v2/board-2026-08-24-engram-v2/`). Every step below is
reversible; the irreversible-looking ones are called out with their rollback.

**Nothing here has been done yet.** Steps 1–2 are Claude-runnable; steps 3–5 are
Shane-only because they touch `~/.claude/settings.json`, which is deny-listed for
Claude by design.

---

## Before you start — the one-line state of play

The registered `SessionStart` hook is still **v1** (`hooks/session-start.py`,
unchanged and committed). v2 lives beside it as `hooks/session_start_v2.py` and
has never run in a real session — only via `--shadow`. Rollback at every stage is
"don't cut over" or one `git checkout`.

---

## Step 1 — Baseline the evals BEFORE anything changes (Claude-runnable)

```bash
cd ~/tools/engram && python3 evals/run_evals.py --label pre-cutover
```

This runs 12 probes as fresh headless sessions against the **v1** hook and
appends to `~/vault/machine/memory-v2/scorecard.md`. Cost: 12 Haiku-class runs,
pennies. The scorecard header records the sha256 of the hook that was actually
registered, so this run is permanently distinguishable from the post-cutover one.

Read the **context-only** number, not the total: those probes run with `--tools ""`
and can only be answered from injected context. That number is the one that
measures the bootstrap.

## Step 2 — Cut over the hook (Claude-runnable, reversible)

```bash
cd ~/tools/engram && git add -A && git commit -m "Engram v2: pre-cutover checkpoint"
cp hooks/session_start_v2.py hooks/session-start.py
uv run --project . --with pytest pytest tests -q   # must be green in ONE run
python3 hooks/session-start.py --shadow | head -40  # eyeball it
```

The registration path in `settings.json` does not change — v2's content simply
becomes the registered file. **Rollback:** `git checkout hooks/session-start.py`.

Then open a fresh terminal session and confirm the bootstrap looks right, and:

```bash
cd ~/tools/engram && python3 evals/run_evals.py --label post-cutover
```

Compare the two scorecard runs. A drop in the context-only number means v2 is
injecting *worse* context than v1 — roll back and investigate, don't push on.

## Step 3 — Install the compactor (Shane, after step 2 has run for a day)

```bash
cp ~/tools/engram/launchd/com.rgardin.engram.compactor.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.rgardin.engram.compactor.plist
launchctl kickstart -p gui/$UID/com.rgardin.engram.compactor   # one supervised run
```

Watch the first run in `~/tools/engram/logs/compactor.log`. It runs daily at
05:15. The **proposals** pass is the only metered spend (Haiku, propose-only,
skips if today's file already exists, `<$1/week`). Disable it any time with
`COMPACTOR_NO_LLM=1` in the plist's environment.

How you find out it broke: a failing pass makes the job exit non-zero
(`launchctl print gui/$UID/com.rgardin.engram.compactor` shows `LastExitStatus`)
**and** `memory_lint` raises `COMPACTOR-STALE` / `COMPACTOR-FAILED`, which rides
the ⚠ line into every session's ACTIVE WORK block. That second channel is the one
that actually reaches a human.

**Rollback:** `launchctl bootout gui/$UID/com.rgardin.engram.compactor` and delete
the plist. Nothing it wrote is destructive — archived files move to
`machine/archive/`, never delete.

## Step 4 — PreCompact hook (Shane) — BLOCKED pending one check

The board **blocked** registration until this is answered, because a silently
dead checkpoint feature is worse than no checkpoint feature:

> Does the harness pass the **same** `session_id` to `PreCompact` and to the
> following `SessionStart(source=compact)`?

If it issues a fresh id at compaction, `checkpoint_matches_session()` will never
match, and the CHECKPOINT block is dead on arrival with no error. To check: add
the hook, trigger one `/compact`, and compare the `session_id` written into the
checkpoint filename under `~/vault/machine/checkpoints/` with the id the next
SessionStart receives. If they differ, correlate on `transcript_path` instead
before relying on it.

Second, board-recommended precondition: the domain gate currently uses **cwd**,
which the code itself documents as a proxy, not a proof. The authoritative signal
is the per-session pin file that `file-guard` maintains — but that store is
Shane-only (it blocked both the auditor and me from reading it, which is the guard
working correctly). Wiring `pre-compact.py` to refuse when a pin file exists for
this `session_id` is a Shane task, and it should fail closed.

Registration, once both are settled — add to the `hooks` object of
`~/.claude/settings.json`:

```json
"PreCompact": [
  { "hooks": [ { "type": "command",
      "command": "python3 /Users/rgardin/tools/engram/hooks/pre-compact.py" } ] }
]
```

The post-compaction re-arm (charter digest) works **without** this hook; the
checkpoint only adds session-specific detail.

## Step 5 — D4 (the two-memory-store split) — RESOLVED, ready to execute

A dedicated 7-agent board (2026-08-24, record:
`~/vault/machine/memory-v2/board-2026-08-24-d4/VERDICT.md`) found the fix the
first board did not know existed. The original proposal — symlink one project
slug and delete the `@`-import — stays **permanently rejected**, along with every
variant that makes two clients share one auto-memory directory (symlink-all, a
user-scope `autoMemoryDirectory` redirect, a "non-indexed quarantine inbox").

**The reframe that settles it: D4 is a LOSS problem, not a SHARING problem.**
Today's 12 sealed per-slug boxes are already isolation-*optimal* —
`~/.claude/projects` is in no ALLOW_ROOT and is loaded by nothing. The only
defect is that a fact dropped into one of those boxes is never read again. Every
"fix" that merges boxes imports a client-isolation problem that does not exist
today in order to solve a loss problem. So: **remove the second store rather
than merge it.**

### 5a — SHANE. Snapshot `~/memory` first (there is still no backup of it)

```bash
mkdir -p ~/Backups && cp -R ~/memory ~/Backups/memory-snapshot-$(date +%F)
```
It must live **outside `~/vault` and outside `~/memory`** — `recall`'s
ALLOW_ROOTS walk both recursively, so a snapshot inside either would double-index
every note and fire `ORPHAN` on all of them.

### 5b — SHANE. The fix: one key in `~/.claude/settings.json` (user scope)

```json
"autoMemoryEnabled": false
```
Merge it into the existing object; do not overwrite the file. This is a
documented Claude Code setting. It costs nothing real: all four auto-memory
directories are empty, no subagent definition uses a `memory:` field, and it also
switches off a session-log tree that would otherwise write files named after
session titles. **Rollback: delete the key.** No data is created, moved, or
deleted by this step.

### 5c — SHANE. Prove it took (this is the acceptance test)

```bash
mkdir -p /tmp/d4-verify && cd /tmp/d4-verify
claude -p --max-turns 4 "Remember this durable fact: my favorite build tool is ninja. Save it to your memory."
find ~/.claude/projects -path '*/memory/*' -type f -newermt '-10 minutes'
```
Expect **no new file**, and no "You have a memory index" block in the session.
Before 5b, this same probe could land a real harness-stamped file — the board's
empirical lane observed exactly that. Falsifiable in both directions.

### 5d — DONE (Claude, 2026-08-24). The durable half: a detector

Prevention can lapse with **zero local edits** — `CLAUDE_CODE_DISABLE_AUTO_MEMORY=0`
force-*enables* the feature and beats the setting, and parts of the subsystem are
governed by remote feature flags. So something watches underneath it:
`memory_lint.py --projects` (wired into the daily compactor) stat-scans every
project slug's `memory/` dir and raises `STRAY-PROJECT-MEMORY` if anything ever
lands there, plus `PREVENTION-OFF` if the setting stops being in force. Slugs are
identified by **hash, never name** — the report is FTS-indexed and read into the
daily outbound Haiku call. Findings are **severity-ordered** so they cannot be
buried behind the stale backlog (the bootstrap injects only the first three).

⚠️ **The ⚠ channel only exists in v2** — the registered hook is still v1, which
has no lint-flag injection at all. Until step 2's cutover, the detector's
findings live in the report file but reach no session.

### 5e — SHANE, ~1 minute, and it is NOT part of D4

```bash
grep -n "memory" ~/.claude/hooks/file-guard.py | head -30
```
Question: **does file-guard stop a client-pinned session from WRITING into
`~/memory`?** The house convention tells *every* session that durable facts go
there — and `~/memory` is `@`-imported into all 12 contexts, is `recall`
ALLOW_ROOT #2, and is read verbatim into the daily Haiku call. If the answer is
no, that is a live isolation hole in the *sanctioned* path, which dwarfs D4's
latent one. The board deliberately did not read that file (owner-only). Give it
its own item — and its own board if the answer is bad.

**Related refusal:** do not add a machine-wide `Write(~/memory/**)` permission to
smooth out headless-session friction until 5e is answered. That friction may
currently be the only thing preventing exactly this leak.

---

## Rollback summary

| Thing | Undo |
|---|---|
| Hook cutover | `git -C ~/tools/engram checkout hooks/session-start.py` |
| Compactor | `launchctl bootout gui/$UID/com.rgardin.engram.compactor`, delete plist |
| PreCompact | remove the `PreCompact` block from settings.json |
| Anything the compactor moved | it moves, never deletes — see `~/vault/machine/archive/` |
| Recall index | disposable cache; `rm -rf ~/vault/.recall` and it rebuilds |
