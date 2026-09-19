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


class TestInputHandling(Base):
    def test_comma_joined_party_is_refused_not_matched(self):
        """`--party a,b` string-equalled a two-party doc's tag and exposed it
        (board 2026-09-19 AUDIT-A #2); main's set logic kept it hidden."""
        self._w(os.path.join(self.vault, "both.md"), "Acme Co and Beta LLC: BOTHMARK\n")
        r = self._recall()
        with self.assertRaises(ValueError):
            r.search("BOTHMARK", party="acme-co,beta-llc")

    def test_cli_refuses_a_comma_or_unregistered_party(self):
        import subprocess
        self._w(os.path.join(self.vault, "both.md"), "Acme Co and Beta LLC: BOTHMARK\n")
        cli = os.path.join(conftest_paths.ROOT, "scripts", "recall.py")
        env = dict(os.environ, ENGRAM_VAULT=self.vault, ENGRAM_MEMORY=self.memory)
        for bad in ("acme-co,beta-llc", "acme-typo"):
            p = subprocess.run([sys.executable, cli, "--party", bad, "BOTHMARK"],
                               capture_output=True, text=True, env=env)
            self.assertEqual(p.returncode, 2, bad)
            self.assertNotIn("both.md", p.stdout)
        ok = subprocess.run([sys.executable, cli, "--party", "acme-co", "BOTHMARK"],
                            capture_output=True, text=True, env=env)
        self.assertEqual(ok.returncode, 0)

    def test_a_dash_leading_query_reaches_the_sidecar_as_a_query(self):
        """No `--` before the query let "-x"/"--vdb=…" parse as sidecar options."""
        seen = os.path.join(self.root, "argv.json")
        stub = os.path.join(self.root, "stub.py")
        self._w(stub, "import json, sys\n"
                      f"json.dump(sys.argv[1:], open({seen!r}, 'w'))\n"
                      "print(json.dumps({'stale': 0, 'results': []}))\n")
        os.makedirs(os.path.join(self.root, "model"))
        try:
            r = self._recall(ENGRAM_RECALL_VECTORS="1", ENGRAM_EMBED_PY=sys.executable,
                             ENGRAM_RECALL_SIDECAR=stub,
                             ENGRAM_EMBED_MODEL=os.path.join(self.root, "model"))
            r.search("--vdb=/tmp/elsewhere")
            with open(seen) as f:
                argv = json.load(f)
            self.assertEqual(argv[-2:], ["--", "--vdb=/tmp/elsewhere"])
        finally:
            for k in ("ENGRAM_EMBED_PY", "ENGRAM_RECALL_SIDECAR", "ENGRAM_EMBED_MODEL"):
                os.environ.pop(k, None)
            os.environ["ENGRAM_RECALL_VECTORS"] = "0"


