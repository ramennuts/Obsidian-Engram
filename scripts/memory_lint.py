#!/usr/bin/env python3
"""Engram — lint the durable-memory directory for integrity.

Catches the drift that makes Layer-1 memory go stale and silently wrong:
  - ORPHANS    : note files on disk that aren't listed in MEMORY.md (the index
                 misses them, so they're loaded as context but invisible in the map).
  - DANGLING   : `[[wikilinks]]` that point at a slug with no matching file.
  - INDEX GAPS : MEMORY.md entries linking to a file that doesn't exist.
  - FRONTMATTER: notes missing a `name:`/`description:`/`type:` field.

Read-only; changes nothing. Exit code 1 if any problem is found (handy in CI / a
pre-commit hook). Point it at your memory dir with $ENGRAM_MEMORY or --dir.

  python3 scripts/memory_lint.py [--dir PATH]
"""
import argparse
import os
import re
import sys

DEFAULT_DIR = os.environ.get("ENGRAM_MEMORY", os.path.expanduser("~/memory"))
INDEX = "MEMORY.md"
LINK_RE = re.compile(r"\[\[([a-zA-Z0-9_\-]+)\]\]")
INDEX_LINK_RE = re.compile(r"\]\(([a-zA-Z0-9_\-]+)\.md\)")
REQUIRED_FIELDS = ("name", "description", "type")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def note_files(d):
    return sorted(f for f in os.listdir(d) if f.endswith(".md") and f != INDEX)


def frontmatter(text):
    m = re.match(r"(?s)^---\n(.*?)\n---", text)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=DEFAULT_DIR)
    args = ap.parse_args()
    d = args.dir

    if not os.path.isdir(d):
        print(f"[memory-lint] directory not found: {d}", file=sys.stderr)
        return 1
    index_path = os.path.join(d, INDEX)
    if not os.path.isfile(index_path):
        print(f"[memory-lint] no {INDEX} index in {d}", file=sys.stderr)
        return 1

    files = note_files(d)
    slugs = {f[:-3] for f in files}
    index_text = read(index_path)
    indexed = set(INDEX_LINK_RE.findall(index_text))

    problems = []

    for slug in sorted(slugs - indexed):
        problems.append(f"ORPHAN     {slug}.md is on disk but not linked in {INDEX}")
    for slug in sorted(indexed - slugs):
        problems.append(f"INDEX GAP  {INDEX} links {slug}.md but the file is missing")

    for f in files:
        text = read(os.path.join(d, f))
        fm = frontmatter(text)
        missing = [k for k in REQUIRED_FIELDS if k not in fm]
        if missing:
            problems.append(f"FRONTMATTER {f} missing: {', '.join(missing)}")
        for target in LINK_RE.findall(text):
            if target not in slugs:
                problems.append(f"DANGLING   {f} links [[{target}]] — no such note")

    print(f"[memory-lint] {len(files)} notes in {d.replace(os.path.expanduser('~'), '~')}")
    if not problems:
        print("[memory-lint] ✓ clean — index complete, no dangling links, frontmatter OK")
        return 0
    print(f"[memory-lint] {len(problems)} problem(s):\n")
    for p in problems:
        print(f"  {p}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
