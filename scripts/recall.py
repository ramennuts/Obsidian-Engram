#!/usr/bin/env python3
"""Engram — `recall`: full-text search over the vault + durable memory.

Answers "have we done X / decided X / where is X recorded?" in under ~1k tokens
instead of a session re-reading 40k-token files or re-deriving past work
(memory-v2 U7). SQLite FTS5, stdlib only, $0.

CANONICAL vs CACHE — the markdown is the source of truth; the index at
$ENGRAM_VAULT/.recall/index.db is a disposable cache, rebuildable any time
(`--rebuild`). Never treat the index as authoritative (agentcairn stance).

ISOLATION — indexes ONLY the allow-list (vault + $ENGRAM_MEMORY). Client
workspaces (~/clients) and ~/personal are NEVER indexed here by construction;
a client workspace gets its own in-workspace index if needed. Enforced by
tests/test_recall.py.

  recall.py "zoho seats"            # top hits: path · date · status · snippet
  recall.py --topics sow --since 2026-08-01 "pricing"
  recall.py --capabilities          # print the capability manifest digest
  recall.py --rebuild               # drop + rebuild the index from scratch
"""
import argparse
import hashlib
import os
import re
import sqlite3
import sys

VAULT = os.environ.get("ENGRAM_VAULT", os.path.expanduser("~/vault"))
MEMORY = os.environ.get("ENGRAM_MEMORY", os.path.expanduser("~/memory"))
DB = os.path.join(VAULT, ".recall", "index.db")
MANIFEST = os.path.join(VAULT, "machine", "capability-manifest.md")
ALLOW_ROOTS = [VAULT, MEMORY]          # the ONLY trees ever indexed
SKIP_DIRS = {".git", ".obsidian", ".trash", ".recall", "node_modules",
             "__pycache__", ".venv",
             # Session-scoped ephemera: indexing checkpoints would make any
             # session's in-flight todos permanently searchable from every
             # other session (board 2026-08-24, audit ADDED-4).
             "checkpoints", "metrics"}
MAX_DOC_BYTES = 400_000                # sanity cap per file
# The registry lists every party in one place. It is READ as config; it must
# never also be a searchable document (board 2026-08-25).
REGISTRY = os.path.join(VAULT, "rgardin-ai", "reference", "party-registry.md")

_FM_RE = re.compile(r"(?s)\A---\s*\n(.*?)\n---")
_REGISTRY_BLOCK = re.compile(r"(?s)```registry\n(.*?)```")


def load_registry(path=None):
    """[(slug, kind, [phrases])]. Empty on ANY failure — recall must degrade to
    today's behaviour, never wedge."""
    try:
        with open(path or REGISTRY, encoding="utf-8") as f:
            m = _REGISTRY_BLOCK.search(f.read())
        if not m:
            return []
        out = []
        for line in m.group(1).splitlines():
            parts = [x.strip() for x in line.split("|") if x.strip()]
            if len(parts) >= 3:
                out.append((parts[0], parts[1].lower(), parts[2:]))
        return out
    except Exception:
        return []


def parties_of(text, registry):
    """SORTED LIST of every client/prospect party whose PHRASE appears.

    NEVER first-match. A document that mentions two parties is routine in a
    two-person shop working several deals, and first-match silently stamped it
    with one of them — so the OTHER party's terms rode along unsuppressed, even
    into a session that had correctly scoped itself with --party. Reproduced
    against real production files (verification round, MUST-FIX #1).
    compactor._parties_in() got this right the same day; these call sites did
    not receive the same fix."""
    low = text.lower()
    found = set()
    for slug, kind, phrases in registry:
        if kind not in ("client", "prospect"):
            continue
        if any(ph.lower() in low for ph in phrases):
            found.add(slug)
    return sorted(found)


def party_of(text, registry):
    """Legacy single-slug helper, kept only for callers that want a display
    label. NEVER use it for a suppression decision — see parties_of().

    Phrase, never token: the two live party names both begin with common English
    words, and a token matcher hit 148 of 377 documents where the phrase matcher
    hits 59. A detector that fires on 39% of the corpus gets ignored exactly like
    a stale warning (board 2026-08-25, chair finding (c)).

    NOTE: deliberately no cwd-based auto-scoping. The board's original design
    read a session-pin file, but no session id reaches a Bash subprocess (checked
    — the env carries none), and a cwd proxy would require hard-coding the
    customer root, which the isolation guard correctly refuses to let a script
    reference. Explicit --party scoping is the control."""
    low = text.lower()
    for slug, _kind, phrases in registry:
        for ph in phrases:
            if ph.lower() in low:
                return slug
    return ""


_F = {k: re.compile(rf"(?m)^{k}:\s*[\"']?(.+?)[\"']?\s*$")
      for k in ("title", "date", "status", "type")}
