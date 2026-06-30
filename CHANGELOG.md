# Changelog

All notable changes to Engram are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); this project uses
[semantic versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/ramennuts/Obsidian-Engram/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/ramennuts/Obsidian-Engram/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/ramennuts/Obsidian-Engram/releases/tag/v1.0.0
