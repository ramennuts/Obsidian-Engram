#!/usr/bin/env python3
"""Engram — retrieval eval for `recall`: ranking quality, not vibes.

Scores search configurations against a ground-truth set of
{question → file(s) that answer it} with standard IR metrics (the pattern in
NornicDB's pkg/eval): Hit@1, Hit@5 and MRR@10, per question shape.

  keyword     phrased with words the answer contains
  paraphrase  same need, different words (where BM25 fails)
  current     "latest status of X": the newest/canonical doc must win
  scoped      a --party search: isolation must not cost recall

The real set lives in the GITIGNORED evals/retrieval.local.jsonl (questions
name real documents; this repo is public). evals/retrieval.sample.jsonl shows
the format.

Overfitting guard: a sweep picks settings on the DEV half (sha1(id) even) and
reports them on the held-out TEST half. A config only ships if it wins on both.

  python3 evals/run_retrieval.py                 # compare the named configs
  python3 evals/run_retrieval.py --sweep         # BM25 field-weight grid
  python3 evals/run_retrieval.py --baseline-ref main   # include pre-change recall
"""
import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~")
_LOCAL = os.path.join(ROOT, "evals", "retrieval.local.jsonl")
SET = _LOCAL if os.path.exists(_LOCAL) else os.path.join(ROOT, "evals", "retrieval.sample.jsonl")
K = 10


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_set():
    with open(SET, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def half(q):
    return "dev" if int(hashlib.sha1(q["id"].encode()).hexdigest(), 16) % 2 == 0 else "test"


def score(ranked, expect):
    exp = {os.path.join(HOME, e) for e in expect}
    for i, p in enumerate(ranked[:K]):
        if p in exp:
            return i + 1
    return None


def summarize(ranks):
    n = len(ranks)
    if not n:
        return {"n": 0}
    return {"n": n,
            "hit1": sum(1 for r in ranks if r == 1) / n,
            "hit5": sum(1 for r in ranks if r and r <= 5) / n,
            "mrr": sum(1 / r for r in ranks if r) / n}


def run(qs, fn):
    """fn(question) -> ranked paths. Returns {shape|all: [rank or None]}."""
    out = {}
    for q in qs:
        r = score(fn(q), q["expect"])
        out.setdefault(q["shape"], []).append(r)
        out.setdefault("all", []).append(r)
    return out


def fmt(name, res):
    cells = []
    for shape in ("all", "keyword", "paraphrase", "current", "scoped"):
        s = summarize(res.get(shape, []))
        if s["n"]:
            cells.append(f"{shape} {s['hit1']:.2f}/{s['hit5']:.2f}/{s['mrr']:.2f}")
    return f"{name:<28} " + " | ".join(cells)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--baseline-ref", help="git ref of the pre-change recall.py")
    ap.add_argument("--no-vectors", action="store_true")
    ap.add_argument("--sweep-vectors", action="store_const", const=None, default=False,
                    help="sweep BM25 weights inside the hybrid (default: BM25 alone)")
    a = ap.parse_args()

    rec = _load(os.path.join(ROOT, "scripts", "recall.py"), "recall_eval")
    rec.index()
    qs = load_set()
    print(f"[eval] {len(qs)} questions from {os.path.basename(SET)}; "
          f"cells = Hit@1/Hit@5/MRR@{K}\n")

    # One sidecar call per question, reused by every config (the model load
    # dominates; results do not depend on BM25 settings).
    vcache = {}
    real_vec = rec._vector_ranks

    def cached_vec(query, stats):
        if query not in vcache:
            vcache[query] = real_vec(query, stats)
        stats["vectors"] = "on" if vcache[query] else "unavailable"
        return vcache[query]
    rec._vector_ranks = cached_vec

    def cfg(weights=None, vectors=None, bm25_w=1.0, vec_w=1.0, match="or"):
        def fn(q):
            rec.BM25_WEIGHT, rec.VECTOR_WEIGHT = bm25_w, vec_w
            rows, _ = rec.search(q["q"], limit=K, party=q.get("party"),
                                 weights=weights, match=match,
                                 vectors=False if (a.no_vectors or vectors is False) else None)
            return [r[0] for r in rows]
        return fn

    if a.sweep:
        grid = [(1, 1, 1), (2, 1, 1), (3, 2, 1), (5, 2, 1), (5, 5, 1), (10, 5, 1),
                (20, 5, 1), (10, 10, 1), (30, 10, 1)]
        dev = [q for q in qs if half(q) == "dev"]
        test = [q for q in qs if half(q) == "test"]
        best = None
        for w in grid:
            d = summarize(run(dev, cfg(weights=w, vectors=a.sweep_vectors))["all"])
            t = summarize(run(test, cfg(weights=w, vectors=a.sweep_vectors))["all"])
            print(f"weights {str(w):<12} dev MRR {d['mrr']:.3f}  test MRR {t['mrr']:.3f}")
            if best is None or d["mrr"] > best[1]:
                best = (w, d["mrr"], t["mrr"])
        print(f"\nbest on dev: {best[0]} (dev {best[1]:.3f}, held-out test {best[2]:.3f})")
        return 0

    rows = []
    if a.baseline_ref:
        src = subprocess.run(["git", "-C", ROOT, "show", f"{a.baseline_ref}:scripts/recall.py"],
                             capture_output=True, text=True, check=True).stdout
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(src)
        old = _load(f.name, "recall_old")
        os.unlink(f.name)
        rows.append(("baseline (" + a.baseline_ref + ")",
                     lambda q: [r[0] for r in old.search(q["q"], limit=K,
                                                         party=q.get("party"))[0]]))
    rows += [
        ("bm25 AND, equal weights", cfg(weights=(1, 1, 1), vectors=False,
                                        match="and")),
        ("bm25 OR, equal weights", cfg(weights=(1, 1, 1), vectors=False)),
        ("bm25 field-weighted", cfg(vectors=False)),
    ]
    if not a.no_vectors:
        rows += [
            ("vectors only", cfg(bm25_w=0.0)),
            ("hybrid RRF (SHIP)", cfg()),
        ]
    splits = ("dev", "test") if os.environ.get("EVAL_SPLITS") else ()
    for name, fn in rows:
        print(fmt(name, run(qs, fn)))
        for split in splits:
            print(fmt(f"  {split}", run([q for q in qs if half(q) == split], fn)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
