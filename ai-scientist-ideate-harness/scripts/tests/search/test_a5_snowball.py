#!/usr/bin/env python3
"""Tests for A5 snowball (it_snowball.py; rules references/search/A5-snowball.md), offline: a fake OpenAlex citation
graph and a fake Semantic Scholar take an A3-finished fixture topic through the snowball, then A3 again on the
additions. One counter-example per handoff check lives in tests/fixtures/search/a5/neg/*.json.

  python3 .claude/skills/ai-scientist-ideate/scripts/tests/search/test_a5_snowball.py
"""

from __future__ import annotations

import asyncio
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
FIX = SCRIPTS / "tests" / "fixtures" / "search" / "a5"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import it_ledger  # noqa: E402
import it_snowball  # noqa: E402
from test_a1_frame import apply_ops  # noqa: E402
from test_a3_screen import build_good as build_a3, fake_fetch as a3_fetch, screen  # noqa: E402


def run(*args):
    p = subprocess.run([sys.executable, str(TOOLS), *map(str, args)], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def _inv(text: str) -> dict:
    inv = {}
    for i, w in enumerate(text.split()):
        inv.setdefault(w, []).append(i)
    return inv


def work(wid, title, abstract, doi, year=2018, refs=(), authors=("Ada Lovelace", "Alan Turing")):
    return {"id": f"https://openalex.org/{wid}", "doi": f"https://doi.org/{doi}", "title": title,
            "publication_year": year, "publication_date": f"{year}-03-01", "type": "article", "is_retracted": False,
            "language": "en", "cited_by_count": 50, "citation_normalized_percentile": {"value": 0.8},
            "counts_by_year": [], "referenced_works": [f"https://openalex.org/{r}" for r in refs],
            "authorships": [{"author": {"display_name": a}} for a in authors],
            "abstract_inverted_index": _inv(abstract), "primary_location": {}}


# outside the collection: one classic three included papers cite (backward), one two cite (below the threshold),
# one the two-seed citers all cite (co-citation), citers of two or more seeds (forward), a citer of one seed (dropped,
# and its references are not counted for co-citation)
EXT = {
    "W_EXT1": work("W_EXT1", "Independent component analysis of EEG artifact sources",
                   "We study EEG artifact handling with independent component analysis on scalp recordings", "10.9/ext1", 2009),
    "W_EXT2": work("W_EXT2", "Blind source separation of EEG artifact mixtures",
                   "We study EEG artifact handling by blind source separation", "10.9/ext2", 2011),
    "W_CO": work("W_CO", "A generic toolbox for signal statistics",
                 "Statistics toolbox routines for arbitrary time series data", "10.9/co", 2012),
}
CITERS = {
    "W_C1": work("W_C1", "Deep EEG artifact detection across many cohorts",
                 "We study EEG artifact handling with deep networks on large cohorts", "10.9/c1", 2024, refs=["W_CO"]),
    "W_C2": work("W_C2", "Muscle artifact atlas for EEG", "We study EEG artifact handling of muscle", "10.9/c2", 2023, refs=["W_CO"]),
    "W_C3": work("W_C3", "Line noise in EEG", "We study EEG artifact handling of line noise", "10.9/c3", 2023, refs=["W_CO"]),
    "W_C4": work("W_C4", "Ocular EEG artifact review", "We study EEG artifact handling of eye blinks", "10.9/c4", 2022, refs=["W_CO"]),
    "W_C5": work("W_C5", "A single-seed citer of the autoreject paper", "We study EEG artifact handling once",
                 "10.9/c5", 2021, refs=["W_CO", "W_ONE"]),
}
CITES = {"W_AUTO": ["W_C1", "W_C2", "W_C4", "W_C5"], "W_PREP": ["W_C1", "W_C2", "W_C3"], "W_FASTER": ["W_C1", "W_C3", "W_C4"],
         "W_05.026": ["W_C1"], "W_2022.1": ["W_C1"]}
EXTRA_REFS = {"10.1016/j.neuroimage.2017.06.030": ["W_EXT1", "W_EXT2"], "10.3389/fninf.2015.00016": ["W_EXT1", "W_EXT2"],
              "10.1016/j.jneumeth.2010.07.015": ["W_EXT1"]}
AUTHORS = {"10.1016/j.neuroimage.2017.06.030": ["Mainak Jas", "Denis A. Engemann", "Yousra Bekhti"]}
BY_DOI = {str(w["doi"]).removeprefix("https://doi.org/"): w for w in {**EXT, **CITERS}.values()}


def graph_fetch(url, rd=None):
    filt = unquote(re.search(r"filter=([^&]+)", url).group(1))
    if filt.startswith("cites:"):
        wid = filt.split(",")[0].split(":", 1)[1]
        return {"results": [CITERS[c] for c in CITES.get(wid, [])]}
    if filt.startswith("openalex:") and "/sources?" not in url:
        return {"results": [EXT[i] for i in filt.split(":", 1)[1].split("|") if i in EXT]}
    out = a3_fetch(url, rd)
    if filt.startswith("doi:"):
        dois = filt.split(":", 1)[1].split("|")
        for w in out["results"]:
            d = str(w["doi"]).removeprefix("https://doi.org/")
            w["referenced_works"] = w["referenced_works"] + [f"https://openalex.org/{r}" for r in EXTRA_REFS.get(d, [])]
            if d in AUTHORS:
                w["authorships"] = [{"author": {"display_name": a}} for a in AUTHORS[d]]
        out["results"] += [BY_DOI[d] for d in dois if d in BY_DOI]
    return out


it_snowball.SIMILAR_RETRY_WAIT = 0        # the retry after a 429 waits 120 s in a real run


class FakeS2:
    def __init__(self, ok=True, fail_first=0):
        self.ok, self.calls, self.fail_first = ok, [], fail_first

    async def call(self, tool, params):
        self.calls.append(tool)
        if tool == "scholar_recommend":
            if not self.ok or self.calls.count(tool) <= self.fail_first:
                return {"_text": "Error: Rate limit exceeded (429)."}
            return {"papers": [
                {"title": "Artifact subspace reconstruction for mobile EEG", "authors": ["Chang C"], "year": 2020,
                 "doi": "10.9/asr", "abstract": "We study EEG artifact handling in mobile recordings",
                 "semantic_scholar_id": "S2ASR"},
                {"title": "Autoreject: Automated artifact rejection for MEG and EEG data", "authors": ["Jas M"],
                 "year": 2017, "doi": "10.1016/j.neuroimage.2017.06.030"}]}       # already in the collection
        if tool == "scholar_snowball":
            return {"references": None}
        raise AssertionError(tool)


def snowball(rd, server=None, round_no=1):
    cfg = json.loads((rd / "step0_session_config.json").read_text())
    return asyncio.run(it_snowball.run_snowball(server or FakeS2(), cfg, rd, "x@example.com", fetch=graph_fetch,
                                                round_no=round_no, embedder=None))


def build_after_round1(tmp: Path) -> Path:
    tmp.mkdir(parents=True, exist_ok=True)
    rd = build_a3(tmp, fetch=graph_fetch)
    snowball(rd)
    return rd


def build_good(tmp: Path) -> Path:
    """A3 -> A5 round 1 -> A3 on the additions: the final shortlist A4 mints keys on."""
    rd = build_after_round1(tmp)
    screen(rd, graph_fetch)
    return rd


class TestRules(unittest.TestCase):
    def test_threshold(self):
        self.assertEqual(it_snowball.threshold(6), 3)
        self.assertEqual(it_snowball.threshold(297), 6)
        self.assertEqual(it_snowball.fallback_threshold(10), 3)
        self.assertEqual(it_snowball.fallback_threshold(3), 2)


class TestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.rd = build_after_round1(cls.tmp / "r1")
        cls.sb = json.loads((cls.rd / "step2b_snowball_papers.json").read_text())
        cls.by_title = {p["title"]: p for p in cls.sb["papers"]}
        (cls.tmp / "fin").mkdir()
        cls.fin = cls.tmp / "fin" / "topic_research"
        shutil.copytree(cls.rd, cls.fin)
        shutil.copy(cls.rd.parent / "topic.md", cls.fin.parent / "topic.md")
        screen(cls.fin, graph_fetch)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_directions(self):
        ext1 = self.by_title["Independent component analysis of EEG artifact sources"]
        self.assertEqual(ext1["snowball_direction"], ["backward"])
        self.assertEqual(ext1["cocited_by_included"], 3)
        self.assertNotIn("Blind source separation of EEG artifact mixtures", self.by_title)        # 2 < 3
        co = self.by_title["A generic toolbox for signal statistics"]
        self.assertEqual(co["snowball_direction"], ["cocitation"])
        self.assertEqual(co["cocited_with_seeds"], 4)                       # C1-C4; the one-seed citer C5 does not count
        r = self.sb["rounds"][0]
        self.assertEqual((r["status"]["cocitation"]["counted_from_citers"], r["threshold_cocitation"]), (4, 3))
        c1 = self.by_title["Deep EEG artifact detection across many cohorts"]
        self.assertEqual(c1["snowball_direction"], ["forward"])
        self.assertEqual(len(c1["cites_seeds"]), 5)
        self.assertEqual(len(self.by_title["Muscle artifact atlas for EEG"]["cites_seeds"]), 2)
        self.assertNotIn("A single-seed citer of the autoreject paper", self.by_title)          # one seed only
        sim = self.by_title["Artifact subspace reconstruction for mobile EEG"]
        self.assertEqual(sim["snowball_direction"], ["similar"])
        self.assertEqual(sum(1 for p in self.sb["papers"] if p["title"].startswith("Autoreject")), 0)

    def test_ids_and_record(self):
        reg = [json.loads(l) for l in (self.rd / "_state/paper_ids.jsonl").read_text().splitlines()]
        a5 = {e["id"] for e in reg if e["minted_by"] == "A5"}
        self.assertEqual(a5, {p["id"] for p in self.sb["papers"]})
        r = self.sb["rounds"][0]
        self.assertEqual(r["threshold"], 3)
        self.assertEqual(set(r["truncated"]), {"backward", "cocitation", "forward", "similar"})
        self.assertEqual(r["status"]["forward"]["seeds"], ["paper_002", "paper_004", "paper_007", "paper_006", "paper_001", "paper_003"])
        self.assertTrue(all(p["found_via"] == "snowball" for p in self.sb["papers"]))
        code, out = run("a5-check", self.rd)
        self.assertEqual(code, 0, out)

    def test_round_rules(self):
        with self.assertRaises(SystemExit):
            snowball(self.rd)                                   # A3 has not screened the additions (stale)
        tmp = Path(tempfile.mkdtemp())
        try:
            rd = tmp / "topic_research"
            shutil.copytree(self.fin, rd)
            shutil.copy(self.fin.parent / "topic.md", tmp / "topic.md")
            with self.assertRaises(SystemExit):
                snowball(rd)                                    # round 1 already ran
            kept = {p["id"] for p in json.loads((rd / "step3_shortlist.json").read_text())["papers"]}
            r1 = {p["id"] for p in json.loads((rd / "step2b_snowball_papers.json").read_text())["papers"]}
            out = snowball(rd, round_no=2)                      # round 1 grew the included set well past 10%
            self.assertEqual([r["round"] for r in out["rounds"]], [1, 2])
            self.assertEqual(out["rounds"][1]["included_before"], len(kept & r1))
            with self.assertRaises(SystemExit):
                snowball(rd, round_no=3)
        finally:
            shutil.rmtree(tmp)

    def test_redo_when_a_seed_is_excluded(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            rd = tmp / "topic_research"
            shutil.copytree(self.fin, rd)
            shutil.copy(self.fin.parent / "topic.md", tmp / "topic.md")
            self.assertEqual(it_ledger.unit_state(rd, "A5")["state"], "done")   # its own additions screened: current
            r1 = json.loads((rd / "step2b_snowball_papers.json").read_text())["rounds"][0]
            seed = r1["status"]["forward"]["seeds"][0]
            (rd / "_human").mkdir()
            (rd / "_human/search_overrides.json").write_text(json.dumps(
                {"entries": [{"kind": "exclude", "id": seed, "reason": "not scalp EEG", "by": "kyc"}]}))
            code, out = run("screen-build", rd, rd / "screening_scores.json")
            self.assertEqual(code, 0, out)
            st = it_ledger.unit_state(rd, "A5")
            self.assertEqual(st["state"], "stale")
            self.assertIn("snowball_basis", st["why"])
            out = snowball(rd)                                  # stale: round 1 is redone, not refused
            self.assertEqual([r["round"] for r in out["rounds"]], [1])
            self.assertNotIn(seed, out["rounds"][0]["status"]["forward"]["seeds"])
            self.assertEqual(len({p["id"] for p in out["papers"]}), len(out["papers"]))
            old_ids = {p["id"] for p in json.loads((self.fin / "step2b_snowball_papers.json").read_text())["papers"]}
            screen(rd, graph_fetch)                             # A3 on the new additions: dropped works withdrawn
            sc = json.loads((rd / "screening_scores.json").read_text())
            dropped = old_ids - {p["id"] for p in out["papers"]}
            self.assertTrue(dropped)                            # the excluded seed's citers leave
            self.assertTrue(old_ids & {p["id"] for p in out["papers"]})   # the rest are found again, same ids
            self.assertEqual({w["id"] for w in sc.get("withdrawn") or []}, dropped)
            self.assertEqual(run("a3-check", rd)[0], 0)
            self.assertEqual(it_ledger.unit_state(rd, "A5")["state"], "done")   # and stays current after its loop
        finally:
            shutil.rmtree(tmp)

    def test_seed_basis_ignores_its_own_feedback(self):
        """A5's additions cite search papers and move their composites; a search paper crossing the inclusion line
        that way is A5's own loop. A judgement or a person's decision on a search paper is a new input."""
        tmp = Path(tempfile.mkdtemp())
        try:
            rd = tmp / "topic_research"
            shutil.copytree(self.fin, rd)
            base = it_snowball.seed_basis(rd)
            sl = json.loads((rd / "step3_shortlist.json").read_text())
            sl["papers"] = [p for p in sl["papers"] if p.get("found_via") == "snowball" or p is not sl["papers"][0]]
            (rd / "step3_shortlist.json").write_text(json.dumps(sl))           # inclusion moved, no judgement did
            self.assertEqual(it_snowball.seed_basis(rd), base)
            pid = json.loads((self.fin / "step3_shortlist.json").read_text())["papers"][0]["id"]
            (rd / "_human").mkdir()
            (rd / "_human/search_overrides.json").write_text(json.dumps(
                {"entries": [{"kind": "exclude", "id": pid, "reason": "not scalp EEG", "by": "kyc"}]}))
            self.assertNotEqual(it_snowball.seed_basis(rd), base)
        finally:
            shutil.rmtree(tmp)

    def test_rescreen_keeps_the_floor(self):
        sl = json.loads((self.fin / "step3_shortlist.json").read_text())
        ids = {p["id"] for p in sl["papers"]}
        co = self.by_title["A generic toolbox for signal statistics"]["id"]
        self.assertNotIn(co, ids)                               # relevance 2: FLOOR, though composite may pass
        self.assertIn(self.by_title["Independent component analysis of EEG artifact sources"]["id"], ids)
        code, out = run("a5-check", self.fin)
        self.assertEqual(code, 0, out)
        self.assertGreaterEqual(it_snowball.growth(self.fin), 0.10)
        res = (self.fin / "step3_screening_results.md").read_text()
        self.assertIn("FLOOR", res)

    def test_cut_from_backward_enters_by_cocitation_only(self):
        """A work over backward's cap that the co-citation pool takes carries that route alone (N04 counts caps)."""
        import copy as _copy
        tmp = Path(tempfile.mkdtemp())
        saved_cap, saved = it_snowball.BACKWARD_CAP, _copy.deepcopy(CITERS)
        try:
            for k in ("W_C1", "W_C2", "W_C3"):                  # three two-seed citers also cite the backward classic
                CITERS[k]["referenced_works"].append("https://openalex.org/W_EXT1")
            it_snowball.BACKWARD_CAP = 0
            rd = build_after_round1(tmp / "x")
            sb = json.loads((rd / "step2b_snowball_papers.json").read_text())
            ext1 = next(p for p in sb["papers"] if p["title"].startswith("Independent component analysis"))
            self.assertEqual(ext1["snowball_direction"], ["cocitation"])
            self.assertEqual(ext1["cocited_by_included"], 3)                 # it did qualify for backward
            self.assertEqual(run("a5-check", rd)[0], 0)
        finally:
            it_snowball.BACKWARD_CAP = saved_cap
            CITERS.clear()
            CITERS.update(saved)
            shutil.rmtree(tmp)

    def test_similar_degrades(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            rd = tmp / "c"
            shutil.copytree(self.rd, rd)
            (rd / "step2b_snowball_papers.json").unlink()
            # A3 is stale without the file it screened: rebuild the A3 view of the search-only collection
            screen(rd, graph_fetch)
            s2 = FakeS2(ok=False)
            out = snowball(rd, s2)
            self.assertEqual(out["rounds"][0]["status"]["similar"]["status"], "skipped")
            self.assertEqual(s2.calls.count("scholar_recommend"), 2)            # §15 G4: one retry after the 429
            self.assertIn("similar-skipped", [c["code"] for c in out["caveats"]])
            self.assertEqual(run("a5-check", rd)[0], 0)
        finally:
            shutil.rmtree(tmp)

    def test_similar_retried_after_a_429(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            rd = tmp / "c"
            shutil.copytree(self.rd, rd)
            (rd / "step2b_snowball_papers.json").unlink()
            screen(rd, graph_fetch)
            s2 = FakeS2(fail_first=1)
            out = snowball(rd, s2)
            st = out["rounds"][0]["status"]["similar"]
            self.assertEqual((st["status"], st.get("retried")), ("ok", True))
            self.assertNotIn("similar-skipped", [c["code"] for c in out["caveats"]])
        finally:
            shutil.rmtree(tmp)


class TestNegativeFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.rd = build_after_round1(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_every_counter_example_fails_its_check(self):
        cases = sorted((FIX / "neg").glob("*.json"))
        self.assertGreaterEqual(len(cases), 10)
        for path in cases:
            case = json.loads(path.read_text())
            with self.subTest(case=path.stem):
                rd = self.tmp / f"c_{path.stem}"
                shutil.copytree(self.rd, rd)
                f = rd / "step2b_snowball_papers.json"
                if case.get("delete"):
                    f.unlink()
                else:
                    f.write_text(json.dumps(apply_ops(json.loads(f.read_text()), case["ops"])))
                cfg = json.loads((rd / "step0_session_config.json").read_text())
                fs = it_snowball.run_checks(cfg, rd)
                codes = {x["code"] for x in fs if x["level"] == case.get("level", "ERROR")}
                self.assertIn(case["expect"], codes, f"{path.stem}: {case['why']} - got {sorted(codes)}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
