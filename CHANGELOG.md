# Changelog

All notable changes to Engram are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); this project uses
[semantic versioning](https://semver.org/).

## [Unreleased]

### Added
- **Hybrid `recall`** (retrieval review 2026-09-19, patterns from NornicDB):
  optional LOCAL meaning search (`scripts/recall_vec.py`, bge-small ONNX,
  pinned + sha256-verified by `scripts/install_recall_vectors.sh`) fused with
  BM25 by Reciprocal Rank Fusion (k=60). Fail-open with a stderr notice;
  `recall.py` itself stays stdlib-only. See `docs/RECALL-VECTORS.md`.
- **`evals/run_retrieval.py`** — Hit@1/Hit@5/MRR@10 per question shape against
  a gitignored ground-truth set (hash printed per run), dev/test split with a
  tested keep-the-incumbent `pick()`, `--baseline-ref` to score the pre-change
  code, and a false-hit rate on unanswerable questions. MRR 0.36 → 0.67 on 80
  live questions (0.09 → 0.49 excluding the saturated keyword shape).
- **Honest "no record" output**: `k/n terms` per hit, `no document in scope
  mentions: …`, `meaning match only` tags, and a `no keyword hits` banner.
- **Stale docs hidden by default**: a status that STARTS with
  SUPERSEDED/OBSOLETE/ARCHIVED/DEPRECATED, or an `archive/` path, is hidden and
  counted; `--include-stale` reveals it.
- **`↳ links:`** — 1-hop `[[wikilink]]` / `(file.md)` neighbours per hit, behind
  the same party and stale filters.

### Changed
- **OR-matched BM25.** Every query word was previously required, so plain
  questions matched almost nothing (paraphrase Hit@5 0.03). Field weights are
  plumbed but stay equal (5:2:1 tied on the held-out half).
- **Suppressed count is relevance-bounded** and labelled "keyword result(s)":
  party docs that would have been candidates (top `max(limit*2, 20)` with
  isolation off), not every doc sharing one word.
- `--party` takes exactly one registered slug (a comma-joined value exposed a
  two-party doc; board 2026-09-19).
- Index schema 3 (adds `links`); an older cache rebuilds itself.
- **Best-match party warning**: the loud ⚠ now fires only when a HIDDEN
  client/prospect doc would be the #1 match (measured: 5/80 internal
  questions vs 7/8 party questions asked unscoped); the per-doc count is a
  quiet ℹ line (it fired on 92% of ordinary questions).
