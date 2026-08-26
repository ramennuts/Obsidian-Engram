"""Board 2026-08-25 — shared-store party isolation.

The finding: the company's own shared stores (~/memory, ~/vault) grew into a
second store nobody put a lock on. Three channels carried party identity to
every session: the always-injected index, the FTS search, and the bootstrap.
A fourth sent it off the machine. These pin all four.
"""
import os
import re
import tempfile
import unittest

import conftest_paths

REGISTRY = ("# reg\n\n```registry\n"
            "acme-co | client | Acme Co | Jane Roe\n"
            "beta-llc | prospect | Beta LLC | Bo Beta\n"
            "ours | internal | Ourselves\n```\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.vault = os.path.join(self.root, "vault")
        self.memory = os.path.join(self.root, "memory")
        os.makedirs(os.path.join(self.vault, "handoffs"))
        os.makedirs(os.path.join(self.vault, "rgardin-ai", "reference"))
        os.makedirs(self.memory)
        self._w(os.path.join(self.vault, "rgardin-ai", "reference",
                             "party-registry.md"), REGISTRY)
        self._w(os.path.join(self.vault, "LIVE-STATE.md"), "# LS\n\n## Services\n- up\n")
        os.environ["ENGRAM_VAULT"] = self.vault
        os.environ["ENGRAM_MEMORY"] = self.memory

    def _w(self, p, body):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(body)

    def _handoff(self, name, body):
        self._w(os.path.join(self.vault, "handoffs", name), body)


class TestBootstrapDegradation(Base):
    def _hook(self):
        return conftest_paths.load("hooks/session_start_v2.py", "party_hook")

    def test_party_brief_is_shown_by_name_only(self):
        self._handoff("2026-08-25-acme-work-handoff.md",
                      "---\ntitle: t\ntype: session-handoff\ndate: 2026-08-25\n---\n"
                      "# h\n\n## Open items / next steps\n"
                      "- Acme Co agreed to SECRETRATE per year.\n")
        self._w(os.path.join(self.vault, "build-queue.md"),
                "# q\n\n## Active items\n### ordinary item\n- x.\n\n## Blocked\n")
        ctx, _ = self._hook().assemble("startup")
        self.assertIn("belongs to party `acme-co`", ctx)
        self.assertNotIn("SECRETRATE", ctx, "the party's terms must not broadcast")

    def test_non_party_brief_is_untouched(self):
        self._handoff("2026-08-25-internal-handoff.md",
                      "---\ntitle: t\ntype: session-handoff\ndate: 2026-08-25\n---\n"
                      "# h\n\n## Open items / next steps\n- KEEPTHISMARK ordinary work.\n")
        self._w(os.path.join(self.vault, "build-queue.md"),
                "# q\n\n## Active items\n### ordinary\n- x.\n\n## Blocked\n")
        ctx, _ = self._hook().assemble("startup")
        self.assertIn("KEEPTHISMARK", ctx, "ordinary continuity must not regress")

    def test_party_queue_headers_degrade_but_stay_countable(self):
        self._handoff("2026-08-25-internal-handoff.md",
                      "---\ntitle: t\ntype: session-handoff\ndate: 2026-08-25\n---\n# h\n\n"
                      "## Open items / next steps\n- fine.\n")
        self._w(os.path.join(self.vault, "build-queue.md"),
                "# q\n\n## Active items\n### PROSPECT Beta LLC — owner Bo Beta, QUEUESECRET\n"
                "- x.\n\n### plain internal item\n- y.\n\n## Blocked\n")
        ctx, _ = self._hook().assemble("startup")
        self.assertNotIn("QUEUESECRET", ctx)
        self.assertNotIn("Bo Beta", ctx)
        self.assertIn("[party `beta-llc`] item #1", ctx, "position kept — still actionable")
        self.assertIn("plain internal item", ctx, "non-party items untouched")
        self.assertIn("(2)", ctx, "the count is unchanged")

    def test_fails_open_without_a_registry(self):
        os.remove(os.path.join(self.vault, "rgardin-ai", "reference",
                               "party-registry.md"))
        self._handoff("2026-08-25-acme-handoff.md",
                      "---\ntitle: t\ntype: session-handoff\ndate: 2026-08-25\n---\n# h\n\n"
                      "## Open items / next steps\n- Acme Co OPENMARK.\n")
        self._w(os.path.join(self.vault, "build-queue.md"),
                "# q\n\n## Active items\n### item\n- x.\n\n## Blocked\n")
        ctx, _ = self._hook().assemble("startup")
        self.assertIn("OPENMARK", ctx, "no registry → today's behaviour, never a wedge")


class TestOutboundBundle(Base):
    def _comp(self):
        return conftest_paths.load("scripts/compactor.py", "party_comp")

    def _seed(self):
        self._w(os.path.join(self.memory, "MEMORY.md"), "# index\n- neutral.\n")
        self._w(os.path.join(self.vault, "machine", "memory-v2",
                             "lint-report-latest.md"), "# r\n\n  FINDING x\n")

    def test_party_handoffs_never_leave_the_machine(self):
        self._seed()
        self._handoff("2026-08-25-acme-handoff.md",
                      "---\ntitle: t\ntype: session-handoff\ndate: 2026-08-25\n---\n# h\n\n"
                      "## Open items / next steps\n- Acme Co OUTBOUNDSECRET.\n")
        self._handoff("2026-08-25-plain-handoff.md",
                      "---\ntitle: t\ntype: session-handoff\ndate: 2026-08-25\n---\n# h\n\n"
                      "## Open items / next steps\n- INCLUDEMARK ordinary.\n")
        self._w(os.path.join(self.vault, "build-queue.md"), "# q\n\n## Active items\n")
        mat = self._comp()._gather_llm_input()
        self.assertNotIn("OUTBOUNDSECRET", mat)
        self.assertNotIn("Acme Co", mat)
        self.assertIn("INCLUDEMARK", mat, "ordinary handoffs still inform proposals")
        self.assertIn("excluded from this bundle by design", mat, "and it SAYS so")

    def test_party_queue_headers_are_redacted_in_the_bundle(self):
        self._seed()
        self._w(os.path.join(self.vault, "build-queue.md"),
                "# q\n\n## Active items\n### Beta LLC deal — BUNDLESECRET\n- x.\n")
        mat = self._comp()._gather_llm_input()
        self.assertNotIn("BUNDLESECRET", mat)
        self.assertIn("[party beta-llc]", mat)

    def test_a_multi_party_bundle_is_refused_fail_closed(self):
        """Drive the REAL refusal path, not just the detector. pass_proposals
        must raise before any outbound call when the bundle spans parties."""
        c = self._comp()
        self.assertEqual(len(c._parties_in("Acme Co and Beta LLC together")), 2)
        self._seed()
        self._w(os.path.join(self.vault, "build-queue.md"), "# q\n\n## Active items\n")
        # force a two-party bundle past the redactors
        c._gather_llm_input = lambda: "Acme Co and Beta LLC in one bundle"
        called = []
        c.subprocess = type("S", (), {
            "run": staticmethod(lambda *a, **k: called.append(1))})()
        with self.assertRaises(RuntimeError) as cm:
            c.pass_proposals()
        self.assertIn("spans 2 parties", str(cm.exception))
        self.assertEqual(called, [], "it must refuse BEFORE any outbound call")

    def test_unreadable_registry_means_refuse_not_proceed(self):
        c = self._comp()
        c.PARTY_REGISTRY = os.path.join(self.root, "nope.md")
        self.assertIsNone(c._parties_in("anything"),
                          "None is the signal pass_proposals refuses on — for the "
                          "one job that sends text OFF the machine, unknown means no")


class TestAlwaysInjectedIndexStaysClean(unittest.TestCase):
    """The regression test the chair asked for by name: the index that loads
    into EVERY session must contain no party identifier, ever."""

    def test_live_memory_index_names_no_party(self):
        reg = os.path.expanduser(
            "~/vault/rgardin-ai/reference/party-registry.md")
        idx = os.path.expanduser("~/memory/MEMORY.md")
        if not (os.path.isfile(reg) and os.path.isfile(idx)):
            self.skipTest("live machine files not present")
        with open(reg, encoding="utf-8") as f:
            block = re.search(r"(?s)```registry\n(.*?)```", f.read())
        phrases = []
        for line in block.group(1).splitlines():
            parts = [x.strip() for x in line.split("|") if x.strip()]
            if len(parts) >= 3 and parts[1].lower() in ("client", "prospect"):
                phrases += parts[2:]
        with open(idx, encoding="utf-8") as f:
            low = f.read().lower()
        hits = [p for p in phrases if p.lower() in low]
        self.assertEqual(hits, [], f"party identifiers in the always-loaded index: {hits}")


if __name__ == "__main__":
    unittest.main()


class TestMultiPartyDocuments(Base):
    """Verification round MUST-FIX #1. Both party_of() and _party_of() returned
    the FIRST matching slug, so a document mentioning two parties was stamped
    with one and the other's terms rode along — reproduced against 22 real
    production documents. compactor._parties_in() got this right the same day;
    these two call sites did not receive the same fix."""

    def _recall(self):
        return conftest_paths.load("scripts/recall.py", "multi_recall")

    def test_a_two_party_doc_is_suppressed_even_when_scoped_to_one(self):
        self._w(os.path.join(self.vault, "mixed.md"),
                "Acme Co agreed X. For reference Beta LLC quoted BETASECRET/hr.\n")
        r = self._recall()
        r.index(rebuild=True)
        rows, sup = r.search("BETASECRET", party="acme-co")
        self.assertEqual(rows, [], "scoping to A must not expose B's number")
        self.assertEqual(sup, 1)

    def test_an_internal_phrase_does_not_exempt_a_client_doc(self):
        self._w(os.path.join(self.vault, "internal-mixed.md"),
                "Ourselves internal planning: Acme Co rate is INTERNALLEAK.\n")
        r = self._recall()
        r.index(rebuild=True)
        rows, sup = r.search("INTERNALLEAK")
        self.assertEqual(rows, [], "an internal co-mention must not exempt it")
        self.assertEqual(sup, 1)

    def test_the_party_column_records_every_party_not_just_the_first(self):
        self._w(os.path.join(self.vault, "mixed2.md"), "Acme Co and Beta LLC both.\n")
        r = self._recall()
        r.index(rebuild=True)
        import sqlite3
        con = sqlite3.connect(r.DB)
        got = dict(con.execute("SELECT path, party FROM docs")).values()
        con.close()
        self.assertIn("acme-co,beta-llc", got)

    def test_all_parties_still_overrides_deliberately(self):
        self._w(os.path.join(self.vault, "mixed3.md"), "Acme Co, Beta LLC: OVERRIDEMARK\n")
        r = self._recall()
        r.index(rebuild=True)
        rows, sup = r.search("OVERRIDEMARK", all_parties=True)
        self.assertEqual(sup, 0)
        self.assertEqual(len(rows), 1)


class TestSiblingPathsAreFiltered(Base):
    """MUST-FIX #3 — the CONCURRENT digest and the sibling notice had NO party
    check at all, so a sibling leaked in full even when the PRIMARY brief was
    correctly degraded."""

    def _hook(self):
        return conftest_paths.load("hooks/session_start_v2.py", "sib_hook")

    def _base_queue(self):
        self._w(os.path.join(self.vault, "build-queue.md"),
                "# q\n\n## Active items\n### ordinary\n- x.\n\n## Blocked\n")

    def test_concurrent_digest_withholds_a_party_siblings_goal(self):
        self._base_queue()
        self._handoff("2026-08-25-zprimary-handoff.md",
                      "---\ntitle: p\ntype: session-handoff\ndate: 2026-08-25\n---\n# h\n\n"
                      "## Open items / next steps\n- ordinary.\n")
        self._handoff("2026-08-25-acme-sib-handoff.md",
                      "---\ntitle: acme sync\ntype: session-handoff\ndate: 2026-08-25\n"
                      "status: active\ngoal: Acme Co wants SECRETGOAL\n"
                      "next_action: send Acme Co SECRETNEXT\n---\n# h\n\nbody\n")
        import time
        p = os.path.join(self.vault, "handoffs", "2026-08-25-zprimary-handoff.md")
        os.utime(p, (time.time() + 60,) * 2)          # keep the neutral one primary
        ctx, _ = self._hook().assemble("startup")
        self.assertNotIn("SECRETGOAL", ctx)
        self.assertNotIn("SECRETNEXT", ctx)
        self.assertIn("party `acme-co`", ctx, "the sibling is still ANNOUNCED")

    def test_legacy_sibling_notice_withholds_a_party_title(self):
        self._base_queue()
        self._handoff("2026-08-25-zprimary-handoff.md",
                      "---\ntitle: p\ntype: session-handoff\ndate: 2026-08-25\n---\n# h\n\n"
                      "## Open items / next steps\n- ordinary.\n")
        self._handoff("2026-08-25-legacy-handoff.md",
                      "---\ntitle: Acme Co deal at TITLESECRET/hr\n"
                      "type: session-handoff\ndate: 2026-08-25\n---\n# h\n\nbody\n")
        import time
        p = os.path.join(self.vault, "handoffs", "2026-08-25-zprimary-handoff.md")
        os.utime(p, (time.time() + 60,) * 2)
        ctx, _ = self._hook().assemble("startup")
        self.assertNotIn("TITLESECRET", ctx, "a sibling TITLE can carry terms")
        self.assertIn("name withheld", ctx)

    def test_a_malformed_registry_is_announced_not_silent(self):
        self._base_queue()
        self._w(os.path.join(self.vault, "rgardin-ai", "reference",
                             "party-registry.md"), "# reg\n\nno fenced block here\n")
        self._handoff("2026-08-25-x-handoff.md",
                      "---\ntitle: t\ntype: session-handoff\ndate: 2026-08-25\n---\n# h\n\n"
                      "## Open items / next steps\n- ordinary.\n")
        ctx, _ = self._hook().assemble("startup")
        self.assertIn("PRESENT but unparsable", ctx,
                      "an editing slip must not silently reopen broadcast")


class TestLintIdentityHygiene(Base):
    def _lint(self):
        return conftest_paths.load("scripts/memory_lint.py", "ident_lint")

    def test_stale_verify_hashes_the_section_name(self):
        self._w(os.path.join(self.vault, "LIVE-STATE.md"),
                "# LS\n\n## Acme Co integration (verified 2020-01-01)\n- x\n")
        found = "\n".join(self._lint().lint_vault(self.vault))
        self.assertIn("STALE-VERIFY", found)
        self.assertNotIn("Acme Co", found,
                         "the one finding that wrote raw header text")

    def test_unregistered_party_record_is_flagged(self):
        self._w(os.path.join(self.vault, "rgardin-ai", "reference", "parties",
                             "ghost-co.md"), "---\ntitle: t\n---\nbody\n")
        found = "\n".join(self._lint().lint_vault(self.vault))
        self.assertIn("UNREGISTERED-PARTY", found)
        self.assertNotIn("ghost-co", found, "flagged by hash, never by name")

    def test_old_backup_check_is_recursive_and_suffix_tolerant(self):
        import datetime
        p = os.path.join(self.vault, "rgardin-ai", "reference", "parties",
                         "x.md.bak-20260101")
        self._w(p, "old")
        old = datetime.datetime.now().timestamp() - 30 * 86400
        os.utime(p, (old, old))
        found = "\n".join(self._lint().lint_vault(self.vault))
        self.assertIn("OLD-BACKUP", found,
                      "nested + date-suffixed backups were invisible before")


class TestCheckpointDualKey(Base):
    """The board blocked PreCompact registration pending 'does the harness reuse
    session_id across compaction?' — if it does not, an id-only lookup silently
    never fires. Matching on session id OR transcript path makes the feature
    correct either way, so the empirical check is no longer a precondition."""

    def _hook(self):
        return conftest_paths.load("hooks/session_start_v2.py", "ckpt_hook")

    def _checkpoint(self, sid8, transcript, body):
        d = os.path.join(self.vault, "machine", "checkpoints")
        os.makedirs(d, exist_ok=True)
        self._w(os.path.join(d, f"2026-08-25-1200-{sid8}-precompact.md"),
                f"# cp\n<!-- transcript: {transcript} -->\n{body}\n")

    def _charter(self, h):
        root = os.path.join(self.root, "dotclaude")
        os.makedirs(root, exist_ok=True)
        self._w(os.path.join(root, "CLAUDE.md"), "## Operating principles\n1. r.\n")
        h.CLAUDE_ROOT, h.CLAUDE_MD = root, os.path.join(root, "CLAUDE.md")

    def test_matches_on_session_id(self):
        h = self._hook()
        self._charter(h)
        self._checkpoint("aaaa1111", "/t/a.jsonl", "IDMATCHMARK")
        ctx, _ = h.assemble("compact", session_id="aaaa1111-rest")
        self.assertIn("IDMATCHMARK", ctx)

    def test_matches_on_transcript_when_the_session_id_CHANGED(self):
        """The exact scenario the board was worried about."""
        h = self._hook()
        self._charter(h)
        self._checkpoint("aaaa1111", "/t/a.jsonl", "TRANSCRIPTMARK")
        ctx, _ = h.assemble("compact", session_id="zzzz9999-different",
                            transcript_path="/t/a.jsonl")
        self.assertIn("TRANSCRIPTMARK", ctx,
                      "a fresh session_id must not orphan the checkpoint")

    def test_still_refuses_another_sessions_checkpoint(self):
        h = self._hook()
        self._charter(h)
        self._checkpoint("bbbb2222", "/t/other.jsonl", "OTHERSESSIONLEAK")
        ctx, _ = h.assemble("compact", session_id="aaaa1111-mine",
                            transcript_path="/t/mine.jsonl")
        self.assertNotIn("OTHERSESSIONLEAK", ctx or "",
                         "neither key matches — must inject nothing")
