"""Tests for recall.py: indexing, search, incrementality — and ISOLATION.

The isolation test is the load-bearing one: the global recall index must be
structurally unable to contain anything outside the vault+memory allow-list
(client workspaces, ~/personal). It asserts by planting a marked file outside
the allow-list and proving it can never be found.
"""
import os
import tempfile
import unittest

import conftest_paths


def load_recall(vault, memory):
    os.environ["ENGRAM_VAULT"] = vault
    os.environ["ENGRAM_MEMORY"] = memory
    return conftest_paths.load("scripts/recall.py", "engram_recall_reload")


class TestRecall(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.vault = os.path.join(self.root, "vault")
        self.memory = os.path.join(self.root, "memory")
        self.clients = os.path.join(self.root, "clients", "acme")  # OUTSIDE allow-list
        for d in (self.vault, self.memory, self.clients,
                  os.path.join(self.vault, "sub")):
            os.makedirs(d, exist_ok=True)
        self._w(os.path.join(self.vault, "note.md"),
                "---\ntitle: Zoho decision\ndate: 2026-08-23\nstatus: done\n---\n"
                "We chose ZOHOMARK Standard, three seats.\n")
        self._w(os.path.join(self.vault, "sub", "deep.md"),
                "# deep\n\nThe DEEPMARK fact lives here.\n")
        self._w(os.path.join(self.memory, "fact.md"),
                "---\nname: fact\ndescription: d\ntype: reference\n---\nMEMMARK value.\n")
        self._w(os.path.join(self.clients, "secret.md"),
                "# client\n\nCLIENTSECRETMARK must never index.\n")
        self.recall = load_recall(self.vault, self.memory)
        self.recall.index(rebuild=True)

    def _w(self, path, body):
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)

    def test_finds_vault_and_memory_content(self):
        self.assertTrue(self.recall.search("ZOHOMARK")[0])
        self.assertTrue(self.recall.search("DEEPMARK")[0])
        self.assertTrue(self.recall.search("MEMMARK")[0])

    def test_isolation_client_content_is_never_indexed(self):
        self.assertEqual(self.recall.search("CLIENTSECRETMARK")[0], [])
        # …and not because search failed: the term IS on disk in this test tree.
        import sqlite3
        con = sqlite3.connect(self.recall.DB)
        paths = [r[0] for r in con.execute("SELECT path FROM docs")]
        con.close()
        self.assertTrue(all("clients" not in p for p in paths),
                        f"client path leaked into index: {paths}")

    def test_metadata_rides_along(self):
        hits, _ = self.recall.search("ZOHOMARK")
        path, title, date, status, snip = hits[0]
        self.assertEqual(title, "Zoho decision")
        self.assertEqual(date, "2026-08-23")
        self.assertEqual(status, "done")

    def test_incremental_update_and_delete(self):
        p = os.path.join(self.vault, "note2.md")
        self._w(p, "# n2\n\nFRESHMARK appears.\n")
        self.recall.index()
        self.assertTrue(self.recall.search("FRESHMARK")[0])
        os.remove(p)
        self.recall.index()
        self.assertEqual(self.recall.search("FRESHMARK")[0], [])

    def test_query_with_fts_hostile_characters(self):
        # hyphens/apostrophes/colons must not raise fts5 syntax errors
        for q in ("cost-first won't:", "a - b's", "(weird) AND syntax"):
            self.recall.search(q)  # must not raise

    def test_since_filter(self):
        hits, _ = self.recall.search("ZOHOMARK", since="2026-09-01")
        self.assertEqual(hits, [])


