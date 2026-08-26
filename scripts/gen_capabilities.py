#!/usr/bin/env python3
"""Engram — generate the capability manifest (memory-v2 U8, failure class F3).

Sessions forget what this machine can do — 51+ local skills, hundreds of plugin
skills, MCP servers, guard hooks, house CLIs — because no inventory is ever
injected. This script greps the LIVE config (never hand-maintained prose, per
operating principle 4) and writes one markdown manifest:

  ## Digest      <= ~45 lines — injected at SessionStart by session_start_v2
  ## Skills / ## Agents / ## Hooks / ## Plugins / ## Tools   — the full listing,
                 one line each, read on demand (progressive disclosure)

Deterministic output for a given config (sorted, no timestamps in the Digest) so
an unchanged config produces a byte-identical manifest.

  python3 scripts/gen_capabilities.py [--out PATH]
"""
import argparse
import glob
import json
import os
import re
import sys

VAULT = os.environ.get("ENGRAM_VAULT", os.path.expanduser("~/vault"))
OUT = os.path.join(VAULT, "machine", "capability-manifest.md")
SETTINGS = os.path.expanduser("~/.claude/settings.json")
SKILLS_DIR = os.path.expanduser("~/.claude/skills")
AGENTS_DIR = os.path.expanduser("~/.claude/agents")
TOOLS_DIR = os.path.expanduser("~/tools")

# The manifest copies descriptions from hundreds of third-party marketplace
# skills. Neutralize the bootstrap's control marker at the SOURCE so a plugin
# author can never forge an Engram line in every session (round-4 verify).
CONTROL = "⟦engram⟧"


def _sanitize(text):
    return text.replace(CONTROL, "⟦quoted⟧") if text else text


_NAME_RE = re.compile(r"(?m)^name:\s*[\"']?(.+?)[\"']?\s*$")
_DESC_RE = re.compile(r"(?m)^description:\s*[\"']?(.+?)[\"']?\s*$")


def _frontmatter_line(path):
    """(name, first-sentence-of-description) from a SKILL.md/agent md file."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            head = f.read(2000)
    except OSError:
        return None
    name = _NAME_RE.search(head)
    desc = _DESC_RE.search(head)
    d = (desc.group(1).strip() if desc else "").split(". ")[0][:110]
    n = name.group(1).strip() if name else os.path.basename(os.path.dirname(path))
    return _sanitize(n), _sanitize(d)


def skills():
    out = []
    for p in sorted(glob.glob(os.path.join(SKILLS_DIR, "*", "SKILL.md"))):
        fm = _frontmatter_line(p)
        if fm:
            out.append(fm)
    return out


def agents():
    out = []
    for p in sorted(glob.glob(os.path.join(AGENTS_DIR, "*.md"))):
        fm = _frontmatter_line(p)
        if fm:
            out.append(fm)
    return out


def settings_bits():
    """Hook wiring + enabled plugin names from settings.json. Names only — a
    manifest must never copy secrets or full config."""
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        return [], []
    hooks = []
    for event, entries in (cfg.get("hooks") or {}).items():
        for entry in entries:
            matcher = entry.get("matcher", "*")
            for h in entry.get("hooks", []):
                # Names-only is an INVARIANT, not a convention: only surface a
                # token that looks like a script path — anything else (inline
                # flags, values, empty commands) renders as an opaque
                # placeholder so a secret can never ride into the manifest.
                parts = h.get("command", "").split()
                tok = parts[-1] if parts else ""
                if "=" in tok or not re.search(r"\.(py|sh|js|ts|rb|pl)$", tok):
                    cmd = "(command)"
                else:
                    cmd = os.path.basename(tok)
                hooks.append((event, matcher, cmd))
    plugins = sorted((cfg.get("enabledPlugins") or {}).keys())
    return sorted(hooks), plugins


def house_tools():
    """Top-level ~/tools/* projects, described by their README's first heading
    or a `# cap:` line in a same-named entry script."""
    out = []
    if not os.path.isdir(TOOLS_DIR):
        return out
    for d in sorted(os.listdir(TOOLS_DIR)):
        path = os.path.join(TOOLS_DIR, d)
        if not os.path.isdir(path) or d.startswith("."):
            continue
        desc = ""
        readme = os.path.join(path, "README.md")
        if os.path.isfile(readme):
            try:
                with open(readme, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and not line.startswith("!["):
                            desc = line[:110]
                            break
            except OSError:
                pass
        out.append((d, desc))
    return out


def build():
    sk, ag = skills(), agents()
    hooks, plugins = settings_bits()
    tools = house_tools()

    # Group skills by rough domain from name prefixes — good enough for a digest.
    domains = {}
    for n, _ in sk:
        key = n.split("-")[0]
        domains[key] = domains.get(key, 0) + 1
    top_domains = sorted(domains.items(), key=lambda kv: (-kv[1], kv[0]))[:8]

    digest = [
        "## Digest",
        "",
        f"- **{len(sk)} local skills** (invoke via Skill tool; body loads on use). "
        "Largest groups: " + ", ".join(f"{k}×{v}" for k, v in top_domains) + ".",
        f"- **{len(ag)} local agents**: " + ", ".join(n for n, _ in ag) + ".",
        f"- **{len(hooks)} hook wirings** (deterministic guards + bootstrap): "
        + ", ".join(sorted({c for _, _, c in hooks})) + ".",
        f"- **{len(plugins)} plugin packs enabled** (hundreds of slash-skills — "
        "marketing, small-business, legal, finance, engineering, data …).",
        # Derived, not literal: hard-coding the names in the one section that
        # gets injected is exactly the drift principle 4 exists to prevent, in
        # a script whose docstring promises it greps live config (chair M8).
        f"- **{len(tools)} house tool projects** under `~/tools/` ("
        + ", ".join(n for n, _ in tools[:6])
        + (", …" if len(tools) > 6 else "") + ").",
        "- Key CLIs: `recall.py` (search past work), `memory_lint.py` "
        "(memory integrity), `compactor.py` (daily circulation), "
        "`gen_capabilities.py` (this manifest).",
        "- Full lists in the sections below this Digest — Read this file, or "
        "`recall.py --capabilities`.",
    ]

    body = ["# Capability manifest", "",
            "_Generated by `scripts/gen_capabilities.py` from the live config — "
            "regenerate after config changes; do not hand-edit._", ""]
    body += digest + [""]
    body.append("## Skills (local)")
    body += [f"- `{n}` — {d}" if d else f"- `{n}`" for n, d in sk] + [""]
    body.append("## Agents (local)")
    body += [f"- `{n}` — {d}" if d else f"- `{n}`" for n, d in ag] + [""]
    body.append("## Hooks (from settings.json)")
    body += [f"- {ev} [{m}] → `{c}`" for ev, m, c in hooks] + [""]
    body.append("## Plugin packs enabled")
    body += [f"- {p}" for p in plugins] + [""]
    body.append("## House tools (~/tools)")
    body += [f"- `{n}` — {d}" if d else f"- `{n}`" for n, d in tools] + [""]
    return "\n".join(body)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args()
    text = build()
    if args.stdout:
        print(text)
        return 0
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, args.out)
    print(f"[capabilities] wrote {args.out.replace(os.path.expanduser('~'), '~')} "
          f"({len(text)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
