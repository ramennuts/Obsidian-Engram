# recall: hybrid search (keyword + local meaning search)

`recall` works with no install at all: SQLite FTS5 BM25, standard library only.
Optionally it can also rank by *meaning* using a small embedding model that runs
on your machine, and fuse the two rankings.

## Why hybrid

Keyword search finds what you can name. It misses a question phrased in words
the answer doesn't use ("where do the encrypted offsite copies live?" vs a note
titled *backup durability*). Embeddings catch those but blur exact tokens:
acronyms, IDs, commit hashes, in-house jargon. Hybrid gives you both.

Measured on an 80-question ground-truth set over a real ~750-doc vault
(`evals/run_retrieval.py`; Hit@5 / MRR@10):

| config | all | keyword | paraphrase | "latest status" | party-scoped |
|---|---|---|---|---|---|
| before (AND-matched BM25, filter after LIMIT) | 0.39 / 0.36 | 0.83 / 0.82 | 0.03 / 0.03 | 0.17 / 0.11 | 0.38 / 0.28 |
| OR-matched, field-weighted BM25 | 0.68 / 0.60 | 1.00 / 0.96 | 0.37 / 0.28 | 0.50 / 0.43 | 0.88 / 0.73 |
| + local embeddings, RRF fusion | **0.79 / 0.66** | 1.00 / 0.97 | **0.57 / 0.39** | 0.67 / 0.50 | 1.00 / 0.69 |

Settings were picked on half the questions and confirmed on the other half.

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

## Tried and rejected (measured)

- **Time-decay prior** (handoffs lose weight with age, memory never decays):
  no setting improved "latest status" questions without costing keyword and
  party-scoped ones. Removed rather than left as a dead knob.
- **Heavier title weights** (10:5:1 and up): won on the tuning half, lost on the
  held-out half. Shipped 5:2:1.