class TestHonestNoRecord(Base):
    """Board 2026-09-19 #6 + eval: OR matching and meaning search both find
    SOMETHING for a question the vault can't answer. The output must say so."""

    def test_a_term_no_doc_contains_is_reported(self):
        self._w(os.path.join(self.vault, "v.md"), "vendor contract notes\n")
        r = self._recall()
        stats = {}
        rows, _ = r.search("which vendor contract covers the forklifts", stats=stats)
        self.assertTrue(rows, "OR matching still returns the vendor doc")
        self.assertEqual(stats["missing_terms"], ["covers", "forklifts"])
        self.assertEqual(stats["coverage"][rows[0][0]], (2, 4))

    def test_missing_terms_never_reveal_a_word_only_party_docs_hold(self):
        self._w(os.path.join(self.vault, "v.md"), "vendor contract notes\n")
        self._w(os.path.join(self.vault, "a.md"), "Acme Co ZEBRAWORD pricing\n")
        r = self._recall()
        stats = {}
        r.search("vendor ZEBRAWORD", stats=stats)
        self.assertEqual(stats["missing_terms"], ["ZEBRAWORD"],
                         "default scope: the party doc's word counts as absent")
        stats = {}
        r.search("vendor ZEBRAWORD", party="acme-co", stats=stats)
        self.assertEqual(stats["missing_terms"], [])

    def test_cli_labels_meaning_only_results_when_no_keyword_hits(self):
        import subprocess
        self._w(os.path.join(self.vault, "m.md"), "entirely different words\n")
        stub = os.path.join(self.root, "stub.py")
        mt = os.stat(os.path.join(self.vault, "m.md")).st_mtime
        self._w(stub, "import json\nprint(json.dumps({'stale': 0, 'results': "
                      f"[[{os.path.join(self.vault, 'm.md')!r}, 0.4, 't\\nx', {mt!r}]]}}))\n")
        os.makedirs(os.path.join(self.root, "model"))
        env = dict(os.environ, ENGRAM_VAULT=self.vault, ENGRAM_MEMORY=self.memory,
                   ENGRAM_RECALL_VECTORS="1", ENGRAM_EMBED_PY=sys.executable,
                   ENGRAM_RECALL_SIDECAR=stub,
                   ENGRAM_EMBED_MODEL=os.path.join(self.root, "model"))
        out = subprocess.run([sys.executable, os.path.join(conftest_paths.ROOT, "scripts",
                                                           "recall.py"), "QQNOTHING"],
                             capture_output=True, text=True, env=env).stdout
        self.assertIn("no keyword hits", out)
        self.assertIn("meaning match only", out)


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

    def _mt(self, name):
        return os.stat(os.path.join(self.vault, name)).st_mtime

    def test_a_chunk_cut_from_other_text_is_never_shown(self):
        """Must-fix 1(iii): the chunk's mtime must equal the LIVE docs row's,
        or its text belongs to a version the party tag no longer describes."""
        self._docs()
        v = self.vault
        env = self._stub({"stale": 0, "results": [
            [os.path.join(v, "meaning.md"), 0.9, "t\nOLD TEXT Acme Co 9999",
             self._mt("meaning.md") - 100]]})
        r = self._recall(**env)
        rows, _ = r.search("VECMARK")
        self.assertNotIn("meaning.md", [os.path.basename(p) for p, *_ in rows])

    def test_vanished_sidecar_is_announced_when_it_was_installed(self):
        self._docs()
        env = self._stub({"stale": 0, "results": []})
        env["ENGRAM_EMBED_PY"] = os.path.join(self.root, "gone", "python")
        r = self._recall(**env)
        stats = {}
        r.search("VECMARK", stats=stats)
        self.assertEqual(stats["vectors"], "not installed", "never installed: stay quiet")
        os.makedirs(os.path.dirname(r.VDB), exist_ok=True)
        open(r.VDB, "w").close()
        stats = {}
        r.search("VECMARK", stats=stats)
        self.assertEqual(stats["vectors"], "missing", "was installed: must be announced")

    def _docs(self):
        self._w(os.path.join(self.vault, "kw.md"), "VECMARK keyword doc\n")
        self._w(os.path.join(self.vault, "meaning.md"), "no shared words at all\n")
        self._w(os.path.join(self.vault, "acme.md"), "Acme Co confidential\n")

    def test_vector_only_hit_is_fused_in_and_party_docs_stay_out(self):
        self._docs()
        v = self.vault
        env = self._stub({"stale": 0, "results": [
            [os.path.join(v, "acme.md"), 0.99, "t\nAcme Co confidential", self._mt("acme.md")],
            [os.path.join(v, "meaning.md"), 0.9, "t\nno shared words at all",
             self._mt("meaning.md")],
            [os.path.join(v, "kw.md"), 0.5, "t\nVECMARK keyword doc", self._mt("kw.md")]]})
        r = self._recall(**env)
        stats = {}
        rows, _ = r.search("VECMARK", stats=stats)
        names = [os.path.basename(p) for p, *_ in rows]
        self.assertEqual(stats["vectors"], "on")
        self.assertIn("meaning.md", names)
        self.assertEqual(stats["meaning_only"], {os.path.join(v, "meaning.md")})
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
