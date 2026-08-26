"""D4 board (2026-08-24): the STRAY-PROJECT-MEMORY detector + report durability.

Prevention (`autoMemoryEnabled: false`, Shane-only) removes the second store;
this detector is the durable half — parts of that subsystem are governed by
remote feature flags and by env overrides that can force it back ON, so no local
settings check is a permanent guarantee.

Fixture slug names are SYNTHETIC. Never copy real slug names in — this repo has
a public remote.
"""
import json
import os
import tempfile
import unittest

import conftest_paths


def lint_mod(memory=None, vault=None):
    if memory:
        os.environ["ENGRAM_MEMORY"] = memory
    if vault:
        os.environ["ENGRAM_VAULT"] = vault
    return conftest_paths.load("scripts/memory_lint.py", "d4_lint_reload")


class TestProjectsDetector(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.projects = os.path.join(self.root, "projects")
        self.outside = os.path.join(self.root, "outside")
        os.makedirs(self.projects)
        os.makedirs(self.outside)
        self.settings = os.path.join(self.root, "settings.json")
        self._settings(False)
        self.lint = lint_mod()
        self.lint.SETTINGS_PATH = self.settings

    def _settings(self, enabled):
        body = {} if enabled is None else {"autoMemoryEnabled": enabled}
        with open(self.settings, "w") as f:
            json.dump(body, f)

    def _slug(self, name, files=(), sub=None):
        mem = os.path.join(self.projects, name, "memory")
        target = os.path.join(mem, sub) if sub else mem
        os.makedirs(target, exist_ok=True)
        for fn in files:
            with open(os.path.join(target, fn), "w") as f:
                f.write("SLUGBODYCANARY durable fact\n")
        return mem

    # T1 — quiet against today's real baseline (4 empty dirs)
    def test_empty_memory_dirs_are_silent(self):
        for n in ("alpha", "beta", "gamma", "delta"):
            self._slug(n)
        self.assertEqual([p for p in self.lint.lint_projects(self.projects)
                          if p.startswith("STRAY")], [])

    # T2 — one stray file detected, aggregated
    def test_one_stray_file_is_detected(self):
        self._slug("alpha", files=["fact.md"])
        found = [p for p in self.lint.lint_projects(self.projects)
                 if p.startswith("STRAY-PROJECT-MEMORY ")]
        self.assertEqual(len(found), 1)
        self.assertIn("1 file(s)", found[0])

    # T3 — THE leak guard, asserted on the WRITTEN REPORT FILE
    def test_report_file_never_contains_slug_names_or_bodies(self):
        self._slug("-", files=["a.md"])                       # 1-char slug
        self._slug("-Users-rgardin-clients-acmecorp", files=["b.md"])
        problems = self.lint.lint_projects(self.projects)
        report = os.path.join(self.root, "report.md")
        self.lint.write_report(report, [], [], problems, 0, self.root)
        with open(report, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("STRAY-PROJECT-MEMORY", text)
        self.assertNotIn("acmecorp", text, "a slug name reached the report")
        self.assertNotIn("clients", text)
        self.assertNotIn("SLUGBODYCANARY", text, "a file BODY reached the report")
        self.assertNotIn("a.md", text)

    # T4 — cross-module invariant: the finding must survive the 3-line window
    def test_stray_finding_reaches_the_injected_flag_line(self):
        """Seeded with the LIVE backlog shape (3 STALE-VERIFY + 4 OVERSIZED).
        Append-order puts the stray finding 8th; _lint_flags injects lines[:3]."""
        vault = os.path.join(self.root, "vault")
        os.makedirs(os.path.join(vault, "machine", "memory-v2"))
        backlog = ([f"STALE-VERIFY LIVE-STATE 'S{i}' verified 2026-07-18 (> 14d)"
                    for i in range(3)]
                   + [f"OVERSIZED-ITEM queue item 'Q{i}' is 9000 chars" for i in range(4)])
        self._slug("alpha", files=["fact.md"])
        problems = self.lint.lint_projects(self.projects)
        report = os.path.join(vault, "machine", "memory-v2", "lint-report-latest.md")
        self.lint.write_report(report, [], backlog, problems, 0, self.root)

        os.environ["ENGRAM_VAULT"] = vault
        hook = conftest_paths.load("hooks/session_start_v2.py", "d4_hook_reload")
        hook.LINT_REPORT = report
        flags = hook._lint_flags()
        self.assertIsNotNone(flags)
        self.assertIn("STRAY-PROJECT-MEMORY", flags,
                      "the stray finding was buried behind the stale backlog")

    # T5 — an ESCAPING symlink is reported, never skipped
    def test_escaping_memory_symlink_is_reported_not_skipped(self):
        os.makedirs(os.path.join(self.projects, "alpha"))
        os.symlink(self.outside, os.path.join(self.projects, "alpha", "memory"))
        found = "\n".join(self.lint.lint_projects(self.projects))
        self.assertIn("STRAY-PROJECT-MEMORY-ESCAPE", found)

    # T6 — recursive: the session-log subtree counts
    def test_nested_log_files_are_counted(self):
        self._slug("alpha", files=["note.md"], sub="logs/2026/08/25")
        found = [p for p in self.lint.lint_projects(self.projects)
                 if p.startswith("STRAY-PROJECT-MEMORY ")]
        self.assertTrue(found, "a non-recursive scan would miss logs/")

    # T7 — a mis-pointed root is LOUD, never zero findings
    def test_missing_projects_root_is_loud(self):
        found = self.lint.lint_projects(os.path.join(self.root, "nope"))
        self.assertTrue(any(p.startswith("LINT-CONFIG") for p in found))

    # T9 — the liveness check notices prevention lapsing
    def test_prevention_off_is_flagged(self):
        self._settings(True)
        self.assertTrue(any(p.startswith("PREVENTION-OFF")
                            for p in self.lint.lint_projects(self.projects)))
        self._settings(None)          # key absent entirely
        self.assertTrue(any(p.startswith("PREVENTION-OFF")
                            for p in self.lint.lint_projects(self.projects)))
        self._settings(False)
        self.assertFalse(any(p.startswith("PREVENTION-OFF")
                             for p in self.lint.lint_projects(self.projects)))


class TestReportDurability(unittest.TestCase):
    """C1/M-5: the report is this machine's only memory-hygiene alarm, and it is
    authored BY the linter — so the linter dying is the one failure it could
    never report. Both stale-report holes are closed here."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.lint = lint_mod()

    # T8 — a crashing pass becomes a finding; the report is still written
    def test_crash_becomes_a_finding_not_a_dead_report(self):
        def boom():
            raise PermissionError("chmod 000")
        out = self.lint.safe("lint_memory", boom)
        self.assertTrue(out[0].startswith("LINT-CRASH"))
        report = os.path.join(self.root, "r.md")
        self.lint.write_report(report, out, ["STALE-VERIFY something"], [], 0, self.root)
        with open(report, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("LINT-CRASH", text)
        self.assertIn("STALE-VERIFY", text, "other passes' findings survive")
        self.assertLess(text.index("LINT-CRASH"), text.index("STALE-VERIFY"),
                        "a crash must outrank routine hygiene")

    # M-5 — a missing memory dir must still WRITE a report
    def test_missing_memory_dir_still_writes_a_report(self):
        import subprocess
        import sys
        report = os.path.join(self.root, "r2.md")
        r = subprocess.run(
            [sys.executable, os.path.join(conftest_paths.ROOT, "scripts",
                                          "memory_lint.py"),
             "--dir", os.path.join(self.root, "does-not-exist"),
             "--report", report],
            capture_output=True, text=True, timeout=60)
        self.assertNotEqual(r.returncode, 0,
                            "a config failure must still alarm the compactor")
        self.assertTrue(os.path.exists(report),
                        "yesterday's report would have been served as today's")
        with open(report, encoding="utf-8") as f:
            self.assertIn("LINT-CONFIG", f.read())


if __name__ == "__main__":
    unittest.main()


class TestHookDrift(unittest.TestCase):
    """`schg` on ~/.claude/hooks/*.py freezes guard CODE but not guard
    REGISTRATION — and settings.json became mutable on 2026-08-25 so Claude Code
    could persist its own settings. Unregistering a guard is as effective as
    deleting it, so prevention became detection here, deliberately."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.lint = lint_mod()
        self.settings = os.path.join(self.root, "settings.json")
        self.baseline = os.path.join(self.root, "baseline.json")
        self._write({
            "hooks": {
                "PreToolUse": [{"matcher": "Bash", "hooks": [
                    {"type": "command", "command": "python3 /h/live-guard.py"},
                    {"type": "command", "command": "python3 /h/file-guard.py"}]}],
                "SessionStart": [{"hooks": [
                    {"type": "command", "command": "python3 /h/session-start.py"}]}],
            },
            "permissions": {"deny": ["Edit(/x/settings.json)", "Read(/x/.ssh/**)"]},
        })
        with open(self.baseline, "w") as f:
            json.dump(self.lint._guard_fingerprint(self.settings), f)

    def _write(self, cfg):
        with open(self.settings, "w") as f:
            json.dump(cfg, f)

    def _run(self):
        return self.lint.lint_hooks(self.settings, self.baseline)

    def test_unchanged_registration_is_silent(self):
        self.assertEqual(self._run(), [])

    def test_cosmetic_reorder_does_not_fire(self):
        """An alarm that cries on formatting gets ignored, and then the real one
        gets ignored too."""
        with open(self.settings) as f:
            cfg = json.load(f)
        cfg["permissions"]["deny"].reverse()
        cfg["hooks"]["PreToolUse"][0]["hooks"].reverse()
        self._write(cfg)
        self.assertEqual(self._run(), [])

    def test_unregistered_guard_is_caught(self):
        with open(self.settings) as f:
            cfg = json.load(f)
        cfg["hooks"]["PreToolUse"][0]["hooks"] = [
            h for h in cfg["hooks"]["PreToolUse"][0]["hooks"]
            if "file-guard" not in h["command"]]
        self._write(cfg)
        found = "\n".join(self._run())
        self.assertIn("HOOK-DRIFT", found)
        self.assertIn("file-guard.py", found)
        self.assertIn("DISAPPEARED", found)

    def test_removed_deny_rule_is_caught(self):
        with open(self.settings) as f:
            cfg = json.load(f)
        cfg["permissions"]["deny"] = ["Read(/x/.ssh/**)"]
        self._write(cfg)
        self.assertIn("HOOK-DRIFT", "\n".join(self._run()))

    def test_impostor_script_swap_is_caught_both_ways(self):
        with open(self.settings) as f:
            cfg = json.load(f)
        cfg["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = "python3 /tmp/evil.py"
        self._write(cfg)
        found = "\n".join(self._run())
        self.assertIn("DISAPPEARED", found)
        self.assertIn("appeared", found)

    def test_new_unexpected_hook_is_caught(self):
        with open(self.settings) as f:
            cfg = json.load(f)
        cfg["hooks"]["PreToolUse"].append(
            {"matcher": "Bash", "hooks": [{"type": "command",
                                           "command": "python3 /tmp/exfil.py"}]})
        self._write(cfg)
        self.assertIn("exfil.py", "\n".join(self._run()))

    def test_missing_baseline_is_loud_not_silent(self):
        out = self.lint.lint_hooks(self.settings, os.path.join(self.root, "nope.json"))
        self.assertTrue(any(p.startswith("LINT-CONFIG") for p in out))
        self.assertIn("UNVERIFIED", "\n".join(out))

    def test_unreadable_settings_is_loud_not_silent(self):
        out = self.lint.lint_hooks(os.path.join(self.root, "gone.json"), self.baseline)
        self.assertTrue(any(p.startswith("LINT-CONFIG") for p in out))

    def test_drift_outranks_hygiene_in_the_report(self):
        """The bootstrap injects only the first three finding lines."""
        with open(self.settings) as f:
            cfg = json.load(f)
        cfg["hooks"]["PreToolUse"][0]["hooks"] = []
        self._write(cfg)
        backlog = [f"STALE-VERIFY LIVE-STATE 'S{i}' verified 2026-07-18" for i in range(3)]
        report = os.path.join(self.root, "r.md")
        self.lint.write_report(report, [], backlog, self._run(), 0, self.root)
        with open(report, encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.startswith("  ")]
        self.assertTrue(lines[0].startswith("HOOK-DRIFT"),
                        f"drift must lead the report, got: {lines[0][:60]}")


class TestNoPartyNamesInReport(unittest.TestCase):
    """Board 2026-08-25: the lint report is recall-indexed AND is chunk 1 of the
    compactor's outbound bundle, and it was republishing a company's legal name
    and its owner's name verbatim from queue headings. Hash, never name."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.vault = os.path.join(self.root, "vault")
        os.makedirs(os.path.join(self.vault, "handoffs"))
        self.lint = lint_mod(vault=self.vault)

    def _w(self, rel, body):
        p = os.path.join(self.vault, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(body)

    def test_oversized_item_never_prints_the_heading(self):
        self._w("build-queue.md",
                "# q\n\n## Active items\n\n### PROSPECT: Acme Widgets, Inc. "
                "(owner Jane Doe) — discovery\n"
                + ("- accreted narrative line.\n" * 300) + "\n## Blocked\n")
        found = "\n".join(self.lint.lint_vault(self.vault))
        self.assertIn("OVERSIZED-ITEM", found)
        self.assertNotIn("Acme Widgets", found, "a company name reached the report")
        self.assertNotIn("Jane Doe", found, "an owner's name reached the report")
        self.assertIn("item #1", found, "must stay actionable — position kept")

    def test_handoff_contract_never_prints_the_topic_slug(self):
        self._w("handoffs/2026-08-25-acme-widgets-pricing-handoff.md",
                "---\ntitle: t\ntype: session-handoff\ndate: 2026-08-25\n---\nbody\n")
        found = "\n".join(self.lint.lint_vault(self.vault))
        self.assertIn("HANDOFF-CONTRACT", found)
        self.assertNotIn("acme-widgets", found)
        self.assertIn("2026-08-25", found, "the date stays — it is how you find it")

    def test_ids_are_stable_so_findings_correlate_across_days(self):
        a = self.lint._slug_id("PROSPECT: Acme Widgets, Inc.")
        b = self.lint._slug_id("PROSPECT: Acme Widgets, Inc.")
        self.assertEqual(a, b)
        self.assertNotEqual(a, self.lint._slug_id("PROSPECT: Other Co"))
