"""Tests for the compactor's deterministic passes (rollup, bak-sweep, archive
reuse, actionable extraction). The LLM proposals pass is NOT tested here — it is
propose-only, gated by D2, and exercised in supervised runs, not unit tests."""
import datetime
import os
import tempfile
import unittest

import conftest_paths


def load_compactor(vault, memory):
    os.environ["ENGRAM_VAULT"] = vault
    os.environ["ENGRAM_MEMORY"] = memory
    return conftest_paths.load("scripts/compactor.py", "engram_compactor_reload")


class TestCompactor(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.vault = os.path.join(self.root, "vault")
        self.memory = os.path.join(self.root, "memory")
        os.makedirs(os.path.join(self.vault, "handoffs"))
        os.makedirs(self.memory)
        self.c = load_compactor(self.vault, self.memory)
        self.today = datetime.date.today().isoformat()

    def _w(self, relpath, body):
        p = os.path.join(self.vault, relpath)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(body)
        return p

    def _handoff(self, name, marker, status="active"):
        self._w(os.path.join("handoffs", name),
                f"---\ntitle: {marker}\ntype: session-handoff\ndate: {self.today}\n"
                f"status: {status}\ngoal: goal-{marker}\nnext_action: next-{marker}\n---\n"
                f"# h\n\nintro {marker}\n\n## Open items / next steps\n- open {marker}\n\n"
                f"## What did NOT work\n- SECRETDEADEND {marker}\n")

    # ---- rollup -----------------------------------------------------------
    def test_rollup_written_for_multi_handoff_day(self):
        self._handoff(f"{self.today}-one-handoff.md", "ALPHA")
        self._handoff(f"{self.today}-two-handoff.md", "BETA")
        result = self.c.pass_rollup()
        self.assertIn("wrote", result)
        rollup = os.path.join(self.vault, "machine", "rollups",
                              f"{self.today}-rollup.md")
        with open(rollup, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("open ALPHA", text)
        self.assertIn("open BETA", text)
        self.assertIn("goal: goal-ALPHA", text)
        self.assertNotIn("SECRETDEADEND", text,
                         "rollup carries ACTIONABLE sections only, verbatim")

    def test_no_rollup_for_single_handoff_day(self):
        self._handoff(f"{self.today}-solo-handoff.md", "SOLO")
        result = self.c.pass_rollup()
        self.assertIn("no multi-handoff", result)

    def test_rollup_is_idempotent_and_refreshes(self):
        self._handoff(f"{self.today}-one-handoff.md", "ALPHA")
        self._handoff(f"{self.today}-two-handoff.md", "BETA")
        self.c.pass_rollup()
        self._handoff(f"{self.today}-three-handoff.md", "GAMMA")
        self.c.pass_rollup()
        with open(os.path.join(self.vault, "machine", "rollups",
                               f"{self.today}-rollup.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("open GAMMA", text)

    # ---- bak sweep --------------------------------------------------------
    def test_old_bak_moved_fresh_bak_kept(self):
        old = self._w("build-queue.md.20260101-000000.bak", "old")
        fresh = self._w("build-queue.md.99990101-000000.bak", "fresh")
        stamp = datetime.datetime.now().timestamp() - 20 * 86400
        os.utime(old, (stamp, stamp))
        result = self.c.pass_bak_sweep()
        self.assertIn("moved 1", result)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(fresh), "recent backups stay put")
        self.assertTrue(os.path.exists(os.path.join(
            self.vault, "machine", "archive", "backups",
            "build-queue.md.20260101-000000.bak")), "archive != delete")

    # ---- archiver reuse ---------------------------------------------------
    def test_archive_pass_reuses_the_existing_classifier(self):
        self._w("build-queue.md",
                "# q\n\n## Active items\n\n### ~~Ship the gizmo~~ — **DONE**\n"
                "- all wrapped.\n\n### Live item\n- in progress.\n\n## Blocked\n")
        result = self.c.pass_archive()
        self.assertIn("APPLIED", result)
        with open(os.path.join(self.vault, "build-queue.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("## Auto-archived", text)
        self.assertIn("Live item", text.split("## Auto-archived")[0],
                      "live items stay in Active")
        self.assertIn("Ship the gizmo", text.split("## Auto-archived")[1])

    # ---- run_pass fail-open ----------------------------------------------
    def test_a_broken_pass_never_stops_the_run(self):
        results = {}
        def boom():
            raise RuntimeError("kaput")
        self.c.run_pass("broken", boom, results)
        self.c.run_pass("fine", lambda: "ok", results)
        self.assertIn("FAILED", results["broken"])
        self.assertEqual(results["fine"], "ok")


if __name__ == "__main__":
    unittest.main()
