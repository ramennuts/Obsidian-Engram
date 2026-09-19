"""Tests for recall's 2026-09-19 retrieval changes (patterns from NornicDB).

The load-bearing ones are the PRE-FILTER tests: filters used to run after a
`LIMIT limit*6` cut, so eligible docs ranked below the cut silently vanished
(measured live: `recall SOW` returned 6 of 8 with 16 eligible docs unreturned).
Each test here fails against the pre-change search().
"""
import json
import os
import sys
import tempfile
import textwrap
import unittest

import conftest_paths

REG = ("# reg\n\n```registry\nacme-co | client | Acme Co\n"
       "beta-llc | prospect | Beta LLC\n```\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.vault = os.path.join(self.root, "vault")
        self.memory = os.path.join(self.root, "memory")
        os.makedirs(os.path.join(self.vault, "rgardin-ai", "reference"))
        os.makedirs(os.path.join(self.vault, "handoffs"))
        os.makedirs(self.memory)
        self._w(os.path.join(self.vault, "rgardin-ai", "reference", "party-registry.md"), REG)

    def _w(self, path, body):
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)

    def _recall(self, **env):
        os.environ["ENGRAM_VAULT"] = self.vault
        os.environ["ENGRAM_MEMORY"] = self.memory
        for k, v in env.items():
            os.environ[k] = v
        r = conftest_paths.load("scripts/recall.py", "rank_recall")
        r.index(rebuild=True)
        return r


class TestFiltersRunBeforeTopK(Base):
    def test_party_docs_crowding_the_top_do_not_starve_internal_results(self):
        for i in range(60):   # far more than limit*6 strong party matches
            self._w(os.path.join(self.vault, f"acme{i}.md"),
                    "Acme Co " + "CROWDMARK " * 20 + "\n")
        for i in range(3):
            self._w(os.path.join(self.vault, f"internal{i}.md"),
                    "weak internal mention of CROWDMARK among many other words " * 5)
        r = self._recall()
        rows, sup = r.search("CROWDMARK", limit=8)
        self.assertEqual(sorted(os.path.basename(p) for p, *_ in rows),
                         ["internal0.md", "internal1.md", "internal2.md"])
        self.assertEqual(sup, 20, "hidden party docs within the candidate depth "
                                  "(max(limit*2, 20)) are counted, not every weak match")

    def test_suppressed_count_ignores_irrelevant_party_docs(self):
        for i in range(30):   # party docs sharing only one common query word
            self._w(os.path.join(self.vault, f"acme{i}.md"),
                    "Acme Co " + "filler text " * 200 + "backup\n")
        for i in range(25):
            self._w(os.path.join(self.vault, f"note{i}.md"),
                    "encrypted offsite backup copies ENCMARK\n")
        r = self._recall()
        rows, sup = r.search("encrypted offsite backup ENCMARK")
        self.assertEqual(len(rows), 8)
        self.assertEqual(sup, 0, "weak one-word party matches outside the candidate "
                                 "depth must not trip the warning")

    def test_topic_filter_does_not_starve_either(self):
        for i in range(60):
            self._w(os.path.join(self.vault, f"other{i}.md"), "TOPMARK " * 20)
        os.makedirs(os.path.join(self.vault, "sow"))
        self._w(os.path.join(self.vault, "sow", "the-one.md"), "a single TOPMARK here " * 3)
        r = self._recall()
        rows, _ = r.search("TOPMARK", topics="sow")
        self.assertEqual([os.path.basename(p) for p, *_ in rows], ["the-one.md"])

    def test_since_filter_does_not_starve_either(self):
        for i in range(60):
            self._w(os.path.join(self.vault, f"old{i}.md"),
                    "---\ndate: 2026-01-01\n---\n" + "SINCEMARK " * 20)
        self._w(os.path.join(self.vault, "new.md"),
                "---\ndate: 2026-09-01\n---\none SINCEMARK mention " * 2)
        r = self._recall()
        rows, _ = r.search("SINCEMARK", since="2026-08-01")
        self.assertEqual([os.path.basename(p) for p, *_ in rows], ["new.md"])


