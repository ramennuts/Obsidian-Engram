"""Tests for gen_capabilities.py: grepped-from-live-config, deterministic, no secrets."""
import json
import os
import tempfile
import unittest

import conftest_paths


class TestCapabilities(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.g = conftest_paths.load("scripts/gen_capabilities.py",
                                     "engram_gen_caps_reload")
        # point every source at fixtures
        self.g.SKILLS_DIR = os.path.join(self.root, "skills")
        self.g.AGENTS_DIR = os.path.join(self.root, "agents")
        self.g.TOOLS_DIR = os.path.join(self.root, "tools")
        self.g.SETTINGS = os.path.join(self.root, "settings.json")
        os.makedirs(os.path.join(self.g.SKILLS_DIR, "backtest"))
        with open(os.path.join(self.g.SKILLS_DIR, "backtest", "SKILL.md"), "w") as f:
            f.write("---\nname: backtest\ndescription: Quick backtest a strategy. "
                    "More detail here.\n---\nbody\n")
        os.makedirs(self.g.AGENTS_DIR)
        with open(os.path.join(self.g.AGENTS_DIR, "code-reviewer.md"), "w") as f:
            f.write("---\nname: code-reviewer\ndescription: Tier-1 reviewer.\n---\n")
        os.makedirs(os.path.join(self.g.TOOLS_DIR, "engram"))
        with open(os.path.join(self.g.TOOLS_DIR, "engram", "README.md"), "w") as f:
            f.write("# Engram\n\nA two-layer agent memory architecture.\n")
        with open(self.g.SETTINGS, "w") as f:
            json.dump({
                "hooks": {"SessionStart": [{"hooks": [
                    {"type": "command",
                     "command": "python3 /x/session-start.py"}]}]},
                "enabledPlugins": {"marketing-skills@m": True},
                "env": {"SECRET_SHOULD_NOT_APPEAR": "hunter2"},
            }, f)

    def test_manifest_contains_all_sources(self):
        text = self.g.build()
        self.assertIn("## Digest", text)
        self.assertIn("`backtest` — Quick backtest a strategy", text)
        self.assertIn("code-reviewer", text)
        self.assertIn("session-start.py", text)
        self.assertIn("marketing-skills@m", text)
        self.assertIn("`engram` — A two-layer agent memory architecture.", text)

    def test_no_config_values_leak(self):
        text = self.g.build()
        self.assertNotIn("hunter2", text, "manifest lists names, never values")

    def test_deterministic(self):
        self.assertEqual(self.g.build(), self.g.build())

    def test_digest_stays_lean(self):
        digest = self.g.build().split("## Skills")[0]
        self.assertLess(len(digest), 2500, "the Digest section is what gets "
                                           "injected — it must stay small")


if __name__ == "__main__":
    unittest.main()
