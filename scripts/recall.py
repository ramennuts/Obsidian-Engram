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

RANKING (retrieval review 2026-09-19, patterns taken from NornicDB) —
  1. every filter (party / topic / date / stale) runs INSIDE the SQL, before
     any top-K cut; filtering after a LIMIT silently dropped eligible docs;
  2. OR-matched BM25; the old AND-of-every-word matching found almost
     nothing for a plain question. Title/tag weights are plumbed but left
     equal: no setting beat equal weights on both eval halves;
  3. optional meaning search from a LOCAL embedding sidecar (recall_vec.py),
     fused with BM25 by Reciprocal Rank Fusion (k=60); FAIL-OPEN, so any
     sidecar problem degrades to BM25 alone and says so;
  4. docs whose status says SUPERSEDED/OBSOLETE/ARCHIVED (or that live in an
     archive/ folder) are hidden unless --include-stale: hidden, never deleted.
     A time-decay prior was built and MEASURED OUT: no setting helped
     "latest status" questions without costing keyword/scoped ones;
  5. 1-hop [[wikilink]] neighbours of each hit, behind the same filters.
Each change above was kept only if evals/run_retrieval.py showed a gain on
BOTH halves of the question set; see docs/RECALL-VECTORS.md for numbers.
"""
import argparse
import datetime
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys

VAULT = os.environ.get("ENGRAM_VAULT", os.path.expanduser("~/vault"))
MEMORY = os.environ.get("ENGRAM_MEMORY", os.path.expanduser("~/memory"))
DB = os.path.join(VAULT, ".recall", "index.db")
VDB = os.path.join(VAULT, ".recall", "vectors.db")
_EMBED_HOME = os.path.expanduser("~/.cache/engram-embed")
EMBED_PY = os.environ.get("ENGRAM_EMBED_PY", os.path.join(_EMBED_HOME, "venv", "bin", "python"))
EMBED_MODEL = os.environ.get("ENGRAM_EMBED_MODEL",
                             os.path.join(_EMBED_HOME, "bge-small-en-v1.5"))
SIDECAR = os.environ.get("ENGRAM_RECALL_SIDECAR",
                         os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "recall_vec.py"))
SIDECAR_TIMEOUT = 60
SCHEMA = "3"                           # bump → the disposable cache rebuilds
MANIFEST = os.path.join(VAULT, "machine", "capability-manifest.md")
# One line per search, COUNTS ONLY: a query can name a client, so query text is
# never written. Exists so "are sessions actually using recall?" is measured
# (nothing ran it 2026-08-29 → 09-19) instead of guessed.
USAGE_LOG = os.path.join(VAULT, "machine", "metrics", "recall-usage.jsonl")
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
    con.execute("CREATE TABLE IF NOT EXISTS links(src TEXT, dst TEXT)")
    con.execute("CREATE INDEX IF NOT EXISTS links_src ON links(src)")
    con.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
    con.create_function("is_stale", 2, _is_stale, deterministic=True)
    return con


# Status lines on this vault are free prose ("⛔ SUPERSEDED 2026-08-25, DO NOT
# SEND…"), so match the LEADING word only; a status that merely mentions an
# earlier superseded draft further along must not hide the current doc.
_STALE_RE = re.compile(r"^[\W_]*(superseded|obsolete|archived|deprecated)\b", re.I)


def _is_stale(status, path):
    return int(bool(_STALE_RE.match(status or ""))
               or f"{os.sep}archive{os.sep}" in (path or ""))


# [[wikilink]] / [[path/name|alias]] and [text](file.md) — resolved by basename.
_LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]|\]\(([^)\s#]+\.md)\)")


def _link_names(text):
    out = set()
    for a, b in _LINK_RE.findall(text):
        name = os.path.basename((a or b).strip())
        if name.lower().endswith(".md"):
            name = name[:-3]
        if name:
            out.add(name.lower())
    return out


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
    row = con.execute("SELECT v FROM meta WHERE k='registry_fp'").fetchone()
    if row and row[0] != fp:
        rebuild = True
        if verbose:
            print("[recall] registry changed — full retag")
    con.execute("INSERT OR REPLACE INTO meta VALUES('registry_fp', ?)", (fp,))
    # A new column/table only fills as files change; an older cache would serve
    # half-populated links forever. Schema change → rebuild the disposable cache.
    row = con.execute("SELECT v FROM meta WHERE k='schema'").fetchone()
    if not row or row[0] != SCHEMA:
        rebuild = True
    con.execute("INSERT OR REPLACE INTO meta VALUES('schema', ?)", (SCHEMA,))
    # Read BEFORE a rebuild clears the table: a doc deleted since the last
    # index must still register as gone so its vectors get purged (board
    # 2026-09-19 follow-up 4).
    known = dict(con.execute("SELECT path, mtime FROM docs"))
    if rebuild:
        con.execute("DELETE FROM docs")
        con.execute("DELETE FROM docs_fts")
        con.execute("DELETE FROM links")
    seen, added, removed = set(), 0, []
    for path in _walk():
        seen.add(path)
        try:
            st = os.stat(path)
        except OSError:
            continue
        if st.st_size > MAX_DOC_BYTES:
            # Honestly absent beats confidently stale: a doc that GREW past the
            # cap must drop out of results, not serve its old snapshot forever.
            removed.append(path)
            con.execute("DELETE FROM docs WHERE path=?", (path,))
            con.execute("DELETE FROM docs_fts WHERE path=?", (path,))
            con.execute("DELETE FROM links WHERE src=?", (path,))
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
        con.execute("DELETE FROM links WHERE src=?", (path,))
        con.executemany("INSERT INTO links VALUES(?,?)",
                        [(path, n) for n in _link_names(text)])
        added += 1
    gone = set(known) - seen
    for path in gone:
        con.execute("DELETE FROM docs WHERE path=?", (path,))
        con.execute("DELETE FROM docs_fts WHERE path=?", (path,))
        con.execute("DELETE FROM links WHERE src=?", (path,))
    con.commit()
    _purge_vectors(removed + sorted(gone))
    n = con.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    if verbose:
        print(f"[recall] indexed {n} docs (+{added}, -{len(gone)}) at {DB}")
    con.close()
    return n


# Only used in OR mode, where a bare "the"/"what" would match every doc.
_STOP = frozenset(["a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "could", "did", "do", "does", "for", "from", "had", "has", "have", "how", "i", "if", "in", "into", "is", "it", "its", "me", "my", "of", "on", "or", "our", "should", "so", "than", "that", "the", "their", "them", "then", "there", "these", "they", "this", "to", "was", "we", "were", "what", "when", "where", "which", "who", "why", "will", "with", "would", "you", "your", "yet", "now", "actually", "just", "still"])


def _purge_vectors(paths):
    """A doc leaving the index must not leave its chunk text in vectors.db
    until some later meaning search happens to run (board 2026-09-19 1(iv)).
    Best-effort and brief: search()'s mtime check covers a miss."""
    if not paths or not os.path.exists(VDB):
        return
    try:
        vc = sqlite3.connect(VDB, timeout=2)
        vc.executemany("DELETE FROM chunks WHERE path=?", [(p,) for p in paths])
        vc.commit()
        vc.close()
    except sqlite3.Error:
        pass


