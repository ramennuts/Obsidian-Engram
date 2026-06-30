# Changelog

All notable changes to Engram are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); this project uses
[semantic versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/ramennuts/Obsidian-Engram/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/ramennuts/Obsidian-Engram/releases/tag/v1.0.0
