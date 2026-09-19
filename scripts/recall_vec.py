#!/usr/bin/env python3
"""Engram — optional meaning-search sidecar for `recall` (NOT stdlib at search time).

recall.py stays standard-library only. This sidecar runs under a separate
interpreter that has numpy + onnxruntime + tokenizers, and a LOCAL embedding
model (default BAAI/bge-small-en-v1.5, ONNX, pinned revision). Nothing leaves
the machine: an embedding API would be a new vendor holding every document it
embeds, client text included.

It embeds ONLY documents already in recall's `docs` table, so it inherits the
allow-list by construction; it never walks the filesystem itself. It returns a
score for EVERY embedded document (brute force; the corpus is hundreds of
docs), so recall.py applies party/topic/date filters BEFORE any top-K cut.

CACHE HONESTY (board 2026-09-19, must-fix 1-2). recall.py filters on the LIVE
`docs` row, but prints chunk text from this cache, so a chunk must never
outlive the text it came from:
  - a doc is embedded only if its file mtime equals the docs-table mtime both
    before AND after the read (an edit mid-update is skipped, not mis-tagged);
  - every changed doc NOT embedded in this call has its old chunks purged;
  - each result carries its chunk mtime, and recall.py drops any mismatch.
And it must never wedge a search: no transaction is held while embedding,
each doc is written in its own short transaction, inline work stops at a time
budget well under recall.py's kill timeout, and a busy writer is skipped
(WAL readers never block).

  recall_vec.py search --db INDEX --vdb VECTORS --model DIR -- "query"   # JSON
  recall_vec.py index  --db INDEX --vdb VECTORS --model DIR [--rebuild]
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import time

# bge-*-v1.5 recommends this instruction on short retrieval queries, not docs.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
CHUNK_WORDS = 180
CHUNK_OVERLAP = 40
MAX_TOKENS = 512
BATCH = 16
INLINE_BUDGET_S = 15.0      # recall.py kills the sidecar at 60 s
SEARCH_BUSY_MS = 2000       # a search never waits long for another writer
LEASE_S = INLINE_BUDGET_S + 10   # one session embeds inline at a time

_FM_RE = re.compile(r"(?s)\A---\s*\n.*?\n---\s*\n?")


class Embedder:
    """bge CLS-pooled, L2-normalised embeddings. embed() returns float32 bytes
    per text, so update() needs no numpy (tests use a stdlib fake)."""

    def __init__(self, model_dir):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.np = np
        self.tok = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        self.tok.enable_truncation(MAX_TOKENS)
        self.tok.enable_padding()
        so = ort.SessionOptions()
        so.log_severity_level = 3
        self.sess = ort.InferenceSession(os.path.join(model_dir, "model.onnx"), so,
                                         providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.sess.get_inputs()}

    def embed(self, texts):
        np = self.np
        out = []
        for i in range(0, len(texts), BATCH):
            enc = self.tok.encode_batch(texts[i:i + BATCH])
            feed = {"input_ids": np.array([e.ids for e in enc], dtype=np.int64),
                    "attention_mask": np.array([e.attention_mask for e in enc],
                                               dtype=np.int64)}
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.array([e.type_ids for e in enc], dtype=np.int64)
            cls = self.sess.run(None, feed)[0][:, 0, :]          # bge uses CLS pooling
            cls = cls / (np.linalg.norm(cls, axis=1, keepdims=True) + 1e-12)
            out += [row.astype(np.float32).tobytes() for row in cls]
        return out


def chunks(title, text):
    body = _FM_RE.sub("", text)
    words = body.split()
    if not words:
        return [title]
    step = CHUNK_WORDS - CHUNK_OVERLAP
    return [f"{title}\n" + " ".join(words[s:s + CHUNK_WORDS])
            for s in range(0, max(len(words) - CHUNK_OVERLAP, 1), step)]


def _vcon(vdb, busy_ms=15000):
    # isolation_level=None: autocommit. Python's sqlite3 otherwise opens an
    # implicit write transaction at the first INSERT and holds it until
    # commit, which is exactly how one search used to lock out every other
    # session for the whole embedding run.
    con = sqlite3.connect(vdb, timeout=busy_ms / 1000, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(f"PRAGMA busy_timeout={int(busy_ms)}")
    con.execute("""CREATE TABLE IF NOT EXISTS chunks(
        path TEXT, mtime REAL, i INTEGER, text TEXT, vec BLOB,
        PRIMARY KEY(path, i))""")
    con.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
    return con


def _write(con, fn):
    """One short write transaction. False (and nothing written) if busy."""
    try:
        con.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError:
        return False
    try:
        fn()
        con.execute("COMMIT")
        return True
    except Exception:
        con.execute("ROLLBACK")
        raise


def _model_id(model_dir):
    try:
        with open(os.path.join(model_dir, "REVISION"), encoding="utf-8") as f:
            rev = f.read().strip()
    except OSError:
        rev = "unknown"
    return f"{os.path.basename(os.path.normpath(model_dir))}@{rev}"


def purge(vdb, paths, busy_ms=2000):
    """Drop every chunk of `paths`. recall.py calls this when index() removes a
    doc, so a deleted doc's text doesn't sit in the cache until the next
    meaning search. Best-effort: recall.py's mtime check covers a miss."""
    if not paths or not os.path.exists(vdb):
        return
    con = _vcon(vdb, busy_ms)
    _write(con, lambda: con.executemany("DELETE FROM chunks WHERE path=?",
                                        [(p,) for p in paths]))
    con.close()