def _fts_quote(query, match="or"):
    """Treat the query as plain words, not FTS syntax — quote each term so
    hyphens/apostrophes in normal prose can't raise fts5 syntax errors.

    match="or" (default): any term may match and BM25 ranks docs holding more
    (and rarer) terms higher, which is standard BM25. match="and" requires
    every word, so a natural-language question matched almost nothing:
    paraphrase Hit@5 was 0.03 on the 2026-09-19 eval."""
    terms = re.findall(r"\w+", query)
    if match == "or":
        kept = [t for t in terms if t.lower() not in _STOP]
        terms = kept or terms
    if not terms:
        return '""'
    return (" OR " if match == "or" else " ").join(f'"{t}"' for t in terms)


# ── ranking knobs (set from evals/run_retrieval.py; see RANKING above) ──────
BM25_WEIGHTS = (1.0, 1.0, 1.0)       # title, tags, body; see evals --sweep
RRF_K = 60.0                         # NornicDB / Cormack et al. default
VECTOR_WEIGHT = 1.0
BM25_WEIGHT = 1.0


def _candidates(limit):
    return max(limit * 2, 20)


def _filters(party, all_parties, topics, since, include_stale):
    """SQL predicates over `docs d`. EVERY caller applies these before choosing
    top-K. Party clause first; the others are split out so the suppressed
    count can report only docs hidden by isolation."""
    party_sql, party_p = "1", []
    if party and "," in party:
        # A comma-joined scope would string-equal a TWO-party doc's tag and
        # expose it (board 2026-09-19 AUDIT-A #2). One party per scope.
        raise ValueError(f"--party takes ONE slug, got {party!r}")
    if not all_parties:
        # d.party is a sorted comma-joined SET. Keep it only when it is empty or
        # exactly the caller's single scope; a two-party doc never matches one
        # slug, so the OTHER party's content stays suppressed.
        party_sql, party_p = "(COALESCE(d.party,'')='' OR d.party=?)", [party or ""]
    rest, rest_p = [], []
    if topics:
        rest.append("(instr(lower(COALESCE(d.tags,'')), ?)>0 OR instr(lower(d.path), ?)>0)")
        rest_p += [topics.lower(), topics.lower()]
    if since:
        rest.append("(COALESCE(d.date,'')!='' AND d.date>=?)")
        rest_p.append(since)
    stale_sql = "1" if include_stale else "is_stale(d.status, d.path)=0"
    return (party_sql, party_p, " AND ".join(rest) or "1", rest_p, stale_sql)