class TestOrMatching(Base):
    """AND-of-every-word matched almost nothing for a natural question
    (paraphrase Hit@5 0.03 on the 2026-09-19 eval)."""

    def test_a_question_matches_docs_missing_some_of_its_words(self):
        self._w(os.path.join(self.vault, "backup.md"), "The ORMARK backup lives in iCloud.\n")
        r = self._recall()
        rows, _ = r.search("where does the ORMARK offsite copy actually live")
        self.assertEqual([os.path.basename(p) for p, *_ in rows], ["backup.md"])

    def test_more_matching_terms_rank_higher(self):
        self._w(os.path.join(self.vault, "one.md"), "ORMARK alone\n")
        self._w(os.path.join(self.vault, "two.md"), "ORMARK with QUERYTWO\n")
        r = self._recall()
        rows, _ = r.search("ORMARK QUERYTWO")
        self.assertEqual(os.path.basename(rows[0][0]), "two.md")

    def test_stopwords_alone_do_not_match_everything(self):
        self._w(os.path.join(self.vault, "a.md"), "the what is it\n")
        r = self._recall()
        self.assertEqual(r._fts_quote("what is the ORMARK"), '"ORMARK"')
        self.assertEqual(r._fts_quote("what is the"), '"what" OR "is" OR "the"',
                         "an all-stopword query still searches rather than going empty")


class TestStaleDocs(Base):
    def setUp(self):
        super().setUp()
        self._w(os.path.join(self.vault, "sow-v1.md"),
                "---\nstatus: ⛔ SUPERSEDED 2026-08-24 by sow-v2, DO NOT SEND\n---\nSTALEMARK terms\n")
        self._w(os.path.join(self.vault, "sow-v2.md"),
                "---\nstatus: current — replaces the superseded v1\n---\nSTALEMARK terms\n")

    def test_superseded_is_hidden_and_counted(self):
        r = self._recall()
        stats = {}
        rows, _ = r.search("STALEMARK", stats=stats)
        self.assertEqual([os.path.basename(p) for p, *_ in rows], ["sow-v2.md"],
                         "a status that merely MENTIONS 'superseded' must stay visible")
        self.assertEqual(stats["stale_hidden"], 1)

    def test_include_stale_reveals_it(self):
        r = self._recall()
        rows, _ = r.search("STALEMARK", include_stale=True)
        self.assertEqual(len(rows), 2)

    def test_archive_folder_counts_as_stale(self):
        os.makedirs(os.path.join(self.vault, "archive"))
        self._w(os.path.join(self.vault, "archive", "x.md"), "ARCHMARK\n")
        r = self._recall()
        self.assertEqual(r.search("ARCHMARK")[0], [])
        self.assertEqual(len(r.search("ARCHMARK", include_stale=True)[0]), 1)


class TestRelatedLinks(Base):
    def test_links_are_found_and_resolved_by_basename(self):
        self._w(os.path.join(self.vault, "hub.md"), "LINKMARK see [[spoke]] and [x](sub/leaf.md)\n")
        self._w(os.path.join(self.vault, "spoke.md"), "spoke\n")
        os.makedirs(os.path.join(self.vault, "sub"))
        self._w(os.path.join(self.vault, "sub", "leaf.md"), "leaf\n")
        r = self._recall()
        hub = os.path.join(self.vault, "hub.md")
        got = {os.path.basename(p) for p in r.related([hub]).get(hub, [])}
        self.assertEqual(got, {"spoke.md", "leaf.md"})

    def test_a_link_is_never_a_side_door_into_a_party_doc(self):
        self._w(os.path.join(self.vault, "hub.md"), "LINKMARK see [[acme-terms]]\n")
        self._w(os.path.join(self.vault, "acme-terms.md"), "Acme Co pays SECRET\n")
        r = self._recall()
        hub = os.path.join(self.vault, "hub.md")
        self.assertEqual(r.related([hub]), {}, "default scope must not surface the party doc")
        self.assertEqual(len(r.related([hub], party="acme-co")[hub]), 1)
        self.assertEqual(r.related([hub], party="beta-llc"), {})

    def test_a_link_never_surfaces_a_stale_doc(self):
        self._w(os.path.join(self.vault, "hub.md"), "see [[old]]\n")
        self._w(os.path.join(self.vault, "old.md"), "---\nstatus: OBSOLETE\n---\nx\n")
        r = self._recall()
        self.assertEqual(r.related([os.path.join(self.vault, "hub.md")]), {})


