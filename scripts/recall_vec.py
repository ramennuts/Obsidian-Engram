#!/usr/bin/env python3
"""Engram — optional meaning-search sidecar for `recall` (NOT stdlib).

recall.py stays standard-library only. This sidecar runs under a separate
interpreter that has numpy + onnxruntime + tokenizers, and a LOCAL embedding
model (default BAAI/bge-small-en-v1.5, ONNX, pinned revision). Nothing leaves
the machine: an embedding API would be a new vendor holding every document it
embeds, client text included.

It embeds ONLY documents already in recall's `docs` table, so it inherits the
allow-list by construction; it never walks the filesystem itself. It returns a
score for EVERY embedded document (brute force; the corpus is hundreds of
docs), so recall.py applies party/topic/date filters BEFORE any top-K cut. A
top-K here would reintroduce the post-filter truncation bug fixed in
recall.search().

  recall_vec.py search --db INDEX --vdb VECTORS --model DIR "query"   # JSON
  recall_vec.py index  --db INDEX --vdb VECTORS --model DIR [--rebuild]
"""
import argparse
import json
import os
import re
import sqlite3
import sys

import numpy as np

# bge-*-v1.5 recommends this instruction on short retrieval queries, not docs.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
CHUNK_WORDS = 180
CHUNK_OVERLAP = 40
MAX_TOKENS = 512
BATCH = 16
# Per search call, re-embed at most this many changed docs inline; beyond that
# the caller is told the vector index is stale rather than stalling a search.
INLINE_UPDATE_CAP = 25

_FM_RE = re.compile(r"(?s)\A---\s*\n.*?\n---\s*\n?")


class Embedder:
    def __init__(self, model_dir):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.tok = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        self.tok.enable_truncation(MAX_TOKENS)
        self.tok.enable_padding()
        so = ort.SessionOptions()
        so.log_severity_level = 3
        self.sess = ort.InferenceSession(os.path.join(model_dir, "model.onnx"), so,
                                         providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.sess.get_inputs()}

    def embed(self, texts):
        out = []
        for i in range(0, len(texts), BATCH):
            enc = self.tok.encode_batch(texts[i:i + BATCH])
            feed = {"input_ids": np.array([e.ids for e in enc], dtype=np.int64),
                    "attention_mask": np.array([e.attention_mask for e in enc],
                                               dtype=np.int64)}
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.array([e.type_ids for e in enc], dtype=np.int64)
            hidden = self.sess.run(None, feed)[0]
            cls = hidden[:, 0, :]                       # bge uses CLS pooling
            cls /= np.linalg.norm(cls, axis=1, keepdims=True) + 1e-12
            out.append(cls.astype(np.float32))
        return np.vstack(out) if out else np.zeros((0, 0), np.float32)


def chunks(title, text):
    body = _FM_RE.sub("", text)
    words = body.split()
    if not words:
        return [title]
    step = CHUNK_WORDS - CHUNK_OVERLAP
    return [f"{title}\n" + " ".join(words[s:s + CHUNK_WORDS])
            for s in range(0, max(len(words) - CHUNK_OVERLAP, 1), step)]


def _vcon(vdb):
    con = sqlite3.connect(vdb, timeout=15)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=15000")
    con.execute("""CREATE TABLE IF NOT EXISTS chunks(
        path TEXT, mtime REAL, i INTEGER, text TEXT, vec BLOB,
        PRIMARY KEY(path, i))""")
    con.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
    return con


def _model_id(model_dir):
    try:
        with open(os.path.join(model_dir, "REVISION"), encoding="utf-8") as f:
            rev = f.read().strip()
    except OSError:
        rev = "unknown"
    return f"{os.path.basename(os.path.normpath(model_dir))}@{rev}"


def update(db, vdb, model_dir, emb=None, rebuild=False, cap=None):
    """Bring the vector store in line with recall's docs table. Returns
    (embedded_docs, still_stale_docs)."""
    src = sqlite3.connect(db, timeout=15)
    docs = {p: (m, t) for p, m, t in src.execute("SELECT path, mtime, title FROM docs")}
    src.close()
    con = _vcon(vdb)
    mid = _model_id(model_dir)
    row = con.execute("SELECT v FROM meta WHERE k='model'").fetchone()
    if rebuild or (row and row[0] != mid):
        con.execute("DELETE FROM chunks")          # vectors from another model are garbage
    con.execute("INSERT OR REPLACE INTO meta VALUES('model', ?)", (mid,))
    have = dict(con.execute("SELECT path, MAX(mtime) FROM chunks GROUP BY path"))
    for gone in set(have) - set(docs):
        con.execute("DELETE FROM chunks WHERE path=?", (gone,))
    todo = [p for p, (m, _t) in docs.items() if have.get(p) != m]
    stale = 0
    if cap is not None and len(todo) > cap:
        stale = len(todo) - cap
        todo = todo[:cap]
    if todo:
        emb = emb or Embedder(model_dir)
    for p in todo:
        mtime, title = docs[p]
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        parts = chunks(title or os.path.basename(p), text)
        vecs = emb.embed(parts)
        con.execute("DELETE FROM chunks WHERE path=?", (p,))
        con.executemany("INSERT INTO chunks VALUES(?,?,?,?,?)",
                        [(p, mtime, i, parts[i], vecs[i].tobytes())
                         for i in range(len(parts))])
    con.commit()
    con.close()
    return len(todo), stale


def search(db, vdb, model_dir, query):
    emb = Embedder(model_dir)
    _n, stale = update(db, vdb, model_dir, emb=emb, cap=INLINE_UPDATE_CAP)
    con = _vcon(vdb)
    rows = con.execute("SELECT path, text, vec FROM chunks").fetchall()
    con.close()
    if not rows:
        return {"results": [], "stale": stale}
    mat = np.frombuffer(b"".join(r[2] for r in rows), dtype=np.float32)
    mat = mat.reshape(len(rows), -1)
    q = emb.embed([QUERY_PREFIX + query])[0]
    sims = mat @ q
    best = {}
    for (path, text, _v), s in zip(rows, sims):
        if path not in best or s > best[path][0]:
            best[path] = (float(s), text)
    ranked = sorted(best.items(), key=lambda kv: -kv[1][0])
    return {"stale": stale,
            "results": [[p, round(s, 4), t] for p, (s, t) in ranked]}


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
        n, _ = update(a.db, a.vdb, a.model, rebuild=a.rebuild)
        print(json.dumps({"embedded": n}))
        return 0
    print(json.dumps(search(a.db, a.vdb, a.model, " ".join(a.query))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
