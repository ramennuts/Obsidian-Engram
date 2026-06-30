"""Tests for the queue archiver's conservative classifier + end-to-end move.

The classifier's whole job is to err toward KEEP: a wrongly-kept done item is
harmless; a wrongly-archived live item hides real work. These tests pin that.
"""
import os
import tempfile
import unittest

from conftest_paths import archive


def classify(item_md):
    """Classify a single `### ` item block given as markdown text."""
    return archive.classify(item_md.split("\n"))


class TestClassifier(unittest.TestCase):
    def test_struck_and_shipped_no_thread_is_archived(self):
        ok, _ = classify("### ~~Build the widget~~ — **SHIPPED 2025-01-10**\n- Done, verified live.")
        self.assertTrue(ok)

    def test_struck_done_closed_resolved_wontfix_all_count(self):
        for marker in ("DONE", "CLOSED", "RESOLVED", "COMPLETE", "won't-fix"):
            ok, _ = classify(f"### ~~Thing~~ — **{marker}**\n- finished.")
            self.assertTrue(ok, f"{marker!r} should be a completion marker")

    def test_unstruck_header_is_kept(self):
        ok, reason = classify("### Add pagination\n- still building this.")
        self.assertFalse(ok)
        self.assertIn("not struck", reason)

    def test_struck_without_completion_marker_is_kept(self):
        # "superseded"/"pushed aside" have no done/shipped/closed marker -> KEEP
        ok, reason = classify("### ~~Old plan~~ — **SUPERSEDED** (pivoted)\n- abandoned.")
        self.assertFalse(ok)
        self.assertIn("no done/shipped/closed marker", reason)

    def test_struck_done_but_open_thread_is_kept(self):
        ok, reason = classify(
            "### ~~Ship OAuth~~ — **DONE**\n- Google live. **Still to do:** Apple review pending."
        )
        self.assertFalse(ok)
        self.assertIn("live thread", reason)

    def test_open_thread_words_each_block_archive(self):
        for word in ("pending", "blocked", "awaiting", "one piece left", "until then"):
            ok, _ = classify(f"### ~~Thing~~ — **DONE**\n- note: {word} on something.")
            self.assertFalse(ok, f"{word!r} should keep the item live")

    def test_struck_span_is_stripped_before_thread_scan(self):
        # the "still pending" is INSIDE the strike, so it must NOT save the item
        ok, _ = classify("### ~~Task still pending~~ — **DONE 2025-01-10**\n- shipped, verified.")
        self.assertTrue(ok)

    def test_quoted_marker_gotcha_keeps_item(self):
        # a resolution note that QUOTES a trigger word keeps the item (documented gotcha)
        ok, reason = classify(
            "### ~~Page~~ — **SHIPPED**\n- The earlier **Still to do** note was stale."
        )
        self.assertFalse(ok)
        self.assertIn("live thread", reason)


QUEUE = """---
title: Build queue
---

# Build queue

## Active items
### Live item one
- working on it.

### ~~Finished thing~~ — **SHIPPED 2025-01-10**
- done and verified.

### ~~Done but open~~ — **DONE**
- **Still to do:** wire it up.

## Blocked
### ~~Resolved blocker~~ — **RESOLVED 2025-01-09**
- unblocked and shipped.

### ~~Abandoned~~ — **SUPERSEDED** (pivot)
- dropped.
"""


class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "build-queue.md")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(QUEUE)

    def _run(self, apply):
        import contextlib
        import io
        import sys
        argv = sys.argv
        sys.argv = ["archive", "--file", self.path] + (["--apply"] if apply else [])
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                return archive.main()
        finally:
            sys.argv = argv

    def _read(self):
        with open(self.path, encoding="utf-8") as f:
            return f.read()

    def test_apply_moves_only_finished_items(self):
        item_count = self._read().count("### ")
        self._run(apply=True)
        out = self._read()
        # the 2 genuinely-finished items moved to Auto-archived
        self.assertIn("## Auto-archived", out)
        archived = out.split("## Auto-archived", 1)[1]
        self.assertIn("Finished thing", archived)
        self.assertIn("Resolved blocker", archived)
        # the kept ones stay above the archive header
        head = out.split("## Auto-archived", 1)[0]
        self.assertIn("Live item one", head)
        self.assertIn("Done but open", head)      # struck+done but open thread
        self.assertIn("Abandoned", head)          # superseded, no completion marker
        # nothing lost
        self.assertEqual(out.count("### "), item_count)

    def test_idempotent(self):
        self._run(apply=True)
        first = self._read()
        self._run(apply=True)
        self.assertEqual(first, self._read(), "second run must be a no-op")

    def test_backup_written_on_apply(self):
        self._run(apply=True)
        baks = [f for f in os.listdir(self.dir) if f.endswith(".bak")]
        self.assertEqual(len(baks), 1)

    def test_dry_run_writes_nothing(self):
        before = self._read()
        self._run(apply=False)
        self.assertEqual(before, self._read())


if __name__ == "__main__":
    unittest.main()
