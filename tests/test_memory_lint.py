"""Tests for the durable-memory linter: orphans, dangling links, index gaps, frontmatter."""
import os
import tempfile
import unittest

from conftest_paths import load

lint = load("scripts/memory_lint.py", "engram_memory_lint")


def write(d, name, body):
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        f.write(body)


NOTE = "---\nname: {n}\ndescription: d\ntype: reference\n---\n\nbody {links}\n"


class TestMemoryLint(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _run(self):
        import contextlib
        import io
        import sys
        argv = sys.argv
        sys.argv = ["lint", "--dir", self.dir]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = lint.main()
        finally:
            sys.argv = argv
        return rc, buf.getvalue()

    def test_clean_vault_passes(self):
        write(self.dir, "MEMORY.md", "## Core\n- [a](a.md)\n- [b](b.md)\n")
        write(self.dir, "a.md", NOTE.format(n="a", links="[[b]]"))
        write(self.dir, "b.md", NOTE.format(n="b", links=""))
        rc, out = self._run()
        self.assertEqual(rc, 0)
        self.assertIn("clean", out)

    def test_orphan_detected(self):
        write(self.dir, "MEMORY.md", "## Core\n- [a](a.md)\n")
        write(self.dir, "a.md", NOTE.format(n="a", links=""))
        write(self.dir, "b.md", NOTE.format(n="b", links=""))  # not in index
        rc, out = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("ORPHAN", out)
        self.assertIn("b.md", out)

    def test_dangling_link_detected(self):
        write(self.dir, "MEMORY.md", "## Core\n- [a](a.md)\n")
        write(self.dir, "a.md", NOTE.format(n="a", links="[[nope]]"))
        rc, out = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("DANGLING", out)

    def test_index_gap_detected(self):
        write(self.dir, "MEMORY.md", "## Core\n- [ghost](ghost.md)\n")  # file missing
        rc, out = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("INDEX GAP", out)

    def test_missing_frontmatter_detected(self):
        write(self.dir, "MEMORY.md", "## Core\n- [a](a.md)\n")
        write(self.dir, "a.md", "no frontmatter here\n")
        rc, out = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("FRONTMATTER", out)


if __name__ == "__main__":
    unittest.main()
