#!/usr/bin/env python3
"""Tests for the planning block's P4 attack-type Related Work (it_plan.py: attack-prefill, attack-render, attack-check
R01-R12; rules references/planning/P4-attack.md), offline. A generation is taken from the A7.R fixture's Q_001 (section 9
hands over T1 smithetal2020#A1 and T2 parketal2019#C1), given test_p1's argument and the P3 fixture tree, and attacked by
tests/fixtures/planning/p4/good_attack.json. One counter-example per check code, in NEG below.

  python3 .claude/skills/ai-scientist-ideate/scripts/tests/planning/test_p4_attack.py
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1]
FIX = SCRIPTS / "tests" / "fixtures" / "planning"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SCRIPTS / "tests"))
sys.path.insert(0, str(SCRIPTS / "tests" / "fusion"))
import it_plan  # noqa: E402
from test_a7d_decon import TOOLS, run  # noqa: E402
from test_a7r_recon import build_good  # noqa: E402
from test_p1_gap2hypo import p1_argument  # noqa: E402


def ok(*args):
    code, out = run(*args, tool=TOOLS)
    assert code == 0, out
    return out


def tgt(p, tid):
    return next(t for t in p["targets"] if t["id"] == tid)


def para(p, role):
    return next(x for x in p["related_work"] if x["role"] == role)


NEG = {
    "R01": lambda p, a: tgt(p, "T2").update(claim_units=["parketal2019#C1", "smithetal2020#A1"]),
    "R02": lambda p, a: tgt(p, "T1").update(papers=["parketal2019"]),
    "R03": lambda p, a: para(p, "T2").update(text=para(p, "T2")["text"] + " This refutes their account."),
    "R04": lambda p, a: tgt(p, "T1").update(lands_on=["L4"]),
    "R05": lambda p, a: tgt(p, "T1").update(if_miss={"leaf": "L2", "say": "x"}),
    "R06": lambda p, a: para(p, "T2").update(text=para(p, "T2")["text"].replace(", from the abstract only,", "")),
    "R07": lambda p, a: para(p, "T1").update(text=para(p, "T1")["text"].replace("E2 tests", "The study tests")),
    "R08": lambda p, a: para(p, "closest").update(text=para(p, "closest")["text"] + " See also [ghostetal2030]."),
    "R09": lambda p, a: tgt(p, "T2").update(concede=""),
    "R10": lambda p, a: (tgt(p, "T1").update(weakness={"collision": "X0003", "type": "agree", "axes": []}, added_because="x"),
                         tgt(p, "T1").update(id="T9"), para(p, "T1").update(role="T9")),
}
LEVEL = {"R03": "WARN", "R09": "WARN"}


class Attack(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.rd = build_good(self.tmp)
        ok("question-take", self.rd, "Q_001")
        self.gd = self.rd / "gen_1"
        (self.gd / "argument.json").write_text(json.dumps(p1_argument()))
        shutil.copy(FIX / "p3" / "good_tree.json", self.gd / "decision_tree.json")
        ok("tree-render", self.gd, "--project")
        shutil.copy(FIX / "p4" / "good_attack.json", self.gd / "attack_plan.json")
        ok("attack-render", self.gd)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def check(self, gd=None, *extra):
        code, out = run("attack-check", gd or self.gd, "--json", *extra, tool=TOOLS)
        return code, json.loads(out[: out.rindex("]") + 1])

    def test_good_plan_passes(self):
        code, fs = self.check()
        self.assertEqual(code, 0, fs)
        self.assertEqual(fs, [], fs)
        t = json.loads((self.gd / "decision_tree.json").read_text())
        self.assertEqual(next(l for l in t["leaves"] if l["id"] == "L2")["targets_hit"], ["T1", "T2"])
        rw = (self.gd / "related_work.md").read_text()
        self.assertTrue(rw.startswith("Cleaning studies"))
        ok("tree-check", self.gd)                      # targets_hit does not make the tree stale

    def test_idea_must_carry_the_plan_text(self):
        rw = (self.gd / "related_work.md").read_text().strip()
        (self.gd / "idea_draft.json").write_text(json.dumps({"Related Work": rw}))
        code, fs = self.check(None, "--idea", str(self.gd / "idea_draft.json"))
        self.assertEqual(code, 0, fs)
        (self.gd / "idea_draft.json").write_text(json.dumps({"Related Work": rw + " Edited by hand."}))
        code, fs = self.check(None, "--idea", str(self.gd / "idea_draft.json"))
        self.assertTrue([f for f in fs if f["code"] == "R07" and "verbatim" in f["text"]], fs)

    def test_prefill(self):
        ok("attack-prefill", self.gd)
        sk = json.loads((self.gd / "attack_plan.draft.json").read_text())
        self.assertEqual([t["id"] for t in sk["targets"]], ["T1", "T2"])
        self.assertEqual(sk["targets"][0]["weapon"], ["E2"])
        self.assertIn("smithetal2020#L1", sk["targets"][0]["concede_candidates"], "its own limitation units")
        self.assertEqual(sk["targets"][0]["lands_on"], ["L2"])
        self.assertEqual(sk["targets"][0]["if_miss"]["leaf"], "L3")

    def test_staleness(self):
        a = json.loads((self.gd / "argument.json").read_text())
        a["claims"][0]["statement"] += " (revised)"
        (self.gd / "argument.json").write_text(json.dumps(a))
        code, fs = self.check()
        self.assertTrue([f for f in fs if f["code"] == "R11"], fs)

    def test_tree_must_know_the_landings(self):
        t = json.loads((self.gd / "decision_tree.json").read_text())
        for l in t["leaves"]:
            l.pop("targets_hit", None)
        (self.gd / "decision_tree.json").write_text(json.dumps(t))
        code, fs = self.check()
        self.assertTrue([f for f in fs if f["code"] == "R12"], fs)

    def test_abstract_first_target(self):
        p = json.loads((self.gd / "attack_plan.json").read_text())
        tgt(p, "T1")["order"], tgt(p, "T2")["order"] = 2, 1
        (self.gd / "attack_plan.json").write_text(json.dumps(p))
        code, fs = self.check()
        self.assertTrue([f for f in fs if f["code"] == "R06" and "first target" in f["text"]], fs)
        tgt(p, "T2")["fulltext_tried"] = "A6 top-up 2026-10-18: paywalled, no preprint"
        (self.gd / "attack_plan.json").write_text(json.dumps(p))
        code, fs = self.check()
        self.assertFalse([f for f in fs if f["code"] == "R06"], fs)

    def test_a_handed_target_is_attacked_or_dropped(self):
        p = json.loads((self.gd / "attack_plan.json").read_text())
        p["targets"] = [x for x in p["targets"] if x["id"] != "T2"]
        tgt(p, "T1")["order"] = 1
        p["related_work"] = [x for x in p["related_work"] if x["role"] != "T2"]
        (self.gd / "attack_plan.json").write_text(json.dumps(p))
        ok("attack-render", self.gd)
        code, fs = self.check()
        self.assertTrue([f for f in fs if f["code"] == "R01" and "neither attacked" in f["text"]], fs)
        p["dropped"] = [{"id": "T2", "why": "no experiment of this design varies the cleaning method"}]
        (self.gd / "attack_plan.json").write_text(json.dumps(p))
        ok("attack-render", self.gd)
        code, fs = self.check()
        self.assertFalse([f for f in fs if f["code"] == "R01" and f["level"] == "ERROR"], fs)

    def test_an_undeliverable_attack_warns(self):
        t = json.loads((self.gd / "decision_tree.json").read_text())
        for b in next(n for n in t["nodes"] if n["id"] == "N2")["branches"]:
            b["prior"] = {"supported": "unlikely", "refuted": "unlikely", "uninformative": "likely"}[b["kind"]]
        (self.gd / "decision_tree.json").write_text(json.dumps(t))
        ok("attack-render", self.gd)
        code, fs = self.check()
        self.assertTrue([f for f in fs if f["code"] == "R04" and f["level"] == "WARN" and "carry about" in f["text"]], fs)

    def test_a_target_lost_since_round_1_needs_its_row(self):
        p = json.loads((self.gd / "attack_plan.json").read_text())
        r1 = json.loads(json.dumps(p))
        r1["targets"].append({**r1["targets"][0], "id": "T7"})
        (self.gd / "attack_plan_r1.json").write_text(json.dumps(r1))
        code, fs = self.check()
        self.assertTrue([f for f in fs if f["code"] == "R13" and "T7" in f["text"]], fs)

    def test_argument_check_sees_stale_planning_files(self):
        a = json.loads((self.gd / "argument.json").read_text())
        a["claims"][0]["warrant"] += " (revised)"
        (self.gd / "argument.json").write_text(json.dumps(a))
        code, out = run("argument-check", self.gd, "--no-idea", "--json", tool=TOOLS)
        res = json.loads(out[out.index("{"): out.rindex("}") + 1])
        c28 = [f for f in res["errors"] if f["check"] == "C28"]
        self.assertTrue([f for f in c28 if "decision_tree.json" in f["text"]], res["errors"])
        self.assertTrue([f for f in c28 if "attack_plan.json" in f["text"]], res["errors"])

    def test_every_counter_example_fails_with_its_code(self):
        for code_, fn in NEG.items():
            with self.subTest(code_):
                g = self.rd / f"gen_neg_{code_}"
                shutil.copytree(self.gd, g)
                p = json.loads((g / "attack_plan.json").read_text())
                fn(p, None)
                (g / "attack_plan.json").write_text(json.dumps(p))
                run("attack-render", g, tool=TOOLS)
                code, fs = self.check(g)
                lvl = LEVEL.get(code_, "ERROR")
                self.assertTrue([f for f in fs if f["code"] == code_ and f["level"] == lvl], f"{code_}: {fs}")

    def test_every_code_has_a_counter_example(self):
        emitted = set(re.findall(r'add\("(?:ERROR|WARN)", "(R\d\d)"', (SCRIPTS / "it_plan.py").read_text()))
        self.assertEqual(emitted - set(NEG) - {"R11", "R12", "R13"}, set())


if __name__ == "__main__":
    unittest.main(verbosity=1)
