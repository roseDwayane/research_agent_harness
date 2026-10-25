#!/usr/bin/env python3
"""Tests for the fusion block's hand-over to the planning block (it_recon question-next / question-take, ideate_tools
consume --question, link-run), offline. Builds on the A7.R fixture (test_a7r_recon.build_good: one ready question Q_001
on GAP_001) and adds a second question on the same gap with other axes.

  python3 .claude/skills/ai-scientist-ideate/scripts/tests/fusion/test_handover.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))
from test_a7d_decon import TOOLS, run  # noqa: E402
from test_a7r_recon import build_good as build_recon  # noqa: E402


def ok(*args):
    code, out = run(*args, tool=TOOLS)
    assert code == 0, out
    return out


def add_second_question(rd: Path) -> None:
    q1 = (rd / "questions" / "Q_001.md").read_text()
    q2 = q1.replace("question: Q_001", "question: Q_002").replace("axes: [construct]", "axes: [measure]") \
           .replace("expert artifact labels as ground truth", "how artifact labels are measured")
    (rd / "questions" / "Q_002.md").write_text(q2)
    ok("questions-index", rd)


class Handover(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.rd = build_recon(self.tmp)
        add_second_question(self.rd)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_take_consume_next(self):
        out = ok("question-next", self.rd)
        self.assertIn("Q_001", out, "rank order first")
        ok("question-take", self.rd, "Q_001")
        p = self.rd / "gen_1" / "step7b_problem.md"
        self.assertTrue(p.exists())
        text = p.read_text()
        self.assertIn("generation: 1", text)
        self.assertIn("source_question: questions/Q_001.md", text)
        qj = json.loads((self.rd / "gen_1" / "question.json").read_text())
        self.assertEqual((qj["question"], qj["gap"], qj["lens_stale"]), ("Q_001", "GAP_001", False))
        # argument-check reads the study label from the copy (C21)
        code = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {str(SCRIPTS)!r}); import ideate_tools; "
                               f"print(ideate_tools._study_of(__import__('pathlib').Path({str(p)!r})))"],
                              capture_output=True, text=True)
        self.assertEqual(code.stdout.strip(), "analytic", code.stderr)
        ok("consume", self.rd, "--question", "Q_001", "--idea", "label_validity")
        led = json.loads((self.rd / "step0_session_config.json").read_text())["consumed"]
        self.assertEqual((led[-1]["question"], led[-1]["gap"]), ("Q_001", "GAP_001"))
        self.assertTrue(led[-1]["angle"].startswith("construct"))
        out = ok("question-next", self.rd)
        self.assertIn("Q_002", out, "the same gap from other axes is still open")
        code, out = run("question-take", self.rd, "Q_001", tool=TOOLS)
        self.assertEqual(code, 1, out)
        code, out = run("consume", self.rd, "--question", "Q_001", "--idea", "again", tool=TOOLS)
        self.assertEqual(code, 1, out)

    def test_abandoned_is_not_taken(self):
        q = self.rd / "questions" / "Q_002.md"
        q.write_text(q.read_text().replace("status: ready", "status: abandoned\nabandoned_reason: settled"))
        ok("questions-index", self.rd)
        code, out = run("question-take", self.rd, "Q_002", tool=TOOLS)
        self.assertEqual(code, 1, out)

    def test_gap_consume_refused_on_a_fusion_topic(self):
        code, out = run("consume", self.rd, "--gap", "GAP_001", "--angle", "measurement side", "--idea", "old_style", tool=TOOLS)
        self.assertEqual(code, 1, out)
        self.assertIn("fusion block", out)
        code, out = run("consume", self.rd, "--idea", "neither", tool=TOOLS)
        self.assertEqual(code, 1, out)

    def test_consume_records_the_generation_folder(self):
        cfg_p = self.rd / "step0_session_config.json"
        cfg = json.loads(cfg_p.read_text())
        cfg["consumed"] = [{"gap": f"GAP_00{i}", "angle": "old", "idea": f"old{i}", "generation": i} for i in (1, 2, 3)]
        cfg_p.write_text(json.dumps(cfg))
        ok("question-take", self.rd, "Q_001")                        # the first gen_k folder of this copy: gen_1
        ok("consume", self.rd, "--question", "Q_001", "--idea", "label_validity")
        led = json.loads(cfg_p.read_text())["consumed"]
        self.assertEqual(led[-1]["generation"], 1, "the folder, not the inherited ledger's length")

    def test_inherited_old_ledger_is_ignored(self):
        cfg_p = self.rd / "step0_session_config.json"
        cfg = json.loads(cfg_p.read_text())
        cfg["consumed"] = [{"gap": "GAP_001", "angle": "an old generation's angle", "idea": "old", "generation": 1}]
        cfg_p.write_text(json.dumps(cfg))
        self.assertIn("Q_001", ok("question-next", self.rd), "old GAP_001 is another gap than the fusion block's")

    def test_link_run_points_at_the_topic(self):
        ok("question-take", self.rd, "Q_001")
        ok("consume", self.rd, "--question", "Q_001", "--idea", "label_validity")
        run_dir = self.tmp / "experiments" / "run1"
        run_dir.mkdir(parents=True)
        (run_dir / "idea.json").write_text(json.dumps({"Name": "label_validity"}))
        ideas_json = self.rd.parent / (self.rd.name[: -len("_research")] + ".json")
        ideas_json.write_text("[]")
        ok("link-run", run_dir, ideas_json)
        src = json.loads((run_dir / "ideation_source.json").read_text())
        self.assertEqual(src["sota_review"], str(self.rd.resolve() / "step6_sota_review.md"))
        self.assertEqual(src["question"], "Q_001")
        self.assertTrue(src["question_file"].endswith("questions/Q_001.md"))
        self.assertTrue(src["gap_list"].endswith("step7_gaps.json"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
