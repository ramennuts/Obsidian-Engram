#!/usr/bin/env python3
"""Engram — a deterministic "rules-as-hooks" guard (PreToolUse on Bash).

WHY: load-bearing rules written as prose in memory or CLAUDE.md are *context, not
enforcement* — a model can fail to honor them under pressure. This hook makes a rule
DETERMINISTIC: it inspects each Bash command and blocks the hard-to-reverse /
outward-facing ones unless the operator has explicitly opted in via an env var.

This is a TEMPLATE. Edit `BLOCKED` to match the rules that matter for your project.
The shipped examples block destructive/irreversible commands — adjust freely.

Design:
  - Exit code 2 BLOCKS the tool call; stderr is shown to the agent.
  - Opt-in override: set GUARD_ALLOW=1 in the environment to bypass (use deliberately).
  - FAIL OPEN: any internal error -> allow the command (exit 0). A guard that crashes
    the session is worse than the rule it enforces.

Register it as a PreToolUse hook on Bash in ~/.claude/settings.json — see
settings.example.json.
"""
import json
import os
import re
import sys

# (human-readable label, regex). These are the commands the rule says require a
# deliberate, opted-in action. EDIT THESE for your project.
BLOCKED = [
    ("destructive recursive delete", r"\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r"),
    ("force-push to a shared branch", r"\bgit\s+push\b.*--force(?!-with-lease)"),
    ("history rewrite", r"\bgit\s+reset\s+--hard\b|\bgit\s+filter-branch\b"),
    # add your own, e.g. a real deploy command, a prod migration, a live send:
    # ("production deploy", r"\b<your-deploy-command>\b"),
]


def read_command():
    """PreToolUse passes the tool input on stdin as JSON; pull the Bash command."""
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return ""
    ti = data.get("tool_input", data)
    return ti.get("command", "") if isinstance(ti, dict) else ""


def main():
    if os.environ.get("GUARD_ALLOW") == "1":
        return 0  # explicit, deliberate override
    command = read_command()
    if not command:
        return 0
    for label, pattern in BLOCKED:
        if re.search(pattern, command):
            sys.stderr.write(
                f"BLOCKED by Engram guard: this looks like a {label}.\n"
                f"If you really mean to, re-run with GUARD_ALLOW=1 set.\n"
            )
            return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # FAIL OPEN — never wedge a session