def _vector_ranks(query, stats):
    """[(path, sim, excerpt, chunk_mtime)] for EVERY embedded doc, best first,
    or None.
    Fail-open: a missing sidecar, a crash, a timeout or bad JSON all return
    None, and BM25 carries the search alone."""
    if os.environ.get("ENGRAM_RECALL_VECTORS", "1") == "0":
        stats["vectors"] = "off"
        return None
    if not (os.path.exists(EMBED_PY) and os.path.isdir(EMBED_MODEL)
            and os.path.exists(SIDECAR)):
        # Silent only where it was never installed. If vectors.db exists, the
        # sidecar WAS here and vanished (e.g. a uv upgrade broke the venv
        # symlink): that degradation must be announced (board 5).
        stats["vectors"] = "missing" if os.path.exists(VDB) else "not installed"
        return None
    try:
        p = subprocess.run([EMBED_PY, SIDECAR, "search", "--db", DB, "--vdb", VDB,
                            "--model", EMBED_MODEL, "--", query],
                           capture_output=True, text=True, timeout=SIDECAR_TIMEOUT)
        if p.returncode != 0:
            lines = (p.stderr or "").strip().splitlines()
            raise RuntimeError(lines[-1] if lines else "exit != 0")
        out = json.loads(p.stdout)
        stats["vectors"] = "on"
        if out.get("stale"):
            stats["vectors"] = f"on ({out['stale']} docs not yet embedded)"
        elif out.get("busy"):
            stats["vectors"] = "on (another session is updating the vector index)"
        return [(r[0], r[1], r[2], r[3]) for r in out.get("results", [])]
    except subprocess.TimeoutExpired:
        stats["vectors"] = ("unavailable (timed out; run `recall.py --rebuild-vectors` "
                            "to catch the vector index up)")
        return None
    except Exception as e:           # noqa: BLE001 — fail-open is the contract
        stats["vectors"] = f"unavailable ({type(e).__name__}: {str(e)[:120]})"
        return None


def related(paths, party=None, all_parties=False, include_stale=False, per_hit=3):
    """{path: [linked doc paths]}: 1-hop wikilink neighbours behind the SAME
    party/stale filters as search results, so a link can never become a side
    door into another party's documents."""
    if not paths:
        return {}
    con = _connect()
    psql, pp, _r, _rp, ssql = _filters(party, all_parties, None, None, include_stale)
    by_name = {}
    for (p,) in con.execute(f"SELECT d.path FROM docs d WHERE {psql} AND {ssql}", pp):
        by_name.setdefault(os.path.basename(p)[:-3].lower(), []).append(p)
    out = {}
    for src in paths:
        names = sorted(r[0] for r in con.execute("SELECT dst FROM links WHERE src=?", (src,)))
        hits = [p for n in names for p in by_name.get(n, []) if p != src]
        if hits:
            out[src] = hits[:per_hit]
    con.close()
    return out


