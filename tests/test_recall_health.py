"""recall usage logging + doctor's recall health line (2026-09-19 follow-ups).

Nothing ran `recall` for three weeks and nothing noticed: the index's mtime
looked fresh whenever anything rebuilt it. Usage is now logged (counts only)
and the doctor reads THAT.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

import conftest_paths


class TestUsage(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.vault = os.path.join(self.root, "vault")
        self.memory = os.path.join(self.root, "memory")
        os.makedirs(os.path.join(self.vault, "rgardin-ai", "reference"))
        os.makedirs(self.memory)
        with open(os.path.join(self.vault, "a.md"), "w") as f:
            f.write("Acme SECRETQUERYWORD notes\n")
        self.env = dict(os.environ, ENGRAM_VAULT=self.vault, ENGRAM_MEMORY=self.memory)
        self.cli = os.path.join(conftest_paths.ROOT, "scripts", "recall.py")
        self.log = os.path.join(self.vault, "machine", "metrics", "recall-usage.jsonl")

    def test_each_search_is_logged_without_its_query(self):
        subprocess.run([sys.executable, self.cli, "SECRETQUERYWORD", "notes"],
                       capture_output=True, text=True, env=self.env, check=True)
        with open(self.log) as f:
            raw = f.read()
        self.assertNotIn("SECRETQUERYWORD", raw, "a query can name a client: never log it")
        row = json.loads(raw.splitlines()[-1])
        self.assertEqual(row["hits"], 1)
        self.assertFalse(row["scoped"])

    def test_doctor_warns_when_the_log_shows_no_recent_searches(self):
        doctor = conftest_paths.load("scripts/doctor.py", "doctor_health")
        subprocess.run([sys.executable, self.cli, "--rebuild"], env=self.env,
                       capture_output=True, check=True)
        os.makedirs(os.path.dirname(self.log), exist_ok=True)
        with open(self.log, "w") as f:
            f.write(json.dumps({"ts": "2020-01-01T00:00:00"}) + "\n")
        rows = {r[0]: r for r in doctor.recall_health(self.vault)}
        self.assertEqual(rows["recall in use"][1], "warn",
                         "a fresh index must NOT read as usage")
        with open(self.log, "a") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
        rows = {r[0]: r for r in doctor.recall_health(self.vault)}
        self.assertIs(rows["recall in use"][1], True)

    def test_doctor_flags_a_vanished_sidecar(self):
        doctor = conftest_paths.load("scripts/doctor.py", "doctor_health2")
        subprocess.run([sys.executable, self.cli, "--rebuild"], env=self.env,
                       capture_output=True, check=True)
        open(os.path.join(self.vault, ".recall", "vectors.db"), "w").close()
        real = os.path.expanduser
        doctor.os.path.expanduser = lambda p: p.replace("~", self.root)
        try:
            rows = {r[0]: r for r in doctor.recall_health(self.vault)}
        finally:
            doctor.os.path.expanduser = real
        self.assertEqual(rows["recall meaning search"][1], "warn")
        self.assertIn("sidecar venv is gone", rows["recall meaning search"][2])


if __name__ == "__main__":
    unittest.main()
