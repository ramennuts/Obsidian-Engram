#!/usr/bin/env python3
"""Engram — lint the durable-memory directory (and optionally the vault) for integrity.

Layer-1 checks (the originals — drift that makes memory silently wrong):
  - ORPHANS    : note files on disk that aren't listed in MEMORY.md.
  - DANGLING   : `[[wikilinks]]` that point at a slug with no matching file.
  - INDEX GAPS : MEMORY.md entries linking to a file that doesn't exist.
  - FRONTMATTER: notes missing a `name:`/`description:`/`type:` field.

Vault checks (--vault; memory-v2 U1/U4/U5 — deterministic flags for the rot the
2026-08-23 audit measured: 36-day-stale "verified" stamps, an 11-12k-token queue
item, contract-less handoffs):
  - BUDGET        : CLAUDE.md > 200 lines; MEMORY.md > 200 lines / 25KB (the
                    built-in auto-memory loader's hard cap — content past it is
                    silently dropped); a memory note > 10KB.
  - STALE-VERIFY  : a LIVE-STATE `(verified YYYY-MM-DD)` header stamp older than
                    14 days. Ground truth that isn't re-verified is just truth.
  - OVERSIZED-ITEM: a queue `###` item over ~6KB (~1.5k tokens, decision D3) —
                    should shrink to a stub + linked project note.
  - HANDOFF-CONTRACT: a handoff dated on/after 2026-08-24 missing the typed
                    `status:` frontmatter (the sibling-digest contract).
  - OLD-BACKUP    : an archiver `*.bak` in the vault root older than 14 days
                    (the compactor sweeps these to machine/archive/backups/).
  - NO-ROLLUP     : >1 same-day handoffs but no machine/rollups/<date>-rollup.md
                    yet (info — the compactor writes these daily).

Read-only; changes nothing. Two modes:
  CI mode (default): print problems, exit 1 if any.
  Report mode (--report PATH): write a markdown report whose finding lines are
  two-space-indented (session_start_v2 injects the top ones as ⚠ flags), exit 0.

  python3 scripts/memory_lint.py [--dir PATH] [--vault [VAULT]] [--report PATH]
"""
import argparse
import datetime
import glob
import hashlib
import json
import os
import re
import sys

DEFAULT_DIR = os.environ.get("ENGRAM_MEMORY", os.path.expanduser("~/memory"))
DEFAULT_VAULT = os.environ.get("ENGRAM_VAULT", os.path.expanduser("~/vault"))
INDEX = "MEMORY.md"
LINK_RE = re.compile(r"\[\[([a-zA-Z0-9_\-]+)\]\]")
INDEX_LINK_RE = re.compile(r"\]\(([a-zA-Z0-9_\-]+)\.md\)")
REQUIRED_FIELDS = ("name", "description", "type")

STALE_DAYS = 14
ITEM_CAP_CHARS = 6000          # ~1.5k tokens per queue item (D3, 2026-08-24)
BAK_DAYS = 14
CONTRACT_START = "2026-08-24"  # handoffs from this date on need `status:`
CLAUDE_MD_MAX_LINES = 200      # Anthropic's own guidance
INDEX_MAX_LINES = 200          # built-in auto-memory load cap
INDEX_MAX_BYTES = 25_000
NOTE_MAX_BYTES = 10_000
_VERIFIED_RE = re.compile(r"\(verified (\d{4})-(\d{2})-(\d{2})")
_FNAME_DATE_RE = re.compile(r"\A(\d{4}-\d{2}-\d{2})")
_STATUS_RE = re.compile(r"(?m)^status:\s*\S")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def note_files(d):
    return sorted(f for f in os.listdir(d) if f.endswith(".md") and f != INDEX)


def frontmatter(text):
    m = re.match(r"(?s)^---\n(.*?)\n---", text)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm


def safe(name, fn, *a):
    """Run a lint pass; a crash becomes a FINDING, never a dead report. The
    report generator is the only alarm channel this machine has for memory
    hygiene, and it is authored BY this script — so this script dying is the one
    failure it could never report (D4 board, M-5 + the circularity note)."""
    try:
        return fn(*a)
    except Exception as e:
        return [f"LINT-CRASH {name} raised {type(e).__name__}: {str(e)[:140]} "
                "— that pass did NOT run; findings below are incomplete"]


