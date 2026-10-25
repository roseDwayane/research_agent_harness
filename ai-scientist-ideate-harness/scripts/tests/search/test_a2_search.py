#!/usr/bin/env python3
"""Tests for A2 search (it_search.py; rules references/search/A2-search.md), offline: a fake scholar server answers the
calls, so the whole path - per-source rendering, retries, the dense instance, the merge rules, stable ids, enrichment,
signals, verdicts, the gates - runs without the network. One counter-example per handoff check lives in
tests/fixtures/search/a2/neg/*.json.

  python3 .claude/skills/ai-scientist-ideate/scripts/tests/search/test_a2_search.py
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2]
TOOLS = SCRIPTS / "ideate_tools.py"
A1FIX = SCRIPTS / "tests" / "fixtures" / "search" / "a1"
FIX = SCRIPTS / "tests" / "fixtures" / "search" / "a2"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import it_frame  # noqa: E402
from it_common import norm_title  # noqa: E402
import it_search  # noqa: E402
from test_a1_frame import apply_ops, build_good as build_a1  # noqa: E402


def apply2(doc, ops):
    """apply_ops plus three edits a dotted path cannot express."""
    for op in ops:
        ps = doc.get("papers") if isinstance(doc, dict) else None
        if op["op"] == "copy_id":
            ps[1]["id"] = ps[0]["id"]
        elif op["op"] == "copy_doi":
            a, b = [p for p in ps if p.get("doi")][:2]
            b["doi"] = a["doi"]
        elif op["op"] == "flip_anchor":
            ps[0]["anchor_match"] = not ps[0]["anchor_match"]
        else:
            apply_ops(doc, [op])
    return doc


def run(*args):
    p = subprocess.run([sys.executable, str(TOOLS), *map(str, args)], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def P(title, src, doi=None, year=2020, authors=("Smith J",), abstract=None, arxiv=None, journal="J Neural Eng"):
    return {"title": title, "authors": list(authors), "year": year, "journal": journal, "doi": doi, "url": None,
            "abstract": abstract if abstract is not None else f"{title}. We study EEG artifact handling.",
            "citation_count": 10, "sources_found_in": list(src), "arxiv_id": arxiv, "openalex_id": None}


AUTOREJECT = P("Autoreject: Automated artifact rejection for MEG and EEG data", [], "10.1016/j.neuroimage.2017.06.030", 2017, ("Jas M",))
PREP = P("The PREP pipeline: standardized preprocessing for large-scale EEG analysis", [], "10.3389/fninf.2015.00016", 2015,
         ("Bigdely-Shamlo N",), abstract="")
FASTER = P("FASTER: Fully Automated Statistical Thresholding for EEG artifact Rejection", [], "10.1016/j.jneumeth.2010.07.015", 2010, ("Nolan H",))
ICLABEL = P("ICLabel: An automated electroencephalographic independent component classifier", [], "10.1016/j.neuroimage.2019.05.026",
            2019, ("Pion-Tonachini L",))
PRE = P("Deep learning artifact detection for scalp EEG", [], None, 2021, ("Lee K",), arxiv="2101.00001", journal="arXiv")
PUB = P("Deep learning artifact detection for scalp EEG recordings", [], "10.1109/tbme.2022.1", 2022, ("Lee K",), arxiv="2101.00001",
        journal="IEEE Trans Biomed Eng")
FUZ1 = P("An Automated EEG Artifact Removal Framework Using ICA", [], None, 2020, ("Smith J",))
FUZ2 = P("An automated EEG artifact removal framework using ICA revisited", [], None, 2021, ("John Smith",))
BEARING = P("Bearing fault detection with vibration signals", [], "10.1/bearing", 2019, ("Wu Q",), abstract="vibration data")
MANUAL = P("Expert manual annotation of EEG artifacts: inter-rater agreement", [], "10.1/manual", 2018, ("Kim A",))
DENSE = P("Unsupervised quality control of electrophysiology recordings", ["semantic_scholar"], "10.1/dense", 2023, ("Ng T",),
          abstract="quality control of electrophysiology signals")

# what each query returns, per source
ANSWERS = {
    "Q1": {"pubmed": [AUTOREJECT, PREP], "scopus": [AUTOREJECT, PUB], "openalex": [AUTOREJECT, FUZ1]},
    "Q2": {"pubmed": [PREP], "scopus": [FUZ2], "openalex": [PREP]},
    "Q3": {"pubmed": [AUTOREJECT, BEARING], "scopus": [FUZ1], "openalex": [AUTOREJECT]},
    "Q4": {"pubmed": [FASTER, ICLABEL], "scopus": [AUTOREJECT, PREP], "openalex": [ICLABEL]},
    "Q5": {"pubmed": [MANUAL], "scopus": [MANUAL], "openalex": [MANUAL]},
}


class FakeServer:
    """Answers like scholar_mcp: per-source papers, totals, errors. Semantic Scholar finds the preprint for Q1 (and for
    QX once shortened to 4 words); Scopus is rate-limited once on Q3."""

    def __init__(self, recommend_ok=True):
        self.calls = []
        self.recommend_ok = recommend_ok
        self.scopus_q3_failed = False

    async def call(self, tool, params):
        self.calls.append((tool, copy.deepcopy(params)))
        if tool == "scholar_search":
            qid, papers, errors, totals, returned = params.get("found_via"), [], {}, {}, {}
            for src in params["sources"]:
                if src == "semantic_scholar":
                    # a 5-word flat query finds nothing; 4 words or fewer find the preprint (Q1 only)
                    hits = [dict(PRE, sources_found_in=["semantic_scholar"])] if qid in ("Q1", "QX") \
                        and len(params["query"].split()) <= 4 else []
                elif src == "scopus" and qid == "Q3" and not self.scopus_q3_failed:
                    self.scopus_q3_failed = True
                    errors[src] = "Error: Rate limit exceeded (429)."
                    continue
                else:
                    hits = [dict(p, sources_found_in=[src]) for p in ANSWERS.get(qid, {}).get(src, [])]
                papers += hits
                totals[src], returned[src] = 1000 + len(hits), len(hits)
            return {"query": params["query"], "sources_queried": params["sources"], "sources_skipped": {},
                    "source_errors": errors, "count": len(papers), "totals": totals, "returned": returned,
                    "papers": [dict(p, found_via=qid) for p in papers]}
        if tool == "scholar_recommend":
            if not self.recommend_ok:
                return {"_text": "Error: Rate limit exceeded (429)."}
            return {"seeds": params["paper_ids"], "count": 2,
                    "papers": [dict(DENSE, found_via="dense"), dict(AUTOREJECT, sources_found_in=["semantic_scholar"], found_via="dense")]}
        if tool == "scholar_recover_dois":
            return {"papers": params["papers"]}
        raise AssertionError(tool)


def fake_fetch(url, rd=None):
    """OpenAlex batch: gives PREP an abstract and an open-access link."""
    return {"results": [{"id": "https://openalex.org/W1", "doi": "https://doi.org/10.3389/fninf.2015.00016",
                         "abstract_inverted_index": {"PREP": [0], "standardizes": [1], "EEG": [2]},
                         "open_access": {"is_oa": True, "oa_url": "https://x/prep"},
                         "best_oa_location": {"pdf_url": "https://x/prep.pdf"}}]}


async def nosleep(_):
    return None


def run_a2(rd: Path, server=None, only=None, dense=True):
    server = server or FakeServer()
    cfg = json.loads((rd / "step0_session_config.json").read_text())

    async def go():
        await it_search.run_search(server, cfg, rd, only=only, dense=dense, sleep=nosleep)
        return await it_search.run_merge(server, cfg, rd, "x@example.com", fetch=fake_fetch, embedder=None)
    return asyncio.run(go()), server


GOOD_VERDICTS = {"summary": "every query on topic", "model": "fixture",
                 "verdicts": [{"query": q, "verdict": "ok", "reason": "on topic"} for q in ("Q1", "Q2", "Q3", "Q4", "Q5")],
                 "known_items": []}


def build_good(tmp: Path) -> Path:
    rd = build_a1(tmp)
    run_a2(rd)
    f = tmp / "verdicts.json"
    f.write_text(json.dumps(GOOD_VERDICTS))
    code, out = run("relevance-set", rd, f)
    assert code == 0, out
    return rd


class TestRendering(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((A1FIX / "good" / "protocol.json").read_text())
        st = json.loads((A1FIX / "good" / "strategy.json").read_text())
        self.cfg.update({"queries": st["queries"], "sources": ["semantic_scholar", "openalex", "pubmed", "scopus", "arxiv"]})
        self.q1 = self.cfg["queries"][0]

    def test_forms(self):
        p = self.cfg["protocol"]
        self.assertEqual(it_search.render(p, self.q1, "boolean"), it_frame.render_boolean(p, self.q1))
        nostar = it_search.render(p, self.q1, "boolean-nostar")
        self.assertNotIn("*", nostar)
        self.assertIn("electroencephalograph OR", nostar)
        arx = it_search.render(p, self.q1, "arxiv")
        self.assertIn('all:"scalp recording"', arx)
        self.assertTrue(arx.startswith("(all:EEG OR "))
        self.assertEqual(it_search.render(p, self.q1, "flat"), self.q1["flat_query"])
        self.assertEqual(it_search.render(p, {"query": "plain legacy words"}, "boolean"), "plain legacy words")

    def test_plan_groups_by_form_and_routes(self):
        plan = it_search.plan(self.cfg, self.q1)
        self.assertEqual(plan["boolean"]["sources"], ["pubmed", "scopus"])
        self.assertEqual(set(plan), {"boolean", "boolean-nostar", "arxiv", "flat"})
        recent = dict(self.q1, strategy="recent", year="last-12-months")
        self.assertEqual(sorted(it_search.query_sources(self.cfg, recent)), ["arxiv", "openalex", "semantic_scholar"])
        self.assertEqual(it_search.query_sources(self.cfg, dict(self.q1, sources=["pubmed"])), ["pubmed"])


class TestRunAndMerge(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.rd = build_a1(self.tmp)
        self.raw, self.server = run_a2(self.rd)
        self.by_title = {p["title"]: p for p in self.raw["papers"]}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_instances_record_every_attempt(self):
        rec = json.loads(it_search.latest_instance(self.rd, "Q1").read_text())
        self.assertEqual(rec["per_source"]["semantic_scholar"]["attempts"][0]["returned"], 1)
        self.assertEqual(rec["per_source"]["pubmed"]["attempts"][0]["total"], 1002)
        self.assertEqual(rec["per_source"]["pubmed"]["form"], "boolean")
        for ps in rec["per_source"].values():
            for a in ps["attempts"]:
                self.assertTrue(a["sent_query"] and a["at"] and "filters" in a)

    def test_flat_zero_retried_shortened(self):
        cfg = json.loads((self.rd / "step0_session_config.json").read_text())
        q = dict(cfg["queries"][0], id="QX", flat_query="EEG automated artifact rejection detection")
        q["query"] = q["flat_query"]
        rec = asyncio.run(it_search.run_query(FakeServer(), cfg, self.rd, q, sleep=nosleep))
        flat = rec["per_source"]["semantic_scholar"]["attempts"]
        self.assertEqual([a.get("returned") for a in flat], [0, 1])          # full flat query, then 4 words
        self.assertEqual(flat[1]["sent_query"], "EEG automated artifact rejection")
        it_search.instance_path(self.rd, "QX", rec["hash"]).unlink()

    def test_transient_failure_retried(self):
        rec = json.loads(it_search.latest_instance(self.rd, "Q3").read_text())
        att = rec["per_source"]["scopus"]["attempts"]
        self.assertIn("429", att[0]["error"])
        self.assertEqual(att[-1]["returned"], 1)

    def test_merge_rules(self):
        m = self.raw["search_summary"]["merges"]
        self.assertGreaterEqual(m.get("doi", 0), 1)
        self.assertEqual(m.get("arxiv"), 1)
        self.assertEqual(m.get("fuzzy"), 1)
        self.assertNotIn("Deep learning artifact detection for scalp EEG", self.by_title)       # the preprint merged ...
        pub = self.by_title["Deep learning artifact detection for scalp EEG recordings"]           # ... into the journal record
        self.assertEqual(pub["doi"], "10.1109/tbme.2022.1")
        auto = self.by_title["Autoreject: Automated artifact rejection for MEG and EEG data"]
        self.assertEqual(auto["found_by"][:3], ["Q1", "Q3", "Q4"])                               # every query that found it
        self.assertIn("D1", auto["found_by"])
        self.assertEqual(auto["found_via"], "Q1")

    def test_dense_only_faces_floor(self):
        d = self.by_title["Unsupervised quality control of electrophysiology recordings"]
        self.assertEqual((d["found_by"], d["found_via"]), (["D1"], "dense"))
        sys.path.insert(0, str(SCRIPTS))
        import it_screen
        self.assertFalse(it_screen.is_included(2, 3.4, d))
        self.assertTrue(it_screen.is_included(3, 3.4, d))

    def test_enrichment_and_identification(self):
        prep = self.by_title["The PREP pipeline: standardized preprocessing for large-scale EEG analysis"]
        self.assertEqual((prep["abstract_source"], prep["oa_url"]), ("openalex", "https://x/prep.pdf"))
        ident = self.raw["search_summary"]["identification"]
        self.assertGreater(ident["pubmed"]["retrieved"], 0)
        self.assertGreater(ident["pubmed"]["reported_total_sum"], 1000)
        self.assertIn("Identification (PRISMA)", (self.rd / "step2_search_summary.md").read_text())

    def test_ids_stable_and_registry_append_only(self):
        ids = {p["title"]: p["id"] for p in self.raw["papers"]}
        n_reg = len(it_search.load_registry(self.rd))
        raw2, _ = run_a2(self.rd)                      # resumes: no instance re-run, same merge
        self.assertEqual({p["title"]: p["id"] for p in raw2["papers"]}, ids)
        self.assertEqual(len(it_search.load_registry(self.rd)), n_reg)

    def test_revision_keeps_old_papers(self):
        (self.tmp / "rev.json").write_text(json.dumps({
            "retire": "Q5", "reason": "contrast too narrow", "round": 1,
            "add": {"id": "Q5b", "strategy": "contrast", "axes": {"C4": ["visual inspection"], "C1": "all"},
                    "flat_query": "EEG visual inspection", "rationale": "visual inspection wording"}}))
        code, out = run("frame", "query-revise", self.rd, self.tmp / "rev.json")
        self.assertEqual(code, 0, out)
        ANSWERS["Q5b"] = {"pubmed": [MANUAL], "scopus": [], "openalex": []}
        try:
            raw2, srv = run_a2(self.rd, only=["Q5b"])
        finally:
            del ANSWERS["Q5b"]
        man = next(p for p in raw2["papers"] if p["title"].startswith("Expert manual annotation"))
        self.assertEqual(man["found_by"], ["Q5", "Q5b"])
        self.assertFalse(man["retired_only"])
        self.assertTrue(all(c[1].get("found_via") in ("Q5b", None) for c in srv.calls if c[0] == "scholar_search"))
        self.assertEqual(len(raw2["papers"]), len(self.raw["papers"]))

    def test_forced_rerun_keeps_old_papers(self):
        """--force asks a query again under the same hash; the earlier instance is kept as superseded, so a paper only
        it found stays in the collection (overwriting it made the paper vanish: M01)."""
        cur = it_search.latest_instance(self.rd, "Q2")
        old = json.loads(cur.read_text())
        old["papers"].append(dict(BEARING, title="Turbine vibration monitoring with accelerometers",
                                  doi="10.1/turbine", sources_found_in=["pubmed"], found_via="Q2"))
        cur.write_text(json.dumps(old))
        cfg = json.loads((self.rd / "step0_session_config.json").read_text())
        asyncio.run(it_search.run_merge(FakeServer(), cfg, self.rd, "x@example.com", fetch=fake_fetch, embedder=None))

        async def go():
            await it_search.run_search(FakeServer(), cfg, self.rd, only=["Q2"], force=True, dense=False, sleep=nosleep)
            return await it_search.run_merge(FakeServer(), cfg, self.rd, "x@example.com", fetch=fake_fetch, embedder=None)
        raw2 = asyncio.run(go())
        kept = cur.with_name(cur.stem + "r1.json")
        self.assertTrue(kept.exists() and json.loads(kept.read_text())["complete"])
        tur = next(p for p in raw2["papers"] if p["title"].startswith("Turbine vibration"))
        self.assertTrue(tur["superseded_only"])
        self.assertEqual(it_frame.errors(it_search.run_checks(cfg, self.rd, "A2.m")), [])

    def test_rerendered_query_keeps_old_papers(self):
        """A query asked again (new rendering or result order) supersedes its instance; what only the old instance
        found stays in the collection, marked, and A2.c judges the query on its latest instance."""
        cur = it_search.latest_instance(self.rd, "Q1")
        old = json.loads(cur.read_text())
        old["papers"].append(dict(BEARING, title="Seismic event detection in borehole recordings",
                                  doi="10.1/seismic", sources_found_in=["pubmed"], found_via="Q1"))
        f = cur.parent / "Q1@0ld0ld00.json"
        f.write_text(json.dumps(old))
        os.utime(f, (cur.stat().st_mtime - 60, cur.stat().st_mtime - 60))     # asked before the current one
        cfg = json.loads((self.rd / "step0_session_config.json").read_text())
        raw2 = asyncio.run(it_search.run_merge(FakeServer(), cfg, self.rd, "x@example.com", fetch=fake_fetch, embedder=None))
        sei = next(p for p in raw2["papers"] if p["title"].startswith("Seismic event"))
        self.assertEqual((sei["found_by"], sei["superseded_only"], sei["found_via"]), (["Q1@0ld0ld00"], True, "Q1@0ld0ld00"))
        both = next(p for p in raw2["papers"] if p["title"] == AUTOREJECT["title"])
        self.assertEqual(both["found_via"], both["found_by"][0])
        self.assertNotIn("@", both["found_via"])                        # a current query leads
        self.assertEqual(it_frame.errors(it_search.run_checks(cfg, self.rd, "A2.m")), [])
        self.assertEqual(it_search.signals(cfg, self.rd)["queries"]["Q1"]["papers"],
                         sum(1 for p in raw2["papers"] if "Q1" in p["found_by"]))
        self.assertEqual(raw2["search_summary"]["superseded_only"], 1)

    def test_arxiv_doi_without_s2_key(self):
        """No Semantic Scholar key: an arXiv record keeps its DataCite DOI, no lookup is sent, the skip is a caveat.
        With a key the published version's DOI is looked up first."""
        from unittest import mock
        cur = it_search.latest_instance(self.rd, "Q1")
        inst = json.loads(cur.read_text())
        inst["papers"].append(dict(P("Self-supervised artifact maps for scalp EEG", ["arxiv"], None, 2023, ("Kim H",),
                                     arxiv="2301.99999", journal="arXiv"), found_via="Q1"))
        f = cur.parent / "Q1@arx00000.json"
        f.write_text(json.dumps(inst))
        os.utime(f, (cur.stat().st_mtime - 60, cur.stat().st_mtime - 60))
        cfg = json.loads((self.rd / "step0_session_config.json").read_text())
        for key, called in ((None, False), ("k", True)):
            srv = FakeServer()
            with mock.patch.object(it_search, "scholar_key", lambda name: key):
                raw = asyncio.run(it_search.run_merge(srv, cfg, self.rd, "x@example.com", fetch=fake_fetch, embedder=None))
            x = next(p for p in raw["papers"] if p["title"].startswith("Self-supervised artifact maps"))
            self.assertEqual((x["doi"], x.get("doi_source")), ("10.48550/arxiv.2301.99999", "arxiv"))
            self.assertEqual(any(c[0] == "scholar_recover_dois" for c in srv.calls), called)
            codes = {c["code"] for c in raw["search_summary"]["caveats"]}
            self.assertEqual("doi-recovery-skipped" in codes, not called)

    def test_recovered_doi_joins_preprint_and_publication(self):
        """A DOI recovered for an arXiv record joins it to its published version before the merge (no M04), and the id
        the joined paper did not keep is recorded as absorbed (no M01)."""
        from unittest import mock
        cur = it_search.latest_instance(self.rd, "Q1")
        inst = json.loads(cur.read_text())
        inst["papers"] += [dict(P("Masked artifact maps: a preprint", ["arxiv"], None, 2023, ("Kim H",), arxiv="2301.99999",
                                  journal="arXiv"), found_via="Q1"),
                           dict(P("Artifact maps for scalp EEG with masked autoencoders", ["scopus"], "10.1/maps.2024", 2024,
                                  ("Kim H",)), found_via="Q1")]
        f = cur.parent / "Q1@arx00000.json"
        f.write_text(json.dumps(inst))
        os.utime(f, (cur.stat().st_mtime - 60, cur.stat().st_mtime - 60))
        cfg = json.loads((self.rd / "step0_session_config.json").read_text())

        class Recovers(FakeServer):
            async def call(self, tool, params):
                if tool == "scholar_recover_dois":
                    return {"papers": [dict(x, doi="10.1/maps.2024") if x.get("arxiv_id") == "2301.99999" else x
                                       for x in params["papers"]]}
                return await super().call(tool, params)
        merge = lambda srv: asyncio.run(it_search.run_merge(srv, cfg, self.rd, "x@example.com", fetch=fake_fetch,
                                                             embedder=None))
        with mock.patch.object(it_search, "scholar_key", lambda name: None):
            raw = merge(FakeServer())                                     # no key: two papers
        two = [p for p in raw["papers"] if "maps" in p["title"].lower()]
        self.assertEqual(len(two), 2)
        with mock.patch.object(it_search, "scholar_key", lambda name: "k"):
            raw = merge(Recovers())                                       # the key finds the published DOI
        one = [p for p in raw["papers"] if "maps" in p["title"].lower()]
        self.assertEqual(len(one), 1)
        codes = {x["code"] for x in it_frame.errors(it_search.run_checks(cfg, self.rd, "A2.m"))}
        self.assertFalse(codes & {"M01", "M04"}, codes)
        gone = ({p["id"] for p in two} - {one[0]["id"]}).pop()
        reg = it_search.load_registry(self.rd)
        self.assertIn({"id": gone, "merged_into": one[0]["id"]},
                      [{k: e[k] for k in ("id", "merged_into")} for e in reg if e.get("merged_into")])

    def test_recovered_doi_never_joins_two_arxiv_works(self):
        from unittest import mock
        cur = it_search.latest_instance(self.rd, "Q1")
        inst = json.loads(cur.read_text())
        inst["papers"] += [dict(P("Suicide risk detection in Bengali posts", ["arxiv"], None, 2018, ("Roy A",),
                                  arxiv="1807.08666", journal="arXiv"), found_via="Q1"),
                           dict(P("Cross-lingual suicide ideation detection", ["arxiv"], None, 2021, ("Roy A",),
                                  arxiv="2108.06174", journal="arXiv"), found_via="Q1")]
        cur.write_text(json.dumps(inst))
        cfg = json.loads((self.rd / "step0_session_config.json").read_text())

        class SameDoi(FakeServer):
            async def call(self, tool, params):
                if tool == "scholar_recover_dois":
                    return {"papers": [dict(x, doi="10.1016/j.csl.2021.101275") for x in params["papers"]]}
                return await super().call(tool, params)
        with mock.patch.object(it_search, "scholar_key", lambda name: "k"):
            raw = asyncio.run(it_search.run_merge(SameDoi(), cfg, self.rd, "x@example.com", fetch=fake_fetch, embedder=None))
        two = [p for p in raw["papers"] if p.get("arxiv_id") in ("1807.08666", "2108.06174")]
        self.assertEqual(len(two), 2)
        self.assertEqual({p["doi"] for p in two}, {"10.48550/arxiv.1807.08666", "10.48550/arxiv.2108.06174"})
        self.assertNotIn("M04", {f["code"] for f in it_search.run_checks(cfg, self.rd, "A2.m")})

    def test_untitled_record_with_doi_is_named_by_openalex(self):
        cur = it_search.latest_instance(self.rd, "Q1")
        inst = json.loads(cur.read_text())
        inst["papers"].append({"title": "", "authors": [], "year": None, "doi": "10.1/untitled.2016",
                               "sources_found_in": ["semantic_scholar"], "found_via": "Q1"})
        cur.write_text(json.dumps(inst))
        cfg = json.loads((self.rd / "step0_session_config.json").read_text())

        def fetch(url, rd=None):
            res = fake_fetch(url, rd)
            if "10.1%2Funtitled.2016" in url or "10.1/untitled.2016" in url:
                res = {"results": list(res.get("results") or []) + [
                    {"id": "https://openalex.org/W9", "doi": "https://doi.org/10.1/untitled.2016",
                     "display_name": "Syntax-guided paraphrase generation", "publication_year": 2016}]}
            return res
        raw = asyncio.run(it_search.run_merge(FakeServer(), cfg, self.rd, "x@example.com", fetch=fetch, embedder=None))
        x = next(p for p in raw["papers"] if p.get("doi") == "10.1/untitled.2016")
        self.assertEqual((x["title"], x.get("title_source"), x.get("year")), ("Syntax-guided paraphrase generation", "openalex", 2016))
        self.assertEqual(raw["search_summary"]["untitled_records"], 0)
        self.assertEqual(it_frame.errors(it_search.run_checks(cfg, self.rd, "A2.m")), [])

    def test_untitled_record_is_no_paper(self):
        cur = it_search.latest_instance(self.rd, "Q1")
        inst = json.loads(cur.read_text())
        inst["papers"].append({"title": "", "authors": [], "year": None, "doi": None, "sources_found_in": ["semantic_scholar"],
                               "found_via": "Q1"})
        cur.write_text(json.dumps(inst))
        before = len(it_search.load_registry(self.rd))
        cfg = json.loads((self.rd / "step0_session_config.json").read_text())
        raw = asyncio.run(it_search.run_merge(FakeServer(), cfg, self.rd, "x@example.com", fetch=fake_fetch, embedder=None))
        self.assertEqual(raw["search_summary"]["untitled_records"], 1)
        self.assertTrue(all(p["title"] for p in raw["papers"]))
        self.assertEqual(len(it_search.load_registry(self.rd)), before)         # no id minted for it
        self.assertEqual(it_frame.errors(it_search.run_checks(cfg, self.rd, "A2.m")), [])

    def test_dense_failure_is_a_caveat(self):
        for f in (self.rd / "step2_queries").glob("D1@*.json"):     # as if the first run had failed: a complete
            f.unlink()                                                # D1 is not asked again
        raw, _ = run_a2(self.rd, server=FakeServer(recommend_ok=False))
        self.assertIn("dense-skipped", [c["code"] for c in raw["search_summary"]["caveats"]])

    def test_rerun_keeps_dense_and_collection(self):
        """A search run again over complete instances asks nothing and rewrites nothing: D1 is kept like a query, and
        the merge keeps step2_raw_papers.json byte for byte (its stamp included), so nothing downstream goes stale."""
        raw_p = self.rd / "step2_raw_papers.json"
        d1 = next((self.rd / "step2_queries").glob("D1@*.json"))
        before = (raw_p.read_bytes(), d1.read_bytes())
        raw, srv = run_a2(self.rd)
        self.assertEqual([c for c in srv.calls if c[0] in ("scholar_search", "scholar_recommend")], [])
        self.assertEqual((raw_p.read_bytes(), d1.read_bytes()), before)


