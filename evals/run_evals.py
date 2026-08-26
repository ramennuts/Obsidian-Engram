#!/usr/bin/env python3
"""Engram — recall eval harness (memory-v2 U10): measure, don't guess.

Runs seeded probes against FRESH headless sessions (`claude -p`) so the answer
must come from the memory system (CLAUDE.md + MEMORY.md + Engram bootstrap +
on-demand file reads), not from the asking session's context. Grades by
distinctive-token match (principle 11) and writes a dated scorecard.

Grading per probe: PASS if every `expect_all` token appears (case-insensitive)
AND at least one `expect_any` token (when present). The probe set lives in
evals/probes.jsonl — extend it as the system grows; keep answers verifiable by
token match, never by vibes.

Cost: each probe is one Haiku-class run that loads the normal session floor
(~10-15k input tokens). A full 12-probe pass costs pennies-equivalent of plan
budget. Run weekly + before/after every memory-system change.

  python3 evals/run_evals.py                  # full set
  python3 evals/run_evals.py --limit 3        # smoke
  python3 evals/run_evals.py --dry-run        # print probes, no sessions
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VAULT = os.environ.get("ENGRAM_VAULT", os.path.expanduser("~/vault"))
# Real probes live in the GITIGNORED probes.local.jsonl — seeded answers are by
# nature sensitive machine facts (this repo has a PUBLIC remote; board
# 2026-08-24 ADDED-1). The committed probes.jsonl is a sanitized sample only.
_LOCAL = os.path.join(ROOT, "evals", "probes.local.jsonl")
PROBES = _LOCAL if os.path.exists(_LOCAL) else os.path.join(ROOT, "evals", "probes.jsonl")
SCORECARD = os.path.join(VAULT, "machine", "memory-v2", "scorecard.md")
METRICS = os.path.join(VAULT, "machine", "metrics", "eval-runs.jsonl")
MODEL = "claude-haiku-4-5-20251001"
PROBE_TIMEOUT = 180

PREAMBLE = ("Answer from your loaded context and this machine's memory files "
            "(you may Read files under ~/vault and ~/memory if needed). "
            "Be terse — one or two sentences. Question: ")


def load_probes():
    out = []
    with open(PROBES, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def registered_hook_fingerprint():
    """sha256 (short) of the hook actually registered in settings.json, so a
    pre-cutover run (v1) and a post-cutover run are never confused in the
    scorecard (chair M3)."""
    import hashlib
    try:
        with open(os.path.expanduser("~/.claude/settings.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        cmd = cfg["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        path = cmd.split()[-1]
        with open(path, "rb") as f:
            return f"{os.path.basename(path)}@{hashlib.sha256(f.read()).hexdigest()[:12]}"
    except Exception:
        return "unknown"


def ask(question, context_only=False):
    """Run one probe.

    context_only=True gives the session NO tools, so the answer can only come
    from injected context. Without that split, most probes are answerable by
    grepping ~/memory and ~/vault with the bootstrap entirely DISABLED — the
    scorecard would read green whether or not the hook works, and a measurement
    that cannot fail is not a measurement (chair M3). Tool-allowed probes still
    exercise the retrieval path; the two classes are scored separately.

    `--tools` (documented allow-list) + --strict-mcp-config: enumerate-the-good
    rather than enumerate-the-bad, which misses pre-approved MCP writes
    inherited from settings.json (board audit ADDED-2)."""
    tools = "" if context_only else "Read,Grep,Glob"
    env = dict(os.environ, ENGRAM_METRICS_MODE="eval")  # don't pollute growth data
    # PROMPT ON STDIN, never as a positional arg: `--tools` and
    # `--disallowedTools` are VARIADIC, so they greedily swallow the trailing
    # prompt and the CLI then dies with "Input must be provided...". That made
    # every probe return a session error — a measurement that could never pass,
    # which is exactly as useless as one that could never fail. Caught only by
    # actually running it (2026-08-25).
    r = subprocess.run(
        ["claude", "-p", "--model", MODEL, "--output-format", "json",
         "--strict-mcp-config", "--max-turns", "4",
         "--tools", tools,
         "--disallowedTools", "Bash,Write,Edit,NotebookEdit,WebFetch,WebSearch,Task,Agent"],
        input=PREAMBLE + question,
        capture_output=True, text=True, timeout=PROBE_TIMEOUT, env=env,
        cwd=os.path.expanduser("~"))
    if r.returncode != 0:
        return None, {"error": r.stderr[:200]}
    try:
        data = json.loads(r.stdout)
        return data.get("result", ""), data.get("usage", {})
    except json.JSONDecodeError:
        return r.stdout, {}


def _has(token, low):
    """Word-boundary match, so "no" can't pass on "know" and "yes" can't pass
    on "yesterday" (board 2026-08-24 — vacuous-pass finding)."""
    return re.search(rf"\b{re.escape(token.lower())}\b", low) is not None


HEDGES = ("not sure", "don't know", "do not know", "unable to", "might be",
          "i think it", "no information", "not certain", "cannot determine",
          "unclear", "don't have", "do not have")


def grade(probe, answer):
    if answer is None:
        return False, "no answer (session error)"
    low = answer.lower()
    # A hedge that happens to name the right token among several guesses is not
    # recall. Four of nine context-only probes had expect_any with no expect_all
    # anchor, so a spread-bet answer scored a full PASS (round-4 verify).
    hedge = next((h for h in HEDGES if h in low), None)
    if hedge:
        return False, f"hedged answer (contains {hedge!r}) — not a recall"
    missing = [t for t in probe.get("expect_all", []) if not _has(t, low)]
    if missing:
        return False, f"missing required token(s): {missing}"
    anys = probe.get("expect_any")
    if anys and not any(_has(t, low) for t in anys):
        return False, f"none of expected-any present: {anys}"
    return True, "ok"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0, help="run only the first N probes")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--label", default="", help="tag this run (e.g. pre-cutover)")
    args = ap.parse_args()

    # M3's fingerprint was inert scorecard text: an unlabeled run against the
    # still-registered v1 hook looked exactly like a v2 measurement.
    fp = registered_hook_fingerprint()
    expected = os.path.join(ROOT, "hooks", "session_start_v2.py")
    try:
        import hashlib
        with open(expected, "rb") as f:
            v2 = hashlib.sha256(f.read()).hexdigest()[:12]
        if v2 not in fp:
            print(f"[evals] ⚠ the REGISTERED SessionStart hook ({fp}) is NOT "
                  "session_start_v2.py — this run measures the hook that is "
                  "live now, not v2.", file=sys.stderr)
            if not args.label:
                args.label = "pre-cutover(auto)"
    except OSError:
        pass

    probes = load_probes()
    if args.limit:
        probes = probes[:args.limit]
    if args.dry_run:
        for p in probes:
            print(f"{p['id']:24s} [{p['layer']}] {p['question'][:80]}")
        return 0

    rows, passed = [], 0
    for p in probes:
        try:
            answer, usage = ask(p["question"], p.get("context_only", False))
        except subprocess.TimeoutExpired:
            answer, usage = None, {"error": "probe timeout"}
        except Exception as e:   # one bad probe must not lose the whole run
            answer, usage = None, {"error": repr(e)[:120]}
        ok, why = grade(p, answer)
        passed += ok
        rows.append((p, ok, why, (answer or "").strip()[:220], usage))
        print(f"{'✅' if ok else '❌'} {p['id']:24s} {why}")

    errored = sum(1 for _p, _ok, why, _a, _u in rows if "session error" in why)
    if errored == len(rows) and rows:
        print(f"[evals] ⚠ ALL {errored} probes returned a session error — that is a "
              "BROKEN HARNESS, not a failing memory system. Do not record this as "
              "a score.", file=sys.stderr)

    date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    label = f" · {args.label}" if args.label else ""
    ctx_rows = [r for r in rows if r[0].get("context_only")]
    ctx_passed = sum(1 for r in ctx_rows if r[1])
    # Which hook actually produced these runs? Without this a pre-cutover run
    # (v1 registered) and a post-cutover run are indistinguishable except by an
    # operator-typed label (chair M3).
    lines = [f"\n## Run {date}{label} — {passed}/{len(rows)} passed "
             f"(model {MODEL})\n",
             f"- **context-only probes: {ctx_passed}/{len(ctx_rows)}** "
             "(no tools — these can ONLY be answered from injected context; "
             "this is the number that measures the bootstrap)",
             f"- tool-allowed probes: {passed - ctx_passed}/"
             f"{len(rows) - len(ctx_rows)} (retrieval path)",
             f"- registered SessionStart hook: `{registered_hook_fingerprint()}`\n"]
    lines += ["| probe | layer | mode | result | note |", "|---|---|---|---|---|"]
    for p, ok, why, ans, _ in rows:
        note = "ok" if ok else f"{why} — got: “{ans[:90]}”"
        mode = "context-only" if p.get("context_only") else "tools"
        lines.append(f"| {p['id']} | {p['layer']} | {mode} | "
                     f"{'PASS' if ok else 'FAIL'} | {note.replace('|', '/')} |")
    lines.append("\n_Rule-compliance canaries: not yet implemented — recall "
                 "probes only. (Honest scorecard: this measures memory recall, "
                 "not mid-session rule adherence.)_")

    os.makedirs(os.path.dirname(SCORECARD), exist_ok=True)
    if not os.path.exists(SCORECARD):
        with open(SCORECARD, "w", encoding="utf-8") as f:
            f.write("---\ntitle: \"Memory v2 — eval scorecard\"\ntype: metrics\n"
                    "date: 2026-08-24\ntags: [memory, evals]\n---\n\n"
                    "# Memory-recall eval scorecard\n\nNewest runs appended at "
                    "the bottom. Runner: `~/tools/engram/evals/run_evals.py`.\n")
    with open(SCORECARD, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    try:
        os.makedirs(os.path.dirname(METRICS), exist_ok=True)
        with open(METRICS, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "label": args.label, "passed": passed, "total": len(rows),
                "usage": [u for *_r, u in rows]}) + "\n")
    except OSError:
        pass
    print(f"\n[evals] {passed}/{len(rows)} — appended to "
          f"{SCORECARD.replace(os.path.expanduser('~'), '~')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