_TAGS_RE = re.compile(r"(?m)^tags:\s*\[(.*?)\]")
_FNAME_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _connect():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB, timeout=15)
    con.execute("PRAGMA journal_mode=WAL")
    # Concurrent sessions are this system's founding premise: without a busy
    # timeout, a session querying during another's reindex gets an unhandled
    # "database is locked" traceback (chair M9).
    con.execute("PRAGMA busy_timeout=15000")
    cols = {r[1] for r in con.execute("PRAGMA table_info(docs)")}
    if cols and "party" not in cols:   # disposable cache — rebuild, never migrate
        con.execute("DROP TABLE IF EXISTS docs")
        con.execute("DROP TABLE IF EXISTS docs_fts")
        con.execute("""CREATE TABLE docs(
            path TEXT PRIMARY KEY, mtime REAL, size INTEGER,
            title TEXT, date TEXT, status TEXT, type TEXT, tags TEXT,
            party TEXT DEFAULT '')""")
        con.execute("""CREATE VIRTUAL TABLE docs_fts USING fts5(
            path UNINDEXED, title, tags, body, tokenize='porter unicode61')""")
    con.execute("""CREATE TABLE IF NOT EXISTS docs(
        path TEXT PRIMARY KEY, mtime REAL, size INTEGER,
        title TEXT, date TEXT, status TEXT, type TEXT, tags TEXT,
        party TEXT DEFAULT '')""")
    con.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
        path UNINDEXED, title, tags, body, tokenize='porter unicode61')""")
    return con


def _walk():
    for root in ALLOW_ROOTS:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            # os.walk never descends dir symlinks (followlinks=False), but a
            # FILE symlink lists as a plain file and open() follows it — an
            # allow-list bypass (board 2026-08-24, B1). Skip links entirely.
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                if not fn.endswith(".md"):
                    continue
                # Containment, not symlink-refusal: an in-tree symlink target
                # is fine, an escape is not (board 2026-08-24 B1 + ADDED-2).
                try:
                    rp, rr = os.path.realpath(p), os.path.realpath(root)
                    if os.path.commonpath([rp, rr]) != rr:
                        continue
                    if rp == os.path.realpath(REGISTRY):
                        continue      # config, never a search result
                except (ValueError, OSError):
                    continue
                yield p


def _meta(text, path):
    fm = _FM_RE.match(text)
    block = fm.group(1) if fm else ""

    def get(k):
        m = _F[k].search(block)
        return m.group(1).strip() if m else ""

    tags = _TAGS_RE.search(block)
    date = get("date")
    if not date:
        m = _FNAME_DATE_RE.search(os.path.basename(path))
        date = m.group(1) if m else ""
    return (get("title") or os.path.basename(path), date, get("status"),
            get("type"), tags.group(1).replace('"', "") if tags else "")


def _registry_fingerprint(registry):
    return hashlib.blake2b(repr(registry).encode(), digest_size=8).hexdigest()


def index(rebuild=False, verbose=False):
    registry = load_registry()
    con = _connect()
    # A party added to the registry today must retag documents indexed
    # yesterday. Incremental indexing skips unchanged files by mtime, so without
    # this a newly-registered party gets ZERO suppression on all existing
    # content — silently (verification round).
    fp = _registry_fingerprint(registry)
    con.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
    row = con.execute("SELECT v FROM meta WHERE k='registry_fp'").fetchone()
    if row and row[0] != fp:
        rebuild = True
        if verbose:
            print("[recall] registry changed — full retag")
    con.execute("INSERT OR REPLACE INTO meta VALUES('registry_fp', ?)", (fp,))
    if rebuild:
        con.execute("DELETE FROM docs")
        con.execute("DELETE FROM docs_fts")
    known = dict(con.execute("SELECT path, mtime FROM docs"))
    seen, added = set(), 0
    for path in _walk():
        seen.add(path)
        try:
            st = os.stat(path)
        except OSError:
            continue
        if st.st_size > MAX_DOC_BYTES:
            # Honestly absent beats confidently stale: a doc that GREW past the
            # cap must drop out of results, not serve its old snapshot forever.
            con.execute("DELETE FROM docs WHERE path=?", (path,))
            con.execute("DELETE FROM docs_fts WHERE path=?", (path,))
            continue
        if not rebuild and known.get(path) == st.st_mtime:
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        title, date, status, typ, tags = _meta(text, path)
        party = ",".join(parties_of(path + "\n" + text, registry))
        con.execute("DELETE FROM docs_fts WHERE path=?", (path,))
        con.execute("INSERT OR REPLACE INTO docs VALUES(?,?,?,?,?,?,?,?,?)",
                    (path, st.st_mtime, st.st_size, title, date, status, typ,
                     tags, party))
        con.execute("INSERT INTO docs_fts(path,title,tags,body) VALUES(?,?,?,?)",
                    (path, title, tags, text))
        added += 1
    gone = set(known) - seen
    for path in gone:
        con.execute("DELETE FROM docs WHERE path=?", (path,))
        con.execute("DELETE FROM docs_fts WHERE path=?", (path,))
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    if verbose:
        print(f"[recall] indexed {n} docs (+{added}, -{len(gone)}) at {DB}")
    con.close()
    return n


def _fts_quote(query):
    """Treat the query as plain words, not FTS syntax — quote each term so
    hyphens/apostrophes in normal prose can't raise fts5 syntax errors."""
    terms = re.findall(r"\w+", query)
    return " ".join(f'"{t}"' for t in terms) if terms else '""'