class TestSemanticSimilarity(unittest.TestCase):
    def test_percentile_and_vocabulary_with_a_fake_model(self):
        """The rules read the percentile; the vocabulary feedback reads top-quartile papers with no anchor term."""
        def fake(texts):           # similarity grows with the number of times "eeg" or "cleaning" occurs
            return [[1.0, t.lower().count("eeg") + t.lower().count("cleaning") + 0.01] for t in texts]
        cfg = json.loads((A1FIX / "good" / "protocol.json").read_text())
        papers = [{"title": "EEG EEG artifact", "abstract": ""}, {"title": "solar panel", "abstract": ""},
                  {"title": "cleaning cleaning cleaning", "abstract": ""}, {"title": "EEG", "abstract": ""}]
        status = it_search.add_sem_sim(cfg, papers, ("fake@0", fake))
        self.assertTrue(status.startswith("enabled: fake@0"))
        self.assertEqual([p["sem_pct"] for p in papers], [66.7, 0.0, 100.0, 33.3])

    @unittest.skipUnless((Path.home() / ".cache/huggingface/hub/models--allenai--specter2_base").exists(),
                         "SPECTER2 not downloaded")
    def test_real_model_ranks_on_topic_first_and_caches(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            emb = it_search.load_embedder(tmp)
            if emb is None:
                self.skipTest("torch / transformers unavailable in this interpreter")
            cfg = json.loads((A1FIX / "good" / "protocol.json").read_text())
            papers = [dict(AUTOREJECT), dict(BEARING), dict(MANUAL)]
            it_search.add_sem_sim(cfg, papers, emb)
            self.assertEqual(min(papers, key=lambda p: p["sem_sim"])["title"], BEARING["title"])
            n = len((tmp / "_state" / "embeddings").glob("*.jsonl").__next__().read_text().splitlines())
            again = [dict(AUTOREJECT), dict(BEARING), dict(MANUAL)]
            it_search.add_sem_sim(cfg, again, it_search.load_embedder(tmp))
            self.assertEqual([p["sem_sim"] for p in again], [p["sem_sim"] for p in papers])   # same input, same output
            n2 = len((tmp / "_state" / "embeddings").glob("*.jsonl").__next__().read_text().splitlines())
            self.assertEqual(n, n2)                                                            # nothing re-embedded
        finally:
            shutil.rmtree(tmp)


class TestRecordReplay(unittest.TestCase):
    def test_answers_replayed_in_order(self):
        import os
        import it_common
        tmp = Path(tempfile.mkdtemp())
        try:
            req = {"tool": "scholar_search", "params": {"query": "x"}}
            it_common.net_save(tmp, "scholar", req, {"source_errors": {"s": "429"}})
            it_common.net_save(tmp, "scholar", req, {"papers": [1]})
            it_common._REPLAY_SEEN.clear()
            os.environ["IDEATE_REPLAY"] = "1"
            try:
                got = [it_common.net_load(tmp, "scholar", req) for _ in range(3)]
                with self.assertRaises(it_common.ReplayMiss):
                    it_common.net_load(tmp, "scholar", {"tool": "other"})
            finally:
                del os.environ["IDEATE_REPLAY"]
            self.assertEqual(got, [{"source_errors": {"s": "429"}}, {"papers": [1]}, {"papers": [1]}])
        finally:
            shutil.rmtree(tmp)


class TestRelevanceAndGates(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.rd = build_good(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_a2_check_passes(self):
        code, out = run("a2-check", self.rd)
        self.assertEqual(code, 0, out)

    def test_signals(self):
        cfg = json.loads((self.rd / "step0_session_config.json").read_text())
        sig = it_search.signals(cfg, self.rd)
        self.assertEqual(sum(1 for k in sig["known_items"] if k["resolved"]), 2)
        self.assertEqual(set(sig["queries"]["Q4"]["anchor_terms_found"]), {"Autoreject", "PREP pipeline", "FASTER", "ICLabel"})
        self.assertGreater(sig["dense"]["dense_only"], 0)
        self.assertIsNone(sig["vocabulary"])
        q4 = next(q for q in cfg["queries"] if q["id"] == "Q4")             # an anchor query asking one anchor only
        q4["axes"] = {**q4["axes"], "C3": ["Autoreject"]}
        self.assertEqual(set(it_search.signals(cfg, self.rd)["queries"]["Q4"]["anchor_terms_found"]), {"Autoreject"})

    def test_screen_build_gated(self):
        (self.rd / "step2_relevance_check.json").unlink()
        code, out = run("screen-build", self.rd, self.tmp / "verdicts.json")
        self.assertEqual(code, 2, out)
        self.assertIn("A2 is not done", out)

    def test_protocol_reset_starts_an_epoch(self):
        """§15 G2: A1.p resetting the protocol after the search starts a new A2.c epoch - the round limit (R04) and
        saturation (R09) count only its rounds; the earlier rounds stay in the file."""
        rp = self.rd / "step2_relevance_check.json"
        rel = json.loads(rp.read_text())
        r0 = rel["rounds"][0]
        self.assertEqual(r0["protocol_sha"], it_frame.protocol_content_hash(
            json.loads((self.rd / "step0_session_config.json").read_text())))
        old = [dict(r0, round=i, protocol_sha="an-earlier-protocol", at=f"2026-01-0{i + 1}T00:00:00+00:00")
               for i in range(it_search.MAX_ROUNDS)]
        rel["rounds"] = old
        rp.write_text(json.dumps(rel))
        f = self.tmp / "verdicts.json"
        f.write_text(json.dumps({**GOOD_VERDICTS, "summary": "the revised protocol, round 0"}))
        code, out = run("relevance-set", self.rd, f)
        self.assertEqual(code, 0, out)                    # without epochs: R04, three rounds already ran
        self.assertIn("new epoch", out)
        rel = json.loads(rp.read_text())
        self.assertEqual((len(rel["rounds"]), rel["rounds"][-1]["epoch_round"]), (it_search.MAX_ROUNDS + 1, 0))
        self.assertIn("a new epoch", (self.rd / "step2_relevance_check.md").read_text())
        # older rounds without protocol_sha: the epoch is told by the time of the reset
        cfg = json.loads((self.rd / "step0_session_config.json").read_text())
        legacy = {"rounds": [{k: v for k, v in r.items() if k != "protocol_sha"} for r in old]}
        self.assertEqual(len(it_search.epoch(cfg, legacy)["rounds"]), it_search.MAX_ROUNDS)    # no reset: all count
        cfg["protocol"]["history"] = list(cfg["protocol"].get("history") or []) + [
            {"at": "2026-01-02T12:00:00+00:00", "by": "A1.p", "action": "reset", "note": "revised"}]
        ep = it_search.epoch(cfg, legacy)
        self.assertEqual([r["round"] for r in ep["rounds"]], [2])
        # a query that came in before the epoch is part of its base; one after the epoch's first round is round 1
        cfg["queries_history"] = list(cfg.get("queries_history") or []) + [
            {"at": "2026-01-01T12:00:00+00:00", "by": "A2.c", "action": "revise", "round": 2, "retired": "Q1",
             "added": {"id": "Q9"}},
            {"at": "2026-01-03T12:00:00+00:00", "by": "A2.c", "action": "revise", "round": 1, "retired": "Q2",
             "added": {"id": "Q10"}}]
        qr = it_search.query_rounds(cfg, ep)
        self.assertEqual((qr["Q9"], qr["Q10"]), (0, 1))
        self.assertEqual(it_search.query_rounds(cfg)["Q9"], 2)                  # without an epoch: as stated

    def test_anchors_revise(self):
        """§15 G2: A2.c may revise the anchor terms after the search, with a reason; A1.q's own strategy still
        counts as unchanged (a resumed A1.q is not refused)."""
        f = self.tmp / "anchors.json"
        cfg0 = json.loads((self.rd / "step0_session_config.json").read_text())
        f.write_text(json.dumps({"anchor_terms": ["artifact", "eeg"]}))
        self.assertEqual(run("frame", "anchors-revise", self.rd, f)[0], 2)          # no reason
        f.write_text(json.dumps({"anchor_terms": ["Artifact"], "reason": "x"}))
        code, out = run("frame", "anchors-revise", self.rd, f)
        self.assertEqual(code, 2, out)                                              # Q14: 2-5 lower-case terms
        self.assertIn("Q14", out)
        f.write_text(json.dumps({"anchor_terms": ["artifact", "eeg"], "reason": "the revised protocol's reading",
                                 "round": 1}))
        code, out = run("frame", "anchors-revise", self.rd, f)
        self.assertEqual(code, 0, out)
        cfg = json.loads((self.rd / "step0_session_config.json").read_text())
        self.assertEqual(cfg["anchor_terms"], ["artifact", "eeg"])
        h = cfg["queries_history"][-1]
        self.assertEqual((h["action"], h["from"], h["to"], h["by"]), ("anchors", cfg0["anchor_terms"], ["artifact", "eeg"], "A2.c"))
        self.assertTrue(it_frame._same_strategy(cfg, {"queries": [q for q in cfg0["queries"] if q.get("added_by") != "A2.c"],
                                                      "anchor_terms": cfg0["anchor_terms"]}))
        self.assertEqual(run("frame", "anchors-revise", self.rd, f)[0], 2)          # the same anchors again
        bare = self.tmp / "bare"
        bare.mkdir()
        rd2 = build_a1(bare)
        self.assertEqual(run("frame", "anchors-revise", rd2, f)[0], 2)              # before the search: set-strategy

    def test_add_terms_round_trip(self):
        f = self.tmp / "terms.json"
        f.write_text(json.dumps({"axis": "C2", "terms": ["artefact rejection"], "reason": "British spelling missing",
                                 "evidence": ["paper_001"], "round": 1}))
        code, out = run("frame", "add-terms", self.rd, f)
        self.assertEqual(code, 0, out)
        cfg = json.loads((self.rd / "step0_session_config.json").read_text())
        codes = {x["code"] for x in it_frame.errors(it_frame.run_checks(cfg, self.rd, "all"))}
        self.assertEqual(codes, {"Q13"})                 # the new term must be asked; nothing else goes stale
        q1 = next(q for q in cfg["queries"] if q["id"] == "Q1")
        self.assertNotIn("artefact rejection", it_frame.render_boolean(cfg["protocol"], q1))   # "all" = A1.p's terms


    def test_query_revise_list_asks_terms_added_for_several_queries(self):
        f = self.tmp / "terms.json"
        f.write_text(json.dumps({"axis": "C2", "terms": ["artefact rejection", "artifact correction"],
                                 "reason": "two missing phrasings, for two queries", "round": 1}))
        self.assertEqual(run("frame", "add-terms", self.rd, f)[0], 0)
        cfg = json.loads((self.rd / "step0_session_config.json").read_text())
        ids = [q["id"] for q in cfg["queries"] if q.get("strategy") == "synonym-swap"][:1]
        loosen = [q["id"] for q in cfg["queries"] if q.get("strategy") == "loosen"][:1]
        one = {"retire": ids[0], "reason": "British spelling", "round": 1,
               "add": {"id": "Q2b", "strategy": "synonym-swap", "axes": {"C1": ["EEG"], "C2": ["artefact rejection"]},
                       "flat_query": "EEG artefact rejection", "rationale": "British spelling"}}
        two = {"retire": loosen[0], "reason": "correction wording", "round": 1,
               "add": {"id": "Q3b", "strategy": "loosen", "axes": {"C2": ["artifact correction", "artifact rejection"]},
                       "flat_query": "artifact correction rejection", "rationale": "correction wording"}}
        r = self.tmp / "rev.json"
        r.write_text(json.dumps(one))
        self.assertEqual(run("frame", "query-revise", self.rd, r)[0], 2)          # alone: 'artifact correction' unasked
        r.write_text(json.dumps([one, two]))
        code, out = run("frame", "query-revise", self.rd, r)
        self.assertEqual(code, 0, out)                                             # together: checked once
        cfg = json.loads((self.rd / "step0_session_config.json").read_text())
        st = {q["id"]: q.get("status", "active") for q in cfg["queries"]}
        self.assertEqual((st[ids[0]], st[loosen[0]], st["Q2b"], st["Q3b"]), ("retired", "retired", "active", "active"))
        self.assertEqual([h["added"]["id"] for h in cfg["queries_history"][-2:]], ["Q2b", "Q3b"])

    def test_retire_terms(self):
        cfg0 = json.loads((self.rd / "step0_session_config.json").read_text())
        before = it_frame.protocol_hash(cfg0)
        h1 = it_search.instance_hash(cfg0, next(q for q in cfg0["queries"] if q["id"] == "Q1"))
        h2 = it_search.instance_hash(cfg0, next(q for q in cfg0["queries"] if q["id"] == "Q2"))
        h4 = it_search.instance_hash(cfg0, next(q for q in cfg0["queries"] if q["id"] == "Q4"))
        f = self.tmp / "retire.json"
        for bad in ({"axis": "C2", "terms": ["artefact removal", "automated cleaning"]},     # Q2 left with no C2 term
                    {"axis": "C2", "terms": ["artifact rejection"]},                        # in Q1's flat form
                    {"axis": "C2", "terms": ["automated cleaning"]},     # Q1's flat word "automated" loses its term (Q12)
                    {"axis": "C3", "terms": ["FASTER"]},                                    # an anchor
                    {"axis": "C2", "terms": ["artifact rejection", "artefact removal", "automated cleaning",
                                             "artifact detection"]}):                       # nothing left
            f.write_text(json.dumps({**bad, "reason": "x", "round": 1}))
            code, out = run("frame", "retire-terms", self.rd, f)
            self.assertEqual(code, 2, (bad, out))
        f.write_text(json.dumps({"axis": "C2", "terms": ["artifact detection"], "reason": "brings in seismic detection",
                                 "evidence": ["paper_001"], "round": 1}))
        code, out = run("frame", "retire-terms", self.rd, f)
        self.assertEqual(code, 0, out)
        cfg = json.loads((self.rd / "step0_session_config.json").read_text())
        for q in cfg["queries"]:
            self.assertNotIn("artifact detection", q["boolean_query"], q["id"])
        self.assertEqual(it_frame.protocol_hash(cfg), before)            # A1.e's basis: a logged deviation
        self.assertEqual(it_frame.errors(it_frame.run_checks(cfg, self.rd, "all")), [])   # no Q13
        q1 = next(q for q in cfg["queries"] if q["id"] == "Q1")
        self.assertNotEqual(it_search.instance_hash(cfg, q1), h1)        # Q1 asked all of C2: stale, runs again
        q2 = next(q for q in cfg["queries"] if q["id"] == "Q2")
        self.assertEqual(it_search.instance_hash(cfg, q2), h2)           # Q2 names two other C2 terms
        self.assertEqual(it_search.instance_hash(cfg, next(q for q in cfg["queries"] if q["id"] == "Q4")), h4)
        sig = it_search.signals(cfg, self.rd)
        self.assertTrue(sig["queries"]["Q1"]["stale_instance"])
        self.assertFalse(sig["queries"]["Q2"]["stale_instance"])
        code, out = run("frame", "retire-terms", self.rd, f)              # retired already
        self.assertEqual(code, 2, out)

    def test_term_pull(self):
        protocol = json.loads((A1FIX / "good" / "protocol.json").read_text())["protocol"]
        def P(i, text, pct):
            return {"id": f"p{i}", "title": text, "abstract": "", "sem_pct": pct,
                    "found_by": ["Q3"] if pct < 25 else ["Q1", "Q3"]}
        papers = [P(i, "automated cleaning of photovoltaic panels", 5.0 + i) for i in range(4)] + \
                 [P(9, "automated cleaning of EEG", 80.0)] + \
                 [P(10 + i, "artifact rejection in scalp EEG", 60.0) for i in range(6)] + \
                 [P(20, "artifact rejection and automated cleaning", 2.0)]          # both terms: neither's own
        texts = {x["id"]: it_search._paper_text(x) for x in papers}
        pull = {(t["axis"], t["term"]): t for t in it_search.term_pull(protocol, papers, texts)}
        t = pull[("C2", "automated cleaning")]
        self.assertEqual((t["own"], t["far"], t["flagged"]), (5, 4, True))
        self.assertEqual((t["far_by_query"], t["near_by_query"]), ({"Q3": 4}, {"Q1": 1, "Q3": 1}))
        self.assertFalse(pull[("C2", "artifact rejection")]["flagged"])
        self.assertNotIn("C3", {a for a, _ in pull})                       # anchors are not judged here
        papers = papers[1:]                                                 # 4 own: below the minimum of 5
        self.assertFalse({(t["axis"], t["term"]): t for t in it_search.term_pull(protocol, papers, texts)}
                         [("C2", "automated cleaning")]["flagged"])
        self.assertIsNone(it_search.term_pull(protocol, [dict(x, sem_pct=None) for x in papers], texts))

    def test_term_pull_answer_stored(self):
        cfg = json.loads((self.rd / "step0_session_config.json").read_text())
        rnd = {**copy.deepcopy(GOOD_VERDICTS), "term_pull": [{"axis": "C2", "term": "automated cleaning",
                                                             "action": "keep", "reason": "the EEG sense dominates"}]}
        sig = it_search.signals(cfg, self.rd)
        sig["term_pull"] = [{"axis": "C2", "term": "automated cleaning", "own": 8, "far": 6, "far_share": 0.75,
                             "flagged": True, "far_titles": []}]
        self.assertEqual(it_frame.errors(it_search.check_round(cfg, sig, rnd, 1)), [])
        rnd["term_pull"][0]["action"] = "drop"
        self.assertEqual({f["code"] for f in it_search.check_round(cfg, sig, rnd, 1)}, {"R10"})

    def test_source_order(self):
        cfg = json.loads((self.rd / "step0_session_config.json").read_text())
        inst = json.loads(it_search.latest_instance(self.rd, "Q1").read_text())
        orders = {a.get("order") for ps in inst["per_source"].values() for a in ps["attempts"]}
        self.assertEqual(orders, {"relevance"})
        q1 = next(q for q in cfg["queries"] if q["id"] == "Q1")
        h = it_search.instance_hash(cfg, q1)
        old = dict(it_search.SOURCE_ORDER)
        try:
            it_search.SOURCE_ORDER["scopus"] = "citations"
            self.assertNotEqual(it_search.instance_hash(cfg, q1), h)     # another order: another instance
        finally:
            it_search.SOURCE_ORDER.clear(); it_search.SOURCE_ORDER.update(old)


class TestNegativeFixtures(unittest.TestCase):
    """Every A2 handoff check has a counter-example that must fail it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.rd = build_good(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_every_counter_example_fails_its_check(self):
        cases = sorted((FIX / "neg").glob("*.json"))
        self.assertGreaterEqual(len(cases), 20)
        for path in cases:
            case = json.loads(path.read_text())
            with self.subTest(case=path.stem):
                rd = self.tmp / f"c_{path.stem}"
                shutil.copytree(self.rd, rd)
                cfg = json.loads((rd / "step0_session_config.json").read_text())
                t = case["target"]
                if t == "round":
                    sig = apply_ops(it_search.signals(cfg, rd), case.get("sig_ops", []))
                    rnd = apply_ops(copy.deepcopy(GOOD_VERDICTS), case["ops"])
                    prev = case.get("prev")
                    fs = it_search.check_round(cfg, sig, rnd, case.get("rounds_before", 0), prev)
                else:
                    if t == "step0":
                        cfg = apply_ops(cfg, case["ops"])
                    else:
                        f = {"raw": rd / "step2_raw_papers.json", "relevance": rd / "step2_relevance_check.json",
                             "instance": it_search.latest_instance(rd, case.get("qid", "Q1"))}[t]
                        f.write_text(json.dumps(apply2(json.loads(f.read_text()), case["ops"])))
                    fs = it_search.run_checks(cfg, rd, case["unit"])
                level = case.get("level", "ERROR")
                codes = {f["code"] for f in fs if f["level"] == level}
                self.assertIn(case["expect"], codes, f"{path.stem}: {case['why']} - got {sorted(codes)} at {level}")


class TestOpenAlexKey(unittest.TestCase):
    """OPENALEX_API_KEY is sent with OpenAlex requests and never written: the recording holds the URL without it."""

    def test_key_sent_not_recorded(self):
        import io
        import os
        import it_common
        sent = []

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=30):
            sent.append(req.full_url)
            return Resp(b'{"meta": {"count": 7}, "results": []}')
        old_open, old_env = it_common._ur.urlopen, os.environ.get("OPENALEX_API_KEY")
        it_common._ur.urlopen = fake_urlopen
        os.environ["OPENALEX_API_KEY"] = "sekret-123"
        try:
            with tempfile.TemporaryDirectory() as t:
                rd = Path(t)
                out = it_common.http_json("https://api.openalex.org/works?filter=doi:10.1/x&per-page=5", rd)
                self.assertEqual(out["meta"]["count"], 7)
                self.assertTrue(sent[0].endswith("&api_key=sekret-123"))
                rec = "".join(f.read_text() for f in (rd / "_state" / "net" / "http").glob("*.json"))
                self.assertNotIn("sekret", rec)
                it_common.http_json("https://api.crossref.org/works?filter=doi:10.1/x", rd)
                self.assertNotIn("api_key", sent[1])                         # only OpenAlex gets the key
        finally:
            it_common._ur.urlopen = old_open
            if old_env is None:
                os.environ.pop("OPENALEX_API_KEY", None)
            else:
                os.environ["OPENALEX_API_KEY"] = old_env


if __name__ == "__main__":
    unittest.main(verbosity=2)
