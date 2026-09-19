"""The REAL recall_vec.update(), run in stdlib CI with a fake embedder.

Board 2026-09-19: every earlier vector test stubbed the whole sidecar, so the
cache logic that could leak a party's old text (must-fix 1) and wedge every
search behind a 60 s timeout (must-fix 2) never ran under test.
"""
import array
import os
import sqlite3
import tempfile
import time
import unittest

import conftest_paths

REG = "# reg\n\n```registry\nacme-co | client | Acme Co\n```\n"


class Fake:
    """4-d float32 vectors, no numpy. Optional hooks per embed() call."""

    def __init__(self, model_dir=None, fail_on=None, delay=0.0, during=None):
        self.calls, self.fail_on, self.delay, self.during = 0, fail_on, delay, during

    def embed(self, texts):
        self.calls += 1
        if self.fail_on and self.calls == self.fail_on:
            raise RuntimeError("embedder crashed")
        if self.during:
            self.during()
        time.sleep(self.delay)
        return [array.array("f", [1.0, 0.0, 0.0, 0.0]).tobytes() for _ in texts]


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.vault = os.path.join(self.root, "vault")
        self.memory = os.path.join(self.root, "memory")
        self.model = os.path.join(self.root, "model")
        for d in (os.path.join(self.vault, "rgardin-ai", "reference"), self.memory, self.model):
            os.makedirs(d)
        self._w(os.path.join(self.vault, "rgardin-ai", "reference", "party-registry.md"), REG)
        os.environ["ENGRAM_VAULT"] = self.vault
        os.environ["ENGRAM_MEMORY"] = self.memory
        self.recall = conftest_paths.load("scripts/recall.py", "vec_recall")
        self.rv = conftest_paths.load("scripts/recall_vec.py", "vec_sidecar")

    def _w(self, path, body, mtime=None):
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        if mtime:
            os.utime(path, (mtime, mtime))

    def _docs(self, n):
        t = time.time() - 1000
        for i in range(n):
            self._w(os.path.join(self.vault, f"d{i}.md"), f"doc {i} body text\n", t)

    def _update(self, **kw):
        kw.setdefault("embedder_factory", Fake)
        return self.rv.update(self.recall.DB, self.recall.VDB, self.model, **kw)

    def _chunked(self):
        con = sqlite3.connect(self.recall.VDB)
        got = {os.path.basename(r[0]) for r in con.execute("SELECT DISTINCT path FROM chunks")}
        con.close()
        return got


class TestCacheHonesty(Base):
    def test_a_changed_doc_left_unembedded_is_purged_not_served_stale(self):
        """1(ii): the reproduced leak. Acme text removed, tag cleared, doc left
        past the budget: its OLD chunk must be gone, not printed."""
        acme = os.path.join(self.vault, "d0.md")
        self._docs(3)
        self._w(acme, "Acme Co monthly retainer 9999\n", time.time() - 1000)
        self.recall.index(rebuild=True)
        self._update()
        self.assertIn("d0.md", self._chunked())
        self._w(acme, "retainer notes, no party here\n", time.time() - 500)
        self.recall.index()
        emb, left = self._update(budget=-1)            # budget already spent
        self.assertEqual(emb, 0)
        self.assertGreaterEqual(left, 1)
        self.assertNotIn("d0.md", self._chunked())

    def test_a_file_edited_after_indexing_is_skipped_not_mis_tagged(self):
        """1(i): the docs row describes older text than the file now holds."""
        self._docs(2)
        self.recall.index(rebuild=True)
        self._w(os.path.join(self.vault, "d1.md"), "Acme Co added later\n", time.time())
        emb, left = self._update()
        self.assertEqual((emb, left), (1, 1))
        self.assertEqual(self._chunked(), {"d0.md"})

    def test_index_purges_vectors_of_a_deleted_doc(self):
        """1(iv): a deleted doc's text must not wait for a meaning search."""
        self._docs(2)
        self.recall.index(rebuild=True)
        self._update()
        os.remove(os.path.join(self.vault, "d1.md"))
        self.recall.index()
        self.assertEqual(self._chunked(), {"d0.md"})