- The bootstrap teach-line says WHEN to run `recall` (before answering "have
  we done / decided / where is X?"), not just that it exists.

### Added (follow-ups)
- `recall` logs one line per search to `machine/metrics/recall-usage.jsonl`
  (counts only, never the query); `doctor.py` reports recall usage from that
  log plus meaning-search install/catch-up health.
- Inline-embed lease: one session catches the vector index up at a time; the
  others read what's stored.

### Fixed
- **`recall` filtered AFTER its `LIMIT limit*6` cut**, so eligible docs ranked
  below it silently vanished (`recall SOW` returned 6 of 8 with 16 eligible
  docs unreturned). Party, topic, date and stale filters now run inside the SQL.
- Board 2026-09-19 (FIX-THEN-SHIP) before first release: stale vector chunks
  could print a party's OLD text in default scope; one slow inline re-embed
  could time out forever and hold a write lock over every other session; a
  query starting with `-` could inject sidecar options; the installer claimed
  "verified" on macOS bash 3.2 without checking. All fixed with tests that run
  the real `update()` in stdlib CI.
- `index(rebuild=True)` read the known-docs list after clearing it, so a doc
  deleted before a rebuild kept its vectors until the next meaning search.

- **`memory_lint.py --projects`** — the D4 stray-auto-memory detector
  (board 2026-08-24, `machine/memory-v2/board-2026-08-24-d4/`). Stat-only scan of
  every project slug's auto-memory dir; slugs identified by blake2b hash, never
  name; `STRAY-PROJECT-MEMORY`, `-ESCAPE` (an escaping symlink is REPORTED, never
  skipped — for a detector, containment semantics are inverted), and
  `PREVENTION-OFF` when `autoMemoryEnabled:false` stops being in force. Wired
  into the compactor's daily `pass_lint`. Optional `--detail` prints the
  hash→slug map to a TTY only.

### Fixed
- **The lint report could go stale-but-confident.** Each pass now runs under
  `safe()`, so a crash becomes a `LINT-CRASH` finding instead of a dead report;
  and a missing memory dir / index now WRITES the report (with `LINT-CONFIG`)
  *and* exits non-zero, so both alarms fire — the ⚠ reaches the session and the
  compactor still marks the pass FAILED. Previously it returned early, leaving
  yesterday's report to be served as today's indefinitely.
- **Findings are severity-ordered** in `write_report` (crashes/config/prevention
  first, stray-memory next, hygiene last). The bootstrap injects only the first
  three finding lines, and the live report's top three were month-old
  `STALE-VERIFY` stamps — so anything appended was a proven no-op.
- `write_report()` takes `project_problems` as an honest fourth argument rather
  than smuggling them through `vault_problems`.
- The `BUDGET` finding on `MEMORY.md` no longer claims content is "silently
  dropped at session start" — that cap belongs to auto-memory's loader, not to
  the `@`-import that actually loads this index.

## [2.1.0] — 2026-08-24 "Engram v2 — circulation"

Built from the 2026-08-23 memory-architecture deep dive (vault:
`machine/memory-v2/00-MASTER-memory-v2.md`). The substrate stays; this release
adds the missing circulation: sibling merge, staleness flags, capability
awareness, retrieval, and a daily compactor. 5-agent board review before cutover
(record: `machine/memory-v2/board-2026-08-24-engram-v2/`).

### Added
- **Typed handoff contract** (`status` / `goal` / `next_action` / `topics` /
  `do_not` frontmatter) in `skills/handoff/SKILL.md`; enforced by
  `memory_lint.py --vault` from 2026-08-24 on.
- **session-start v2** (`hooks/session_start_v2.py`, replaces the v1 hook body
  at cutover): same-day sibling DIGESTS for contract handoffs (700 chars × ≤6);
  LIVE-STATE changed-section names (7-day git delta) + `(verified …)` staleness
  flags (>14d); memory-lint ⚠ flags injected ahead of the queue headers;
  CAPABILITIES digest + `recall` teach-line; `source == "compact"` → lean
  re-arm (charter + latest checkpoint) instead of a full bootstrap;
  `source == "fork"` → no injection (parent context already has it);
  per-session size metering to `machine/metrics/bootstrap-sizes.jsonl`;
  SAFE_TOTAL 14000-char ceiling with priority-drop. `--shadow` prints the raw
  context for diffing.
- **`scripts/recall.py`** — SQLite FTS5 search over vault + memory (disposable
  index at `.recall/`, markdown canonical). Allow-list confined; customer
  workspaces and the personal domain are never indexed.
- **`scripts/gen_capabilities.py`** — capability manifest generated from live
  config (skills, agents, hooks, plugin packs, house tools); Digest section is
  what the bootstrap injects.
- **`scripts/compactor.py`** + `launchd/com.rgardin.engram.compactor.plist` —
  daily: lint report, manifest refresh, finished-item archiving (reuses
  `archive_finished_queue.py`), same-day handoff rollups, old-backup sweep
  (archive ≠ delete), and a PROPOSE-ONLY Haiku merge pass (ADD/UPDATE/DELETE/
  NOOP + contradictions) — decision D2, <$1/wk.
- **`hooks/pre-compact.py`** — pre-compaction checkpoint writer (todos tail +
  marker); registration is manual (settings.json is owner-only).
- **`evals/`** — recall eval harness: 12 seeded probes run headless, graded by
  distinctive-token match, appended to `machine/memory-v2/scorecard.md`.
- `memory_lint.py`: `--vault` checks (BUDGET / STALE-VERIFY / OVERSIZED-ITEM /
  HANDOFF-CONTRACT / OLD-BACKUP / NO-ROLLUP) and `--report` mode whose
  two-space-indented finding lines are the bootstrap's injection contract.
- 40 new tests (v1-parity suite carried onto v2, isolation, rollup verbatim,
  budgets); suite at 263.

## [2.0.1]

### Added
- A terminal **demo GIF** in the README (`docs/demo.gif`), reproducible from
  `docs/demo.tape` with [vhs](https://github.com/charmbracelet/vhs).
- The two-layer architecture diagram now sits alongside the "Two layers" section.

### Changed
- `doctor.py` and `memory_lint.py` print `~/…` paths instead of absolute home paths
  (cleaner output; matches the hook).

## [2.0.0]

Expanded from a session-continuity loop into the **complete two-layer memory
architecture**: durable memory (Layer 1) + working memory (Layer 2), plus the tooling
and principles that keep both sharp.

### Added
- **Durable-memory layer (Layer 1).** `docs/memory-architecture.md` (the two-layer
  model), `docs/memory-format.md` (the typed-note spec: `user`/`feedback`/`project`/
  `reference`, the `MEMORY.md` index, scoping, wikilinks), and `memory-template/` — a
  starter index with one filled-in example of each note type.
- **`/reflect` skill** — periodic self-improvement: reviews recent work, proposes
  concrete memory/workflow improvements, and never self-applies.
- **`hooks/guard.py`** — an optional deterministic "rules-as-hooks" PreToolUse guard
  (fail-open, env-var override) for making a load-bearing rule enforcement, not prose.
- **`scripts/memory_lint.py`** — integrity check for the durable-memory dir: orphans,
  dangling `[[wikilinks]]`, index gaps, missing frontmatter.
- **`docs/principles.md`** — the six operating principles (lean injection, fail open,
  verify against live, rules as hooks, conservative pruning, cite the source).
- Doctor now checks the durable-memory layer + the reflect skill; installer seeds both
  layers and both skills; 29 tests total (added memory-lint + guard suites).

### Changed
- README reframed around the two layers and the full toolkit.

## [1.0.0]

First public release.

### Added
- **SessionStart bootstrap hook** (`hooks/session-start.py`) — injects a lean
  orientation (latest handoff's open items + resume command, live work-queue headers,
  and a ground-truth table-of-contents) at the start of every session. Fail-open.
- **`/handoff` skill** (`skills/handoff/`) — writes a dense, structured session
  handoff (headlines, dead-ends, open threads, gotchas, verification status, rollback,
  resume command) into the vault.
- **Queue archiver** (`scripts/archive_finished_queue.py`) — conservatively moves
  fully-finished items out of `Active items` / `Blocked` into `Auto-archived`. Dry-run
  by default; backs up before writing; idempotent.
- **Doctor** (`scripts/doctor.py`) — checks the vault, memory-spine files, hook
  registration, and skill install.
- **Vault template** (`vault-template/`) — a ready-to-copy skeleton with example
  `LIVE-STATE.md`, `build-queue.md`, a sample handoff, and agent operating instructions.
- **Installer** (`install.sh`), test suite (`tests/`, stdlib `unittest`), CI
  (tests on Python 3.9–3.13 + ruff + an end-to-end smoke test), and full docs.

[Unreleased]: https://github.com/ramennuts/Obsidian-Engram/compare/v2.0.1...HEAD
[2.0.1]: https://github.com/ramennuts/Obsidian-Engram/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/ramennuts/Obsidian-Engram/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/ramennuts/Obsidian-Engram/releases/tag/v1.0.0