def lint_memory(d):
    """The Layer-1 checks. Returns a list of problem strings."""
    problems = []
    index_path = os.path.join(d, INDEX)
    files = note_files(d)
    slugs = {f[:-3] for f in files}
    index_text = read(index_path)
    indexed = set(INDEX_LINK_RE.findall(index_text))

    for slug in sorted(slugs - indexed):
        problems.append(f"ORPHAN     {slug}.md is on disk but not linked in {INDEX}")
    for slug in sorted(indexed - slugs):
        problems.append(f"INDEX GAP  {INDEX} links {slug}.md but the file is missing")

    if len(index_text.splitlines()) > INDEX_MAX_LINES or len(index_text) > INDEX_MAX_BYTES:
        problems.append(
            f"BUDGET     {INDEX} exceeds {INDEX_MAX_LINES} lines / "
            f"{INDEX_MAX_BYTES}B — a conservative cap borrowed from the "
            "auto-memory loader. This index is loaded by the @-import in "
            "~/.claude/CLAUDE.md, which has its own (larger, undocumented) "
            "limits, so treat this as a hygiene target, not a hard cliff")

    for f in files:
        path = os.path.join(d, f)
        if os.path.islink(path):
            problems.append(f"SYMLINK    {f} is a symbolic link — skipped "
                            "(allow-list bypass risk; replace with a real file)")
            continue
        text = read(path)
        fm = frontmatter(text)
        missing = [k for k in REQUIRED_FIELDS if k not in fm]
        if missing:
            problems.append(f"FRONTMATTER {f} missing: {', '.join(missing)}")
        for target in LINK_RE.findall(text):
            if target not in slugs:
                problems.append(f"DANGLING   {f} links [[{target}]] — no such note")
        if os.path.getsize(path) > NOTE_MAX_BYTES:
            problems.append(f"BUDGET     {f} is {os.path.getsize(path)}B "
                            f"(cap {NOTE_MAX_BYTES}B) — split or tighten the fact")
    return problems


PROJECTS_ROOT = os.environ.get(
    "ENGRAM_PROJECTS",
    os.path.join(os.environ.get("CLAUDE_CONFIG_DIR",
                                os.path.expanduser("~/.claude")), "projects"))
SETTINGS_PATH = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR",
                                            os.path.expanduser("~/.claude")),
                             "settings.json")


def _slug_id(slug):
    """Hash, never name. A project slug can encode a client name, and this
    report is FTS-indexed by recall AND read verbatim into the daily outbound
    Haiku call — so identity must be non-identifying (D4 board, ruling on
    Auditor-of-B). A hash also survives the live slug whose entire name is "-"."""
    return hashlib.blake2b(slug.encode("utf-8"), digest_size=4).hexdigest()


