# Engram — design notes

The principles behind the code, and the mistakes that shaped them. If you adapt
Engram, keep these in mind — each one came from something breaking.

## 1. Lean injection — there's a hard ceiling on hook context

A `SessionStart` hook returns `additionalContext` that the harness prepends to the
session. It's tempting to dump your whole state board + handoff + queue into it. Don't.

If the output is too large, the harness **truncates it to a small preview** and
spills the rest to a file — so most of your "auto-injected" context never reaches
the model, and you don't get an error. The first version of this hook emitted ~42KB
and was silently cut to a 2KB preview.

The fix: inject a **summary + pointers**, not documents. The hook sends:
- the latest handoff's intro + open items + resume command,
- the queue's active/blocked item **headers** (one line each),
- a **table of contents** of the ground-truth board + a "read it before trusting
  older docs" pointer.

That's a few KB and it's all signal. The full files are one `Read` away when needed.
**Rule of thumb: keep the injection under a few KB.**

## 2. Fail open — a memory hook must never wedge a session

Every code path in `session-start.py` is wrapped so that *any* error results in
emitting nothing and exiting 0. A vault file is missing, malformed, mid-edit? You get
a session with no bootstrap — never a session that won't start. A memory aid that can
break your tooling is worse than no memory aid.

## 3. Conservative archiving — err toward keeping

The archiver moves finished items out of the queue so the injection stays
high-signal. The danger is archiving something that's actually still live — that
*hides real work*. So the classifier only archives when ALL of:
1. the item's header is struck (`~~...~~`), AND
2. the post-strike text has a completion marker (done/shipped/closed/resolved/won't-fix), AND
3. the item has no open-thread word (still to do / pending / blocked / next / …).

Two subtleties:
- It **strips struck spans before** scanning for open-thread words — so a struck
  "still pending" can't fool it; the resolution after the strike is what counts.
- "superseded" / "deferred" are **not** completion markers — pushed-aside items are
  kept, not archived. Abandoned ≠ finished.

A wrongly-kept done item is harmless clutter. A wrongly-archived live item is a bug.
The rule is tuned so the only failure mode is the harmless one.

**Gotcha:** a resolution note that *quotes* a trigger word ("the **Still to do** note
was stale") will keep the item, because the classifier can't tell a quote from a live
callout. Phrase resolutions without the trigger words.

## 4. Verify against live — the board overrides the docs

Notes drift. The `LIVE-STATE.md` board is the one place where every line was checked
against the running system on a dated pass. The convention — and the hook's injected
pointer — is: when an older doc disagrees with LIVE-STATE, or you're about to act on
an "is/isn't built" claim, **check the live system first** (the URL, the logs, the
config). Re-verify the board when big things ship; a periodic reconcile is cheaper
than rediscovering drift mid-task.

## 5. Two ends of the loop, deliberately different

- **Reading is automatic** (the SessionStart hook). You should never have to tell a
  session "go read the handoff."
- **Writing is triggered** (the `/handoff` skill), not automatic. A good handoff
  requires the model to actually summarize the session — that's model work, not a
  shell script, and "session end" is ambiguous to a hook. So writing stays a
  one-word, model-driven step; reading is free.
