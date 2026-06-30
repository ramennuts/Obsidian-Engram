#!/usr/bin/env python3
"""Engram doctor — check that your setup is wired correctly.

Run anytime: `python3 scripts/doctor.py`. It verifies the vault, the memory-spine
files, the hook registration, and the skill install, then prints a tidy report with
fixes for anything missing. Read-only; changes nothing.
"""
import json
import os
import sys

VAULT = os.environ.get("ENGRAM_VAULT", os.path.expanduser("~/vault"))
SETTINGS = os.path.expanduser("~/.claude/settings.json")
SKILL = os.path.expanduser("~/.claude/skills/handoff/SKILL.md")

OK, WARN, BAD = "✅", "⚠️ ", "❌"


def check(label, ok, detail="", fix=""):
    mark = OK if ok is True else (WARN if ok == "warn" else BAD)
    line = f"{mark} {label}"
    if detail:
        line += f" — {detail}"
    print(line)
    if ok is not True and fix:
        print(f"     ↳ fix: {fix}")
    return ok is True


def main():
    print(f"Engram doctor — vault: {VAULT}\n")
    passed = True

    passed &= check(
        "Vault directory exists", os.path.isdir(VAULT), VAULT,
        f"create it or set ENGRAM_VAULT, e.g. `cp -R vault-template {VAULT}`",
    )

    for fname, role in (("LIVE-STATE.md", "ground-truth board"),
                        ("build-queue.md", "work queue")):
        p = os.path.join(VAULT, fname)
        passed &= check(f"{fname} present ({role})", os.path.isfile(p), "",
                        f"copy it from vault-template/ into {VAULT}")

    hdir = os.path.join(VAULT, "handoffs")
    handoffs = list(os.listdir(hdir)) if os.path.isdir(hdir) else []
    md = [f for f in handoffs if f.endswith(".md")]
    if not os.path.isdir(hdir):
        passed &= check("handoffs/ directory present", False, "",
                        f"mkdir {hdir}")
    else:
        check("handoffs/ has at least one handoff",
              "warn" if not md else True,
              f"{len(md)} handoff(s)" if md else "none yet",
              "write one with the /handoff skill at the end of a session")

    # SessionStart hook registered?
    hook_ok = False
    if os.path.isfile(SETTINGS):
        try:
            with open(SETTINGS, encoding="utf-8") as f:
                data = json.load(f)
            cmds = [
                c.get("command", "")
                for grp in data.get("hooks", {}).get("SessionStart", [])
                for c in grp.get("hooks", [])
            ]
            hook_ok = any("session-start.py" in c for c in cmds)
        except (json.JSONDecodeError, OSError):
            hook_ok = False
    passed &= check(
        "SessionStart hook registered", hook_ok, SETTINGS,
        "merge the hooks block from settings.example.json into ~/.claude/settings.json",
    )

    passed &= check(
        "/handoff skill installed", os.path.isfile(SKILL), SKILL,
        "cp -R skills/handoff ~/.claude/skills/",
    )

    print()
    if passed:
        print("All good — start a new session and the bootstrap will auto-inject. 🎉")
        return 0
    print("Some checks need attention (see fixes above).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
