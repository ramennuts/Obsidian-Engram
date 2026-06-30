#!/usr/bin/env python3
"""Engram — SessionStart memory bootstrap for Claude Code + an Obsidian vault.

Injects a LEAN orientation (current state + open work + pointers) at the start of
every session, so the agent resumes grounded instead of re-deriving context from
scratch. Registered as a `SessionStart` hook in ~/.claude/settings.json (see
settings.example.json).

Reads three files from your vault (path via $ENGRAM_VAULT, default ~/vault):
  - LIVE-STATE.md   : the verified "ground truth" board (services, config, current state)
  - build-queue.md  : the work queue — `## Active items` / `## Blocked` of `### ` items
  - handoffs/*.md   : dated session handoffs; the NEWEST is the pickup brief

Design rules (learned the hard way — see docs/design.md):
  - LEAN: a SessionStart hook's additionalContext has a hard size ceiling; if you
    exceed it the harness truncates to a tiny preview and the injection is wasted.
    So inject a SUMMARY + POINTERS (a few KB), never whole docs. The full files are
    one `Read` away.
  - FAIL OPEN: any error -> emit nothing, exit 0. A memory hook must NEVER wedge a
    session.
"""
import glob
import json
import os
import re
import sys

VAULT = os.environ.get("ENGRAM_VAULT", os.path.expanduser("~/vault"))
LIVE_STATE = os.path.join(VAULT, "LIVE-STATE.md")
HANDOFF_DIR = os.path.join(VAULT, "handoffs")
BUILD_QUEUE = os.path.join(VAULT, "build-queue.md")

# Handoff `##` sections injected in full (the actionable ones). Substring match.
HANDOFF_FULL = ["Open items", "Next steps", "Resume", "Pending decisions"]
# build-queue `##` sections whose `###` item HEADERS we list (one line each).
BQ_HEADER_SECTIONS = ["Active", "Blocked"]
STRIKE = re.compile(r"~~(.*?)~~")
SECTION_CAP = 4000  # safety cap on any single injected block


def tilde(p):
    return p.replace(os.path.expanduser("~"), "~")


def read_text(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def latest_handoff():
    files = glob.glob(os.path.join(HANDOFF_DIR, "*.md"))
    return max(files, key=os.path.getmtime) if files else None


def unwrap(s):
    return STRIKE.sub(r"\1", s).strip()


def split_h2(text):
    """Return (intro_before_first_h2, [(header_line, body_text), ...])."""
    parts = re.split(r"(?m)^(## .*)$", text)
    sections = []
    for i in range(1, len(parts), 2):
        sections.append((parts[i], parts[i + 1] if i + 1 < len(parts) else ""))
    return parts[0], sections


def cap(s):
    return s if len(s) <= SECTION_CAP else s[:SECTION_CAP].rstrip() + "\n…[truncated — Read the file]"


def handoff_block():
    hp = latest_handoff()
    if not hp:
        return None
    text = read_text(hp)
    intro, sections = split_h2(text)
    intro = re.sub(r"(?s)^---.*?---\s*", "", intro)   # drop frontmatter
    intro = re.sub(r"(?m)^#\s+.*$", "", intro).strip()  # drop the title line
    out = []
    if intro:
        out.append(intro)
    for hdr, body in sections:  # one-line index of the headlines, if any
        if "headline" in hdr.lower():
            titles = [unwrap(m.group(1)) for m in re.finditer(r"(?m)^###\s+(.*)$", body)]
            if titles:
                out.append("**Headlines:** " + " · ".join(titles))
    for hdr, body in sections:  # the actionable sections, in full
        if any(m.lower() in hdr.lower() for m in HANDOFF_FULL):
            out.append(hdr + "\n" + body.rstrip())
    out.append(f"_Full handoff: `{tilde(hp)}`_")
    return cap("\n\n".join(out))


def bq_block():
    if not os.path.isfile(BUILD_QUEUE):
        return None
    _, sections = split_h2(read_text(BUILD_QUEUE))
    out = []
    for match in BQ_HEADER_SECTIONS:
        for hdr, body in sections:
            if match.lower() in hdr.lower() and "archiv" not in hdr.lower():
                items = [unwrap(m.group(1)) for m in re.finditer(r"(?m)^###\s+(.*)$", body)]
                if items:
                    out.append(f"**{unwrap(hdr[3:])}** ({len(items)}):\n"
                               + "\n".join(f"- {it}" for it in items))
    if not out:
        return None
    out.append(f"_Full items + history: `{tilde(BUILD_QUEUE)}`_")
    return cap("\n\n".join(out))


def live_state_block():
    if not os.path.isfile(LIVE_STATE):
        return None
    _, sections = split_h2(read_text(LIVE_STATE))
    toc = [unwrap(h[3:]) for h, _ in sections]
    body = "Sections: " + " · ".join(toc) if toc else "(no sections parsed)"
    return (body + f"\n\n_**Read `{tilde(LIVE_STATE)}` before acting on any "
            "state/config claim — it overrides older docs.**_")


def main():
    blocks = []
    for label, fn in (
        ("▶ RESUME — latest session handoff (the pickup brief)", handoff_block),
        ("▶ ACTIVE WORK — work queue (live sections only)", bq_block),
        ("▶ GROUND TRUTH — LIVE-STATE index", live_state_block),
    ):
        try:
            body = fn()
        except Exception:
            body = None
        if body and body.strip():
            blocks.append(f"### {label}\n\n{body}")
    if not blocks:
        return
    header = (
        "Session bootstrap — a LEAN orientation auto-injected from your Obsidian "
        "vault by Engram. It's a summary + pointers, NOT the full docs — Read the "
        "linked files for detail. If anything here conflicts with what you observe "
        "live, trust live and flag it.\n"
    )
    context = header + "\n\n" + "\n\n---\n\n".join(blocks)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart", "additionalContext": context}}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # FAIL OPEN
    sys.exit(0)
