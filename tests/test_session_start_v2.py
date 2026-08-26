"""Tests for the v2 bootstrap hook: v1 parity, sibling digests, re-arm, budgets.

Every v1 behavior test is carried over (same expectations, v2 module) — v2 must
never regress the hard-won selection/notice semantics — plus the memory-v2
additions: typed-sibling digests, compact-source re-arm, fork suppression,
lint-flag injection, capability digest, stale-stamp flags, SAFE_TOTAL.
"""
import contextlib
import io
import json
import os
import tempfile
import unittest

import conftest_paths

VAULT_FILES = {
    "LIVE-STATE.md": "# LIVE STATE\n\n## Services\n- api up\n\n## Config flags\n- X=1\n",
    "build-queue.md": (
        "# Build queue\n\n"
        "## Active items\n### Do the thing\n- in progress.\n\n"
        "## Blocked\n### Waiting on infra\n- blocked.\n\n"
        "## Auto-archived\n### ~~Old done thing~~ — **SHIPPED**\n- moved here.\n"
    ),
}
HANDOFF = (
    "---\ntitle: t\ntype: session-handoff\n---\n# Session handoff — 2025-01-15\n\n"
    "Orientation line.\n\n"
    "## Headlines\n### A) Did a thing\n\n"
    "## Open items / next steps\n- finish the thing.\n\n"
    "## Resume command\nRead X, run Y.\n"
)


def handoff_text(marker, date="2025-01-15", typ="session-handoff", extra_fm=""):
    fm = f"---\ntitle: {marker}\ntype: {typ}\ndate: {date}\n{extra_fm}---\n"
    return fm + f"# H {marker}\n\nOrientation {marker}.\n\n## Resume command\nDo {marker}.\n"


def reload_hook(vault):
    os.environ["ENGRAM_VAULT"] = vault
    return conftest_paths.load("hooks/session_start_v2.py", "engram_session_start_v2_reload")


