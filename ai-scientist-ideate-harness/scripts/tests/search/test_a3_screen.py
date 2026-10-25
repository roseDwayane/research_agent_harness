#!/usr/bin/env python3
"""Tests for A3 screen (it_screen.py; rules references/search/A3-screen.md), offline: a fake OpenAlex, a fake Scopus
venue tool and a fake scoring subagent take an A2-finished fixture topic through A3.b -> A3.g -> plan -> merge ->
build. One counter-example per handoff check lives in tests/fixtures/search/a3/neg/*.json.

  python3 .claude/skills/ai-scientist-ideate/scripts/tests/search/test_a3_screen.py
"""

from __future__ import annotations

import asyncio
import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

SCRIPTS = Path(__file__).resolve().parents[2]
TOOLS = SCRIPTS / "ideate_tools.py"
FIX = SCRIPTS / "tests" / "fixtures" / "search" / "a3"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import it_screen  # noqa: E402
from test_a1_frame import apply_ops  # noqa: E402
from test_a2_search import build_good as build_a2  # noqa: E402


def run(*args):
    p = subprocess.run([sys.executable, str(TOOLS), *map(str, args)], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


# OpenAlex as the fixture topic would answer it: types, a retraction, a language, citations, the collection's edges
META = {
    "10.1016/j.neuroimage.2017.06.030": dict(type="article", cit=0.99, refs=["W_FASTER", "W_PREP"], src="S1", year=2017),
    "10.3389/fninf.2015.00016": dict(type="review", cit=0.95, refs=[], src="S2", year=2015),
    "10.1016/j.jneumeth.2010.07.015": dict(type="article", cit=0.97, refs=[], src="S3", year=2010),
    "10.1016/j.neuroimage.2019.05.026": dict(type="article", cit=0.9, refs=["W_AUTO"], src="S1", year=2019),
    "10.1109/tbme.2022.1": dict(type="article", cit=0.6, refs=["W_AUTO"], src="S4", year=2022),
    "10.1/bearing": dict(type="editorial", cit=0.1, refs=[], src=None, year=2019),
    "10.1/manual": dict(type="article", cit=0.4, refs=["W_AUTO"], src=None, year=2018, lang="de"),
    "10.1/dense": dict(type="article", cit=None, refs=[], src=None, year=2025, retracted=True),
}
WID = {"10.1016/j.neuroimage.2017.06.030": "W_AUTO", "10.3389/fninf.2015.00016": "W_PREP",
       "10.1016/j.jneumeth.2010.07.015": "W_FASTER"}
SOURCES = {"S1": ("NeuroImage", "1053-8119", 4.2), "S2": ("Frontiers in Neuroinformatics", "1662-5196", 2.5),
           "S3": ("Journal of Neuroscience Methods", "0165-0270", 2.2), "S4": ("IEEE TBME", "0018-9294", 3.0)}


def fake_fetch(url, rd=None):
    filt = unquote(re.search(r"filter=([^&]+)", url).group(1))
    if "/sources?" in url:
        ids = filt.split(":", 1)[1].split("|")
        return {"results": [{"id": f"https://openalex.org/{i}", "display_name": SOURCES[i][0], "type": "journal",
                             "issn_l": SOURCES[i][1], "summary_stats": {"2yr_mean_citedness": SOURCES[i][2]}}
                            for i in ids if i in SOURCES]}
    dois = filt.split(":", 1)[1].split("|") if filt.startswith("doi:") else []
    out = []
    for d in dois:
        m = META.get(d)
        if not m:
            continue
        out.append({"id": f"https://openalex.org/{WID.get(d, 'W_' + d[-6:])}", "doi": f"https://doi.org/{d}",
                    "type": m["type"], "is_retracted": m.get("retracted", False), "language": m.get("lang", "en"),
                    "cited_by_count": 100, "fwci": 2.0,
                    "citation_normalized_percentile": {"value": m["cit"]} if m["cit"] is not None else None,
                    "counts_by_year": [{"year": 2025, "cited_by_count": 20}, {"year": 2024, "cited_by_count": 10}],
                    "referenced_works": [f"https://openalex.org/{r}" for r in m["refs"]], "publication_year": m["year"],
                    "primary_location": {"source": {"id": f"https://openalex.org/{m['src']}", "display_name": SOURCES[m["src"]][0],
                                                    "type": "journal"}} if m["src"] else {}})
    return {"results": out}


S2_ABSTRACTS: dict = {}          # id asked -> abstract the fake Semantic Scholar holds (a test sets and clears it)


class FakeVenues:
    async def call(self, tool, params):
        if tool == "scholar_abstracts":
            got = {i: S2_ABSTRACTS[i] for i in params["paper_ids"] if i in S2_ABSTRACTS}
            return {"abstracts": got, "missing": [i for i in params["paper_ids"] if i not in got], "count": len(got)}
        assert tool == "scholar_venues"
        snip = {"1053-8119": 1.68, "1662-5196": 0.99, "0165-0270": 0.89}
        return {"venues": {i: {"snip": snip[i], "sjr": 1.0} for i in params["issns"] if i in snip},
                "missing": [i for i in params["issns"] if i not in snip]}


def fake_subagent(batch: dict) -> dict:
    """Scores like a careful reader: verbatim evidence, one rationale per paper."""
    scores = []
    for p in batch["papers"]:
        title, ab = p["title"] or "", p["abstract"] or ""
        problem = " ".join(title.split()[:3])
        method = "We study EEG artifact handling" if "We study EEG artifact handling" in ab else \
            (" ".join(ab.split()[:3]) if len(ab.split()) >= 3 else "not stated")
        rel = 5 if "artifact" in (title + ab).lower() or "eeg" in (title + ab).lower() else 2
        lead = "no abstract: " if "NO-ABSTRACT" in (p.get("flags") or []) and rel >= 3 else ""
        scores.append({"id": p["id"], "evidence": {"problem": problem, "method": method, "data": "not stated",
                                                    "code": "not stated"},
                       "rel": rel, "qual": 4, "rationale": f"{lead}judged on its own terms: {title[:50]}"})
    return {"model": "fixture-subagent", "scores": scores}


def screen(rd: Path, fetch=None) -> None:
    """A3.b -> A3.g -> plan -> (fake subagents) -> merge -> build on whatever candidates the research dir holds."""
    cfg = json.loads((rd / "step0_session_config.json").read_text())
    asyncio.run(it_screen.run_bibliometrics(FakeVenues(), cfg, rd, "x@example.com", fetch=fetch or fake_fetch))
    for cmd in (("screen-gate", rd), ("screen-plan", rd, "--size", "4")):
        code, out = run(*cmd)
        assert code == 0, out
    fan = rd / "_state" / "fanout" / "A3"
    for f in sorted(fan.glob("batch_*.in.json")):
        b = json.loads(f.read_text())
        (fan / b["out"]).write_text(json.dumps(fake_subagent(b)))
    for cmd in (("screen-merge", rd), ("screen-build", rd, rd / "screening_scores.json")):
        code, out = run(*cmd)
        assert code == 0, out


def build_good(tmp: Path, fetch=None) -> Path:
    rd = build_a2(tmp)
    screen(rd, fetch)
    return rd


def apply3(doc, ops):
    for op in ops:
        if op["op"] == "drop_first":
            d = doc
            for k in op["path"].split("."):
                d = d[k]
            del d[next(iter(d))]
        elif op["op"] == "set_first":
            d = doc
            for k in op["path"].split("."):
                d = d[k]
            d[next(iter(d))][op["field"]] = op["value"]
        elif op["op"] == "copy_rationale":
            scored = [e for e in doc["scores"] if "rel" in e and e["rel"] >= 3]
            scored[1]["rationale"] = scored[0]["rationale"]
        else:
            apply_ops(doc, [op])
    return doc


class TestImpact(unittest.TestCase):
    def test_cold_start_and_neutral_venue(self):
        old = {"cit_pct": 0.9, "in_pct": 50, "venue_pct": 10, "age": 8}
        new = dict(old, age=0)
        self.assertEqual(it_screen.impact_value(old), round(0.7 * 0.9 + 0.3 * 0.5, 4))      # venue ignored when old
        self.assertEqual(it_screen.impact_value(new), round(0.5 * (0.7 * 0.9 + 0.15) + 0.5 * 0.10, 4))
        preprint = dict(new, venue_pct=None)
        self.assertGreater(it_screen.impact_value(preprint), it_screen.impact_value(new))   # no venue = neutral, not low
        self.assertEqual(it_screen.impact_score({"age": 3}), 3.0)                          # no metadata at all

    def test_english_abstract_passes_the_language_gate(self):
        bib = {"papers": {"a": {"language": "nl", "abstract_english": True}, "b": {"language": "fr", "abstract_english": False},
                          "c": {"language": "en", "abstract_english": False}}}
        self.assertEqual([e["id"] for e in it_screen.gate_decisions({}, bib)], ["b"])
        self.assertTrue(it_screen.english_abstract("Conventional EEG techniques are based on visual inspection of the record and we show that this is the case"))
        self.assertFalse(it_screen.english_abstract("Avancées en rejet automatique des artéfacts EEG basées sur la géométrie"))

    def test_percentile_ties(self):
        self.assertEqual(it_screen.pct(1, [0, 1, 1, 2]), 50.0)
        self.assertIsNone(it_screen.pct(None, [1]))


class TestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.rd = build_good(cls.tmp)
        cls.sl = json.loads((cls.rd / "step3_shortlist.json").read_text())
        cls.by_title = {p["title"]: p for p in cls.sl["papers"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_a3_check_passes(self):
        code, out = run("a3-check", self.rd)
        self.assertEqual(code, 0, out)

    def test_gate_codes(self):
        g = json.loads((self.rd / "step3_gate.json").read_text())
        self.assertEqual(sorted(e["code"] for e in g["excluded"]), ["X-LANG", "X-RET", "X-TYPE"])
        self.assertEqual(self.sl["summary"]["gate_excluded"], 3)

    def test_scorer_is_blind(self):
        b = json.loads(sorted((self.rd / "_state/fanout/A3").glob("batch_*.in.json"))[0].read_text())
        keys = {k for p in b["papers"] for k in p}
        self.assertEqual(keys, {"id", "title", "abstract", "year", "flags"})
        brief = (self.rd / "_state/fanout/A3/brief.md").read_text()
        self.assertIn("EX1:", brief)
        self.assertIn("no journal, no citation counts", brief)

    def test_impact_computed_and_roles(self):
        auto = self.by_title["Autoreject: Automated artifact rejection for MEG and EEG data"]
        self.assertGreater(auto["impact"]["in_degree"], 0)
        self.assertEqual(auto["screening"]["recency_impact"],
                         json.loads((self.rd / "step3_bibliometrics.json").read_text())["papers"][auto["id"]]["impact"])
        prep = self.by_title["The PREP pipeline: standardized preprocessing for large-scale EEG analysis"]
        self.assertIn("survey", prep["roles"])                       # OpenAlex type review
        self.assertIn("foundational", auto["roles"])
        self.assertTrue(all(p["roles"] for p in self.sl["papers"]))

    def test_export_gated_then_open(self):
        sl = self.rd / "step3_shortlist.json"
        keep = sl.read_text()
        sl.write_text(keep.replace('"composite": ', '"composite": 9', 1))
        code, out = run("export", self.rd)
        self.assertEqual(code, 2, out)
        self.assertIn("A3 is not done", out)
        sl.write_text(keep)
        code, out = run("export", self.rd)
        self.assertEqual(code, 2, out)                 # A3 done, A5 not: keys are minted on the final shortlist
        self.assertIn("A5 is not done", out)
        code, out = run("export", self.rd, "--no-snowball", "fixture: A3 only")
        self.assertEqual(code, 0, out)
        self.assertIn("Exported before the snowball:** fixture: A3 only",
                      (self.rd / "step4_citation_keys.md").read_text())

    def test_bulk_spares_close_papers(self):
        papers = {"p1": {"id": "p1", "title": "bearing fault", "anchor_match": False, "sem_pct": 10},
                  "p2": {"id": "p2", "title": "bearing fault EEG", "anchor_match": False, "sem_pct": 60},
                  "p3": {"id": "p3", "title": "bearing fault", "anchor_match": True, "sem_pct": 5}}
        hit = it_screen.bulk_targets({"bulk": [{"title_regex": "bearing", "rel": 1}], "scores": []}, papers, set())
        self.assertEqual(sorted(hit), ["p1"])

    def test_citation_text_is_no_abstract(self):
        """OpenAlex gives some ACL Anthology papers their citation as the abstract: screened as NO-ABSTRACT."""
        cite = {"title": "Small and Practical BERT Models for Sequence Labeling", "authors": ["Henry Tsai", "Jason Riesa"],
                "abstract": "Henry Tsai, Jason Riesa, Melvin Johnson, Naveen Arivazhagan, Xin Li, Amelia Archer. Proceedings "
                            "of the 2019 Conference on Empirical Methods in Natural Language Processing"}
        real = {"title": "A study", "authors": ["Ann Lee"], "abstract": " ".join(["We study EEG artifact handling."] * 12)
                + " Results were presented at the Proceedings of a workshop."}
        self.assertFalse(it_screen.has_abstract(cite))
        self.assertTrue(it_screen.has_abstract(real))
        self.assertIn("NO-ABSTRACT", it_screen._flags(cite, None))
        e = {"evidence": {"problem": "Small and Practical BERT Models", "method": "not stated", "data": "not stated",
                          "code": "not stated"}, "rel": 3, "qual": 2, "rationale": "no abstract: title only"}
        self.assertEqual(it_screen.evidence_problems(e, cite), [])          # a title quote is enough, as for no abstract
        e2 = {**e, "evidence": {**e["evidence"], "problem": "EEG artifact handling"}}
        self.assertEqual(it_screen.evidence_problems(e2, real), ["relevance 3 needs a quoted method"])

    def test_text_without_prose_is_no_abstract(self):
        """§14 F2 (s20): an abstract field holding names, repository boilerplate or a table of contents is no abstract;
        text mostly in another script is left to the scorer."""
        for junk in ("Khok Hong Jing", "International audience", "status: Published", ",", "-- 12.",
                     "Thomas Wolf, Lysandre Debut, Victor Sanh, Julien Chaumond, Clement Delangue, Anthony Moi, "
                     "Pierric Cistac, Tim Rault, Remi Louf, Morgan Funtowicz, Joe Davison, Sam Shleifer",
                     "1. Interactive Speech Systems.- 1.1 Introduction.- 1.2 Background and Scope of This Book.- 2. "
                     "Speech Input.- 2.1 Recognition",
                     # §15 validation: OpenAlex's "abstract" of a citation line (accented names, a DOI link)
                     "Gustavo Alberto Nuñez-Alvarez, Arturo Aguilar Pérez, Armando Gonzalez-Sanchez, Federico Mendez, "
                     "and Wenceslao Bonilla-Blancas. International Journal of Fuzzy Logic and Intelligent Systems "
                     "2025;25:351-63. https://doi.org/10.5391/IJFIS.2025.25.3.351"):
            self.assertFalse(it_screen.has_abstract({"title": "t", "abstract": junk}), junk)
            self.assertIn("NO-ABSTRACT", it_screen._flags({"title": "t", "abstract": junk}, None))
        for real in ("We propose a dense phrase index for building entity dictionaries.",
                     "Nous proposons une méthode d'évaluation pour les résumés générés automatiquement en français.",
                     "基于模仿函数的Mimicry文本隐写法利用上下文无关文法(CFG)构造树形结构，生成的含密仿自然文本存在缺陷。",
                     "テキスト分類のための新しい手法を提案する。"):
            self.assertTrue(it_screen.has_abstract({"title": "t", "abstract": real}), real)

    def test_abstract_mismatch_is_judged_on_the_title(self):
        """§14 F3: the scorer flags an abstract that belongs to another paper; quotes then come from the title only and
        relevance >= 3 needs only the problem."""
        p = {"title": "Generating Sequences With Recurrent Neural Networks",
             "abstract": "We analyse GNSS station time series for tectonic deformation across the region."}
        ev = {"problem": "Generating Sequences", "method": "not stated", "data": "not stated", "code": "not stated"}
        e = {"evidence": ev, "rel": 4, "qual": 3, "rationale": "abstract of another paper: judged on the title",
             "record_problem": "abstract-mismatch"}
        self.assertEqual(it_screen.evidence_problems(e, p), [])
        bad = {**e, "evidence": {**ev, "data": "GNSS station time series"}}
        self.assertTrue(any("title (abstract-mismatch" in m for m in it_screen.evidence_problems(bad, p)))
        self.assertEqual(it_screen.entry_problems({**e, "record_problem": "odd"}, p, {"IN1"})[0][0], "C17")

    def test_soft_criterion_keeps_the_paper_at_the_borderline(self):
        """§14 F4 + §15 G1: a criterion A1.e names under E6 is soft - a paper that fails it under the protocol's reading
        but meets it under the other one is kept at tier 4, its composite computed on relevance <= 2; a criterion holding
        the same word is linked; failing both readings is a plain violation with its reason (`both_readings`)."""
        tmp = Path(tempfile.mkdtemp())
        try:
            rd = tmp / "topic_research"
            shutil.copytree(self.rd, rd)
            shutil.copy(self.rd.parent / "topic.md", tmp / "topic.md")
            evp = rd / "step1_protocol_evaluation.json"
            ev = json.loads(evp.read_text())
            last = ev["rounds"][-1]
            last["checks"] = ["E1", "E2", "E3", "E4", "E5", "E6"]
            last["findings"] = [f for f in last["findings"] if f["check"] != "E6"] + [
                {"check": "E6", "result": "note", "criterion": "EX1", "word": "automated",
                 "alt_reading": "semi-automated with a human check", "evidence": "EX1"}]
            evp.write_text(json.dumps(ev))
            self.assertEqual(set(it_screen._soft(rd)), {"EX1"})
            cfg = json.loads((rd / "step0_session_config.json").read_text())
            linked = {c["id"] for c in cfg["protocol"]["criteria"]["inclusion"] + cfg["protocol"]["criteria"]["exclusion"]
                      if c["id"] != "EX1" and "automated" in c["text"].lower()}
            self.assertEqual(it_screen._soft_sets(rd), ({"EX1"}, linked))
            sp = rd / "screening_scores.json"
            sc = json.loads(sp.read_text())
            self.assertTrue(all(e.get("brief") == 2 for e in sc["scores"] if "rel" in e))
            tgt = next(e for e in sc["scores"] if (e.get("rel") or 0) >= 4 and "violates" not in e)
            tgt["soft_violates"] = {"EX1": "meets it under the other reading: a person checks each output"}
            low = next(e for e in sc["scores"] if "rel" in e and "violates" not in e and e is not tgt)
            low.update(rel=1, qual=1, soft_violates={"EX1": "meets it under the other reading, but off topic"})
            low["evidence"] = {k: "not stated" for k in low["evidence"]}     # would not be included anyway: not kept
            sp.write_text(json.dumps(sc))
            code, out = run("screen-build", rd, sp)
            self.assertEqual(code, 0, out)
            sl = json.loads((rd / "step3_shortlist.json").read_text())
            kept = next(p for p in sl["papers"] if p["id"] == tgt["id"])
            self.assertEqual(kept["screening"]["tier"], 4)
            self.assertEqual(set(kept["screening"]["soft_violates"]), {"EX1"})
            self.assertIn("capped at 2", kept["screening"]["arithmetic"])
            self.assertEqual(sl["summary"]["soft_kept"], 1)
            self.assertNotIn(low["id"], {p["id"] for p in sl["papers"]})
            self.assertEqual([f for f in it_screen.check_shortlist(cfg, rd) if f["level"] == "ERROR"], [])
            brief = (rd / "_state/fanout/A3/brief.md").read_text() if run("screen-plan", rd)[0] == 0 else ""
            self.assertIn("soft:", brief)
            if linked:
                self.assertIn("linked to soft EX1", brief)
            errs = lambda: [f for f in it_screen.check_scores(cfg, rd, sc) if f["level"] == "ERROR"]
            tgt["soft_violates"] = ["EX1"]                                   # brief 2: a reason per criterion
            self.assertIn("C16", {f["code"] for f in errs()})
            tgt["soft_violates"] = {"EX2": "meets it under the other reading somehow"}   # not soft
            self.assertIn("C16", {f["code"] for f in errs()})
            del tgt["soft_violates"]
            for k in ("evidence", "rel", "qual"):
                tgt.pop(k, None)
            tgt["violates"] = ["EX1"]                                        # both readings? say so
            self.assertIn("C16", {f["code"] for f in errs()})
            tgt["both_readings"] = {"EX1": "fully automatic, no person ever checks"}
            self.assertNotIn("C16", {f["code"] for f in errs()})
            tgt["brief"] = 1                                                 # an entry from before brief 2: old rule
            self.assertIn("C16", {f["code"] for f in errs()})                # (soft alone in violates is refused)
            del tgt["violates"], tgt["both_readings"]
            tgt.update(rel=4, qual=3, soft_violates=["EX1"],
                       evidence=next(e for e in sc["scores"] if e is not tgt and (e.get("rel") or 0) >= 4)["evidence"])
            self.assertNotIn("C16", {f["code"] for f in errs() if f["msg"].startswith(tgt["id"])})
            sp.write_text(json.dumps(sc))
            code, out = run("screen-plan", rd, "--rescore", "soft")       # read the old-rule entry again
            self.assertEqual(code, 0, out)
            self.assertIn("1 entr(y/ies) to read again (soft)", out)
            b = json.loads(sorted((rd / "_state/fanout/A3").glob("batch_*.in.json"))[-1].read_text())
            self.assertEqual((b["ids"], b["rescore"]["kind"], b["brief"]), ([tgt["id"]], "soft", 2))
        finally:
            shutil.rmtree(tmp)

    def test_abstract_fill_and_rescore(self):
        """§15 G3: A3.b finds the abstracts the records lack (OpenAlex's own, then Semantic Scholar's); an entry scored
        on the title alone is WARNed (C19) and read again with `--rescore filled`; a fill is not asked for twice."""
        tmp = Path(tempfile.mkdtemp())
        try:
            rd = tmp / "topic_research"
            shutil.copytree(self.rd, rd)
            shutil.copy(self.rd.parent / "topic.md", tmp / "topic.md")
            cfg = json.loads((rd / "step0_session_config.json").read_text())
            prep = ("The PREP pipeline standardizes early-stage EEG processing: it removes line noise, references the "
                    "data robustly and detects bad channels, and we report results on several large datasets.")
            words = prep.split()

            def fetch_with_abstract(url, rd_):
                out = fake_fetch(url, rd_)
                for w in out.get("results") or []:
                    if str(w.get("doi", "")).endswith("10.3389/fninf.2015.00016"):
                        w["abstract_inverted_index"] = {}
                        for i, t in enumerate(words):
                            w["abstract_inverted_index"].setdefault(t, []).append(i)
                return out
            bearing = ("We detect bearing faults from vibration signals with a convolutional network and compare it "
                       "with envelope analysis on two public benchmarks.")
            S2_ABSTRACTS.update({"DOI:10.1/bearing": bearing})
            try:
                asyncio.run(it_screen.run_bibliometrics(FakeVenues(), cfg, rd, "x@example.com", fetch=fetch_with_abstract))
            finally:
                S2_ABSTRACTS.clear()
            bib = json.loads((rd / "step3_bibliometrics.json").read_text())
            self.assertEqual(bib["papers"]["paper_004"]["abstract_fill"], {"text": prep, "source": "openalex"})
            self.assertEqual(bib["papers"]["paper_005"]["abstract_fill"]["source"], "semantic_scholar")
            self.assertEqual(bib["abstract_fill"], {"lacking": 2, "openalex": 1, "semantic_scholar": 1, "still_missing": 0})
            cand = {p["id"]: p for p in it_screen.candidates(rd)}
            self.assertEqual((cand["paper_004"]["abstract"], cand["paper_004"]["abstract_filled_by"]), (prep, "openalex"))
            raw = {p["id"]: p for p in it_screen.candidates(rd, filled=False)}
            self.assertNotIn("abstract_filled_by", raw["paper_004"])                  # the step2 files are not changed
            # a second A3.b keeps the fills without asking again (the fake S2 now holds nothing)
            asyncio.run(it_screen.run_bibliometrics(FakeVenues(), cfg, rd, "x@example.com", fetch=fake_fetch))
            bib = json.loads((rd / "step3_bibliometrics.json").read_text())
            self.assertEqual(bib["papers"]["paper_005"]["abstract_fill"]["text"], bearing)
            self.assertEqual(bib["papers"]["paper_004"]["abstract_fill"]["text"], prep)
            self.assertEqual(run("screen-gate", rd)[0], 0)
            self.assertEqual(run("screen-merge", rd)[0], 0)
            sc0 = json.loads((rd / "screening_scores.json").read_text())
            self.assertIn("paper_004", {e["id"] for e in sc0["scores"]})     # its title-only reading still stands
            self.assertNotIn("paper_004", {r["id"] for r in sc0.get("refused") or []})
            code, out = run("a3-check", rd)
            self.assertIn("C19", out)
            code, out = run("screen-plan", rd, "--rescore", "filled")
            self.assertEqual(code, 0, out)
            fan = rd / "_state/fanout/A3"
            b = json.loads(sorted(fan.glob("batch_*.in.json"))[-1].read_text())
            self.assertEqual((sorted(b["ids"]), b["rescore"]["kind"]), (["paper_004"], "filled"))   # paper_005: gated
            self.assertTrue(all("NO-ABSTRACT" not in p["flags"] for p in b["papers"]))   # the scorer sees the fill
            ans = fake_subagent(b)
            for e in ans["scores"]:
                e["evidence"]["method"] = "not stated" if e["rel"] < 3 else e["evidence"]["method"]
            (fan / b["out"]).write_text(json.dumps(ans))
            code, out = run("screen-merge", rd)
            self.assertEqual(code, 0, out)
            sc = json.loads((rd / "screening_scores.json").read_text())
            again = {e["id"]: e for e in sc["scores"] if e.get("rescore")}
            self.assertEqual(set(again), {"paper_004"})
            self.assertEqual({x["id"] for x in sc["superseded"]}, {"paper_004"})
            code, out = run("screen-build", rd, rd / "screening_scores.json")
            self.assertEqual(code, 0, out)
            code, out = run("a3-check", rd)
            self.assertNotIn("C19", out)
            sl = json.loads((rd / "step3_shortlist.json").read_text())
            inc = {p["id"]: p for p in sl["papers"]}
            self.assertEqual(inc["paper_004"]["abstract_filled_by"], "openalex")
            self.assertGreaterEqual(sl["summary"]["abstract_filled"], 1)
        finally:
            S2_ABSTRACTS.clear()
            shutil.rmtree(tmp)

    def test_no_abstract_needs_text(self):
        """§15 G3: a NO-ABSTRACT paper whose title does not settle it - relevance 3, needs_text, `no abstract:`; build
        marks it for A6; without `no abstract:` the entry is refused (C18)."""
        tmp = Path(tempfile.mkdtemp())
        try:
            rd = tmp / "topic_research"
            shutil.copytree(self.rd, rd)
            shutil.copy(self.rd.parent / "topic.md", tmp / "topic.md")
            cfg = json.loads((rd / "step0_session_config.json").read_text())
            sp = rd / "screening_scores.json"
            sc = json.loads(sp.read_text())
            e = next(x for x in sc["scores"] if x["id"] == "paper_004")
            e.update(rel=3, qual=3, needs_text=True, rationale="the title names a pipeline; this work is known for robust "
                                                               "referencing")
            errs = {f["code"] for f in it_screen.check_scores(cfg, rd, sc) if f["level"] == "ERROR"}
            self.assertIn("C18", errs)
            e["rationale"] = "no abstract: the title does not settle whether artifacts are detected"
            sp.write_text(json.dumps(sc))
            code, out = run("screen-build", rd, sp)
            self.assertEqual(code, 0, out)
            sl = json.loads((rd / "step3_shortlist.json").read_text())
            q = next(p for p in sl["papers"] if p["id"] == "paper_004")
            self.assertTrue(q["screening"]["needs_text"])
            self.assertEqual(sl["summary"]["needs_text"], 1)
            self.assertIn("needs_text", (rd / "step3_screening_results.md").read_text())
        finally:
            shutil.rmtree(tmp)

    def test_merge_refuses_a_bad_entry_and_batches_it_again(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            rd = tmp / "topic_research"
            shutil.copytree(self.rd.parent / "topic_research", rd)
            shutil.copy(self.rd.parent / "topic.md", tmp / "topic.md")
            (rd / "screening_scores.json").unlink()
            fan = rd / "_state" / "fanout" / "A3"
            shutil.rmtree(fan)
            self.assertEqual(run("screen-plan", rd, "--size", "4")[0], 0)
            first = sorted(fan.glob("batch_*.in.json"))
            bad = None
            for f in first:
                b = json.loads(f.read_text())
                ans = fake_subagent(b)
                if bad is None:
                    e = next(x for x in ans["scores"] if x["rel"] >= 3)
                    e["evidence"]["data"], bad = "EEG", e["id"]          # one word: not a phrase (C03)
                (fan / b["out"]).write_text(json.dumps(ans))
            code, out = run("screen-merge", rd)
            self.assertEqual(code, 0, out)
            self.assertIn(f"refused {bad}", out)
            sc = json.loads((rd / "screening_scores.json").read_text())
            self.assertNotIn(bad, {e["id"] for e in sc["scores"]})
            self.assertEqual([r["id"] for r in sc["refused"]], [bad])
            self.assertEqual(run("screen-plan", rd, "--size", "4")[0], 0)   # only the refused paper, in a new batch
            new = [json.loads(f.read_text()) for f in sorted(fan.glob("batch_*.in.json")) if f not in first]
            self.assertEqual([b["ids"] for b in new], [[bad]])
            (fan / new[0]["out"]).write_text(json.dumps(fake_subagent(new[0])))
            self.assertEqual(run("screen-merge", rd)[0], 0)
            self.assertEqual(run("screen-build", rd, rd / "screening_scores.json")[0], 0)
            self.assertEqual(len(json.loads((rd / "screening_scores.json").read_text())["refused"]), 1)
        finally:
            shutil.rmtree(tmp)

    def test_rescue(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            shutil.copytree(self.rd.parent, tmp / "c")
            rd = tmp / "c" / "topic_research"
            # a first reading that excluded a paper (relevance 1 -> SCORE)
            scores = json.loads((rd / "screening_scores.json").read_text())
            gate = {e["id"] for e in json.loads((rd / "step3_gate.json").read_text())["excluded"]}
            old = next(e for e in scores["scores"] if "rel" in e and e["id"] != "paper_002")
            pid = old["id"]
            old.update(rel=1, qual=2, rationale="first reading: judged outside the protocol")
            (rd / "screening_scores.json").write_text(json.dumps(scores))
            self.assertEqual(run("screen-build", rd, rd / "screening_scores.json")[0], 0)
            inc = {p["id"] for p in json.loads((rd / "step3_shortlist.json").read_text())["papers"]}
            self.assertNotIn(pid, inc)
            self.assertEqual(run("screen-rescue", rd, pid)[0], 2)                         # --reason is required
            self.assertEqual(run("screen-rescue", rd, sorted(inc)[0], "--reason", "x")[0], 2)   # already included
            self.assertEqual(run("screen-rescue", rd, sorted(gate)[0], "--reason", "x")[0], 2)  # a mechanical exclusion
            code, out = run("screen-rescue", rd, pid, "--reason", "bears on O2, which gen_1 hinges on", "--by", "gen_1")
            self.assertEqual(code, 0, out)
            fan = rd / "_state/fanout/A3"
            b = json.loads(sorted(fan.glob("batch_*.in.json"))[-1].read_text())
            self.assertEqual((b["ids"], b["rescue"]["supersedes"]), ([pid], old["batch"]))
            self.assertEqual(set(b["papers"][0]), {"id", "title", "abstract", "year", "flags"})   # still blind
            self.assertEqual(run("screen-rescue", rd, pid, "--reason", "again")[0], 2)    # one rescue at a time
            ans = fake_subagent(b)
            ans["scores"][0].update(rel=5, qual=4, rationale="read again: the method applies to the protocol's outcome")
            (fan / b["out"]).write_text(json.dumps(ans))                 # a NO-ABSTRACT paper without `no abstract:`
            code, out = run("screen-merge", rd)
            self.assertIn("C18", out)                                    # refused like any answer: the first reading stays
            sc = json.loads((rd / "screening_scores.json").read_text())
            self.assertEqual([e["batch"] for e in sc["scores"] if e["id"] == pid], [old["batch"]])
            self.assertFalse(sc.get("superseded"))
            ans["scores"][0]["rationale"] = "no abstract: read again, the title names the protocol's outcome"
            (fan / b["out"]).write_text(json.dumps(ans))
            for _ in range(2):                                                             # merging twice changes nothing
                code, out = run("screen-merge", rd)
                self.assertEqual(code, 0, out)
            sc = json.loads((rd / "screening_scores.json").read_text())
            self.assertEqual(sum(1 for e in sc["scores"] if e["id"] == pid), 1)
            self.assertEqual([(x["id"], x["superseded_by"]) for x in sc["superseded"]], [(pid, b["batch"])])
            code, out = run("screen-build", rd, rd / "screening_scores.json")
            self.assertEqual(code, 0, out)
            self.assertIn(pid, {p["id"] for p in json.loads((rd / "step3_shortlist.json").read_text())["papers"]})
            self.assertIn("Read again on request", (rd / "step3_screening_results.md").read_text())
            code, out = run("a3-check", rd)
            self.assertEqual(code, 0, out)
        finally:
            shutil.rmtree(tmp)

    def test_merge_redispatches_missing(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            rd = tmp / "c"
            shutil.copytree(self.rd, rd)
            fan = rd / "_state/fanout/A3"
            first = sorted(fan.glob("batch_*.out.json"))[0]
            ans = json.loads(first.read_text())
            ans["scores"] = ans["scores"][1:]
            first.write_text(json.dumps(ans))
            (rd / "screening_scores.json").unlink()
            code, out = run("screen-merge", rd)
            self.assertEqual(code, 0, out)
            self.assertIn("missing - re-dispatch", out)
            code, out = run("screen-build", rd, rd / "screening_scores.json")
            self.assertEqual(code, 2, out)
            self.assertIn("C01", out)
        finally:
            shutil.rmtree(tmp)


class TestNegativeFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.rd = build_good(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_every_counter_example_fails_its_check(self):
        cases = sorted((FIX / "neg").glob("*.json"))
        self.assertGreaterEqual(len(cases), 15)
        files = {"bib": "step3_bibliometrics.json", "gate": "step3_gate.json", "scores": "screening_scores.json",
                 "shortlist": "step3_shortlist.json", "overrides": "_human/search_overrides.json"}
        for path in cases:
            case = json.loads(path.read_text())
            with self.subTest(case=path.stem):
                rd = self.tmp / f"c_{path.stem}"
                shutil.copytree(self.rd, rd)
                f = rd / files[case["target"]]
                if not f.exists():
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_text(json.dumps({"entries": []}))
                f.write_text(json.dumps(apply3(json.loads(f.read_text()), case["ops"])))
                cfg = json.loads((rd / "step0_session_config.json").read_text())
                fs = it_screen.run_checks(cfg, rd, case["unit"])
                codes = {x["code"] for x in fs if x["level"] == case.get("level", "ERROR")}
                self.assertIn(case["expect"], codes, f"{path.stem}: {case['why']} - got {sorted(codes)}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
