# Security & privacy

Engram has **no runtime dependencies** and makes **no network calls** — it only reads
and writes markdown files in a vault path you control. There is no server, no
telemetry, and nothing is sent anywhere.

## Your vault is yours — keep it private

The whole point of Engram is to accumulate working context (state, decisions,
handoffs) over time. That content is often sensitive. A few habits:

- **Don't commit your vault to a public repo.** If you version it, use a private one.
  This repo's `.gitignore` ignores `*.bak` and Obsidian local state, but it is *not* a
  substitute for keeping the vault itself private.
- **Keep secrets out of the vault.** Reference where a secret lives (a path, a vault
  manager), don't paste the secret in.
- **The SessionStart hook injects vault content into your agent's context.** That's by
  design — just be aware that whatever is in `LIVE-STATE.md` / the latest handoff /
  the active queue headers becomes part of the session.

## Reporting a vulnerability

If you find a security issue in the code (e.g. a path-handling bug), please open a
private security advisory on the repo, or an issue if it's low-risk. There's no formal
SLA — this is a small project — but reports are genuinely appreciated.
