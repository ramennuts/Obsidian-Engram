"""Tests for the SessionStart bootstrap hook: lean output, right content, fail-open."""
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
# `type:` is REQUIRED for this fixture to register as a handoff. The selector
# counts a file only if it is typed `*handoff*` OR named `*-handoff.md`; this
# fixture is named `2025-01-15-h.md`, so the type field is what qualifies it.
# That filter was added 2026-08-13 and silently broke this suite — the RESUME
# block vanished from every test and `main()`'s fail-open try/except swallowed
# it, so the only symptom was two assertions failing on missing content.
HANDOFF = (
    "---\ntitle: t\ntype: session-handoff\n---\n# Session handoff — 2025-01-15\n\n"
    "Orientation line.\n\n"
    "## Headlines\n### A) Did a thing\n\n"
    "## Open items / next steps\n- finish the thing.\n\n"
    "## Resume command\nRead X, run Y.\n"
)


def handoff_text(marker, date="2025-01-15", typ="session-handoff"):
    fm = f"---\ntitle: {marker}\ntype: {typ}\ndate: {date}\n---\n"
    return fm + f"# H {marker}\n\nOrientation {marker}.\n\n## Resume command\nDo {marker}.\n"


def reload_hook(vault):
    """Reload the hook module with ENGRAM_VAULT pointed at a temp vault."""
    os.environ["ENGRAM_VAULT"] = vault
    return conftest_paths.load("hooks/session-start.py", "engram_session_start_reload")


