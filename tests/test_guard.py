"""Tests for the rules-as-hooks guard: blocks listed commands, fails open, honors override."""
import json
import os
import unittest

from conftest_paths import load

guard = load("hooks/guard.py", "engram_guard")


class TestGuard(unittest.TestCase):
    def _run(self, command, allow=False):
        """Feed a PreToolUse-shaped payload on stdin; return the exit code."""
        import contextlib
        import io
        import sys
        payload = json.dumps({"tool_input": {"command": command}})
        old_env = os.environ.get("GUARD_ALLOW")
        if allow:
            os.environ["GUARD_ALLOW"] = "1"
        elif "GUARD_ALLOW" in os.environ:
            del os.environ["GUARD_ALLOW"]
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(payload)
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                return guard.main()
        finally:
            sys.stdin = old_stdin
            if old_env is None:
                os.environ.pop("GUARD_ALLOW", None)
            else:
                os.environ["GUARD_ALLOW"] = old_env

    def test_blocks_rm_rf(self):
        self.assertEqual(self._run("rm -rf /important"), 2)

    def test_blocks_force_push(self):
        self.assertEqual(self._run("git push origin main --force"), 2)

    def test_allows_force_with_lease(self):
        self.assertEqual(self._run("git push origin main --force-with-lease"), 0)

    def test_allows_ordinary_command(self):
        self.assertEqual(self._run("ls -la && python3 test.py"), 0)

    def test_override_bypasses(self):
        self.assertEqual(self._run("rm -rf /important", allow=True), 0)

    def test_fail_open_on_garbage_stdin(self):
        import io
        import sys
        old = sys.stdin
        sys.stdin = io.StringIO("not json at all")
        try:
            self.assertEqual(guard.main(), 0)
        finally:
            sys.stdin = old


if __name__ == "__main__":
    unittest.main()
