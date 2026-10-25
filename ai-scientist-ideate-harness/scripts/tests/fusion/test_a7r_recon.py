#!/usr/bin/env python3
"""Tests for A7.R reconstruct, B2 synthesis, B3.5 questions and the F.9 index / fusion map (it_recon.py; rules
references/fusion/F4-reconstruct.md), offline. Builds on the A7.X fixture (test_a7x_collide.build_good: X0001 conflict,
X0002 assumption-challenged, X0003 agree, X0004 extends, GAP_001), then lays tests/fixtures/fusion/a7r/good over it.
One counter-example per check in tests/fixtures/fusion/a7r/neg/.

  python3 .claude/skills/ai-scientist-ideate/scripts/tests/fusion/test_a7r_recon.py
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
FIX = SCRIPTS / "tests" / "fixtures" / "fusion" / "a7r"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))
import it_recon  # noqa: E402
from test_a7d_decon import TOOLS, apply_ops, run  # noqa: E402
from test_a7x_collide import build_good as build_collide  # noqa: E402


def ok(*args):
    code, out = run(*args, tool=TOOLS)
    assert code == 0, out
    return out


def build_good(tmp: Path) -> Path:
    rd = build_collide(tmp)
    g = FIX / "good"
    shutil.copytree(g / "lines", rd / "knowledge" / "lines", dirs_exist_ok=True)
    shutil.copytree(g / "body", rd / "knowledge" / "body", dirs_exist_ok=True)
    shutil.copytree(g / "questions", rd / "questions", dirs_exist_ok=True)
    shutil.copy(g / "step6_sota_review.md", rd / "step6_sota_review.md")
    shutil.copy(g / "knowledge_cards.json", rd / "knowledge_cards.json")
    ok("build-cards", rd, rd / "knowledge_cards.json")
    ok("fusion-map", rd)
    ok("questions-index", rd)
    return rd


def check(rd):
    code, out = run("recon-check", rd, "--json", tool=TOOLS)
    return code, json.loads(out[: out.rindex("]") + 1])


def apply_case(rd: Path, case: dict) -> None:
    for o in [o for o in case["ops"] if o.get("target")]:            # an op aimed at another file than the case's
        _apply(rd, o["target"], [o])
    _apply(rd, case["target"], [o for o in case["ops"] if not o.get("target")])


def _apply(rd: Path, target: str, ops: list) -> None:
    case = {"target": target, "ops": ops}
    kind, _, name = case["target"].partition(":")
    files = {"line": rd / "knowledge" / "lines" / name, "body": rd / "knowledge" / "body" / name,
             "question": rd / "questions" / name, "sota": rd / "step6_sota_review.md", "map": rd / it_recon.MAP}
    if kind in files:
        p = files[kind]
        t = p.read_text()
        for o in case["ops"]:
            if o["op"] == "replace":
                assert o["path"] in t, (case, o["path"])
                t = t.replace(o["path"], o["value"])
            else:
                t += o["value"]
        p.write_text(t)
    elif kind in ("cards", "index"):
        p = rd / ("knowledge_cards.json" if kind == "cards" else it_recon.INDEX)
        p.write_text(json.dumps(apply_ops(json.loads(p.read_text()), case["ops"])))
    elif kind == "log":
        p = rd / "knowledge" / "collisions.jsonl"
        recs = apply_ops([json.loads(l) for l in p.read_text().splitlines() if l.strip()], case["ops"])
        p.write_text("".join(json.dumps(r) + "\n" for r in recs))
    elif kind == "rm_line":
        (rd / "knowledge" / "lines" / name).unlink()
    elif kind == "add_question":
        src = (rd / "questions" / "Q_001.md").read_text().replace("question: Q_001", "question: Q_002")
        (rd / "questions" / name).write_text(src)
    else:
        raise ValueError(case["target"])


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

    def test_promotion(self):
        ok("recon-candidates", self.rd)
        p = json.loads((self.rd / it_recon.WORK / "promotion.json").read_text())
        self.assertEqual([d["collisions"] for d in p["debates"]], [["X0001"]])
        self.assertEqual(p["evolution"], [{"papers": ["parketal2019", "smithetal2020"], "collisions": ["X0004"], "size": 2}])
        self.assertEqual([f["collisions"] for f in p["findings"]], [["X0003"]])

    def test_index(self):
        idx = json.loads((self.rd / it_recon.INDEX).read_text())
        self.assertEqual(idx["ready"], 1)
        self.assertEqual(idx["target_ready"], 5)
        q = idx["questions"][0]
        self.assertEqual((q["id"], q["gap"], q["gap_rank"], q["status"]), ("Q_001", "GAP_001", 1, "ready"))
        self.assertEqual(q["screens"], {"settled": "no", "derivable": "no", "data": "yes", "larger": "yes"})
        self.assertTrue(q["research_question"].startswith("How far"))

    def test_fusion_map(self):
        m = (self.rd / it_recon.MAP).read_text()
        self.assertIn("class-correlated artifacts", m)
        self.assertIn("X0001", m)

    def test_concept_index_fusion_signals(self):
        ok("concept-index", self.rd)
        s = json.loads((self.rd / "knowledge" / "concept_index.json").read_text())["signals"]
        self.assertEqual([c["collision"] for c in s["consensus"]], ["X0003"])
        self.assertEqual([c["collision"] for c in s["premises"]], ["X0002"])
        self.assertEqual(s["collision_coverage"]["judged"], 4)
        self.assertIn("assumptions", s, "the older keys stay")

    def test_prefill(self):
        out = ok("questions-prefill", self.rd, "GAP_001")
        self.assertIn("no agree / boundary collision", out)


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
                    if case["level"] == "ERROR":
                        self.assertEqual(code, 1, f.stem)
        finally:
            shutil.rmtree(tmp)

    def test_every_code_has_a_counter_example(self):
        import re
        emitted = set(re.findall(r'F\("ERROR", "([JY]\d\d)"', (SCRIPTS / "it_recon.py").read_text()))
        covered = {json.loads(f.read_text())["expect"] for f in (FIX / "neg").glob("*.json")}
        self.assertEqual(emitted - covered, set())


if __name__ == "__main__":
    unittest.main(verbosity=1)