class TestVectorFusion(Base):
    """The sidecar is stubbed: a tiny script that prints a canned ranking, so
    this runs in CI with no model. The real sidecar is exercised by
    evals/run_retrieval.py on the live corpus."""

    def _stub(self, payload, code=0):
        p = os.path.join(self.root, "stub.py")
        self._w(p, textwrap.dedent(f"""
            import json, sys
            print(json.dumps({json.dumps(payload)}))
            sys.exit({code})
        """))
        model = os.path.join(self.root, "model")
        os.makedirs(model, exist_ok=True)
        return {"ENGRAM_RECALL_VECTORS": "1", "ENGRAM_EMBED_PY": sys.executable,
                "ENGRAM_RECALL_SIDECAR": p, "ENGRAM_EMBED_MODEL": model}

    def tearDown(self):
        for k in ("ENGRAM_EMBED_PY", "ENGRAM_RECALL_SIDECAR", "ENGRAM_EMBED_MODEL"):
            os.environ.pop(k, None)
        os.environ["ENGRAM_RECALL_VECTORS"] = "0"

    def _docs(self):
        self._w(os.path.join(self.vault, "kw.md"), "VECMARK keyword doc\n")
        self._w(os.path.join(self.vault, "meaning.md"), "no shared words at all\n")
        self._w(os.path.join(self.vault, "acme.md"), "Acme Co confidential\n")

    def test_vector_only_hit_is_fused_in_and_party_docs_stay_out(self):
        self._docs()
        v = self.vault
        env = self._stub({"stale": 0, "results": [
            [os.path.join(v, "acme.md"), 0.99, "t\nAcme Co confidential"],
            [os.path.join(v, "meaning.md"), 0.9, "t\nno shared words at all"],
            [os.path.join(v, "kw.md"), 0.5, "t\nVECMARK keyword doc"]]})
        r = self._recall(**env)
        stats = {}
        rows, _ = r.search("VECMARK", stats=stats)
        names = [os.path.basename(p) for p, *_ in rows]
        self.assertEqual(stats["vectors"], "on")
        self.assertIn("meaning.md", names)
        self.assertNotIn("acme.md", names, "the vector branch must obey party isolation")
        self.assertEqual(names[0], "kw.md", "in both lists → ranks first under RRF")

    def test_sidecar_failure_fails_open_to_bm25(self):
        self._docs()
        r = self._recall(**self._stub({}, code=1))
        stats = {}
        rows, _ = r.search("VECMARK", stats=stats)
        self.assertEqual([os.path.basename(p) for p, *_ in rows], ["kw.md"])
        self.assertTrue(stats["vectors"].startswith("unavailable"))

    def test_garbage_output_fails_open_too(self):
        self._docs()
        env = self._stub({})
        self._w(env["ENGRAM_RECALL_SIDECAR"], "print('not json')\n")
        r = self._recall(**env)
        stats = {}
        rows, _ = r.search("VECMARK", stats=stats)
        self.assertEqual(len(rows), 1)
        self.assertTrue(stats["vectors"].startswith("unavailable"))


class TestSchemaUpgrade(Base):
    def test_an_old_cache_is_rebuilt_so_links_fill_in(self):
        self._w(os.path.join(self.vault, "hub.md"), "see [[spoke]]\n")
        self._w(os.path.join(self.vault, "spoke.md"), "x\n")
        r = self._recall()
        import sqlite3
        con = sqlite3.connect(r.DB)
        con.execute("DELETE FROM links")
        con.execute("UPDATE meta SET v='2' WHERE k='schema'")
        con.commit()
        con.close()
        r.index()                     # incremental; files unchanged
        hub = os.path.join(self.vault, "hub.md")
        self.assertIn(hub, r.related([hub]))


if __name__ == "__main__":
    unittest.main()
