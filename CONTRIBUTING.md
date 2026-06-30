# Contributing to Engram

Thanks for your interest! Engram is intentionally small and dependency-free — the bar
for additions is "does this make the memory loop more reliable without adding weight."

## Principles (please keep these)

- **No runtime dependencies.** Standard library only. If a feature needs a package,
  it probably belongs in a companion project, not here.
- **Fail open.** Anything that runs as a hook must never be able to wedge a session.
- **Conservative by default.** The archiver errs toward keeping items. Don't add a
  rule that could hide live work to save a little clutter.
- **Lean injection.** The SessionStart hook stays a summary + pointers, well under the
  context ceiling. See [docs/design.md](docs/design.md).

## Dev setup

```bash
git clone https://github.com/ramennuts/Obsidian-Engram.git && cd Obsidian-Engram
python3 -m unittest discover -s tests -p "test_*.py" -v   # run the tests
pipx install ruff && ruff check .                         # lint
ENGRAM_VAULT=./vault-template python3 scripts/doctor.py   # sanity-check wiring
```

No build step, no install — the hook and scripts run directly.

## Before you open a PR

1. Add/adjust tests in `tests/` (they're stdlib `unittest`, zero deps).
2. `ruff check .` is clean.
3. The full suite passes: `python3 -m unittest discover -s tests -p "test_*.py"`.
4. If you changed behavior, update the README and `docs/design.md`.
5. Add a line to `CHANGELOG.md` under "Unreleased".

## Good first contributions

- Adapters for other agents/CLIs that support session hooks.
- A Windows-friendly `install.ps1`.
- Additional completion-marker / open-thread words for non-English vaults.
- Editor integrations or a Bases view template for the vault.

Open an issue first for anything large so we can agree on the shape.