def search(query, topics=None, since=None, limit=8, party=None,
           all_parties=False, include_stale=False, vectors=None, stats=None,
           weights=None, match="or"):
    """(rows, suppressed_count). `stats`, if a dict, receives diagnostics:
    stale_hidden, vectors (on / off / unavailable…). `vectors` None = auto.
    `weights` / `match` exist for evals/run_retrieval.py.

    Filters run BEFORE the top-K cut (they used to run after `LIMIT limit*6`,
    which silently dropped eligible docs ranked below the cut: measured
    2026-09-19, `recall SOW` returned 6 of 8 while 16 eligible docs existed).
    Suppressed = keyword matches hidden ONLY by party isolation.

    By DEFAULT a result belonging to a client/prospect party is suppressed, and
    the count is reported. Cross-party exposure becomes a deliberate keystroke
    (`--party <slug>` / `--all-parties`) instead of an accident — which is the
    whole finding: one `recall "pricing"` used to return one party's economics
    while working for another (board 2026-08-25).

    Chosen over the board's pin-file design because no session id reaches a Bash
    subprocess, so a pin-keyed lookup cannot work — and this also covers the
    UNPINNED machine-wide session, which the pin design would have missed
    entirely."""
    stats = {} if stats is None else stats
    wt, wg, wb = weights or BM25_WEIGHTS
    fts = _fts_quote(query, match)
    psql, pp, rsql, rp, ssql = _filters(party, all_parties, topics, since, include_stale)
    n = _candidates(limit)
    con = _connect()
    base = "FROM docs_fts f JOIN docs d ON d.path = f.path WHERE docs_fts MATCH ?"
    lex = con.execute(
        f"""SELECT f.path, snippet(docs_fts, 3, '»', '«', ' … ', 22) {base}
            AND {psql} AND {rsql} AND {ssql}
            ORDER BY bm25(docs_fts, 0.0, ?, ?, ?) LIMIT ?""",
        [fts] + pp + rp + [wt, wg, wb, n]).fetchall()
    # Suppressed = party docs that WOULD have been candidates: the top n of the
    # same ranking with isolation switched off. Counting every OR-match made a
    # plain question report ~90 hidden docs, and an always-firing warning gets
    # ignored (board 2026-08-25, chair finding (c)).
    suppressed = con.execute(
        f"""SELECT COUNT(*) FROM (SELECT d.party {base} AND {rsql} AND {ssql}
            ORDER BY bm25(docs_fts, 0.0, ?, ?, ?) LIMIT ?) WHERE NOT (
            {psql.replace('d.party', 'party')})""",
        [fts] + rp + [wt, wg, wb, n] + pp).fetchone()[0]
    stats["stale_hidden"] = 0 if include_stale else con.execute(
        f"SELECT COUNT(*) {base} AND {psql} AND {rsql} AND NOT {ssql}",
        [fts] + pp + rp).fetchone()[0]

    ranked = {p: {"bm25": i} for i, (p, _s) in enumerate(lex)}
    snippets = dict(lex)
    vec = None if vectors is False else _vector_ranks(query, stats)
    if vec:
        # The sidecar scores EVERY embedded doc; apply the same SQL filters to
        # all of them, THEN take the top n (never filter a pre-cut list).
        # path -> mtime of the LIVE docs row. A chunk whose mtime differs was
        # cut from other text than the row (and party tag) now describes:
        # never print it (board 2026-09-19 must-fix 1(iii)).
        allowed = dict(con.execute(
            f"SELECT d.path, d.mtime FROM docs d WHERE {psql} AND {rsql} AND {ssql}", pp + rp))
        kept = [(p, s, t) for p, s, t, m in vec if p in allowed and allowed[p] == m][:n]
        for i, (p, _s, t) in enumerate(kept):
            ranked.setdefault(p, {})["vec"] = i
            if p not in snippets:
                snippets[p] = " ".join(t.split("\n", 1)[-1].split()[:40]) + " …"

    stats["party_top1"] = False if all_parties else _party_is_best(
        con, fts, rsql, rp, ssql, (wt, wg, wb), n, vec, party)

    meta = {}
    if ranked:
        qs = ",".join("?" * len(ranked))
        meta = {r[0]: r[1:] for r in con.execute(
            f"SELECT path, title, date, status FROM docs WHERE path IN ({qs})", list(ranked))}
    con.close()
    scored = []
    for p, r in ranked.items():
        if p not in meta:
            continue
        s = 0.0
        if "bm25" in r:
            s += BM25_WEIGHT / (RRF_K + r["bm25"] + 1)
        if "vec" in r:
            s += VECTOR_WEIGHT / (RRF_K + r["vec"] + 1)
        scored.append((-s, r.get("bm25", math.inf), p))
    scored.sort()
    out = [(p, *meta[p], snippets.get(p, "")) for _s, _b, p in scored[:limit]]
    stats["keyword_hits"] = len(lex)
    stats["meaning_only"] = {p for p, *_ in out if "bm25" not in ranked[p]}
    stats["missing_terms"], stats["coverage"] = _term_coverage(
        query, [p for p, *_ in out], psql + f" AND {ssql}", pp)
    return out, suppressed


