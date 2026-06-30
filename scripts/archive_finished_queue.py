#!/usr/bin/env python3
"""Engram — archive fully-finished items out of your work queue's live sections.

`build-queue.md`'s `## Active items` / `## Blocked` sections accumulate
struck-through DONE/SHIPPED items that bloat the file (and the SessionStart hook's
injection). This moves the UNAMBIGUOUSLY FINISHED ones into a `## Auto-archived`
section, leaving anything still live in place.

SAFETY — the classifier errs toward KEEP. A wrongly-kept done item is harmless
clutter; a wrongly-archived live item hides real work. A struck header is NOT
enough — an item can be struck yet still carry an open thread (a pending sub-task,
a blocker, a to-do).

  ARCHIVE an item  <=>  ALL of:
    1. its `### ` header is struck-through ( ~~...~~ ), AND
    2. the header's POST-STRIKE text has a completion marker
       (shipped / done / closed / resolved / complete / won't-fix), AND
    3. the item — with all ~~struck~~ spans removed first — has NO live-thread
       word (still to do / pending / blocked / next callout / one piece left /
       optional follow-up / held for / awaiting / resume checklist / until then / to-do).
  KEEP otherwise. (Note: "superseded" / "deferred" have no completion marker, so
  pushed-aside items are KEPT, not archived.)

Removing struck spans BEFORE the live-thread scan is the crux: a header like
`~~eval-runner still pending~~ — DONE` reads as DONE, because the "still pending"
is struck out. Conversely `~~Build page~~ SHIPPED ... **Still to do:** wire it up`
stays live because that callout is NOT struck.

GOTCHA: a resolution note that *quotes* a marker ("the **Still to do** note was
stale") will keep the item — phrase resolutions WITHOUT the trigger words.

DRY-RUN by default; prints the decision + reason per item. `--apply` writes after
a timestamped `.bak`. Idempotent: the archive section is never re-scanned.

Vault path via $ENGRAM_VAULT (default ~/vault); override the file with --file.
"""
import argparse
import datetime
import os
import re
import shutil
import sys

VAULT = os.environ.get("ENGRAM_VAULT", os.path.expanduser("~/vault"))
DEFAULT_FILE = os.path.join(VAULT, "build-queue.md")
SOURCE_HEADERS = ["## Active items", "## Blocked"]
ARCHIVE_HEADER = "## Auto-archived"
ARCHIVE_NOTE = (
    "_Auto-moved here by `scripts/archive_finished_queue.py` once an item was "
    "fully finished (struck header + a done/shipped/closed marker + no open "
    "thread). Newest at top. Anything still live — even if struck, superseded, or "
    "pushed-aside — stays put._"
)

STRIKE_RE = re.compile(r"~~.*?~~")
COMPLETION_RE = re.compile(r"\b(shipped|done|closed|resolved|complete|completed)\b", re.I)
WONTFIX_RE = re.compile(r"won'?t[ -]?fix", re.I)
LIVE_RES = [re.compile(p, re.I) for p in (
    r"still to do", r"\boutstanding\b", r"\bpending\b", r"\bblocked\b",
    r"\*\*[^*\n]{0,40}next\b", r"optional follow", r"follow-?up",
    r"one piece left", r"pieces? left", r"held for", r"awaiting",
    r"waiting on", r"still needs?\b", r"resume checklist", r"until then",
    r"\bto-?do\b", r"not urgent",
)]


def find_section(content, header):
    m = re.search(r"(?m)^" + re.escape(header) + r"[ \t]*$", content)
    if not m:
        return None
    nxt = re.search(r"(?m)^## ", content[m.end():])
    return m.start(), (m.end() + nxt.start() if nxt else len(content))


def split_items(section_text):
    lines = section_text.split("\n")
    header, rest = lines[0], lines[1:]
    preamble, items, cur = [], [], None
    for ln in rest:
        if ln.startswith("### "):
            if cur is not None:
                items.append(cur)
            cur = [ln]
        elif cur is None:
            preamble.append(ln)
        else:
            cur.append(ln)
    if cur is not None:
        items.append(cur)
    return header, preamble, items


def classify(item_lines):
    text = "\n".join(item_lines)
    header = item_lines[0]
    if "~~" not in header:
        return False, "KEEP — header not struck (treated as still-active)"
    stripped_header = STRIKE_RE.sub("", header)
    if not (COMPLETION_RE.search(stripped_header) or WONTFIX_RE.search(stripped_header)):
        return False, "KEEP — struck but no done/shipped/closed marker in header"
    stripped = STRIKE_RE.sub("", text)
    hit = next((r.pattern for r in LIVE_RES if r.search(stripped)), None)
    if hit:
        return False, f"KEEP — struck+done but live thread present (/{hit}/)"
    return True, "ARCHIVE — struck + completion marker + no open thread"


def short(header):
    return STRIKE_RE.sub(lambda m: m.group(0)[2:-2], header)[4:].strip()[:90]


def build_archive_section(existing_span, content, new_items):
    new_block = "\n".join("\n".join(it).rstrip("\n") for it in new_items)
    if existing_span:
        s, e = existing_span
        body = content[s:e].split("\n", 1)[1] if "\n" in content[s:e] else ""
        body = re.sub(r"^\s*_Auto-moved.*?_\s*", "", body, flags=re.S).strip("\n")
        parts = [ARCHIVE_HEADER, "", ARCHIVE_NOTE, "", new_block]
        if body:
            parts += ["", body]
        return "\n".join(parts).rstrip("\n") + "\n"
    return "\n".join([ARCHIVE_HEADER, "", ARCHIVE_NOTE, "", new_block]).rstrip("\n") + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=DEFAULT_FILE)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = ap.parse_args()

    if not os.path.isfile(args.file):
        print(f"[archive] file not found: {args.file}", file=sys.stderr)
        return 1
    with open(args.file, encoding="utf-8") as f:
        content = f.read()

    archive_all = []
    for src in SOURCE_HEADERS:
        span = find_section(content, src)
        if not span:
            continue
        start, end = span
        header, preamble, items = split_items(content[start:end])
        keep, archive = [], []
        print(f"\n[archive] scanning {len(items)} item(s) under '{src}':\n")
        for it in items:
            do_archive, reason = classify(it)
            print(f"  {'📦 ARCHIVE' if do_archive else '✅ KEEP   '}  {short(it[0])}")
            print(f"            ↳ {reason}")
            (archive if do_archive else keep).append(it)
        if not archive:
            continue
        kept = [header] + preamble + [ln for it in keep for ln in it]
        content = content[:start] + ("\n".join(kept).rstrip("\n") + "\n\n") + content[end:]
        archive_all.extend(archive)

    print(f"\n[archive] result: {len(archive_all)} to archive.")
    if not archive_all:
        print("[archive] nothing finished to move — no change.")
        return 0

    arch_span = find_section(content, ARCHIVE_HEADER)
    archive_text = build_archive_section(arch_span, content, archive_all)
    if arch_span:
        s2, e2 = arch_span
        new_content = content[:s2] + archive_text + content[e2:]
    else:
        new_content = content.rstrip("\n") + "\n\n" + archive_text

    if not args.apply:
        print("\n[archive] DRY-RUN — no file written. Re-run with --apply to commit.")
        return 0

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = f"{args.file}.{stamp}.bak"
    shutil.copy2(args.file, bak)
    tmp = f"{args.file}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new_content)
    os.replace(tmp, args.file)
    print(f"\n[archive] APPLIED — moved {len(archive_all)} item(s). Backup: {bak}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
