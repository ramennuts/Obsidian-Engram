# recall: hybrid search (keyword + local meaning search)

`recall` works with no install at all: SQLite FTS5 BM25, standard library only.
Optionally it can also rank by *meaning* using a small embedding model that runs
on your machine, and fuse the two rankings.

## Why hybrid

Keyword search finds what you can name. It misses a question phrased in words
the answer doesn't use ("where do the encrypted offsite copies live?" vs a note
titled *backup durability*). Embeddings catch those but blur exact tokens:
acronyms, IDs, commit hashes, in-house jargon. Hybrid gives you both.

Measured on a ground-truth set over a real ~760-doc vault
(`evals/run_retrieval.py`): 80 answerable questions (Hit@5 / MRR@10) plus 8
unanswerable ones (false hits = keyword results shown with no warning).

| config | all | all minus keyword | paraphrase | "latest status" | party-scoped | false hits |
|---|---|---|---|---|---|---|
| before (AND-matched BM25, filter after LIMIT) | 0.39 / 0.36 | 0.12 / 0.09 | 0.03 / 0.03 | 0.17 / 0.11 | 0.38 / 0.28 | 0/8 |
| OR-matched BM25 | 0.69 / 0.59 | 0.50 / 0.36 | 0.37 / 0.26 | 0.58 / 0.41 | 0.88 / 0.65 | 0/8 * |
| + local embeddings, RRF fusion | **0.79 / 0.67** | **0.66 / 0.49** | **0.57 / 0.41** | 0.67 / 0.56 | 1.00 / 0.71 | 0/8 * |

Where the gain comes from: OR matching (MRR 0.36 → 0.59) and fusion
(0.59 → 0.67). The 30 keyword questions are near-verbatim index lines and
saturate (~0.96) under every new config, so "all minus keyword" is the column
that separates them. Each change was kept because it beat the previous config
on BOTH halves of the question set (sha1 split).

\* OR matching finds *something* for almost any question: without a warning
all 8 unanswerable questions got keyword hits. `recall` now prints which query
terms no in-scope document contains, plus `k/n terms` per hit, which flags all
8 with no false alarm on the 80 answerable ones. Caveat: the unanswerable
questions were chosen for topic words absent from the vault, so this measures
"asked about a topic we never wrote down", not every way a record can be missing.

## Install

```bash
scripts/install_recall_vectors.sh        # pinned model + wheels, sha256-verified
python3 scripts/recall.py --rebuild-vectors   # embed the vault once (~5 min / 750 docs)
```

After that, every `recall` call uses both rankings automatically, re-embedding
up to 25 changed docs inline. `--no-vectors` forces keyword-only.

## Design

- **Local only.** A hosted embedding API is a new vendor that receives every
  document you embed. `recall_vec.py` runs `BAAI/bge-small-en-v1.5` (MIT,
  384-d, ONNX) on CPU with onnxruntime.
- **Separate interpreter.** `recall.py` stays stdlib-only; it calls the
  sidecar in its own venv (`~/.cache/engram-embed`).
- **Fail-open, never silent.** Missing, crashing, slow (60s) or garbled
  sidecar → keyword results only, with a one-line notice on stderr.
- **Filter before top-K.** The sidecar scores *every* embedded doc; `recall.py`
  applies party/topic/date/stale filters to that full list, then cuts. A
  pre-cut vector list would re-create the truncation bug this release fixed.
- **Inherits the allow-list.** The sidecar embeds only paths already in
  recall's `docs` table; it never walks the filesystem.
- **Fusion:** Reciprocal Rank Fusion, k=60, equal weights (the NornicDB and
  Cormack et al. default; heavier vector weight measured within noise).
- **Chunks:** 180 words, 40-word overlap, title prepended; a doc scores as its
  best chunk. Stored in `$ENGRAM_VAULT/.recall/vectors.db`, a disposable cache
  (a model change wipes it).

## Honest output

- Hits found only by meaning are tagged `meaning match only`. When no keyword
  matched at all, `recall` says `no keyword hits … nearest by meaning (may be
  unrelated)` rather than presenting eight plausible documents as an answer.
- `ℹ no document in scope mentions: …` lists query terms absent from every
  document you're allowed to see (never from party docs outside your scope).
- A vanished sidecar (`vectors.db` exists but the venv/model is gone) is
  announced on stderr; a machine that never installed it stays quiet.

## Cache honesty (board 2026-09-19)

The vector cache prints chunk text, while isolation is decided by the live
`docs` row, so a chunk must never outlive its text: a doc is embedded only if
its file mtime matches the index before and after the read; changed docs not
embedded in a call are purged; every result carries its chunk mtime and
`recall` drops mismatches; `index()` purges vectors of removed docs. Inline
work stops at a 15 s budget, each doc commits on its own, and a busy writer is
skipped, so a search never waits on another session.

## Tried and rejected (measured)

- **Time-decay prior** (handoffs lose weight with age, memory never decays):
  no setting improved "latest status" questions without costing keyword and
  party-scoped ones. Removed rather than left as a dead knob.
- **Field weights** (title/tags over body): 5:2:1 won the tuning half but tied
  equal weights on the held-out half (0.588 vs 0.587), so equal weights stay.
  `--sweep` now enforces that rule in code (`pick()`).
- **Heavier vector weight in the fusion:** +0.01 MRR on each half, about one question; within noise.
