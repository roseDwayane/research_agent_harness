#!/usr/bin/env python3
"""Tests for the planning block's P3 decision tree (it_plan.py: tree-prefill, tree-render [--project], tree-check
T01-T13; rules references/planning/P3-decision-tree.md), offline. The argument is tests/test_question_tools.py's
base_argument (C1 primary test on E2, E3 its control, E0 instrument, C2 an estimate on E4); the good tree is
tests/fixtures/planning/p3/good_tree.json. One counter-example per check code, in NEG below.

  python3 .claude/skills/ai-scientist-ideate/scripts/tests/planning/test_p3_tree.py
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1]
FIX = SCRIPTS / "tests" / "fixtures" / "planning" / "p3"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "tests"))
sys.path.insert(0, str(SCRIPTS / "tests" / "fusion"))
import it_plan  # noqa: E402
from test_a7d_decon import TOOLS, run  # noqa: E402
from test_question_tools import base_argument  # noqa: E402


def ok(*args):
    code, out = run(*args, tool=TOOLS)
    assert code == 0, out
    return out


def node(t, nid):
    return next(n for n in t["nodes"] if n["id"] == nid)


def branch(t, nid, kind):
    return next(b for b in node(t, nid)["branches"] if b["kind"] == kind)


def leaf(t, lid):
    return next(l for l in t["leaves"] if l["id"] == lid)


def _t01(t, a):
    t["nodes"] = [n for n in t["nodes"] if n["id"] != "N1"]
    branch(t, "N0", "pass")["next"] = "N2"


def _t02(t, a):
    for b in node(t, "N2")["branches"]:
        b["if"] = re.sub(r"\d+", "x", b["if"])
    node(t, "N2")["reads"] = "mean decoding accuracy drop"


def _t03(t, a):
    node(t, "N2")["branches"] = [b for b in node(t, "N2")["branches"] if b["kind"] != "uninformative"]
    t["leaves"] = [l for l in t["leaves"] if l["id"] != "L4"]


def _t04(t, a):                 # the positive control after the test it licenses
    branch(t, "N0", "pass")["next"] = "N2"
    branch(t, "N2", "supported")["next"] = "N1"
    branch(t, "N1", "pass").pop("next")
    branch(t, "N1", "pass")["leaf"] = "L2"
    t["nodes"] = [n for n in t["nodes"] if n["id"] != "N3"]
    t["leaves"] = [l for l in t["leaves"] if l["id"] != "L5"]


def _t05(t, a):
    branch(t, "N2", "refuted")["leaf"] = "L9"


def _t06(t, a):
    leaf(t, "L3")["claims"]["C1"] = "supported"


def _t07(t, a):
    leaf(t, "L3")["conclusion"] = leaf(t, "L2")["conclusion"]
    branch(t, "N2", "supported").pop("next")
    branch(t, "N2", "supported")["leaf"] = "L2"
    t["nodes"] = [n for n in t["nodes"] if n["id"] != "N3"]
    t["leaves"] = [l for l in t["leaves"] if l["id"] != "L5"]
    leaf(t, "L2")["claims"].pop("C2")
    leaf(t, "L3")["claims"]["C1"] = "refuted"


def _t08(t, a):
    for l in t["leaves"]:
        l["rivals"]["killed"] = [x for x in l["rivals"]["killed"] if x != "bias"]


def _t09_floor(t, a):
    a["claims"][0]["power"]["verdict"] = "underpowered"


def _t09_gate(t, a):
    branch(t, "N2", "uninformative")["prior"] = "likely"


def _t10(t, a):
    a["claims"][0]["outcomes"]["if_not"] = "something else"


def _t12(t, a):
    leaf(t, "L0").pop("then")


def _t13(t, a):
    a["claims"][0]["statement"] += " (revised)"


NEG = {"T01": _t01, "T02": _t02, "T03": _t03, "T04": _t04, "T05": _t05, "T06": _t06, "T07": _t07, "T08": _t08,
       "T09": _t09_floor, "T09b": _t09_gate, "T10": _t10, "T12": _t12, "T13": _t13}
LEVEL = {"T07": "WARN"}


class Tree(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.gd = self.tmp / "gen_1"
        self.gd.mkdir()
        (self.gd / "argument.json").write_text(json.dumps(base_argument()))
        shutil.copy(FIX / "good_tree.json", self.gd / "decision_tree.json")
        ok("tree-render", self.gd, "--project")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def check(self):
        code, out = run("tree-check", self.gd, "--json", tool=TOOLS)
        return code, json.loads(out[: out.rindex("]") + 1])

    def test_good_tree_passes(self):
        code, fs = self.check()
        self.assertEqual(code, 0, fs)
        self.assertEqual(fs, [], fs)

    def test_projection_reaches_the_argument(self):
        a = json.loads((self.gd / "argument.json").read_text())
        o = a["claims"][0]["outcomes"]
        self.assertTrue(o["if_supported"].startswith("[L2]"), o)
        self.assertIn("[L3]", o["if_not"])
        self.assertIn("[L1]", o["if_undecided"])
        self.assertTrue(a["claims"][1]["outcomes"]["if_not"].startswith("[L5]"))
        code, out = run("argument-check", self.gd, "--no-idea", "--json", tool=TOOLS)
        res = json.loads(out[out.index("{"): out.rindex("}") + 1])
        self.assertFalse([f for f in res["errors"] if f["check"] == "C6"], res["errors"])
        md = (self.gd / "decision_tree.md").read_text()
        self.assertIn("N2  E2 [tests C1]", md)
        self.assertIn("→ L3 informative-null", md)

    def test_prefill_orders_and_floors(self):
        a = base_argument()
        a["claims"][0]["power"]["verdict"] = "marginal"
        a["claims"][0]["controls"]["positive_expected"] = "equals the planted 8 points only when the unplanted drop is not negative"
        (self.gd / "argument.json").write_text(json.dumps(a))
        ok("tree-prefill", self.gd)
        sk = json.loads((self.gd / "decision_tree.draft.json").read_text())
        self.assertEqual([n["experiment"] for n in sk["nodes"]], ["E0", "E1", "E3", "E2", "E4"],
                         "instruments, the positive control, the primary test, the rest")
        n2 = next(n for n in sk["nodes"] if n["experiment"] == "E2")
        self.assertEqual({b["kind"]: b["prior_floor"] for b in n2["branches"]}["uninformative"], "likely",
                         "marginal power with no literature effect")
        n3 = next(n for n in sk["nodes"] if n["experiment"] == "E3")
        self.assertEqual({b["kind"]: b["prior_floor"] for b in n3["branches"]}["fail"], "possible")
        self.assertIn("2 points", n2["reads"])

    def test_every_counter_example_fails_with_its_code(self):
        for code_, fn in NEG.items():
            want = code_[:3]
            with self.subTest(code_):
                t = json.loads((FIX / "good_tree.json").read_text())
                a = json.loads((self.gd / "argument.json").read_text())
                fn(t, a)
                g = self.tmp / f"neg_{code_}"
                g.mkdir()
                (g / "argument.json").write_text(json.dumps(a))
                (g / "decision_tree.json").write_text(json.dumps(t))
                if code_ not in ("T10", "T13"):         # the projection and based_on of the mutated pair
                    run("tree-render", g, "--project", tool=TOOLS)
                else:
                    t2 = json.loads((self.gd / "decision_tree.json").read_text())
                    (g / "decision_tree.json").write_text(json.dumps({**t, "based_on": t2["based_on"]}))
                code, out = run("tree-check", g, "--json", tool=TOOLS)
                fs = json.loads(out[: out.rindex("]") + 1])
                lvl = LEVEL.get(want, "ERROR")
                self.assertTrue([f for f in fs if f["code"] == want and f["level"] == lvl], f"{code_}: {fs}")

    def test_every_code_has_a_counter_example(self):
        emitted = set(re.findall(r'add\("(?:ERROR|WARN)", "(T\d\d)"', (SCRIPTS / "it_plan.py").read_text()))
        covered = {c[:3] for c in NEG} | {"T11", "T14"}
        self.assertEqual(emitted - covered, set())

    def test_no_checkpoint_warns(self):
        t = json.loads((self.gd / "decision_tree.json").read_text())
        for n in t["nodes"]:
            n["checkpoint"] = False
        (self.gd / "decision_tree.json").write_text(json.dumps(t))
        code, fs = self.check()
        self.assertEqual(code, 0, fs)
        self.assertTrue([f for f in fs if f["code"] == "T11" and f["level"] == "WARN"], fs)


    def _mutate(self, fn):
        t = json.loads((self.gd / "decision_tree.json").read_text())
        a = json.loads((self.gd / "argument.json").read_text())
        fn(t, a)
        (self.gd / "argument.json").write_text(json.dumps(a))
        (self.gd / "decision_tree.json").write_text(json.dumps(t))
        run("tree-render", self.gd, "--project", tool=TOOLS)
        return self.check()

    def test_a_kind_may_repeat_with_another_if(self):
        def fn(t, a):
            node(t, "N2")["branches"].append({"kind": "refuted", "if": "mean drop <= -2 points (the opposite effect)",
                                              "leaf": "L6", "prior": "unlikely", "prior_basis": "no mechanism"})
            t["leaves"].append({"id": "L6", "claims": {"C1": "refuted"}, "conclusion": "a mismatch raises accuracy",
                                "paper": "finding", "answers_question": "whole", "rivals": {"killed": [], "alive": []}})
        code, fs = self._mutate(fn)
        self.assertEqual(code, 0, fs)

    def test_role_must_be_the_arguments(self):
        code, fs = self._mutate(lambda t, a: node(t, "N3").update(role="control",
                                branches=[{"kind": "pass", "if": "ok", "leaf": "L2", "prior": "likely"},
                                          {"kind": "fail", "if": "not ok", "leaf": "L5", "prior": "possible"}]))
        self.assertTrue([f for f in fs if f["code"] == "T05" and "has role 'descriptive'" in f["text"]], fs)

    def test_subtree_for_a_secondary_claim(self):
        def fn(t, a):
            branch(t, "N2", "supported").pop("next")
            branch(t, "N2", "supported")["leaf"] = "L2"
            leaf(t, "L2")["claims"].pop("C2")
            t["leaves"] = [l for l in t["leaves"] if l["id"] != "L5"]
            t["leaves"] += [{"id": "L7", "claims": {"C2": "estimated"}, "conclusion": "the angle is known per operator",
                             "paper": "descriptive", "answers_question": "part", "rivals": {"killed": [], "alive": []}},
                            {"id": "L8", "claims": {"C2": "imprecise"}, "conclusion": "the angle is unresolved",
                             "paper": "methods-caveat", "answers_question": "none", "rivals": {"killed": [], "alive": []}}]
            branch(t, "N3", "precise")["leaf"] = "L7"
            branch(t, "N3", "imprecise")["leaf"] = "L8"
            t["subtrees"] = ["N3"]
        code, fs = self._mutate(fn)
        self.assertEqual(code, 0, fs)
        a = json.loads((self.gd / "argument.json").read_text())
        self.assertTrue(a["claims"][1]["outcomes"]["if_supported"].startswith("[L7]"))
        md = (self.gd / "decision_tree.md").read_text()
        self.assertIn("subtree (read on every path)", md)

    def test_floor_lifted_by_a_node_above(self):
        def fn(t, a):
            a["claims"][0]["power"]["verdict"] = "underpowered"
            b = branch(t, "N2", "uninformative")
            b["prior"], b["floor_lifted_by"] = "unlikely", "N1"
            b["prior_basis"] = "N1 measures the effect of the generator's own size"
        code, fs = self._mutate(fn)
        self.assertFalse([f for f in fs if f["code"] == "T09"], fs)
        code, fs = self._mutate(lambda t, a: branch(t, "N2", "uninformative").update(floor_lifted_by="N3"))
        self.assertTrue([f for f in fs if f["code"] == "T09" and "not a node above" in f["text"]], fs)

    def test_paper_mass(self):
        mass = it_plan.paper_mass(json.loads((self.gd / "decision_tree.json").read_text()))
        self.assertAlmostEqual(sum(mass.values()), 1.0, places=6)
        self.assertLess(sum(v for k, v in mass.items() if k in it_plan.WEAK_LEAF), 0.5)

    def test_likeliest_leaf_gate(self):
        def fn(t, a):           # no single branch is likely-and-weak, yet the weak leaf is the likeliest
            for b in node(t, "N2")["branches"]:
                b["prior"] = "possible"
            branch(t, "N2", "supported")["prior"] = "unlikely"
            branch(t, "N2", "refuted")["prior"] = "unlikely"
        code, fs = self._mutate(fn)
        self.assertTrue([f for f in fs if f["code"] == "T09" and "weak outcomes" in f["text"]], fs)

    def test_conditional_wording_raises_the_control_floor(self):
        for pe in ("comes through when the unplanted drop is near zero", "only for E = 0",
                   "if it stays below m the design cannot detect it"):
            a = base_argument()
            a["claims"][0]["controls"]["positive_expected"] = pe
            n = {"experiment": "E3", "role": "control", "claims": ["C1"]}
            self.assertEqual(it_plan.prior_floor(a, n, "fail")[0], "possible", pe)

    def test_main_rival_dies_where_its_experiment_runs(self):
        def fn(t, a):
            rv = next(r for r in a["claims"][0]["rivals"] if r.get("main"))
            rv["ruled_out_by"] = "E4"           # an experiment the publishable leaves' paths do not all pass
            for l in t["leaves"]:
                if l["id"] in ("L3",):
                    l["rivals"]["killed"].append("bias")
            for l in t["leaves"]:
                if l["id"] in ("L2", "L5"):
                    l["rivals"]["killed"] = ["chance"]
        code, fs = self._mutate(fn)
        self.assertTrue([f for f in fs if f["code"] == "T08"], fs)

    def test_claim_in_no_leaf_is_flagged(self):
        def fn(t, a):
            for l in t["leaves"]:
                l["claims"].pop("C2", None)
            branch(t, "N2", "supported").pop("next")
            branch(t, "N2", "supported")["leaf"] = "L2"
            t["nodes"] = [n for n in t["nodes"] if n["id"] != "N3"]
            t["leaves"] = [l for l in t["leaves"] if l["id"] != "L5"]
        code, fs = self._mutate(fn)
        self.assertTrue([f for f in fs if f["code"] == "T10" and f["level"] == "WARN" and "C2 is in no leaf" in f["text"]], fs)

    def test_a_leaf_lost_since_round_1_needs_its_row(self):
        t = json.loads((self.gd / "decision_tree.json").read_text())
        r1 = json.loads(json.dumps(t))
        r1["leaves"].append({"id": "L9", "claims": {"C1": "supported"}, "conclusion": "a cut finding", "paper": "finding",
                             "answers_question": "part", "rivals": {"killed": [], "alive": []}})
        (self.gd / "decision_tree_r1.json").write_text(json.dumps(r1))
        code, fs = self.check()
        self.assertTrue([f for f in fs if f["code"] == "T14" and "L9" in f["text"]], fs)
        a = json.loads((self.gd / "argument.json").read_text())
        a["tradeoffs"].append({"gate": "none", "ids": ["L9"], "change": "leaf L9 cut", "because": "x", "lost": "x",
                               "still_answers_question": True, "covers_gap": True, "covers_angle": True, "why": "x"})
        (self.gd / "argument.json").write_text(json.dumps(a))
        ok("tree-render", self.gd, "--project")
        code, fs = self.check()
        self.assertFalse([f for f in fs if f["code"] in ("T14", "T13")], fs)

    def test_a_control_after_the_test_may_void_it(self):
        def fn(t, a):                 # E3 read after E2: its failure leaves C1 supported-with-caveat or undecided
            n1, n2 = node(t, "N1"), node(t, "N2")
            branch(t, "N0", "pass")["next"] = "N2"
            branch(t, "N2", "supported")["next"] = "N1"
            branch(t, "N1", "pass")["next"] = "N3"
            branch(t, "N1", "fail")["leaf"] = "L1"
            leaf(t, "L1")["claims"]["C1"] = "undecided"
        code, fs = self._mutate(fn)
        self.assertFalse([f for f in fs if f["code"] == "T06"], fs)
        code, fs = self._mutate(lambda t, a: leaf(t, "L1")["claims"].update(C1="refuted"))
        self.assertTrue([f for f in fs if f["code"] == "T06" and "undecided or" in f["text"] or
                         f["code"] == "T06" and "supported or undecided" in f["text"]], fs)


if __name__ == "__main__":
    unittest.main(verbosity=1)