class TestHook(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for name, body in VAULT_FILES.items():
            with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
                f.write(body)
        os.makedirs(os.path.join(self.dir, "handoffs"))
        with open(os.path.join(self.dir, "handoffs", "2025-01-15-h.md"), "w", encoding="utf-8") as f:
            f.write(HANDOFF)

    def _emit(self, vault):
        """Run main(), capture stdout, return parsed additionalContext or None."""
        import contextlib
        import io
        hook = reload_hook(vault)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            hook.main()
        out = buf.getvalue().strip()
        if not out:
            return None
        return json.loads(out)["hookSpecificOutput"]["additionalContext"]

    def test_emits_valid_json_with_three_blocks(self):
        ctx = self._emit(self.dir)
        self.assertIsNotNone(ctx)
        self.assertIn("RESUME", ctx)
        self.assertIn("ACTIVE WORK", ctx)
        self.assertIn("GROUND TRUTH", ctx)

    def test_is_lean(self):
        ctx = self._emit(self.dir)
        self.assertLess(len(ctx), 10000, "injection must stay well under the harness ceiling")

    def test_includes_resume_and_open_items(self):
        ctx = self._emit(self.dir)
        self.assertIn("Resume command", ctx)
        self.assertIn("finish the thing", ctx)

    def test_excludes_auto_archived_section(self):
        ctx = self._emit(self.dir)
        self.assertIn("Do the thing", ctx)        # active item header injected
        self.assertNotIn("Old done thing", ctx)   # archived section NOT injected

    def test_ground_truth_is_a_toc_not_full_body(self):
        ctx = self._emit(self.dir)
        self.assertIn("Services", ctx)            # section title in the TOC
        self.assertNotIn("api up", ctx)           # but not the section body

    def test_fail_open_on_missing_vault(self):
        ctx = self._emit(os.path.join(self.dir, "does-not-exist"))
        self.assertIsNone(ctx, "missing vault must emit nothing, not crash")

    # --- same-date sibling surfacing (2026-08-13) -------------------------
    # Several sessions a day is normal and they do not see each other's
    # handoffs. The selector returns exactly ONE file, so whichever session
    # wrote last silently became the pickup brief regardless of what it
    # covered: on 2026-08-13 five handoffs shared a date, one was injected,
    # and a session resuming from it missed binding constraints recorded in a
    # sibling. The primary stays deterministic; the siblings get named.

    def _write(self, name, body):
        with open(os.path.join(self.dir, "handoffs", name), "w",
                  encoding="utf-8") as f:
            f.write(body)

    def test_names_same_date_siblings(self):
        self._write("2025-01-15-sibling-one-handoff.md",
                    handoff_text("SIBONE"))
        self._write("2025-01-15-sibling-two-handoff.md",
                    handoff_text("SIBTWO"))
        ctx = self._emit(self.dir)
        self.assertIn("OTHER handoff(s) share this date", ctx)
        self.assertIn("sibling-one-handoff.md", ctx)
        self.assertIn("sibling-two-handoff.md", ctx)

    def test_sibling_notice_lists_titles_not_just_filenames(self):
        self._write("2025-01-15-sib-handoff.md", handoff_text("FINDME"))
        ctx = self._emit(self.dir)
        self.assertIn("FINDME", ctx, "frontmatter title must be shown so the "
                                     "reader can tell what the sibling covers")

    def test_no_notice_when_only_one_handoff_that_date(self):
        ctx = self._emit(self.dir)
        self.assertNotIn("OTHER handoff(s) share this date", ctx,
                         "a lone handoff must not carry a scary warning")

    def test_older_dates_are_not_listed_as_siblings(self):
        self._write("2024-06-01-ancient-handoff.md",
                    handoff_text("ANCIENT", date="2024-06-01"))
        ctx = self._emit(self.dir)
        self.assertNotIn("ANCIENT", ctx, "older handoffs are legitimately "
                                         "superseded — only same-day concurrency matters")

    def test_notice_survives_a_huge_intro(self):
        """The finding-6 case: the notice must survive a large PRE-## intro, not
        just trailing bulk. cap() truncates the tail, and the notice is placed
        ahead of the intro precisely so an oversized intro cannot bury it. A
        primary whose intro alone exceeds the cap is the only thing that tests
        placement; filler in a trailing section always survives regardless."""
        sib = handoff_text("SIB2025")
        self._write("2025-01-15-sib-handoff.md", sib)
        # primary with a >cap intro (text BEFORE the first ## heading)
        huge_intro = ("---\ntitle: PRIMARY\ntype: session-handoff\n"
                      "date: 2025-01-15\n---\n# H\n\n"
                      + "intro filler line.\n" * 900
                      + "\n## Resume command\nDo it.\n")
        self._write("2025-01-15-zprimary-handoff.md", huge_intro)  # sorts newest
        ctx = self._emit(self.dir)
        self.assertIn("OTHER handoff(s) share this date", ctx,
                      "notice must appear even when the primary's intro exceeds the cap")

    def test_sibling_scan_never_wedges_startup(self):
        """An unreadable sibling must not cost the whole RESUME block."""
        p = os.path.join(self.dir, "handoffs", "2025-01-15-bad-handoff.md")
        with open(p, "wb") as f:
            f.write(b"\xff\xfe not valid utf-8 \x00\x00")
        ctx = self._emit(self.dir)
        self.assertIsNotNone(ctx)
        self.assertIn("RESUME", ctx)

    def test_untyped_oddly_named_file_is_not_a_handoff(self):
        """Locks in the 2026-08-13 filter that broke this suite. The decoy is
        dated NEWER than the real handoff and carries a unique body marker, so if
        the filter were removed it would win primary and its content would leak
        into ctx. A same-date decoy would not test the filter — it would be
        ranked out by date regardless (finding 2)."""
        self._write("2025-02-01-notes-scratch.md",
                    "---\ntitle: x\n---\n# not a handoff\n\nDECOYBODY should not appear.\n")
        ctx = self._emit(self.dir)
        self.assertNotIn("DECOYBODY", ctx, "an untyped, non-*-handoff.md file must "
                                           "not be selectable as the pickup brief")
        self.assertIn("finish the thing", ctx, "the real handoff stays primary")

    def test_newer_unreadable_handoff_is_flagged_not_dropped(self):
        """finding 1: if the newest handoff cannot be read, the older one is used
        BUT the skip is announced, not silent."""
        with open(os.path.join(self.dir, "handoffs",
                               "2025-03-01-corrupt-handoff.md"), "wb") as f:
            f.write(b"---\ntitle: C\n---\n\xff\xfe\x00 binary junk \x00\x00")
        ctx = self._emit(self.dir)
        self.assertIsNotNone(ctx)
        self.assertIn("finish the thing", ctx, "falls back to the readable older brief")
        self.assertIn("could not be read", ctx, "and SAYS the newer one was skipped")
        self.assertIn("corrupt-handoff.md", ctx)

    def test_undated_handoffs_do_not_cross_list_as_siblings(self):
        """finding 3: two undated handoffs must not be reported as sharing a date
        just because both fall back to the (1,1,1) sentinel."""
        self._write("alpha-handoff.md", "# no frontmatter date\n\nbody.\n")
        self._write("beta-handoff.md", "# no frontmatter date\n\nbody.\n")
        # the real fixture 2025-01-15-h.md is dated, so it wins primary; the two
        # undated ones must not appear as its siblings, nor each other's.
        ctx = self._emit(self.dir)
        self.assertNotIn("alpha-handoff.md", ctx)
        self.assertNotIn("beta-handoff.md", ctx)


if __name__ == "__main__":
    unittest.main()