def update(db, vdb, model_dir, emb=None, rebuild=False, budget=None, busy_ms=15000,
           embedder_factory=None):
    """Bring the vector store in line with recall's docs table.
    Returns (embedded, not_embedded): not_embedded docs are ABSENT (purged),
    never stale."""
    src = sqlite3.connect(db, timeout=15)
    docs = {p: (m, t) for p, m, t in src.execute("SELECT path, mtime, title FROM docs")}
    src.close()
    con = _vcon(vdb, busy_ms)
    mid = _model_id(model_dir)
    row = con.execute("SELECT v FROM meta WHERE k='model'").fetchone()
    if rebuild or not row or row[0] != mid:
        def reset():
            if rebuild or row:                     # vectors from another model are garbage
                con.execute("DELETE FROM chunks")
            con.execute("INSERT OR REPLACE INTO meta VALUES('model', ?)", (mid,))
        if not _write(con, reset):
            con.close()
            return 0, len(docs)
    have = dict(con.execute("SELECT path, MAX(mtime) FROM chunks GROUP BY path"))
    gone = [p for p in have if p not in docs]
    todo = [p for p, (m, _t) in docs.items() if have.get(p) != m]
    deadline = time.monotonic() + budget if budget else None
    embedded, skipped = 0, []
    for n, p in enumerate(todo):
        if deadline is not None and time.monotonic() > deadline:
            skipped += todo[n:]
            break
        mtime, title = docs[p]
        try:
            before = os.stat(p).st_mtime
            with open(p, encoding="utf-8", errors="replace") as f:
                text = f.read()
            after = os.stat(p).st_mtime
        except OSError:
            skipped.append(p)
            continue
        if not before == after == mtime:
            # Edited since recall indexed it: the docs row (and its party tag)
            # describes other text. Leave it absent until recall re-indexes.
            skipped.append(p)
            continue
        if emb is None:
            emb = (embedder_factory or Embedder)(model_dir)
        parts = chunks(title or os.path.basename(p), text)
        vecs = emb.embed(parts)

        def put(p=p, mtime=mtime, parts=parts, vecs=vecs):
            con.execute("DELETE FROM chunks WHERE path=?", (p,))
            con.executemany("INSERT INTO chunks VALUES(?,?,?,?,?)",
                            [(p, mtime, i, parts[i], vecs[i]) for i in range(len(parts))])
        if not _write(con, put):
            skipped += todo[n:]                      # another writer: stop, don't wait
            break
        embedded += 1
    doomed = gone + [p for p in skipped if p in have]
    if doomed:
        _write(con, lambda: con.executemany("DELETE FROM chunks WHERE path=?",
                                            [(p,) for p in doomed]))
    con.close()
    return embedded, len(skipped)