def _party_is_best(con, fts, rsql, rp, ssql, weights, n, vec, party):
    """Would a HIDDEN party doc be the single best match with isolation off?
    Measured 2026-09-19: the per-doc suppressed count fires on 92% of ordinary
    questions (the always-on warning the 2026-08-25 board rejected), a fused
    top-8 near-miss on 72%, but a hidden party doc at #1 on only 6% of them,
    and on 7 of 8 genuinely party questions asked without --party. Only this
    earns the loud warning. It never names the party."""
    blind = [r[0] for r in con.execute(
        f"""SELECT f.path FROM docs_fts f JOIN docs d ON d.path = f.path
            WHERE docs_fts MATCH ? AND {rsql} AND {ssql}
            ORDER BY bm25(docs_fts, 0.0, ?, ?, ?) LIMIT ?""",
        [fts] + rp + list(weights) + [n])]
    score = {p: BM25_WEIGHT / (RRF_K + i + 1) for i, p in enumerate(blind)}
    tags = {p: (pt or "", m) for p, pt, m in con.execute(
        f"SELECT d.path, d.party, d.mtime FROM docs d WHERE {rsql} AND {ssql}", rp)}
    if vec:
        live = [p for p, _s, _t, m in vec if p in tags and tags[p][1] == m]
        for i, p in enumerate(live[:n]):
            score[p] = score.get(p, 0.0) + VECTOR_WEIGHT / (RRF_K + i + 1)
    if not score:
        return False
    best = max(score, key=score.get)
    doc_parties = {x for x in tags.get(best, ("", 0))[0].split(",") if x}
    return bool(doc_parties - ({party} if party else set()))


def _term_coverage(query, paths, scope_sql, scope_p):
    """OR matching finds SOMETHING for nearly any question (8/8 unanswerable
    eval questions got keyword hits, vs 0/8 under AND). So say how much each
    hit matched, and which query terms NO in-scope doc contains: a question
    about a topic the vault never mentions says so. Counted within the
    caller's party scope, so it never reveals a word that only party docs hold.
    Returns ([missing terms], {path: (matched, total)})."""
    terms = [t for t in dict.fromkeys(re.findall(r"\w+", query))
             if t.lower() not in _STOP]
    if len(terms) < 2:
        return [], {}
    con = _connect()
    missing, hits = [], dict.fromkeys(paths, 0)
    for t in terms:
        found = {r[0] for r in con.execute(
            f"""SELECT f.path FROM docs_fts f JOIN docs d ON d.path = f.path
                WHERE docs_fts MATCH ? AND {scope_sql}""", [f'"{t}"'] + scope_p)}
        if not found:
            missing.append(t)
        for p in paths:
            hits[p] += p in found
    con.close()
    return missing, {p: (k, len(terms)) for p, k in hits.items()}


