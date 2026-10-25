#!/usr/bin/env python3
"""Tests for what the fusion block hands the planning block beyond the question itself (PLAN_ideate_planning §5,
F-M1-M3 and F-M5): a question's optional section 9 (targets, rival accounts, magnitudes), `questions-handover`, the
index keys and `question-take`'s copy into gen_k/question.json. Offline; builds on the A7.R fixture, whose Q_001
carries a section 9.

  python3 .claude/skills/ai-scientist-ideate/scripts/tests/planning/test_p0_handover.py
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
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "tests" / "fusion"))
import it_recon  # noqa: E402
from test_a7d_decon import TOOLS, run  # noqa: E402
from test_a7r_recon import build_good, check  # noqa: E402


def ok(*args):
    code, out = run(*args, tool=TOOLS)
    assert code == 0, out
    return out


def drop_section9(rd: Path) -> None:
    p = rd / "questions" / "Q_001.md"
    p.write_text(re.sub(r"\n## 9\. For the planning block.*\Z", "\n", p.read_text(), flags=re.S))


class Handover(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.rd = build_good(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_section9_passes_and_reaches_the_index(self):
        code, fs = check(self.rd)
        self.assertEqual(code, 0, fs)
        self.assertFalse([f for f in fs if f["code"] in ("Y11", "Y12", "Y13")], fs)
        q = json.loads((self.rd / it_recon.INDEX).read_text())["questions"][0]
        self.assertEqual([t["id"] for t in q["targets"]], ["T1", "T2"])
        self.assertEqual(q["rival_accounts"][0]["basis"], ["X0001"])
        self.assertEqual(q["magnitudes"][0]["exp_id"], "smithetal2020#E1")

    def test_prefill_lists_the_sides_axes_and_rows(self):
        out = ok("questions-handover", self.rd, "Q_001")
        self.assertIn("smithetal2020#A1", out)
        c = json.loads((self.rd / "knowledge" / "_work" / "B35" / "handover_Q_001.json").read_text())
        by = {t["unit"]: t for t in c["targets"]}
        self.assertEqual(len(by), len(c["targets"]), "one entry per unit, its collisions listed inside")
        self.assertEqual([(x["id"], x["role"]) for x in by["smithetal2020#A1"]["collisions"]],
                         [("X0002", "holder")], "the #A side holds the premise")
        roles = {x["id"]: x["role"] for x in by["parketal2019#C1"]["collisions"]}
        self.assertEqual(roles, {"X0002": "challenger", "X0001": "side"}, "the gap's other collision is listed too")
        self.assertEqual(by["parketal2019#C1"]["evidence_level"], "abstract")
        self.assertNotIn("smithetal2020#C1", [x["unit"] for x in c["claims_without_collision"]],
                         "a claim that sits in a conflict collision is not a loose claim")
        self.assertIn("measure-definition", [a["axis"] for a in c["axes"]])
        self.assertIn("D_draft_RejectionVsICA", [L["line"] for L in c["debate_lines"]])
        self.assertTrue({"parketal2019#E1", "smithetal2020#E1"} <= {m["exp_id"] for m in c["magnitudes"]})

    def test_take_copies_the_handover(self):
        ok("question-take", self.rd, "Q_001")
        qj = json.loads((self.rd / "gen_1" / "question.json").read_text())
        self.assertTrue(qj["handover"])
        self.assertEqual([t["id"] for t in qj["targets"]], ["T1", "T2"])
        self.assertEqual(qj["magnitudes"][0]["value"], "+4.2 pp accuracy after rejection")

    def test_absent_section9_is_a_warning_and_leaves_the_index_alone(self):
        drop_section9(self.rd)
        ok("questions-index", self.rd)
        code, fs = check(self.rd)
        self.assertEqual(code, 0, fs)
        self.assertTrue([f for f in fs if f["code"] == "Y11" and f["level"] == "WARN"], fs)
        q = json.loads((self.rd / it_recon.INDEX).read_text())["questions"][0]
        self.assertNotIn("targets", q, "an older question adds no keys (Y08 keeps older indexes current)")
        ok("question-take", self.rd, "Q_001")
        qj = json.loads((self.rd / "gen_1" / "question.json").read_text())
        self.assertFalse(qj["handover"])
        self.assertNotIn("targets", qj)

    def test_malformed_section9_is_an_error(self):
        p = self.rd / "questions" / "Q_001.md"
        p.write_text(p.read_text().replace('"targets": [', '"targets": [[', 1))
        code, fs = check(self.rd)
        self.assertEqual(code, 1)
        self.assertTrue([f for f in fs if f["code"] == "Y11" and "does not parse" in f["msg"]], fs)

    def test_overreach_weakness(self):
        p = self.rd / "questions" / "Q_001.md"
        t = p.read_text().replace('"weakness": {"collision": "X0001", "type": "conflict", "axes": ["claim-strength", "method-config"]}',
                                  '"weakness": {"overreach": "parketal2019#C1"}')
        p.write_text(t)
        code, fs = check(self.rd)
        self.assertTrue([f for f in fs if f["code"] == "Y11" and "overreach" in f["msg"]], "C1 is not marked overreach")


    def _edit(self, old, new):
        p = self.rd / "questions" / "Q_001.md"
        t = p.read_text()
        self.assertIn(old, t)
        p.write_text(t.replace(old, new, 1))
        code, out = run("recon-check", self.rd, "--unit", "B3.5", "--json", tool=TOOLS)
        return code, json.loads(out[: out.rindex("]") + 1])

    def test_challenger_is_not_a_target(self):
        code, fs = self._edit('"claim_units": ["smithetal2020#A1"], "strength": null,\n     "weakness": {"collision": "X0002"',
                              '"claim_units": ["smithetal2020#A1"], "strength": null,\n     "weakness": {"collision": "X0001"')
        self.assertTrue([f for f in fs if f["code"] == "Y11" and "on a side" in f["msg"]], fs)

    def test_premise_target_must_hold_it(self):
        code, fs = self._edit('{"id": "T1", "papers": ["smithetal2020"], "claim_units": ["smithetal2020#A1"], "strength": null,\n'
                              '     "weakness": {"collision": "X0002", "type": "assumption-challenged", "axes": ["measure-definition"]},\n'
                              '     "evidence_level": "full"',
                              '{"id": "T1", "papers": ["parketal2019"], "claim_units": ["parketal2019#C1"], "strength": "may",\n'
                              '     "weakness": {"collision": "X0002", "type": "assumption-challenged", "axes": ["measure-definition"]},\n'
                              '     "evidence_level": "abstract"')
        self.assertTrue([f for f in fs if f["code"] == "Y11" and "holds the premise" in f["msg"]], fs)

    def test_weakness_axes_are_the_collisions(self):
        code, fs = self._edit('"axes": ["claim-strength", "method-config"]', '"axes": ["population"]')
        self.assertTrue([f for f in fs if f["code"] == "Y11" and "axes_differ" in f["msg"]], fs)

    def test_rival_on_the_varied_axis(self):
        code, fs = self._edit('"varies": ["measure-definition"]', '"varies": ["claim-strength"]')
        self.assertTrue([f for f in fs if f["code"] == "Y12" and "the question varies" in f["msg"]], fs)

    def test_rival_basis_kinds_and_unrecorded(self):
        code, fs = self._edit('"basis": ["X0001"]', '"basis": ["smithetal2020#E1"]')
        self.assertTrue([f for f in fs if f["code"] == "Y12" and "only collision" in f["msg"]], fs)
        code, fs = self._edit('"basis": ["smithetal2020#E1"]', '"basis": [], "unrecorded": "only in the narrowed note"')
        self.assertEqual(code, 0, fs)
        self.assertTrue([f for f in fs if f["code"] == "Y12" and f["level"] == "WARN"], fs)

    def test_varies_off_the_collisions_warns(self):
        code, fs = self._edit('"varies": ["measure-definition"]', '"varies": ["population"]')
        self.assertEqual(code, 0, fs)
        self.assertTrue([f for f in fs if f["code"] == "Y12" and f["level"] == "WARN" and "none of the question" in f["msg"]], fs)

    def test_neighbour_numbers_need_the_absence_named(self):
        code, fs = self._edit('"value": "+4.2 pp accuracy after rejection"}',
                              '"value": "+4.2 pp accuracy after rejection", "relation": "neighbour"}')
        self.assertTrue([f for f in fs if f["code"] == "Y13" and "magnitude_absent" in f["msg"]], fs)
        code, fs = self._edit('"magnitudes": [', '"magnitude_absent": "label differences by class", "magnitudes": [')
        self.assertEqual(code, 0, fs)

    def test_abandoned_question_is_passed_over(self):
        ok("question-take", self.rd, "Q_001")
        code, out = run("consume", self.rd, "--question", "Q_001", tool=TOOLS)
        self.assertEqual(code, 1, "consume needs --idea or --abandoned")
        ok("consume", self.rd, "--question", "Q_001", "--abandoned", "T09: the uninformative branch stays likely with n = 4")
        led = json.loads((self.rd / "step0_session_config.json").read_text())["consumed"]
        self.assertEqual((led[-1]["status"], led[-1]["idea"]), ("abandoned", None))
        code, out = run("question-next", self.rd, tool=TOOLS)
        self.assertEqual(code, 1, "the only question is abandoned: nothing left to take")
        code, out = run("consume", self.rd, "--question", "Q_001", "--idea", "x", tool=TOOLS)
        self.assertEqual(code, 1, out)
        self.assertIn("abandoned", out)

    def test_abstract_only_targets_reach_the_fulltext_candidates(self):
        out = ok("tier1", self.rd, "--targets")
        self.assertIn("parketal2019", out)
        c = json.loads((self.rd / "step3_tier1_candidates.json").read_text())
        self.assertEqual([x["citation_key"] for x in c["candidates"]], ["parketal2019"])
        import it_recon
        self.assertEqual(it_recon.abstract_targets(self.rd)[0]["questions"], ["Q_001:T2"])


class UnitStubs(unittest.TestCase):
    def test_every_counter_example_pointer_names_a_real_test(self):
        """the planning cards' neg/*.json are pointers (units check needs a file); the counter-example itself is built in
        the named test - which must exist"""
        stubs = sorted((SCRIPTS / "tests" / "fixtures" / "planning").glob("p*/neg/*.json"))
        self.assertTrue(stubs)
        for f in stubs:
            by = json.loads(f.read_text())["exercised_by"]
            path, _, name = by.partition("::")
            src = (SCRIPTS / path.split(" ")[0]).read_text()
            if name:
                self.assertRegex(src, rf"def {re.escape(name.rsplit('.', 1)[-1])}\(", f.name)

if __name__ == "__main__":
    unittest.main(verbosity=1)
