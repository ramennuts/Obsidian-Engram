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
HANDOFF = (
    "---\ntitle: t\n---\n# Session handoff — 2025-01-15\n\nOrientation line.\n\n"
    "## Headlines\n### A) Did a thing\n\n"
    "## Open items / next steps\n- finish the thing.\n\n"
    "## Resume command\nRead X, run Y.\n"
)


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


if __name__ == "__main__":
    unittest.main()
