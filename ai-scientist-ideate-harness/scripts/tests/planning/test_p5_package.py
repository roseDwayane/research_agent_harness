#!/usr/bin/env python3
"""Tests for the planning block's P5 packaging (it_plan.py: pack-prefill, pack-render, pack-check K01-K10; rules
references/planning/P5-package.md), offline. Builds on test_p4's generation (question Q_001, test_p1's argument, the P3
fixture tree, the P4 fixture attack plan) and packages it with tests/fixtures/planning/p5/good_packaging.json.

  python3 .claude/skills/ai-scientist-ideate/scripts/tests/planning/test_p5_package.py
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
from test_a7d_decon import TOOLS, run  # noqa: E402
from test_a7r_recon import build_good  # noqa: E402
from test_p1_gap2hypo import p1_argument  # noqa: E402


def ok(*args):
    code, out = run(*args, tool=TOOLS)
    assert code == 0, out
    return out


def sent(p, move, i=0):
    return [s for s in p["abstract"] if s["move"] == move][i]


NEG = {
    "K01": lambda p: p["abstract"].append({"move": "contribution", "text": " ".join(["word"] * 80), "sources": ["C1"]}),
    "K02": lambda p: sent(p, "approach").update(text=sent(p, "approach")["text"] + " (E2)"),
    "K03": lambda p: p["abstract"].insert(0, p["abstract"].pop(3)),
    "K05": lambda p: sent(p, "outcomes").update(sources=["L2"]),
    "K06": lambda p: p.update(title=""),
    "K07": lambda p: p["by_leaf"].pop("L3"),
    "K09": lambda p: p["short_hypothesis"].pop(),
    "K04": lambda p: sent(p, "contribution").update(text="We show that the reference must be matched between calibration and use."),
}
LEVEL = {"K04": "WARN"}


class Package(unittest.TestCase):
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
        shutil.copy(FIX / "p5" / "good_packaging.json", self.gd / "packaging.json")
        ok("pack-render", self.gd)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def check(self, gd=None, idea=True):
        extra = ["--idea", str((gd or self.gd) / "idea_draft.json")] if idea else []
        code, out = run("pack-check", gd or self.gd, "--json", *extra, tool=TOOLS)
        return code, json.loads(out[: out.rindex("]") + 1])

    def test_good_packaging_passes(self):
        code, fs = self.check()
        self.assertEqual(code, 0, fs)
        self.assertEqual(fs, [], fs)
        idea = json.loads((self.gd / "idea_draft.json").read_text())
        self.assertEqual(list(idea), ["Name", "Title", "Short Hypothesis", "Related Work", "Abstract", "Experiments",
                                      "Risk Factors and Limitations"])
        self.assertTrue(idea["Abstract"].startswith("Artifact cleaning"))
        self.assertTrue(idea["Short Hypothesis"].startswith("Why does a reference mismatch"))
        ok("attack-check", self.gd, "--idea", str(self.gd / "idea_draft.json"))

    def test_render_keeps_experiments_and_risks(self):
        p = self.gd / "idea_draft.json"
        d = json.loads(p.read_text())
        d["Experiments"], d["Risk Factors and Limitations"] = ["E2 [tests C1] crossover"], ["Single dataset: one site"]
        p.write_text(json.dumps(d))
        ok("pack-render", self.gd)
        d = json.loads(p.read_text())
        self.assertEqual(d["Experiments"], ["E2 [tests C1] crossover"])
        self.assertEqual(d["Risk Factors and Limitations"], ["Single dataset: one site"])

    def test_hand_edited_idea_is_caught(self):
        p = self.gd / "idea_draft.json"
        d = json.loads(p.read_text())
        d["Abstract"] += " Edited."
        p.write_text(json.dumps(d))
        code, fs = self.check()
        self.assertTrue([f for f in fs if f["code"] == "K08" and "Abstract" in f["text"]], fs)

    def test_stale_after_the_attack_plan_changes(self):
        a = json.loads((self.gd / "attack_plan.json").read_text())
        a["targets"][0]["concede"] += " (revised)"
        (self.gd / "attack_plan.json").write_text(json.dumps(a))
        code, fs = self.check(idea=False)
        self.assertTrue([f for f in fs if f["code"] == "K10"], fs)

    def test_electrode_names_are_not_ids(self):
        p = json.loads((self.gd / "packaging.json").read_text())
        sent(p, "approach", 1).update(text="We also estimate how far each operator moves the geometry at C3, Cz and T7.")
        (self.gd / "packaging.json").write_text(json.dumps(p))
        ok("pack-render", self.gd)
        code, fs = self.check()
        self.assertFalse([f for f in fs if f["code"] == "K02"], fs)

    def test_a_likely_methods_caveat_leaf_is_packaged(self):
        t = json.loads((self.gd / "decision_tree.json").read_text())
        n2 = next(n for n in t["nodes"] if n["id"] == "N2")
        for b in n2["branches"]:
            b["prior"] = {"supported": "possible", "refuted": "possible", "uninformative": "likely"}[b["kind"]]
        (self.gd / "decision_tree.json").write_text(json.dumps(t))
        ok("attack-render", self.gd)
        ok("pack-render", self.gd)
        code, fs = self.check()
        self.assertTrue([f for f in fs if f["code"] == "K07" and "L4 (methods-caveat" in f["text"]], fs)
        p = json.loads((self.gd / "packaging.json").read_text())
        self.assertTrue(p["tree_gate"].startswith("failed"), p["tree_gate"])

    def test_leaf_ids_leak(self):
        p = json.loads((self.gd / "packaging.json").read_text())
        sent(p, "outcomes").update(text=sent(p, "outcomes")["text"] + " (leaf L2)")
        (self.gd / "packaging.json").write_text(json.dumps(p))
        ok("pack-render", self.gd)
        code, fs = self.check()
        self.assertTrue([f for f in fs if f["code"] == "K02" and "L2" in f["text"]], fs)

    def test_pipeline_vocabulary_and_duplicate_risks(self):
        p = self.gd / "idea_draft.json"
        d = json.loads(p.read_text())
        d["Risk Factors and Limitations"] = ["Blind restatement unresolved (restatement-1): power is marginal",
                                             "Blind restatement unresolved (restatement-2): power is marginal",
                                             "If the tree ends at leaf L4, nothing is decided"]
        p.write_text(json.dumps(d))
        code, fs = self.check()
        k11 = [f["text"] for f in fs if f["code"] == "K11"]
        self.assertTrue([x for x in k11 if "vocabulary" in x], fs)
        self.assertTrue([x for x in k11 if "repeat" in x], fs)

    def test_prefill(self):
        ok("pack-prefill", self.gd)
        sk = json.loads((self.gd / "packaging.draft.json").read_text())
        mv = [s["move"] for s in sk["abstract"]]
        self.assertEqual(sorted(set(mv), key=mv.index), ["context", "gap", "approach", "outcomes", "contribution"])
        self.assertTrue(all(s["sources"] for s in sk["abstract"] if s["move"] == "outcomes"))
        self.assertIn("L2", sk["by_leaf"])
        self.assertEqual(sk["short_hypothesis"][0], p1_argument()["question"])

    def test_every_counter_example_fails_with_its_code(self):
        for code_, fn in NEG.items():
            with self.subTest(code_):
                g = self.rd / f"gen_neg_{code_}"
                shutil.copytree(self.gd, g)
                p = json.loads((g / "packaging.json").read_text())
                fn(p)
                (g / "packaging.json").write_text(json.dumps(p))
                run("pack-render", g, tool=TOOLS)
                code, fs = self.check(g)
                lvl = LEVEL.get(code_, "ERROR")
                self.assertTrue([f for f in fs if f["code"] == code_ and f["level"] == lvl], f"{code_}: {fs}")

    def test_every_code_has_a_counter_example(self):
        emitted = set(re.findall(r'add\("(?:ERROR|WARN)", "(K\d\d)"', (SCRIPTS / "it_plan.py").read_text()))
        self.assertEqual(emitted - set(NEG) - {"K08", "K10", "K11"}, set())


if __name__ == "__main__":
    unittest.main(verbosity=1)