class TestHookV2(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for name, body in VAULT_FILES.items():
            with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
                f.write(body)
        os.makedirs(os.path.join(self.dir, "handoffs"))
        self._write("2025-01-15-h.md", HANDOFF)

    def _write(self, name, body):
        with open(os.path.join(self.dir, "handoffs", name), "w", encoding="utf-8") as f:
            f.write(body)

    def _promote(self, name="2025-01-15-h.md"):
        """Make `name` the primary again. Same-date selection tiebreaks on
        mtime, so a sibling written later would otherwise WIN primary and the
        test would silently stop testing sibling rendering."""
        import time
        p = os.path.join(self.dir, "handoffs", name)
        t = time.time() + 60
        os.utime(p, (t, t))

    def _emit(self, vault=None):
        hook = reload_hook(vault or self.dir)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            hook.main()
        out = buf.getvalue().strip()
        if not out:
            return None
        return json.loads(out)["hookSpecificOutput"]["additionalContext"]

    # ---- v1 parity ------------------------------------------------------
    def test_emits_valid_json_with_core_blocks(self):
        ctx = self._emit()
        self.assertIsNotNone(ctx)
        for token in ("RESUME", "ACTIVE WORK", "GROUND TRUTH"):
            self.assertIn(token, ctx)

    def test_is_lean(self):
        hook = reload_hook(self.dir)
        ctx, _ = hook.assemble("startup")
        self.assertLessEqual(len(ctx), hook.SAFE_TOTAL + 100)

    def test_includes_resume_and_open_items(self):
        ctx = self._emit()
        self.assertIn("Resume command", ctx)
        self.assertIn("finish the thing", ctx)

    def test_excludes_auto_archived_section(self):
        ctx = self._emit()
        self.assertIn("Do the thing", ctx)
        self.assertNotIn("Old done thing", ctx)

    def test_ground_truth_is_a_toc_not_full_body(self):
        ctx = self._emit()
        self.assertIn("Services", ctx)
        self.assertNotIn("api up", ctx)

    def test_fail_open_on_missing_vault(self):
        ctx = self._emit(os.path.join(self.dir, "does-not-exist"))
        self.assertIsNone(ctx)

    def test_untyped_oddly_named_file_is_not_a_handoff(self):
        self._write("2025-02-01-notes-scratch.md",
                    "---\ntitle: x\n---\n# not a handoff\n\nDECOYBODY should not appear.\n")
        ctx = self._emit()
        self.assertNotIn("DECOYBODY", ctx)
        self.assertIn("finish the thing", ctx)

    def test_newer_unreadable_handoff_is_flagged_not_dropped(self):
        with open(os.path.join(self.dir, "handoffs",
                               "2025-03-01-corrupt-handoff.md"), "wb") as f:
            f.write(b"---\ntitle: C\n---\n\xff\xfe\x00 binary junk \x00\x00")
        ctx = self._emit()
        self.assertIn("finish the thing", ctx)
        self.assertIn("could not be read", ctx)

    def test_undated_handoffs_do_not_cross_list_as_siblings(self):
        self._write("alpha-handoff.md", "# no frontmatter date\n\nbody.\n")
        self._write("beta-handoff.md", "# no frontmatter date\n\nbody.\n")
        ctx = self._emit()
        self.assertNotIn("alpha-handoff.md", ctx)
        self.assertNotIn("beta-handoff.md", ctx)

    def test_legacy_siblings_still_get_the_name_notice(self):
        self._write("2025-01-15-sib-handoff.md", handoff_text("FINDME"))
        self._promote()
        ctx = self._emit()
        self.assertIn("OTHER handoff(s) share this date", ctx)
        self.assertIn("FINDME", ctx)

    # ---- v2: typed sibling digests --------------------------------------
    def test_status_sibling_gets_a_digest_not_just_a_name(self):
        self._write("2025-01-15-sib-handoff.md", handoff_text(
            "SIBLING", extra_fm="status: active\ngoal: ship the widget\n"
                               "next_action: wire the tests\n"))
        self._promote()
        ctx = self._emit()
        self.assertIn("CONCURRENT", ctx)
        self.assertIn("ship the widget", ctx)
        self.assertIn("wire the tests", ctx)

    def test_status_sibling_is_not_double_listed_in_the_notice(self):
        self._write("2025-01-15-sib-handoff.md", handoff_text(
            "SIBLING", extra_fm="status: active\ngoal: g\n"))
        self._promote()
        ctx = self._emit()
        self.assertNotIn("OTHER handoff(s) share this date", ctx,
                         "a digested sibling must not also trigger the legacy notice")

    def test_done_sibling_is_one_lined_as_closed(self):
        self._write("2025-01-15-sib-handoff.md", handoff_text(
            "CLOSEDONE", extra_fm="status: done\ngoal: was finished\n"))
        self._promote()
        ctx = self._emit()
        self.assertIn("Closed threads", ctx)
        self.assertNotIn("was finished", ctx, "closed digests stay one-line")

    def test_digest_count_is_capped(self):
        hook = reload_hook(self.dir)
        for i in range(9):
            self._write(f"2025-01-15-s{i}-handoff.md", handoff_text(
                f"S{i}", extra_fm=f"status: active\ngoal: goal {i}\n"))
        self._promote()
        ctx = self._emit()
        block = ctx.split("CONCURRENT")[1].split("###")[0]
        self.assertLessEqual(block.count("goal:"), hook.SIB_DIGEST_MAX)
        self.assertIn("more live", block)

    # ---- v2: sources ----------------------------------------------------
    def test_compact_source_emits_rearm_not_full_bootstrap(self):
        hook = reload_hook(self.dir)
        claude_root = os.path.join(self.dir, "dotclaude")
        os.makedirs(claude_root, exist_ok=True)
        claude_md = os.path.join(claude_root, "CLAUDE.md")
        with open(claude_md, "w", encoding="utf-8") as f:
            f.write("# ops\n\n## Operating principles (standing behavior)\n\n"
                    "1. **Cost-first** — cheapest capable path.\n")
        hook.CLAUDE_ROOT, hook.CLAUDE_MD = claude_root, claude_md
        ctx, blocks = hook.assemble("compact")
        self.assertIn("CHARTER", ctx)
        self.assertIn("Cost-first", ctx)
        self.assertNotIn("RESUME", ctx)

    def test_compact_includes_fresh_checkpoint_for_this_session(self):
        hook = reload_hook(self.dir)
        claude_root = os.path.join(self.dir, "dotclaude")
        os.makedirs(claude_root, exist_ok=True)
        claude_md = os.path.join(claude_root, "CLAUDE.md")
        with open(claude_md, "w", encoding="utf-8") as f:
            f.write("## Operating principles\n1. rule.\n")
        hook.CLAUDE_ROOT, hook.CLAUDE_MD = claude_root, claude_md
        os.makedirs(hook.CHECKPOINT_DIR, exist_ok=True)
        with open(os.path.join(hook.CHECKPOINT_DIR,
                               "2026-08-24-1200-sid12345-precompact.md"),
                  "w", encoding="utf-8") as f:
            f.write("CHECKPOINTMARK todo A\n")
        ctx, _ = hook.assemble("compact", session_id="sid12345-full-uuid")
        self.assertIn("CHECKPOINTMARK", ctx)

    def test_fork_source_injects_nothing(self):
        hook = reload_hook(self.dir)
        ctx, _ = hook.assemble("fork")
        self.assertIsNone(ctx)

    def test_garbage_stdin_treated_as_startup(self):
        hook = reload_hook(self.dir)
        import io as _io
        real = os.sys.stdin
        try:
            os.sys.stdin = _io.StringIO("not json{{{")
            self.assertEqual(hook.read_hook_input(), ("startup", None))
        finally:
            os.sys.stdin = real

    # ---- v2: flags, capabilities, staleness, budget ---------------------
    def test_lint_flags_are_injected_when_report_has_findings(self):
        hook = reload_hook(self.dir)
        os.makedirs(os.path.dirname(hook.LINT_REPORT), exist_ok=True)
        with open(hook.LINT_REPORT, "w", encoding="utf-8") as f:
            f.write("# report\n\n2 finding(s):\n\n  STALE-VERIFY LintFindingMark\n"
                    "  OVERSIZED-ITEM another\n")
        ctx, _ = hook.assemble("startup")
        self.assertIn("memory-lint: 2 finding(s)", ctx)
        self.assertIn("LintFindingMark", ctx)

    def test_capabilities_digest_injected_when_manifest_exists(self):
        hook = reload_hook(self.dir)
        os.makedirs(os.path.dirname(hook.MANIFEST), exist_ok=True)
        with open(hook.MANIFEST, "w", encoding="utf-8") as f:
            f.write("# m\n\n## Digest\n\n- CAPMARK 51 skills\n\n## Skills\n- x\n")
        ctx, _ = hook.assemble("startup")
        self.assertIn("CAPABILITIES", ctx)
        self.assertIn("CAPMARK", ctx)
        self.assertNotIn("## Skills", ctx, "only the Digest section is injected")

    def test_recall_teach_line_present_even_without_manifest(self):
        ctx = self._emit()
        self.assertIn("recall.py", ctx)

    def test_stale_verified_stamp_is_flagged(self):
        with open(os.path.join(self.dir, "LIVE-STATE.md"), "w", encoding="utf-8") as f:
            f.write("# LS\n\n## Old section (verified 2020-01-01)\n- ancient\n\n"
                    "## Fresh section\n- fine\n")
        ctx = self._emit()
        self.assertIn("STALE", ctx)
        self.assertIn("Old section", ctx)
        self.assertNotIn("ancient", ctx, "still names-only, never bodies")

    def test_priority_drop_keeps_core_blocks_under_ceiling(self):
        hook = reload_hook(self.dir)
        os.makedirs(os.path.dirname(hook.MANIFEST), exist_ok=True)
        with open(hook.MANIFEST, "w", encoding="utf-8") as f:
            f.write("## Digest\n\n" + ("- filler line\n" * 120))
        for i in range(6):
            self._write(f"2025-01-15-s{i}-handoff.md", handoff_text(
                f"S{i}", extra_fm=f"status: active\ngoal: {'g' * 600}\n"))
        big = ("---\ntitle: BIG\ntype: session-handoff\ndate: 2025-01-15\n---\n# H\n\n"
               + "intro filler.\n" * 400
               + "\n## Open items / next steps\n" + "- item.\n" * 200
               + "\n## Resume command\nDo.\n")
        self._write("2025-01-15-zzz-primary-handoff.md", big)
        ctx, blocks = hook.assemble("startup")
        self.assertLessEqual(len(ctx), hook.SAFE_TOTAL + 100)
        self.assertIn("RESUME", ctx)
        self.assertIn("ACTIVE", ctx)

    def test_metrics_line_is_appended(self):
        hook = reload_hook(self.dir)
        ctx, blocks = hook.assemble("startup")
        hook.metrics_append("startup", blocks, len(ctx))
        with open(hook.METRICS, encoding="utf-8") as f:
            rec = json.loads(f.readlines()[-1])
        self.assertEqual(rec["source"], "startup")
        self.assertGreater(rec["chars"], 100)


if __name__ == "__main__":
    unittest.main()