def lint_projects(root=None):
    """STRAY-PROJECT-MEMORY detector — the durable half of the D4 fix.

    `autoMemoryEnabled: false` (user scope) is the prevention layer, but parts
    of that subsystem are governed by REMOTE feature flags and by env-var
    overrides (`CLAUDE_CODE_DISABLE_AUTO_MEMORY=0` force-ENABLES it, beating the
    setting). So prevention can lapse with zero local edits, and something must
    be watching underneath it — a hook, not prose (principle 3).

    STAT ONLY: never open() a file under a project slug. That removes both the
    leak surface and the decode-crash surface in one decision.
    """
    root = root or PROJECTS_ROOT
    problems = []
    if not os.path.isdir(root):
        # Silence must never read as clean (the ADDED-5 idiom).
        return [f"LINT-CONFIG projects path not found: {root} — checks did NOT run"]

    # Liveness: is the prevention layer still in force? Reports the BOOLEAN only,
    # never any other part of the settings file.
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            enabled = json.load(f).get("autoMemoryEnabled")
        if enabled is not False:
            problems.append(
                "PREVENTION-OFF auto-memory is not disabled at user scope "
                "(autoMemoryEnabled is not false) — stray writes are possible "
                "again; see machine/memory-v2/board-2026-08-24-d4/VERDICT.md")
    except FileNotFoundError:
        problems.append(f"LINT-CONFIG no settings file at {SETTINGS_PATH} — "
                        "cannot confirm auto-memory is disabled")
    except (OSError, ValueError) as e:
        problems.append(f"LINT-CONFIG settings unreadable ({type(e).__name__}) — "
                        "cannot confirm auto-memory is disabled")

    stray = []
    try:
        slugs = sorted(os.listdir(root))
    except OSError as e:
        return problems + [f"LINT-CONFIG projects root unreadable "
                           f"({type(e).__name__}) — checks did NOT run"]
    for slug in slugs:
        mem = os.path.join(root, slug, "memory")
        if not os.path.isdir(mem):
            continue
        sid = _slug_id(slug)
        # An ESCAPING symlink is REPORTED, never skipped: for a detector,
        # read-gate containment semantics are inverted — skipping would freeze
        # the blind spot in as asserted-correct (D4 board, Auditor-of-B).
        try:
            if os.path.realpath(mem) != os.path.abspath(mem) and \
               os.path.commonpath([os.path.realpath(mem),
                                   os.path.realpath(root)]) != os.path.realpath(root):
                problems.append(f"STRAY-PROJECT-MEMORY-ESCAPE slug {sid}: its "
                                "memory/ resolves OUTSIDE the projects root")
                continue
        except (ValueError, OSError):
            problems.append(f"STRAY-PROJECT-MEMORY-ESCAPE slug {sid}: memory/ "
                            "path could not be resolved")
            continue
        n = 0
        for _dirpath, _dirnames, filenames in os.walk(mem):   # recursive: logs/ too
            n += len(filenames)
        if n:
            stray.append((sid, n))
    if stray:
        total = sum(n for _, n in stray)
        detail = ", ".join(f"{sid}:{n}" for sid, n in stray)
        problems.append(
            f"STRAY-PROJECT-MEMORY {total} file(s) in {len(stray)} project "
            f"auto-memory dir(s) [{detail}] — durable facts may have been "
            "written where nothing reads them. Recover manually (propose-only); "
            "run `memory_lint.py --projects --detail` in a terminal to map ids.")
    return problems


HOOKS_BASELINE = os.path.join(
    os.environ.get("ENGRAM_VAULT", os.path.expanduser("~/vault")),
    "machine", "hooks-baseline.json")


