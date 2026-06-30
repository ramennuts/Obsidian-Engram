# Engram — operating principles

Six rules that the whole system is built around. They apply to both memory layers and
to anything you add. Each came from something breaking.

### 1. Lean injection
What's auto-loaded into a session is a **summary + pointers**, never whole documents.
Hook context has a hard size ceiling — exceed it and the harness silently truncates, so
your "auto-injected" memory never arrives. Inject the headlines and where-to-read-more;
the full files are one `Read` away.

### 2. Fail open
Anything that runs as a hook must **never be able to wedge a session**. A missing file,
malformed note, or unexpected input results in *no injection / no block* and a clean
exit — never a session that won't start. A memory aid that can break your tooling is
worse than no memory aid.

### 3. Verify against live
The `LIVE-STATE.md` board is the one place where every line was checked against the
running system on a dated pass. When an older doc disagrees with it — or you're about
to act on an "is/isn't built" claim — **check the live system first** (the URL, the
logs, the config). Notes drift; the live system doesn't. Re-verify the board when big
things ship.

### 4. Rules as hooks, not prose
A rule that *must* hold every time belongs in a **deterministic hook**, not a memory
note. Prose is context the model can fail to honor under pressure; a `PreToolUse` guard
is enforcement. If you find yourself writing "always remember to…", consider whether it
should be a hook instead (see `hooks/guard.py`).

### 5. Conservative archiving / pruning
When trimming working or durable memory, **err toward keeping.** A wrongly-kept item is
harmless clutter; a wrongly-removed one hides real work or loses a fact. The archiver
only moves *unambiguously* finished items; memory pruning deletes only what's confirmed
false (closed-but-still-useful "don't re-open this" notes stay).

### 6. Cite the source
When the agent makes a claim, it should be groundable in a note or a file path. If it
can't be, say "I'm guessing." This keeps durable memory honest and makes drift visible —
a cited claim can be re-verified; an uncited one just rots.

---

These compose. Lean injection + verify-against-live keeps each session both cheap and
correct. Fail-open + rules-as-hooks makes the automation safe to trust. Conservative
pruning + cite-the-source keeps the memory itself from rotting as it grows.