class TestPartyScoping(unittest.TestCase):
    """Board 2026-08-25: one `recall "pricing"` used to return one party's
    economics while working for another. Suppression is default; exposure is a
    deliberate keystroke."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.vault = os.path.join(self.root, "vault")
        self.memory = os.path.join(self.root, "memory")
        os.makedirs(os.path.join(self.vault, "rgardin-ai", "reference"))
        os.makedirs(self.memory)
        self._w(os.path.join(self.vault, "rgardin-ai", "reference",
                             "party-registry.md"),
                "# reg\n\n```registry\nacme-co | client | Acme Co | Jane Roe\n"
                "beta-llc | prospect | Beta LLC\nours | internal | Ourselves\n```\n")
        self._w(os.path.join(self.vault, "a.md"), "Acme Co pays RATEMARK per year.\n")
        self._w(os.path.join(self.vault, "b.md"), "Beta LLC quoted RATEMARK too.\n")
        self._w(os.path.join(self.vault, "c.md"), "Ourselves: RATEMARK is undecided.\n")
        self._w(os.path.join(self.vault, "d.md"), "Generic note about RATEMARK policy.\n")
        self.recall = load_recall(self.vault, self.memory)
        self.recall.index(rebuild=True)

    def _w(self, p, body):
        with open(p, "w") as f:
            f.write(body)

    def test_default_suppresses_party_results_and_counts_them(self):
        rows, suppressed = self.recall.search("RATEMARK")
        paths = [os.path.basename(p) for p, *_ in rows]
        self.assertEqual(suppressed, 2, "both client/prospect docs suppressed")
        self.assertNotIn("a.md", paths)
        self.assertNotIn("b.md", paths)
        self.assertIn("d.md", paths, "non-party results still returned")
        self.assertIn("c.md", paths, "internal parties are NOT suppressed")

    def test_scoping_to_one_party_shows_only_that_one(self):
        rows, suppressed = self.recall.search("RATEMARK", party="acme-co")
        paths = [os.path.basename(p) for p, *_ in rows]
        self.assertIn("a.md", paths)
        self.assertNotIn("b.md", paths, "the OTHER party stays suppressed")
        self.assertEqual(suppressed, 1)

    def test_all_parties_is_a_deliberate_override(self):
        rows, suppressed = self.recall.search("RATEMARK", all_parties=True)
        paths = [os.path.basename(p) for p, *_ in rows]
        self.assertEqual(suppressed, 0)
        for f in ("a.md", "b.md", "c.md", "d.md"):
            self.assertIn(f, paths)

    def test_registry_is_never_itself_a_search_result(self):
        rows, _ = self.recall.search("registry", all_parties=True)
        self.assertTrue(all("party-registry" not in p for p, *_ in rows))

    def test_fails_open_when_the_registry_is_missing(self):
        os.remove(os.path.join(self.vault, "rgardin-ai", "reference",
                               "party-registry.md"))
        r = load_recall(self.vault, self.memory)
        r.index(rebuild=True)
        rows, suppressed = r.search("RATEMARK")
        self.assertEqual(suppressed, 0, "no registry → behave exactly as before")
        self.assertEqual(len(rows), 4)

    def test_phrase_matching_not_token_matching(self):
        """The live party names start with common English words; a token matcher
        hit 148/377 docs where the phrase matcher hits 59."""
        self._w(os.path.join(self.vault, "e.md"),
                "The beta build shifted; acme practices are generic. RATEMARK.\n")
        self.recall.index()
        rows, _ = self.recall.search("RATEMARK")
        self.assertIn("e.md", [os.path.basename(p) for p, *_ in rows],
                      "a token-level matcher would have suppressed this")

class TestRegistryChangeRetags(unittest.TestCase):
    """Party tags are computed at INDEX time. Adding a party later must retag
    already-indexed documents, or the new party gets zero suppression on all
    existing content — silently (verification round)."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.vault = os.path.join(self.root, "vault")
        self.memory = os.path.join(self.root, "memory")
        os.makedirs(os.path.join(self.vault, "rgardin-ai", "reference"))
        os.makedirs(self.memory)
        self.reg = os.path.join(self.vault, "rgardin-ai", "reference",
                                "party-registry.md")
        self._w(self.reg, "# r\n\n```registry\nacme-co | client | Acme Co\n```\n")
        self._w(os.path.join(self.vault, "later.md"),
                "Gamma Group agreed LATERMARK terms.\n")

    def _w(self, p, body):
        with open(p, "w") as f:
            f.write(body)

    def test_adding_a_party_retags_existing_documents(self):
        r = load_recall(self.vault, self.memory)
        r.index(rebuild=True)
        rows, sup = r.search("LATERMARK")
        self.assertEqual(sup, 0, "not yet a registered party")
        self.assertEqual(len(rows), 1)
        # register the party AFTER the doc was already indexed and unchanged
        self._w(self.reg, "# r\n\n```registry\nacme-co | client | Acme Co\n"
                          "gamma | client | Gamma Group\n```\n")
        r2 = load_recall(self.vault, self.memory)
        r2.index()                       # incremental — the file has NOT changed
        rows, sup = r2.search("LATERMARK")
        self.assertEqual(sup, 1, "the newly-registered party must be suppressed")
        self.assertEqual(rows, [])

if __name__ == "__main__":
    unittest.main()