def _take_lease(vdb, now=None):
    """A lease token if this search may do the inline catch-up, else None.
    Two sessions used to each burn every core for 15 s on the SAME backlog
    (board 2026-09-19 follow-up 1). An expired lease (a killed holder) is
    simply taken over."""
    now = time.time() if now is None else now
    con = _vcon(vdb, SEARCH_BUSY_MS)
    got = []

    def claim():
        row = con.execute("SELECT v FROM meta WHERE k='lease'").fetchone()
        if row and float(row[0]) > now:
            return
        token = repr(now + LEASE_S)
        con.execute("INSERT OR REPLACE INTO meta VALUES('lease', ?)", (token,))
        got.append(token)
    try:
        _write(con, claim)
    finally:
        con.close()
    return got[0] if got else None


def _drop_lease(vdb, token):
    """Release ONLY our own lease: if it expired and another session took it
    over, deleting by key alone would free theirs too (chair follow-up)."""
    con = _vcon(vdb, SEARCH_BUSY_MS)
    try:
        _write(con, lambda: con.execute("DELETE FROM meta WHERE k='lease' AND v=?", (token,)))
    finally:
        con.close()


def inline_update(db, vdb, model_dir, emb=None, embedder_factory=None):
    """(embedded, not_embedded, busy). busy=True: another session holds the
    lease, so this search reads what's stored (recall's mtime check drops
    anything out of date) and doesn't embed."""
    token = _take_lease(vdb)
    if token is None:
        return 0, 0, True
    try:
        n, left = update(db, vdb, model_dir, emb=emb, budget=INLINE_BUDGET_S,
                         busy_ms=SEARCH_BUSY_MS, embedder_factory=embedder_factory)
        return n, left, False
    finally:
        _drop_lease(vdb, token)


def search(db, vdb, model_dir, query):
    import numpy as np
    emb = Embedder(model_dir)
    _n, stale, busy = inline_update(db, vdb, model_dir, emb=emb)
    con = sqlite3.connect(vdb, timeout=15)
    rows = con.execute("SELECT path, mtime, text, vec FROM chunks").fetchall()
    con.close()
    if not rows:
        return {"results": [], "stale": stale, "busy": busy}
    mat = np.frombuffer(b"".join(r[3] for r in rows), dtype=np.float32).reshape(len(rows), -1)
    q = np.frombuffer(emb.embed([QUERY_PREFIX + query])[0], dtype=np.float32)
    with np.errstate(all="ignore"):   # spurious Accelerate BLAS warnings (board B-audit)
        sims = mat @ q
    best = {}
    for (path, mtime, text, _v), s in zip(rows, sims):
        if path not in best or s > best[path][0]:
            best[path] = (float(s), text, mtime)
    ranked = sorted(best.items(), key=lambda kv: -kv[1][0])
    return {"stale": stale, "busy": busy,
            "results": [[p, round(s, 4), t, m] for p, (s, t, m) in ranked]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["search", "index"])
    ap.add_argument("query", nargs="*")
    ap.add_argument("--db", required=True)
    ap.add_argument("--vdb", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    if a.cmd == "index":
        n, left = update(a.db, a.vdb, a.model, rebuild=a.rebuild)
        print(json.dumps({"embedded": n, "not_embedded": left}))
        return 0
    print(json.dumps(search(a.db, a.vdb, a.model, " ".join(a.query))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