def _guard_fingerprint(settings_path=None):
    """Canonical, order-independent fingerprint of the security-relevant parts of
    settings.json: which hook scripts are registered on which events/matchers,
    and the permission deny list. Names and shapes only — never values."""
    with open(settings_path or SETTINGS_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    hooks = []
    for event, entries in (cfg.get("hooks") or {}).items():
        for entry in entries:
            matcher = entry.get("matcher", "*")
            for h in entry.get("hooks", []):
                parts = (h.get("command") or "").split()
                script = os.path.basename(parts[-1]) if parts else "?"
                # " :: " not "|" — matchers legitimately contain pipes
                # (^(Read|Write|Edit|...)$), which mangled the very line a human
                # reads when a guard disappears.
                hooks.append(f"{event} :: {script} :: matcher={matcher}")
    return {"hooks": sorted(hooks),
            "deny": sorted((cfg.get("permissions") or {}).get("deny", []))}


def lint_hooks(settings_path=None, baseline_path=None):
    """HOOK-DRIFT detector.

    `schg` on ~/.claude/hooks/*.py freezes the guard CODE. It does not freeze the
    guard REGISTRATION — every hook runs only because settings.json lists it, so
    unregistering one is as effective as deleting it. When settings.json is
    mutable (Shane removed schg from it 2026-08-25 so Claude Code could persist
    its own settings), this check is what stands in for that lost guarantee:
    prevention became detection, deliberately.

    Compares the live fingerprint against a committed baseline. Drift in EITHER
    direction is reported — a guard vanishing is an alarm, and a NEW hook
    appearing is equally interesting.
    """
    problems = []
    bp = baseline_path or HOOKS_BASELINE
    try:
        live = _guard_fingerprint(settings_path)
    except (OSError, ValueError) as e:
        return [f"LINT-CONFIG cannot read settings for hook-drift check "
                f"({type(e).__name__}) — guard registration is UNVERIFIED"]
    if not os.path.isfile(bp):
        return [f"LINT-CONFIG no hook baseline at {bp} — guard registration is "
                "UNVERIFIED. Create it with `memory_lint.py --update-hooks-baseline` "
                "after confirming the current registration is correct"]
    try:
        with open(bp, encoding="utf-8") as f:
            base = json.load(f)
    except (OSError, ValueError) as e:
        return [f"LINT-CONFIG hook baseline unreadable ({type(e).__name__}) — "
                "guard registration is UNVERIFIED"]

    for key, label in (("hooks", "hook registration"), ("deny", "permission deny rule")):
        lost = [x for x in base.get(key, []) if x not in live.get(key, [])]
        gained = [x for x in live.get(key, []) if x not in base.get(key, [])]
        for x in lost:
            problems.append(f"HOOK-DRIFT a {label} DISAPPEARED since the baseline: "
                            f"{x} — a guard that is not registered does not run")
        for x in gained:
            problems.append(f"HOOK-DRIFT a new {label} appeared since the "
                            f"baseline: {x} — confirm it was intentional")
    return problems


def unwrap_h(h):
    return re.sub(r"~~(.*?)~~", r"\1", h)


def _split_h2(text):
    parts = re.split(r"(?m)^(## .*)$", text)
    return [(parts[i], parts[i + 1] if i + 1 < len(parts) else "")
            for i in range(1, len(parts), 2)]


HANDOFF_HEAD_BYTES = 16384   # must match the bootstrap's bounded re-read, or a
                             # long typed contract yields a FALSE contract
                             # finding injected every session (board ADDED-4)


def lint_vault(vault):
    """The memory-v2 vault checks. Every check independent and best-effort —
    a missing file yields no findings for that check, never a crash."""
    problems = []
    today = datetime.date.today()
    if not os.path.isdir(vault):
        # A misconfigured path must be LOUD: silently returning "clean" is how
        # a fail-open design turns breakage into silence (board ADDED-5).
        return [f"LINT-CONFIG vault path not found: {vault} — checks did NOT run"]

    claude_md = os.path.expanduser("~/.claude/CLAUDE.md")
    if os.path.isfile(claude_md):
        n = len(read(claude_md).splitlines())
        if n > CLAUDE_MD_MAX_LINES:
            problems.append(f"BUDGET     ~/.claude/CLAUDE.md is {n} lines "
                            f"(guidance ≤{CLAUDE_MD_MAX_LINES}) — move procedure "
                            "to skills")

    live_state = os.path.join(vault, "LIVE-STATE.md")
    if os.path.isfile(live_state):
        for hdr, _ in _split_h2(read(live_state)):
            m = _VERIFIED_RE.search(hdr)
            if not m:
                continue
            try:
                d = datetime.date(*map(int, m.groups()))
            except ValueError:
                problems.append(f"BAD-STAMP  LIVE-STATE header {hdr[3:60]!r} "
                                "has an invalid (verified …) date — fix the typo")
                continue
            if (today - d).days > STALE_DAYS:
                # Every OTHER identity-bearing finding goes through _slug_id
                # because this report is FTS-indexed AND read verbatim into the
                # daily outbound call AND injected into every bootstrap.
                # STALE-VERIFY was the one exception, writing the raw LIVE-STATE
                # header straight through all three (verification MUST-FIX #2).
                name = hdr[3:].split("(")[0].strip()
                problems.append(f"STALE-VERIFY LIVE-STATE section "
                                f"(id {_slug_id(name)}) verified "
                                f"{d.isoformat()} (> {STALE_DAYS}d) — re-verify; "
                                f"`--detail` on a TTY maps ids to names")

    bq = os.path.join(vault, "build-queue.md")
    if os.path.isfile(bq):
        for hdr, body in _split_h2(read(bq)):
            if "archiv" in hdr.lower() or not any(
                    k.lower() in hdr.lower() for k in ("Active", "Blocked")):
                continue
            section = _VERIFIED_RE.sub("", unwrap_h(hdr))[3:].strip() or "queue"
            for idx, m in enumerate(
                    re.finditer(r"(?ms)^### (.+?)$(.*?)(?=^### |\Z)", body), 1):
                size = len(m.group(0))
                if size > ITEM_CAP_CHARS:
                    # POSITION + HASH, never the heading. Queue headings carry
                    # company legal names and owners' names, and this report is
                    # recall-indexed AND is chunk 1 of the compactor's outbound
                    # bundle (board 2026-08-25). Same "hash, never name"
                    # contract as _slug_id, 200 lines up.
                    problems.append(
                        f"OVERSIZED-ITEM {section} item #{idx} "
                        f"(id {_slug_id(m.group(1))}) is {size} chars "
                        f"(cap {ITEM_CAP_CHARS}) — shrink to a stub + linked note")

    # A party record with no registry line is a party with NO protection: it is
    # not suppressed in search, not degraded in the bootstrap, not caught by the
    # outbound guard. Nothing else would ever notice (verification round).
    pdir = os.path.join(vault, "rgardin-ai", "reference", "parties")
    preg = os.path.join(vault, "rgardin-ai", "reference", "party-registry.md")
    if os.path.isdir(pdir):
        try:
            slugs = set()
            if os.path.isfile(preg):
                blk = re.search(r"(?s)```registry\n(.*?)```", read(preg))
                for line in (blk.group(1).splitlines() if blk else []):
                    parts = [x.strip() for x in line.split("|") if x.strip()]
                    if parts:
                        slugs.add(parts[0])
            for fn in sorted(os.listdir(pdir)):
                if fn.endswith(".md") and fn[:-3] not in slugs:
                    problems.append(
                        f"UNREGISTERED-PARTY a party record exists for "
                        f"(id {_slug_id(fn[:-3])}) with no line in "
                        "party-registry.md — that party gets NO suppression, "
                        "NO bootstrap redaction and NO outbound guard")
        except (OSError, ValueError) as e:
            problems.append(f"LINT-CONFIG party registry check failed "
                            f"({type(e).__name__}) — party coverage UNVERIFIED")

    hdir = os.path.join(vault, "handoffs")
    # A symlinked handoffs/ DIRECTORY makes every file inside it look ordinary
    # to a per-file islink check, so nothing flagged it (round-4 verify).
    if os.path.exists(hdir):
        try:
            vroot = os.path.realpath(vault)
            if os.path.commonpath([os.path.realpath(hdir), vroot]) != vroot:
                problems.append("SYMLINK    handoffs/ resolves OUTSIDE the vault "
                                "— every handoff in it is excluded everywhere "
                                "(rollups, bootstrap, recall)")
        except (ValueError, OSError):
            problems.append("SYMLINK    handoffs/ path could not be resolved")
    for core in ("LIVE-STATE.md", "build-queue.md"):
        cp = os.path.join(vault, core)
        if os.path.islink(cp):
            problems.append(f"SYMLINK    {core} is a symbolic link — the "
                            "bootstrap refuses symlinks, so this file is dark")
    by_date = {}
    for p in glob.glob(os.path.join(hdir, "*.md")):
        name = os.path.basename(p)
        if os.path.islink(p):
            problems.append(f"SYMLINK    a handoff (id {_slug_id(name)}) is a "
                            "symbolic link — excluded everywhere "
                            "(allow-list bypass risk)")
            continue
        dm = _FNAME_DATE_RE.match(name)
        if not dm:
            continue
        by_date.setdefault(dm.group(1), []).append(name)
        if dm.group(1) >= CONTRACT_START:
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    head = f.read(HANDOFF_HEAD_BYTES)
            except OSError:
                continue
            fm = re.match(r"(?s)\A---\s*\n(.*?)\n---", head)
            if not fm or not _STATUS_RE.search(fm.group(1)):
                problems.append(
                    f"HANDOFF-CONTRACT handoff dated {dm.group(1)} "
                    f"(id {_slug_id(name)}) has no `status:` frontmatter "
                    "(typed-handoff contract)")
    for date, names in sorted(by_date.items()):
        if len(names) > 1 and date >= CONTRACT_START and not os.path.isfile(
                os.path.join(vault, "machine", "rollups", f"{date}-rollup.md")):
            problems.append(f"NO-ROLLUP  {len(names)} handoffs on {date} but no "
                            "rollup yet (compactor writes these)")

    # COMPACTOR-STALE: the channel that actually reaches a human. A daily
    # unattended job whose only failure signal is an unread log has no failure
    # signal (chair C5); this rides the ⚠ path into ACTIVE WORK.
    runs = os.path.join(vault, "machine", "metrics", "compactor-runs.jsonl")
    if os.path.isfile(runs):
        try:
            lines = [ln for ln in read(runs).splitlines() if ln.strip()]
            last = json.loads(lines[-1]) if lines else {}
            ts = last.get("ts", "")
            age_h = (datetime.datetime.now()
                     - datetime.datetime.fromisoformat(ts)).total_seconds() / 3600
            if age_h > 48:
                problems.append(f"COMPACTOR-STALE last compactor run was "
                                f"{int(age_h)}h ago (>48h) — the daily job may "
                                "be dead; check logs/compactor.log")
            failed = [k for k, v in (last.get("results") or {}).items()
                      if str(v).startswith("FAILED")]
            if failed:
                problems.append(f"COMPACTOR-FAILED last run had failing pass(es): "
                                f"{', '.join(failed)} — check logs/compactor.log")
        except (OSError, ValueError, IndexError, KeyError, TypeError):
            problems.append("COMPACTOR-STALE compactor-runs.jsonl is unreadable "
                            "or malformed — the daily job's health is unknown")
    elif os.path.isdir(os.path.join(vault, "machine")):
        problems.append("COMPACTOR-STALE no compactor-runs.jsonl — the daily "
                        "job has never recorded a run")

    now = datetime.datetime.now().timestamp()
    # Recursive and suffix-tolerant: the vault's own convention is
    # `<name>.bak-YYYYMMDD…`, and backups get left in nested dirs — neither of
    # which the old root-only `*.bak` glob could ever see.
    stray = glob.glob(os.path.join(vault, "**", "*.bak*"), recursive=True)
    for p in sorted(set(glob.glob(os.path.join(vault, "*.bak")) + stray)):
        age = (now - os.path.getmtime(p)) / 86400
        if age > BAK_DAYS:
            problems.append(f"OLD-BACKUP {os.path.basename(p)} is {int(age)}d old "
                            "— compactor sweeps to machine/archive/backups/")
    return problems


def write_report(path, mem_problems, vault_problems, project_problems,
                 n_notes, mem_dir):
    """Two-space-indented finding lines are the machine contract —
    session_start_v2._lint_flags() counts and injects them."""
    lines = ["---", 'title: "memory-lint report (latest)"', "type: report",
             f"date: {datetime.date.today().isoformat()}", "tags: [lint, memory]",
             "---", "", "# memory-lint report",
             f"_{n_notes} notes in {mem_dir.replace(os.path.expanduser('~'), '~')} · "
             f"regenerated by `scripts/memory_lint.py --report` (compactor runs it "
             "daily) — findings below are two-space-indented for the bootstrap "
             "injector._", ""]
    # SEVERITY ORDER, not append order. session_start_v2._lint_flags() injects
    # only the FIRST THREE finding lines; the live report has 7 findings whose
    # top 3 are month-old STALE-VERIFY stamps, so anything appended is a proven
    # no-op (D4 board, chair's own re-derivation).
    RANK = (("LINT-CRASH", 0), ("LINT-CONFIG", 0), ("PREVENTION-OFF", 0),
            ("COMPACTOR-", 0), ("HOOK-DRIFT", 0), ("UNREGISTERED-PARTY", 0),
            ("STRAY-PROJECT-MEMORY", 1))

    def rank(p):
        for prefix, r in RANK:
            if p.startswith(prefix):
                return r
        return 2

    all_p = sorted(mem_problems + vault_problems + project_problems, key=rank)
    if not all_p:
        lines += ["✓ clean — index complete, budgets ok, no stale stamps, no "
                  "dangling links"]
    else:
        lines += [f"{len(all_p)} finding(s):", ""]
        lines += [f"  {p}" for p in all_p]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=DEFAULT_DIR)
    ap.add_argument("--vault", nargs="?", const=DEFAULT_VAULT, default=None,
                    help="also run the vault checks (optional path)")
    ap.add_argument("--report", metavar="PATH",
                    help="write a markdown report to PATH and exit 0")
    ap.add_argument("--projects", nargs="?", const=PROJECTS_ROOT, default=None,
                    help="also scan per-project auto-memory dirs for stray writes")
    ap.add_argument("--hooks", nargs="?", const=True, default=None,
                    help="check guard registration in settings.json against the baseline")
    ap.add_argument("--update-hooks-baseline", action="store_true",
                    help="record the CURRENT guard registration as the baseline")
    ap.add_argument("--detail", action="store_true",
                    help="print the slug-id map to a TTY only (never to a file)")
    args = ap.parse_args()
    d = args.dir

    if args.update_hooks_baseline:
        fp = _guard_fingerprint()
        os.makedirs(os.path.dirname(HOOKS_BASELINE), exist_ok=True)
        with open(HOOKS_BASELINE, "w", encoding="utf-8") as f:
            json.dump(fp, f, indent=2)
            f.write("\n")
        print(f"[memory-lint] baseline recorded: {len(fp['hooks'])} hook "
              f"registrations, {len(fp['deny'])} deny rules → "
              f"{HOOKS_BASELINE.replace(os.path.expanduser('~'), '~')}")
        return 0

    project_problems = safe("lint_projects", lint_projects,
                            args.projects) if args.projects else []
    if args.hooks:
        project_problems += safe("lint_hooks", lint_hooks)

    # A misconfigured memory dir must still produce a REPORT. Returning early
    # left yesterday's report in place to be served as today's, indefinitely,
    # with an exit code nobody reads as the only signal (D4 board, M-5).
    fatal = None
    if not os.path.isdir(d):
        fatal = f"LINT-CONFIG memory directory not found: {d} — memory checks did NOT run"
    elif not os.path.isfile(os.path.join(d, INDEX)):
        fatal = f"LINT-CONFIG no {INDEX} index in {d} — memory checks did NOT run"
    if fatal:
        print(f"[memory-lint] {fatal}", file=sys.stderr)
        if args.report:
            write_report(args.report, [fatal], safe("lint_vault", lint_vault, args.vault)
                         if args.vault else [], project_problems, 0, d)
            print(f"[memory-lint] report → {args.report.replace(os.path.expanduser('~'), '~')}")
        # NON-ZERO even in report mode: a config failure is "the check did not
        # run", not "the check found things". Both alarms must fire — the ⚠
        # finding reaches the session AND the compactor marks the pass FAILED.
        # Returning 0 here silenced the compactor (caught by the suite).
        return 1

    mem_problems = safe("lint_memory", lint_memory, d)
    vault_problems = safe("lint_vault", lint_vault, args.vault) if args.vault else []
    files = note_files(d)

    if args.detail and args.projects and sys.stdout.isatty():
        print("[memory-lint] slug id map (TTY only, never written to a file):")
        for slug in sorted(os.listdir(args.projects)):
            if os.path.isdir(os.path.join(args.projects, slug, "memory")):
                print(f"  {_slug_id(slug)}  {slug}")

    if args.report:
        write_report(args.report, mem_problems, vault_problems, project_problems,
                     len(files), d)
        print(f"[memory-lint] report → "
              f"{args.report.replace(os.path.expanduser('~'), '~')} "
              f"({len(mem_problems) + len(vault_problems)} finding(s))")
        return 0

    problems = sorted(mem_problems + vault_problems + project_problems,
                      key=lambda p: 0 if p.startswith(("LINT-", "PREVENTION-OFF")) else 1)
    print(f"[memory-lint] {len(files)} notes in "
          f"{d.replace(os.path.expanduser('~'), '~')}")
    if not problems:
        print("[memory-lint] ✓ clean — index complete, no dangling links, "
              "frontmatter OK")
        return 0
    print(f"[memory-lint] {len(problems)} problem(s):\n")
    for p in problems:
        print(f"  {p}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