def search(query, topics=None, since=None, limit=8, party=None,
           all_parties=False):
    """(rows, suppressed_count).

    By DEFAULT a result belonging to a client/prospect party is suppressed, and
    the count is reported. Cross-party exposure becomes a deliberate keystroke
    (`--party <slug>` / `--all-parties`) instead of an accident — which is the
    whole finding: one `recall "pricing"` used to return one party's economics
    while working for another (board 2026-08-25).

    Chosen over the board's pin-file design because no session id reaches a Bash
    subprocess, so a pin-keyed lookup cannot work — and this also covers the
    UNPINNED machine-wide session, which the pin design would have missed
    entirely."""
    con = _connect()
    rows = con.execute(
        """SELECT f.path, d.title, d.date, d.status,
                  snippet(docs_fts, 3, '»', '«', ' … ', 22), d.party
           FROM docs_fts f JOIN docs d ON d.path = f.path
           WHERE docs_fts MATCH ? ORDER BY bm25(docs_fts) LIMIT ?""",
        (_fts_quote(query), limit * 6)).fetchall()
    out, suppressed = [], 0
    for path, title, date, status, snip, rparty in rows:
        # rparty is a comma-joined SET. Suppress when the document belongs to
        # ANY client/prospect party other than the caller's single scope — an
        # internal phrase co-occurring in the file must never exempt it.
        doc_parties = {x for x in (rparty or "").split(",") if x}
        if not all_parties and (doc_parties - ({party} if party else set())):
            suppressed += 1
            continue
        if topics:
            tags = (con.execute("SELECT tags FROM docs WHERE path=?",
                                (path,)).fetchone() or [""])[0]
            if topics.lower() not in tags.lower() and topics.lower() not in path.lower():
                continue
        if since and (not date or date < since):
            continue
        out.append((path, title, date, status, snip))
        if len(out) >= limit:
            break
    con.close()
    return out, suppressed


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="*", help="search terms")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--reindex", action="store_true",
                    help="incremental refresh before searching (default on)")
    ap.add_argument("--no-reindex", action="store_true")
    ap.add_argument("--topics", help="require tag/path substring")
    ap.add_argument("--since", help="YYYY-MM-DD floor on the doc date")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--party", help="scope to ONE party slug (see the registry)")
    ap.add_argument("--all-parties", action="store_true",
                    help="deliberately include every party's results")
    ap.add_argument("--capabilities", action="store_true",
                    help="print the capability manifest digest and exit")
    args = ap.parse_args()

    if args.capabilities:
        try:
            with open(MANIFEST, encoding="utf-8") as f:
                text = f.read()
            m = re.search(r"(?s)## Digest\n(.*?)(?=\n## |\Z)", text)
            print(m.group(1).strip() if m else text[:2000])
        except OSError:
            print("[recall] no capability manifest yet — run "
                  "scripts/gen_capabilities.py", file=sys.stderr)
            return 1
        return 0

    if args.rebuild:
        index(rebuild=True, verbose=True)
        if not args.query:
            return 0
    if not args.query:
        ap.print_usage()
        return 1
    if not args.no_reindex:
        index()  # incremental; cheap
    q = " ".join(args.query)
    hits, suppressed = search(q, topics=args.topics, since=args.since,
                              limit=args.limit, party=args.party,
                              all_parties=args.all_parties)
    if not hits and not suppressed:
        print(f"[recall] no hits for: {q}")
        return 0
    if suppressed:
        # Counted and VISIBLE at the moment of the near-miss — the operator is
        # already reading this output.
        print(f"⚠ {suppressed} result(s) suppressed (party-scoped isolation). "
              f"Use --party <slug> for one party, or --all-parties, "
              f"deliberately.")
    if not hits:
        print(f"[recall] no unsuppressed hits for: {q}")
        return 0
    home = os.path.expanduser("~")
    for path, title, date, status, snip in hits:
        meta = " · ".join(x for x in (date, status) if x)
        print(f"• {path.replace(home, '~')}  ({meta})" if meta
              else f"• {path.replace(home, '~')}")
        print(f"  {title}")
        print(f"  {snip.strip()}".replace("\n", " ")[:300])
    return 0


if __name__ == "__main__":
    sys.exit(main())