class TestNeverWedges(Base):
    def test_each_doc_persists_as_it_goes(self):
        """2: a crash (or a kill at the timeout) must keep finished work."""
        self._docs(8)
        self.recall.index(rebuild=True)
        with self.assertRaises(RuntimeError):
            self._update(embedder_factory=lambda m: Fake(fail_on=5))
        self.assertEqual(len(self._chunked()), 4)

    def test_budget_stops_inline_work_and_leaves_the_rest_absent(self):
        self._docs(10)
        self.recall.index(rebuild=True)
        emb, left = self._update(budget=0.25, embedder_factory=lambda m: Fake(delay=0.1))
        self.assertGreater(emb, 0)
        self.assertGreater(left, 0)
        self.assertEqual(emb + left, 10)
        self.assertEqual(len(self._chunked()), emb)

    def test_no_write_lock_is_held_while_embedding(self):
        """2: a second session must be able to write while this one embeds."""
        self._docs(3)
        self.recall.index(rebuild=True)
        self._update(embedder_factory=Fake)       # create the store first
        os.utime(os.path.join(self.vault, "d2.md"), (time.time(), time.time()))
        self.recall.index()
        results = []

        def other_session_writes():
            c = sqlite3.connect(self.recall.VDB, timeout=0, isolation_level=None)
            try:
                c.execute("BEGIN IMMEDIATE")
                c.execute("COMMIT")
                results.append("ok")
            except sqlite3.OperationalError as e:
                results.append(str(e))
            finally:
                c.close()
        self._update(embedder_factory=lambda m: Fake(during=other_session_writes))
        self.assertEqual(results, ["ok"])

    def test_a_busy_store_is_skipped_quickly(self):
        self._docs(3)
        self.recall.index(rebuild=True)
        self._update()
        os.utime(os.path.join(self.vault, "d2.md"), (time.time(), time.time()))
        self.recall.index()
        hold = sqlite3.connect(self.recall.VDB, isolation_level=None)
        hold.execute("BEGIN IMMEDIATE")
        try:
            t = time.monotonic()
            emb, left = self._update(busy_ms=100)
            self.assertLess(time.monotonic() - t, 5)
            self.assertEqual((emb, left), (0, 1))
        finally:
            hold.execute("ROLLBACK")
            hold.close()


class TestLeaseAndRebuild(Base):
    def test_a_held_lease_skips_inline_embedding_fast(self):
        """Follow-up 1: two sessions each burned every core for 15 s on the
        same backlog. The second must read what's stored and move on."""
        self._docs(3)
        self.recall.index(rebuild=True)
        self.assertTrue(self.rv._take_lease(self.recall.VDB))
        t = time.monotonic()
        emb, left, busy = self.rv.inline_update(self.recall.DB, self.recall.VDB, self.model,
                                                embedder_factory=Fake)
        self.assertLess(time.monotonic() - t, 1)
        self.assertEqual((emb, busy), (0, True))
        self.assertEqual(self._chunked(), set())

    def test_an_expired_lease_is_taken_over(self):
        self._docs(2)
        self.recall.index(rebuild=True)
        self.assertTrue(self.rv._take_lease(self.recall.VDB, now=time.time() - 3600))
        emb, _left, busy = self.rv.inline_update(self.recall.DB, self.recall.VDB, self.model,
                                                 embedder_factory=Fake)
        self.assertEqual((emb, busy), (2, False))

    def test_the_lease_is_released_after_the_update(self):
        self._docs(1)
        self.recall.index(rebuild=True)
        self.rv.inline_update(self.recall.DB, self.recall.VDB, self.model, embedder_factory=Fake)
        self.assertTrue(self.rv._take_lease(self.recall.VDB))

    def test_a_rebuild_still_purges_vectors_of_a_deleted_doc(self):
        """Follow-up 4: `known` was read after the rebuild's DELETE, so a doc
        deleted in that window never registered as gone."""
        self._docs(2)
        self.recall.index(rebuild=True)
        self._update()
        os.remove(os.path.join(self.vault, "d1.md"))
        self.recall.index(rebuild=True)
        self.assertEqual(self._chunked(), {"d0.md"})


if __name__ == "__main__":
    unittest.main()