def _log_usage(hits, stats, scoped):
    try:
        os.makedirs(os.path.dirname(USAGE_LOG), exist_ok=True)
        with open(USAGE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "hits": len(hits), "keyword_hits": stats.get("keyword_hits", 0),
                "vectors": stats.get("vectors", "").split(" ")[0],
                "no_record_signal": bool(stats.get("missing_terms")),
                "scoped": scoped}) + "\n")
    except OSError:
        pass                      # a metric must never break a search


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
    ap.add_argument("--include-stale", action="store_true",
                    help="also show docs whose status is SUPERSEDED/OBSOLETE/ARCHIVED")
    ap.add_argument("--no-vectors", action="store_true",
                    help="keyword (BM25) search only; skip the meaning-search sidecar")
    ap.add_argument("--rebuild-vectors", action="store_true",
                    help="re-embed every document with the local model, then exit")
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
        if not args.query and not args.rebuild_vectors:
            return 0
    if args.rebuild_vectors:
        index()
        if not (os.path.exists(EMBED_PY) and os.path.isdir(EMBED_MODEL)):
            print("[recall] meaning search is not installed (see docs/RECALL-VECTORS.md)",
                  file=sys.stderr)
            return 1
        return subprocess.run([EMBED_PY, SIDECAR, "index", "--rebuild", "--db", DB,
                               "--vdb", VDB, "--model", EMBED_MODEL]).returncode
    if not args.query:
        ap.print_usage()
        return 1
    if not args.no_reindex:
        index()  # incremental; cheap
    q = " ".join(args.query)
    if args.party:
        slugs = {slug for slug, _k, _p in load_registry()}
        if "," in args.party or (slugs and args.party not in slugs):
            print(f"[recall] --party takes ONE registered slug; got {args.party!r}",
                  file=sys.stderr)
            return 2
    stats = {}
    hits, suppressed = search(q, topics=args.topics, since=args.since,
                              limit=args.limit, party=args.party,
                              all_parties=args.all_parties,
                              include_stale=args.include_stale,
                              vectors=False if args.no_vectors else None, stats=stats)
    _log_usage(hits, stats, scoped=bool(args.party or args.all_parties))
    vstat = stats.get("vectors", "")
    # Fail-open must never be SILENT: say when BM25 carried this search alone.
    if vstat.startswith("unavailable"):
        print(f"[recall] meaning search {vstat}; keyword results only", file=sys.stderr)
    elif vstat == "missing":
        print("[recall] meaning search was installed (vectors.db exists) but its "
              "sidecar/model is gone; keyword results only. Reinstall: "
              "scripts/install_recall_vectors.sh", file=sys.stderr)
    elif vstat.startswith("on ("):
        print(f"[recall] meaning search {vstat}", file=sys.stderr)
    if not hits and not suppressed and not stats.get("stale_hidden"):
        print(f"[recall] no hits for: {q}")
        return 0
    if stats.get("party_top1"):
        # Loud only when it matters: the best match is a hidden party doc.
        print("⚠ The BEST match for this is a client/prospect document, hidden by "
              "party isolation. If this session works for that party, re-run with "
              "--party <slug> (or --all-parties, deliberately).")
    if suppressed:
        print(f"ℹ {suppressed} keyword result(s) from client/prospect docs hidden "
              f"(party isolation).")
    if stats.get("stale_hidden"):
        print(f"ℹ {stats['stale_hidden']} superseded/obsolete doc(s) hidden. "
              f"Use --include-stale to see them.")
    if not hits:
        print(f"[recall] no unsuppressed hits for: {q}")
        return 0
    if stats.get("missing_terms"):
        print(f"ℹ no document in scope mentions: {', '.join(stats['missing_terms'])} "
              f"(results below match other words only)")
    if not stats.get("keyword_hits"):
        # Meaning search ranks EVERY doc, so it always "finds" something. An
        # honest "no record of that" must survive it (board 2026-09-19 #6).
        print(f"[recall] no keyword hits for: {q}; nearest by meaning "
              f"(may be unrelated):")
    home = os.path.expanduser("~")
    meaning_only = stats.get("meaning_only", set())
    links = related([h[0] for h in hits], party=args.party,
                    all_parties=args.all_parties, include_stale=args.include_stale)
    for path, title, date, status, snip in hits:
        cov = stats.get("coverage", {}).get(path)
        tag = ("meaning match only" if path in meaning_only
               else f"{cov[0]}/{cov[1]} terms" if cov else "")
        meta = " · ".join(x for x in (date, (status or "")[:60], tag) if x)
        print(f"• {path.replace(home, '~')}  ({meta})" if meta
              else f"• {path.replace(home, '~')}")
        print(f"  {title}")
        print(f"  {snip.strip()}".replace("\n", " ")[:300])
        if links.get(path):
            print("  ↳ links: " + ", ".join(os.path.basename(p)[:-3] for p in links[path]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
