#!/usr/bin/env python3
"""Tests for A7.X collide, B3.c lens collisions and B3 gaps (it_collide.py; rules references/fusion/F3-collide.md),
offline. Builds on the A7.A fixture (test_a7a_align.build_good), then gives the two evidence papers a shared dataset and
method family and two coordinates (tests/fixtures/fusion/a7x/good/coords.json) so that every paper x paper candidate type
but shared-assumption appears; judges them from good/judgements_by_type.json and sets good/gaps.json. One counter-example
per check in tests/fixtures/fusion/a7x/neg/.

  python3 .claude/skills/ai-scientist-ideate/scripts/tests/fusion/test_a7x_collide.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1]
FIX = SCRIPTS / "tests" / "fixtures" / "fusion" / "a7x"
A7A = SCRIPTS / "tests" / "fixtures" / "fusion" / "a7a"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))
import it_collide  # noqa: E402
from test_a7a_align import build_good as build_align  # noqa: E402
from test_a7d_decon import TOOLS, apply_ops, run  # noqa: E402

ORDER = ["same-coords", "assumption-vs-claim", "numbers", "lineage"]


def ok(*args):
    code, out = run(*args, tool=TOOLS)
    assert code == 0, out
    return out


def build_candidates(tmp: Path) -> Path:
    rd = build_align(tmp)
    ad = rd / "knowledge" / "_work" / "A7D" / "answers"
    s = json.loads((ad / "smithetal2020.json").read_text())
    s["experiments"][0]["data"].append({"name": "BNCI 2014-001"})
    (ad / "smithetal2020.json").write_text(json.dumps(s))
    p = json.loads((ad / "parketal2019.json").read_text())
    p["experiments"][0].update(data=[{"name": "BNCI 2014-001"}], split="10-fold CV over trials",
                               headline="+3 pp accuracy after cleaning", method_family=["ica", "artifact-rejection"])
    (ad / "parketal2019.json").write_text(json.dumps(p))
    ok("decon-merge", rd, "--revise", "fixture: a shared dataset")
    ok("align-set", rd, A7A / "good" / "vocab.json", "--reason", "records revised")
    ok("align-coords", rd, "--apply", FIX / "good" / "coords.json")
    decon = sorted((rd / "knowledge" / "decon").glob("*.json"))
    ok("build-methods", rd, rd / "knowledge" / "methods_matrix_input.json", *decon)
    ok("collide-candidates", rd)
    return rd


def answer_all(rd: Path) -> None:
    ok("collide-plan", rd)
    batch = json.loads((rd / it_collide.WORK / "batch_001.json").read_text())
    by_type = json.loads((FIX / "good" / "judgements_by_type.json").read_text())
    cands = sorted(batch["candidates"], key=lambda c: ORDER.index(c["type"]))
    ans = {"model": "claude-opus-5-5", "judgements": [{"candidate": c["id"], "relations": by_type[c["type"]]} for c in cands]}
    (rd / it_collide.WORK / "answers" / "batch_001.json").write_text(json.dumps(ans))
    ok("collide-merge", rd)


def build_good(tmp: Path) -> Path:
    rd = build_candidates(tmp)
    answer_all(rd)
    ok("gaps-set", rd, FIX / "good" / "gaps.json")
    return rd


def check(rd):
    code, out = run("collide-check", rd, "--json", tool=TOOLS)
    return code, json.loads(out[: out.rindex("]") + 1])


def apply_case(rd: Path, case: dict) -> None:
    cand = {c["type"]: c["id"] for c in json.loads((rd / it_collide.CANDS).read_text())["candidates"]}
    logp = rd / it_collide.LOG
    for o in case["ops"]:
        target = o.get("target") or case["target"]
        v = json.loads(json.dumps(o.get("value")).replace('"@assumption-vs-claim"', json.dumps(cand.get("assumption-vs-claim"))))
        o = {**o, "value": v}
        if target in ("log", "log_add"):
            recs = [json.loads(l) for l in logp.read_text().splitlines() if l.strip()]
            if target == "log_add":
                recs.append(o["value"])
            else:
                apply_ops(recs, [o])
            logp.write_text("".join(json.dumps(r) + "\n" for r in recs))
        elif target == "coords":
            p = rd / "knowledge" / "alignment.json"
            p.write_text(json.dumps(apply_ops(json.loads(p.read_text()), [{**o, "path": "coords." + o["path"]}])))
        elif target == "gaps":
            p = rd / it_collide.GAPS
            p.write_text(json.dumps(apply_ops(json.loads(p.read_text()), [o])))
        elif target == "gaps_md":
            p = rd / it_collide.GAPS_MD
            p.write_text(p.read_text() + o["value"])
        else:
            raise ValueError(target)


class Good(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.rd = build_good(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_check_passes(self):
        code, fs = check(self.rd)
        self.assertEqual(code, 0, fs)

    def test_candidate_types(self):
        c = json.loads((self.rd / it_collide.CANDS).read_text())
        self.assertEqual(sorted(x["type"] for x in c["candidates"]), sorted(ORDER))
        avc = next(x for x in c["candidates"] if x["type"] == "assumption-vs-claim")
        self.assertEqual(avc["members"], ["parketal2019#C1", "smithetal2020#A1"], "the assumption against other papers' claims")

    def test_log_and_projection(self):
        recs = it_collide.log(self.rd)
        self.assertEqual([r["result"] for r in recs], ["conflict", "assumption-challenged", "agree", "extends"])
        self.assertEqual(recs[1]["sides"][0]["quote"], "whose labels we treat as ground truth for all comparisons")
        self.assertEqual(recs[0]["evidence_level"], "mixed")
        note = (self.rd / "knowledge" / "_notes" / "smithetal2020.md").read_text()
        dis = [l for l in note.splitlines() if l.startswith("Disagrees with:")]
        self.assertEqual(len(dis), 2)
        self.assertTrue(all("parketal2019" in l for l in dis))
        self.assertEqual(run("decon-check", self.rd, tool=TOOLS)[0], 0, "the note is still its record's rendering")
        ok("concept-index", self.rd)
        ci = json.loads((self.rd / "knowledge" / "concept_index.json").read_text())
        self.assertEqual(len(ci["signals"]["disagreements"]), 2)

    def test_plan_after_merge_is_empty(self):
        ok("collide-plan", self.rd)
        self.assertEqual(json.loads((self.rd / it_collide.WORK / "plan.json").read_text())["unjudged"], 0)

    def test_gap_view(self):
        md = (self.rd / it_collide.GAPS_MD).read_text()
        self.assertIn("GAP_001", md)
        self.assertIn("composite = 4 × 0.40 + 4 × 0.30 + 4 × 0.30 = 4.00", md)
        doc = json.loads((self.rd / it_collide.GAPS).read_text())
        self.assertEqual(doc["ranked"], ["GAP_001"])


class Flow(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.rd = build_candidates(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_refused_judgement_writes_nothing(self):
        ok("collide-plan", self.rd)
        batch = json.loads((self.rd / it_collide.WORK / "batch_001.json").read_text())
        c = next(x for x in batch["candidates"] if x["type"] == "same-coords")
        ans = {"model": "m", "judgements": [{"candidate": c["id"], "relations": [
            {"result": "conflict", "sides": ["parketal2019#C1", "smithetal2020#C1"], "axes_differ": ["none"], "reason": "x"}]}]}
        (self.rd / it_collide.WORK / "answers" / "batch_001.json").write_text(json.dumps(ans))
        code, out = run("collide-merge", self.rd, tool=TOOLS)
        self.assertEqual(code, 1, out)
        self.assertIn("H04", out)
        self.assertEqual(it_collide.log(self.rd), [])

    def test_revision_supersedes(self):
        answer_all(self.rd)
        ans_p = self.rd / it_collide.WORK / "answers" / "batch_001.json"
        ans = json.loads(ans_p.read_text())
        ans["judgements"] = ans["judgements"][2:3]          # numbers: agree -> independent
        ans["judgements"][0]["relations"] = [{"result": "independent", "sides": [], "reason": "different subsets of BNCI"}]
        ans_p.write_text(json.dumps(ans))
        code, out = run("collide-merge", self.rd, "--revise", "re-read the BNCI subsets", tool=TOOLS)
        self.assertEqual(code, 0, out)
        cur = it_collide.current(it_collide.log(self.rd))
        self.assertEqual(sorted(r["result"] for r in cur), ["assumption-challenged", "conflict", "extends", "independent"])
        self.assertEqual(it_collide.log(self.rd)[-1]["supersedes"], ["X0003"])

    def test_a_repeated_relation_is_kept_once(self):
        ok("collide-plan", self.rd)
        batch = json.loads((self.rd / it_collide.WORK / "batch_001.json").read_text())
        by_type = {c["type"]: c["id"] for c in batch["candidates"]}
        same = [{"result": "agree", "sides": ["parketal2019#E1", "smithetal2020#E1"], "axes_differ": [], "reason": "both gain on BNCI"}]
        ans = {"model": "m", "judgements": [{"candidate": by_type["numbers"], "relations": same},
                                            {"candidate": by_type["lineage"], "relations": same}]}
        (self.rd / it_collide.WORK / "answers" / "batch_001.json").write_text(json.dumps(ans))
        out = ok("collide-merge", self.rd)
        self.assertIn("1 repeat a relation", out)
        recs = it_collide.log(self.rd)
        self.assertEqual(recs[1]["duplicate_of"], recs[0]["collision_id"])
        self.assertEqual(len(it_collide.current(recs)), 1)
        self.assertEqual(len(it_collide.current(recs, keep_duplicates=True)), 2)

    def test_same_data_is_flagged(self):
        answer_all(self.rd)
        I = it_collide.inputs(self.rd)
        agree = next(r for r in it_collide.log(self.rd) if r["result"] == "agree")
        self.assertEqual(it_collide.same_data(I, agree), ["dataset:bnci-2a"])

    def test_retired_gap_id_is_never_reused(self):
        answer_all(self.rd)
        ok("gaps-set", self.rd, FIX / "good" / "gaps.json")
        g = json.loads((FIX / "good" / "gaps.json").read_text())
        g["gaps"][0]["id"] = "GAP_002"
        p = self.tmp / "g2.json"
        p.write_text(json.dumps(g))
        ok("gaps-set", self.rd, p)
        self.assertEqual(json.loads((self.rd / it_collide.GAPS).read_text())["retired"], ["GAP_001"])
        g["gaps"][0]["id"] = "GAP_001"
        p.write_text(json.dumps(g))
        code, out = run("gaps-set", self.rd, p, tool=TOOLS)
        self.assertEqual(code, 1, out)
        self.assertIn("retired", out)


class PlansApart(unittest.TestCase):
    def test_lens_plan_leaves_paper_batches_alone(self):
        with tempfile.TemporaryDirectory() as t:
            rd = build_candidates(Path(t))
            ok("collide-plan", rd)
            ok("collide-plan", rd, "--lens")
            self.assertTrue((rd / it_collide.WORK / "batch_001.json").exists())

    def test_a_candidate_with_only_repeated_relations_is_judged(self):
        with tempfile.TemporaryDirectory() as t:
            rd = build_good(Path(t))
            logp = rd / it_collide.LOG
            recs = [json.loads(l) for l in logp.read_text().splitlines() if l.strip()]
            recs[-1]["duplicate_of"] = recs[0]["collision_id"]         # its only relation repeats another candidate's
            logp.write_text("".join(json.dumps(r) + "\n" for r in recs))
            self.assertEqual(it_collide.plan(rd)["unjudged"], 0)


class NotShared(unittest.TestCase):
    def test_placeholder_dataset_makes_no_numbers_candidate(self):
        """Two papers whose rows both say 'own MI EEG' (a not-shared placeholder) report on different data: no
        `numbers` candidate may pair them (F2: placeholders stay out of the field's comparisons)."""
        tmp = Path(tempfile.mkdtemp())
        try:
            rd = build_candidates(tmp)
            ad = rd / "knowledge" / "_work" / "A7D" / "answers"
            for k in ("smithetal2020", "parketal2019"):
                a = json.loads((ad / f"{k}.json").read_text())
                a["experiments"][0]["data"] = [{"name": "own MI EEG"}]
                a["experiments"][0]["headline"] = "+3 pp accuracy"
                a["experiments"][0]["split"] = "10-fold CV over trials"
                (ad / f"{k}.json").write_text(json.dumps(a))
            ok("decon-merge", rd, "--revise", "fixture: placeholder data in both")
            ok("align-set", rd, A7A / "good" / "vocab.json", "--reason", "records revised")
            ok("align-coords", rd, "--apply", FIX / "good" / "coords.json")
            ok("build-methods", rd, rd / "knowledge" / "methods_matrix_input.json", *sorted((rd / "knowledge" / "decon").glob("*.json")))
            ok("collide-candidates", rd)
            cands = json.loads((rd / "knowledge" / "collision_candidates.json").read_text())
            rows = cands.get("candidates") if isinstance(cands, dict) else cands
            self.assertFalse([c for c in rows if c["type"] == "numbers"])
        finally:
            shutil.rmtree(tmp)


class Units(unittest.TestCase):
    def test_cap_is_shared_across_types(self):
        mk = lambda t, n: [{"type": t, "papers": ["a", "b"], "key": f"{t}{i}"} for i in range(n)]
        paper = mk("assumption-vs-claim", 101) + mk("same-coords", 83) + mk("shared-assumption", 21) + mk("lineage", 42)
        kept, cut = it_collide.share_cap(paper, 150)
        from collections import Counter
        self.assertEqual(Counter(c["type"] for c in kept),
                         {"assumption-vs-claim": 44, "same-coords": 43, "lineage": 42, "shared-assumption": 21})
        self.assertEqual(len(cut), 97)
        self.assertEqual(it_collide.share_cap(paper, 400), (paper, []))
        self.assertEqual(it_collide.share_cap(paper, 0)[0], [])

    def test_empty_cells_shared_across_datasets(self):
        cells = [[ds, fm] for ds in ("A", "B", "C") for fm in ("ica", "asr", "guideline", "lof") * 4]
        by_name = {("method-family", f): f"method-family:{f}" for f in ("ica", "asr", "lof")}
        out = it_collide.empty_cells({"aggregates": {"dataset_family_empty_cells": cells}}, by_name)
        from collections import Counter
        self.assertEqual(Counter(ds for ds, _ in out), {"A": 10, "B": 10, "C": 10})
        self.assertNotIn("guideline", {fm for _, fm in out}, "a set-aside word is not a family")

    def test_lens_candidates(self):
        I = {"lens": {"on_coords": {"dataset:bnci": {"on_disk": "no", "why": "x"},
                                    "method-family:deep": {"affordable": "no", "why": "GPU-days"}}},
             "al": {"vocab": {"concepts": [{"id": "dataset:bnci", "kind": "dataset", "name": "BNCI"},
                                           {"id": "method-family:deep", "kind": "method-family", "name": "deep nets"}]}},
             "mm": {"aggregates": {"conventions_full_text": {"dataset": [{"item": "BNCI", "status": "convention", "share": 0.6,
                                                                          "papers": ["a", "b"]}]},
                                   "dataset_family_empty_cells": [["BNCI", "deep nets"]]}},
             "rows": {"a#E1": {"exp_id": "a#E1", "evidence": "full-text", "data": [{"name": "BNCI"}], "method_family": ["deep"]}}}
        out = it_collide.lens_candidates(I)
        self.assertEqual([c["type"] for c in out], ["convention-vs-lens", "empty-cell"])
        self.assertEqual(out[0]["members"], ["convention:dataset:BNCI", "lens:dataset:bnci", "lens:method-family:deep"])

    def test_quantity_joins_normalisation_variants(self):
        ax = lambda m, c="construct:x": {"axes": {"construct": c, "measure": m, "population": "unstated", "data": "unstated",
                                                   "split": "n/a", "method_family": "unstated"}}
        coords = {"a#C1": ax("measure:alpha-db", "construct:outcome"), "b#C1": ax("measure:alpha-change", "construct:prep")}
        units = {"a#C1": {"id": "a#C1", "kind": "claim", "paper": "a", "year": 2024},
                 "b#C1": {"id": "b#C1", "kind": "claim", "paper": "b", "year": 2014}}
        vocab = {"concepts": [{"id": "measure:alpha-db", "kind": "measure", "quantity": "alpha-band-power"},
                              {"id": "measure:alpha-change", "kind": "measure", "quantity": "alpha-band-power"}]}
        I = {"al": {"coords": coords, "vocab": vocab}, "units": units, "rows": {}}
        got = [c for c in it_collide.paper_candidates(I) if c["type"] == "same-coords"]
        self.assertEqual([(c["key"], c["members"]) for c in got], [("measure=q:alpha-band-power", ["a#C1", "b#C1"])])
        I["al"]["vocab"] = {"concepts": [{"id": "measure:alpha-db", "kind": "measure"}, {"id": "measure:alpha-change", "kind": "measure"}]}
        self.assertEqual([c for c in it_collide.paper_candidates(I) if c["type"] == "same-coords"], [],
                         "without a shared quantity the two papers never meet")

    def test_retired_records_leave_the_current_set(self):
        recs = [{"collision_id": "X0001", "candidate": "K1", "result": "agree", "sides": []},
                {"collision_id": "X0002", "candidate": "K2", "result": "conflict", "sides": []},
                {"collision_id": "X0003", "candidate": None, "result": "retired", "retires": ["X0001"], "sides": []}]
        self.assertEqual([r["collision_id"] for r in it_collide.current(recs)], ["X0002"])

    def test_criterion_from_several_units_of_one_paper(self):
        I = {"units": {"h#C1": {"paper": "h", "kind": "claim", "basis": "full-text", "year": 2020},
                       "h#C4": {"paper": "h", "kind": "claim", "basis": "full-text", "year": 2020},
                       "z#A2": {"paper": "z", "kind": "assumption", "basis": "full-text", "year": 2026}},
             "rows": {}, "recs": {}, "al": {}, "lens": {}}
        cand = {"type": "assumption-vs-claim", "members": ["h#C1", "h#C4", "z#A2"]}
        rel = lambda sides: [{"result": "criterion-unmet", "sides": sides, "axes_differ": ["split-unit"], "reason": "r"}]
        self.assertEqual(it_collide.judgement_problems(I, cand, rel(["h#C1", "h#C4", "z#A2"]), "m"), [])
        self.assertTrue(it_collide.judgement_problems(I, cand, rel(["h#C1", "z#A2", "h#C4"]), "m"), "the criterion units come first")

    def test_rank_ties_by_novelty(self):
        g = lambda i, n, f: {"id": i, "move": "apply-wider", "severity": 4, "novelty": n, "feasibility": f}
        self.assertEqual([x["id"] for x in it_collide.rank([g("GAP_001", 3, 5), g("GAP_002", 5, 3)])], ["GAP_002", "GAP_001"])

    def test_rank_tie_break(self):
        g = lambda i, m, s, n, f: {"id": i, "move": m, "severity": s, "novelty": n, "feasibility": f}
        a = g("GAP_001", "apply-wider", 4, 4, 4)       # 4.00, extension
        b = g("GAP_002", "cause", 4, 4, 3)             # 3.70, contradiction, within 0.3
        c = g("GAP_003", "add-evidence", 5, 5, 5)      # 5.00
        self.assertEqual([x["id"] for x in it_collide.rank([a, b, c])], ["GAP_003", "GAP_002", "GAP_001"])


class Ranking(unittest.TestCase):
    g = staticmethod(lambda i, m, s, n, f: {"id": i, "move": m, "severity": s, "novelty": n, "feasibility": f})

    def test_exactly_point_three_is_a_tie(self):
        a = self.g("GAP_003", "confirm-assumed", 4, 4, 3)     # 3.70
        b = self.g("GAP_008", "part-whole", 4, 3, 3)          # 3.40, contradiction: 0.30 below - a tie
        self.assertEqual([x["id"] for x in it_collide.rank([a, b])], ["GAP_008", "GAP_003"])

    def test_order_does_not_depend_on_input_order(self):
        x = self.g("X", "cause", 3, 4, 4)            # 3.60? 1.2+1.2+1.2 = 3.60, contradiction
        y = self.g("Y", "apply-wider", 5, 3, 3)      # 3.80
        z = self.g("Z", "apply-wider", 3, 5, 5)      # 4.20
        import itertools
        orders = {tuple(g["id"] for g in it_collide.rank(list(p))) for p in itertools.permutations([x, y, z])}
        self.assertEqual(len(orders), 1)


class Negative(unittest.TestCase):
    def test_every_counter_example_fails_with_its_code(self):
        cases = sorted((FIX / "neg").glob("*.json"))
        self.assertTrue(cases)
        tmp = Path(tempfile.mkdtemp())
        try:
            base = build_good(tmp / "base")
            for f in cases:
                case = json.loads(f.read_text())
                with self.subTest(f.stem):
                    rd = tmp / f.stem / base.name
                    shutil.copytree(base, rd)
                    apply_case(rd, case)
                    code, fs = check(rd)
                    hits = [x for x in fs if x["code"] == case["expect"] and x["level"] == case["level"]]
                    self.assertTrue(hits, f"{f.stem}: expected {case['level']} {case['expect']}, got {fs}")
                    self.assertEqual(code, 1, f.stem)
        finally:
            shutil.rmtree(tmp)

    def test_every_code_has_a_counter_example(self):
        import re
        src = (SCRIPTS / "it_collide.py").read_text()
        emitted = set(re.findall(r'"([HW]\d\d)"', src)) | set(re.findall(r'f?"([HW]\d\d) ', src))
        covered = {json.loads(f.read_text())["expect"] for f in (FIX / "neg").glob("*.json")}
        self.assertEqual(emitted - covered, set())


if __name__ == "__main__":
    unittest.main(verbosity=1)
