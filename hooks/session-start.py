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
import collections
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


# Handoff selection is DETERMINISTIC: primary key is the handoff's own date
# (frontmatter `date:`, else the filename's YYYY-MM-DD prefix), mtime only
# breaks ties within a single date. mtime alone is not trusted across dates —
# a bulk touch / rsync / restore silently promoted stale briefs (2026-08-13).
# Files typed anything other than a handoff (e.g. session-prompt) are excluded;
# untyped files count only if named `*-handoff.md`.
_FM_RE = re.compile(r"(?s)\A---\s*\n(.*?)\n---")
_DATE_RE = re.compile(r"(?m)^date:\s*[\"']?(\d{4})-(\d{2})-(\d{2})")
_TYPE_RE = re.compile(r"(?m)^type:\s*[\"']?([\w-]+)")
_TITLE_RE = re.compile(r"(?m)^title:\s*[\"']?(.+?)[\"']?\s*$")
_FNAME_DATE_RE = re.compile(r"\A(\d{4})-(\d{2})-(\d{2})")

# Sentinel date for a handoff we accepted but could not date. Kept distinct so
# undated files never masquerade as sharing a real date with each other.
_UNDATED = (1, 1, 1)
SIBLING_LIST_CAP = 8

# A scanned handoff. `date_key`/`mtime` are the sort key (date primary, mtime
# tiebreak — mtime alone silently promoted stale briefs on a bulk touch,
# 2026-08-13). `title` is captured in the SAME read that classifies the file, so
# the whole selection reads each file exactly once per session start.
Handoff = collections.namedtuple("Handoff", "date_key mtime path title")


def scan_handoffs():
    """Every handoff under HANDOFF_DIR, best-pickup-first (newest date, then
    newest mtime). One open per file; non-handoffs excluded. Never raises."""
    out = []
    for path in glob.glob(os.path.join(HANDOFF_DIR, "*.md")):
        name = os.path.basename(path)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                head = f.read(4096)
        except OSError:
            continue
        fm = _FM_RE.match(head)
        block = fm.group(1) if fm else ""
        typ = _TYPE_RE.search(block)
        if typ and "handoff" not in typ.group(1).lower():
            continue  # explicitly typed as something else (session-prompt etc.)
        if not typ and not name.endswith("-handoff.md"):
            continue  # untyped and not named like a handoff
        date = _DATE_RE.search(block) or _FNAME_DATE_RE.match(name)
        date_key = tuple(map(int, date.groups())) if date else _UNDATED
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0.0
        tm = _TITLE_RE.search(block)
        title = tm.group(1).strip() if tm else name
        out.append(Handoff(date_key, mtime, path, title))
    out.sort(key=lambda h: (h.date_key, h.mtime), reverse=True)
    return out


def latest_handoff():
    """The single pickup brief, or None. Thin wrapper over scan_handoffs so
    external callers keep one selection path. NOT read-validated — handoff_block
    is where readability is enforced."""
    hs = scan_handoffs()
    return hs[0].path if hs else None


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


def _list_line(h):
    return f"- `{os.path.basename(h.path)}` — {h.title}"


def _sibling_notice(primary, records, skipped):
    """The concurrency notice, or None. Two concerns, most-urgent first:

    1. Handoffs newer-or-equal to `primary` that we had to SKIP because they
       would not read — the newest brief may be the one we dropped, and skipping
       it silently is the exact failure this whole change exists to prevent.
    2. Other handoffs sharing the primary's date — concurrent work that this one
       brief cannot claim to summarize.

    Same-date grouping ignores the `_UNDATED` sentinel so undated files never
    cross-list as sharing a real date.
    """
    lines = []
    newer_skipped = [h for h in skipped
                     if (h.date_key, h.mtime) >= (primary.date_key, primary.mtime)]
    if newer_skipped:
        lines.append(f"⛔ **{len(newer_skipped)} NEWER handoff(s) could not be "
                     "read and were skipped** — the most recent brief may be "
                     "among them. Investigate before trusting the one below:")
        lines += [_list_line(h) for h in newer_skipped[:SIBLING_LIST_CAP]]

    sibs = [h for h in records
            if h.path != primary.path
            and h.date_key != _UNDATED
            and h.date_key == primary.date_key]
    if sibs:
        if lines:
            lines.append("")
        lines.append(f"⚠️ **{len(sibs)} OTHER handoff(s) share this date and are "
                     "NOT loaded below.** Concurrent sessions do not see each "
                     "other's handoffs, so this brief is one of several and may "
                     "not be the whole picture. Read these before treating it as "
                     "complete:")
        lines += [_list_line(h) for h in sibs[:SIBLING_LIST_CAP]]
        if len(sibs) > SIBLING_LIST_CAP:
            lines.append(f"- …and {len(sibs) - SIBLING_LIST_CAP} more — "
                         f"`ls -t {tilde(HANDOFF_DIR)}`")
    return "\n".join(lines) if lines else None


def handoff_block():
    # One scan drives everything: pick the newest-dated handoff that actually
    # READS (a binary/truncated `*-handoff.md` classifies as a handoff via the
    # errors="replace" head-read but blows up on the strict read here — and
    # main()'s fail-open would then swallow the exception, costing the ENTIRE
    # RESUME block with no symptom). Any newer file we skip for that reason is
    # surfaced in the notice rather than dropped silently.
    records = scan_handoffs()
    primary, text, skipped = None, None, []
    for h in records:
        try:
            text = read_text(h.path)
        except (OSError, UnicodeDecodeError):
            skipped.append(h)
            continue
        primary = h
        break
    if primary is None:
        return None
    intro, sections = split_h2(text)
    intro = re.sub(r"(?s)^---.*?---\s*", "", intro)   # drop frontmatter
    intro = re.sub(r"(?m)^#\s+.*$", "", intro).strip()  # drop the title line
    out = []
    # The notice goes FIRST — ahead of the intro — because cap() truncates the
    # TAIL, and a large intro could otherwise push a warning past the 4000-char
    # cap, where its absence reads as an all-clear.
    notice = _sibling_notice(primary, records, skipped)
    if notice:
        out.append(notice)
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
    out.append(f"_Full handoff: `{tilde(primary.path)}`_")
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
    # Headless workers that don't need the bootstrap (e.g. the Slack
    # responder's relevance-triage runs) set ENGRAM_SKIP=1: dramatically
    # cheaper per-run, since the bootstrap otherwise rides every `claude -p`.
    if os.environ.get("ENGRAM_SKIP"):
        sys.exit(0)
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
