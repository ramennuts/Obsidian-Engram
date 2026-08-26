#!/usr/bin/env python3
"""Engram — PreCompact checkpoint writer (memory-v2 U2, second half).

Compaction can summarize away in-flight, session-specific state (open todos,
active exceptions, what was mid-flight). This hook snapshots the cheap-to-grab
parts to a checkpoint file BEFORE compaction runs; session_start_v2 re-injects
the newest checkpoint when it fires with source == "compact".

NOT self-registering: ~/.claude/settings.json is Shane-only (deny-listed for
Claude). To enable, Shane adds to the "hooks" object:

    "PreCompact": [
      { "hooks": [ { "type": "command",
          "command": "python3 /Users/rgardin/tools/engram/hooks/pre-compact.py" } ] }
    ]

Until registered, the RE-ARM block still works (charter digest re-injects at
SessionStart source=compact); the checkpoint just adds session-specific detail.

Reads the PreCompact stdin JSON: {session_id, transcript_path, trigger, ...}.
Scans the TAIL of the transcript for the last TodoWrite state (the working todo
list) — cheap, no LLM. FAIL OPEN: never blocks compaction, always exit 0.
"""
import datetime
import json
import os
import re
import sys

VAULT = os.environ.get("ENGRAM_VAULT", os.path.expanduser("~/vault"))
CHECKPOINT_DIR = os.path.join(VAULT, "machine", "checkpoints")
TAIL_BYTES = 400_000   # transcript tail to scan for the last todo state
KEEP = 20              # checkpoints retained; older ones pruned (they are snapshots)

# Domain gate (board 2026-08-24, finding B2): a customer or personal session's
# transcript-derived state must NEVER land in the shared vault. cwd is the
# session's working directory (hooks run in it) — a proxy, not a proof, of the
# session's domain; the session-id-correlated read on the other side is the
# second lock. Roots overridable for tests only.
RESTRICTED_ROOTS = [os.path.realpath(os.path.expanduser(p)) for p in os.environ.get(
    "PRECOMPACT_RESTRICTED_ROOTS", "~/clients:~/personal").split(":") if p]


def _restricted_cwd():
    # realpath both sides: on macOS /var is a symlink to /private/var, and a
    # prefix check on unresolved paths would silently miss the match.
    cwd = os.path.realpath(os.getcwd())
    return any(cwd == r or cwd.startswith(r + os.sep) for r in RESTRICTED_ROOTS)


def last_todos(transcript_path):
    """The most recent TodoWrite todos list in the transcript tail, or None."""
    try:
        size = os.path.getsize(transcript_path)
        with open(transcript_path, encoding="utf-8", errors="replace") as f:
            if size > TAIL_BYTES:
                f.seek(size - TAIL_BYTES)
                f.readline()  # skip the partial line
            todos = None
            for line in f:
                if '"todos"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                def find(o):
                    if isinstance(o, dict):
                        if isinstance(o.get("todos"), list):
                            return o["todos"]
                        for v in o.values():
                            r = find(v)
                            if r is not None:
                                return r
                    elif isinstance(o, list):
                        for v in o:
                            r = find(v)
                            if r is not None:
                                return r
                    return None
                found = find(obj)
                if found is not None:
                    todos = found
            return todos
    except OSError:
        return None


def main():
    if _restricted_cwd():
        return   # customer/personal session state never lands in the shared vault
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        data = {}
    now = datetime.datetime.now()
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    # Sanitize THEN truncate — this expression must stay byte-identical to
    # session_start_v2.session_key(), or the checkpoint is written under a key
    # the reader never looks for: silently, forever (board chair C3).
    # tests/test_board_fixes.py asserts the two agree.
    sid = re.sub(r"[^A-Za-z0-9]", "", str(data.get("session_id", "unknown")))[:8] or "unknown"
    path = os.path.join(CHECKPOINT_DIR,
                        f"{now.strftime('%Y-%m-%d-%H%M')}-{sid}-precompact.md")
    lines = [
        f"# Pre-compact checkpoint — {now.strftime('%Y-%m-%d %H:%M')}",
        f"- session: {sid} · trigger: {data.get('trigger', '?')} · cwd: "
        f"{os.getcwd().replace(os.path.expanduser('~'), '~')}",
        "- Context was compacted after this point. Re-read the active queue "
        "item and any in-flight approvals before continuing.",
    ]
    todos = last_todos(data.get("transcript_path", "")) if data.get("transcript_path") else None
    if todos:
        lines.append("\n## Working todos at compaction")
        for t in todos[:20]:
            if isinstance(t, dict):
                lines.append(f"- [{t.get('status', '?')}] {str(t.get('content', ''))[:160]}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    # prune old checkpoints (snapshots, not records — KEEP newest N). Scoped to
    # OUR filenames: a broad *.md prune would silently delete anything else that
    # ever lands here (board audit ADDED-6 — silent data loss in an unattended
    # hook is the category that matters most).
    snaps = sorted((os.path.getmtime(p), p) for p in
                   (os.path.join(CHECKPOINT_DIR, n) for n in os.listdir(CHECKPOINT_DIR))
                   if p.endswith("-precompact.md"))
    for _, p in snaps[:-KEEP]:
        os.remove(p)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # FAIL OPEN — never block compaction
    sys.exit(0)
