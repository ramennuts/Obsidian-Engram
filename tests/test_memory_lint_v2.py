"""Tests for the memory-v2 lint extensions: budgets, staleness, contracts, report."""
import datetime
import os
import tempfile
import unittest

import conftest_paths


def load_lint(memory, vault):
    os.environ["ENGRAM_MEMORY"] = memory
    os.environ["ENGRAM_VAULT"] = vault
    return conftest_paths.load("scripts/memory_lint.py", "engram_memory_lint_reload")


def note(name, typ="reference", body="fact."):
    return (f"---\nname: {name}\ndescription: d\nmetadata:\n  type: {typ}\n"
            f"type: {typ}\n---\n\n{body}\n")


class TestLintV2(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.memory = os.path.join(self.root, "memory")
        self.vault = os.path.join(self.root, "vault")
        os.makedirs(self.memory)
        os.makedirs(os.path.join(self.vault, "handoffs"))
        self._w(os.path.join(self.memory, "MEMORY.md"),
                "# index\n- [Fact](fact_one.md) — a fact.\n")
        self._w(os.path.join(self.memory, "fact_one.md"), note("fact_one"))
        self.lint = load_lint(self.memory, self.vault)

    def _w(self, path, body):
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)

    # ---- original checks still work -------------------------------------
    def test_clean_memory_is_clean(self):
        self.assertEqual(self.lint.lint_memory(self.memory), [])

    def test_orphan_and_dangling_still_caught(self):
        self._w(os.path.join(self.memory, "fact_two.md"),
                note("fact_two", body="see [[nope_missing]]"))
        problems = "\n".join(self.lint.lint_memory(self.memory))
        self.assertIn("ORPHAN", problems)
        self.assertIn("DANGLING", problems)

    # ---- v2 memory budgets ----------------------------------------------
    def test_oversized_note_flagged(self):
        self._w(os.path.join(self.memory, "MEMORY.md"),
                "# index\n- [Fact](fact_one.md) — a.\n- [Big](fact_big.md) — b.\n")
        self._w(os.path.join(self.memory, "fact_big.md"),
                note("fact_big", body="x" * 12_000))
        problems = "\n".join(self.lint.lint_memory(self.memory))
        self.assertIn("BUDGET", problems)
        self.assertIn("fact_big", problems)

    # ---- v2 vault checks -------------------------------------------------
    def test_stale_verified_stamp_flagged_fresh_not(self):
        today = datetime.date.today().isoformat()
        self._w(os.path.join(self.vault, "LIVE-STATE.md"),
                f"# LS\n\n## Ancient (verified 2020-01-01)\n- x\n\n"
                f"## Fresh (verified {today})\n- y\n")
        problems = "\n".join(self.lint.lint_vault(self.vault))
        self.assertIn("STALE-VERIFY", problems)
        # Contract flipped by the verification round: a LIVE-STATE header can
        # name a party, and this report is FTS-indexed, injected into every
        # bootstrap AND read into the outbound bundle. Hash, never name.
        self.assertNotIn("Ancient", problems)
        self.assertIn("2020-01-01", problems, "the date stays — it is the signal")
        self.assertNotIn("Fresh", problems)

    def test_oversized_queue_item_flagged(self):
        self._w(os.path.join(self.vault, "build-queue.md"),
                "# q\n\n## Active items\n\n### Small item\n- fine.\n\n"
                "### Bloated item\n" + ("- accreted narrative line.\n" * 300)
                + "\n## Blocked\n")
        problems = "\n".join(self.lint.lint_vault(self.vault))
        self.assertIn("OVERSIZED-ITEM", problems)
        # Board 2026-08-25 flipped this contract: headings carry company and
        # owner names, and this report is recall-indexed AND is chunk 1 of the
        # compactor's outbound bundle. Position + hash, never the heading.
        self.assertNotIn("Bloated", problems)
        self.assertNotIn("Small item", problems)
        self.assertIn("item #2", problems, "the oversized one is the 2nd item")

    def test_handoff_contract_only_enforced_from_start_date(self):
        self._w(os.path.join(self.vault, "handoffs", "2026-08-25-x-handoff.md"),
                "---\ntitle: t\ntype: session-handoff\ndate: 2026-08-25\n---\nbody\n")
        self._w(os.path.join(self.vault, "handoffs", "2026-08-01-old-handoff.md"),
                "---\ntitle: t\ntype: session-handoff\ndate: 2026-08-01\n---\nbody\n")
        problems = "\n".join(self.lint.lint_vault(self.vault))
        self.assertIn("HANDOFF-CONTRACT", problems)
        self.assertIn("2026-08-25", problems)
        self.assertNotIn("2026-08-01", problems, "pre-contract handoffs are exempt")

    def test_old_backup_flagged(self):
        p = os.path.join(self.vault, "build-queue.md.20260101-000000.bak")
        self._w(p, "old backup")
        old = datetime.datetime.now().timestamp() - 20 * 86400
        os.utime(p, (old, old))
        problems = "\n".join(self.lint.lint_vault(self.vault))
        self.assertIn("OLD-BACKUP", problems)

    def test_no_rollup_flagged_for_multi_handoff_days(self):
        for n in ("a", "b"):
            self._w(os.path.join(self.vault, "handoffs", f"2026-08-25-{n}-handoff.md"),
                    "---\ntitle: t\ntype: session-handoff\ndate: 2026-08-25\n"
                    "status: done\n---\nbody\n")
        problems = "\n".join(self.lint.lint_vault(self.vault))
        self.assertIn("NO-ROLLUP", problems)

    # ---- report mode ------------------------------------------------------
    def test_report_written_with_indented_findings(self):
        self._w(os.path.join(self.vault, "LIVE-STATE.md"),
                "# LS\n\n## Ancient (verified 2020-01-01)\n- x\n")
        report = os.path.join(self.vault, "machine", "memory-v2", "lint-report-latest.md")
        self.lint.write_report(report, [], self.lint.lint_vault(self.vault),
                               [], 1, self.memory)
        with open(report, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("  STALE-VERIFY", text, "findings must be two-space-indented "
                                              "(the bootstrap injector's contract)")

    def test_report_clean_when_clean(self):
        report = os.path.join(self.vault, "machine", "memory-v2", "lint-report-latest.md")
        self.lint.write_report(report, [], [], [], 1, self.memory)
        with open(report, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("✓ clean", text)
        self.assertNotIn("\n  ", text.split("---", 2)[2], "no indented finding lines")


if __name__ == "__main__":
    unittest.main()
