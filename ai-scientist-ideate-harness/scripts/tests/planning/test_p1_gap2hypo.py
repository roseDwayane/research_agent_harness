#!/usr/bin/env python3
"""Tests for the planning block's P1 Gap2Hypo (it_plan.py: hypo-prefill, the checks C25-C27 inside argument-check;
rules references/planning/P1-gap2hypo.md), offline. A generation is taken from the A7.R fixture's Q_001 (gap GAP_001,
primary collision X0002 assumption-challenged -> default form `share`; section 9 hands over RA1 and smithetal2020#E1),
and given the argument of tests/test_question_tools.py with the P1 fields added.

  python3 .claude/skills/ai-scientist-ideate/scripts/tests/planning/test_p1_gap2hypo.py
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "tests"))
sys.path.insert(0, str(SCRIPTS / "tests" / "fusion"))
import it_plan  # noqa: E402
from test_a7d_decon import TOOLS, run  # noqa: E402
from test_a7r_recon import build_good  # noqa: E402
from test_question_tools import base_argument  # noqa: E402

P1_CHECKS = ("C25", "C26", "C27")


def ok(*args):
    code, out = run(*args, tool=TOOLS)
    assert code == 0, out
    return out


def p1_argument() -> dict:
    a = base_argument()
    c = a["claims"][0]
    for i, r in enumerate(c["rivals"], 1):
        r["id"] = f"R{i}"
    c["rivals"][1]["account"] = "RA1"          # the main rival is the field's own account
    c["derivation"] = {"gap": "GAP_001", "move": "confirm-assumed", "primary_collision": "X0002", "form": "share",
                       "deviation": None}
    c["power"]["literature_effect"] = "+4.2 pp after rejection [smithetal2020#E1]"
    return a


class P1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.rd = build_good(cls.tmp)
        ok("question-take", cls.rd, "Q_001")
        cls.gd = cls.rd / "gen_1"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def findings(self, arg: dict) -> list[dict]:
        (self.gd / "argument.json").write_text(json.dumps(arg))
        code, out = run("argument-check", self.gd, "--no-idea", "--json", tool=TOOLS)
        res = json.loads(out[out.index("{"): out.rindex("}") + 1])
        return [dict(f, level=lvl) for lvl, k in (("ERROR", "errors"), ("WARN", "warnings")) for f in res[k]
                if f["check"] in P1_CHECKS]

    def assert_finding(self, arg, check, level, needle):
        fs = self.findings(arg)
        self.assertTrue([f for f in fs if f["check"] == check and f["level"] == level and needle in f["text"]], fs)

    def test_good_has_no_p1_finding(self):
        self.assertEqual(self.findings(p1_argument()), [])

    def test_prefill(self):
        out = ok("hypo-prefill", self.gd)
        self.assertIn("default form: share", out)
        p = json.loads((self.gd / "p1_prefill.json").read_text())
        self.assertEqual((p["primary_collision"], p["default_form"], p["suggested_main"]), ("X0002", "share", "RA1"))
        self.assertEqual(p["modes"], ["estimate", "test"])
        self.assertEqual([r["account"] for r in p["rival_candidates"]], ["RA1"])

    def test_derivation_required(self):
        a = p1_argument()
        del a["claims"][0]["derivation"]
        self.assert_finding(a, "C25", "ERROR", "no `derivation`")

    def test_other_form_needs_a_deviation(self):
        a = p1_argument()
        a["claims"][0]["derivation"]["form"] = "moderation"
        self.assert_finding(a, "C25", "ERROR", "departs from the default 'share'")
        a["claims"][0]["derivation"]["deviation"] = "the question varies the label definition, a moderator"
        self.assertEqual(self.findings(a), [])

    def test_form_fixes_the_mode(self):
        a = p1_argument()
        a["claims"][0]["derivation"].update(form="estimate", deviation="descriptive on purpose")
        self.assert_finding(a, "C25", "ERROR", "takes mode estimate")

    def test_collision_must_be_the_questions(self):
        a = p1_argument()
        a["claims"][0]["derivation"]["primary_collision"] = "X0001"
        self.assert_finding(a, "C25", "ERROR", "not one of the question's collisions")
        a["claims"][0]["derivation"].update(primary_collision="X0002", gap="GAP_009")
        self.assert_finding(a, "C25", "ERROR", "are not the question's")

    def test_every_account_is_used_or_set_aside(self):
        a = p1_argument()
        del a["claims"][0]["rivals"][1]["account"]
        self.assert_finding(a, "C26", "ERROR", "rival account RA1")
        a["claims"][0]["derivation"]["set_aside"] = [{"account": "RA1", "why": "the hedge is ruled out by design: both "
                                                      "labellings are scored on the same wording"}]
        fs = self.findings(a)
        self.assertFalse([f for f in fs if f["level"] == "ERROR"], fs)
        self.assertTrue([f for f in fs if f["check"] == "C26" and f["level"] == "WARN"], "main rival is no account")

    def test_rival_ids(self):
        a = p1_argument()
        a["claims"][0]["rivals"][2]["id"] = "R1"
        self.assert_finding(a, "C26", "ERROR", "carries an id")

    def test_numbers_reach_direction_and_power(self):
        a = p1_argument()
        a["claims"][0]["expected_direction"]["basis"] = "unknown: nothing predicts it"
        self.assert_finding(a, "C27", "ERROR", "expected_direction is 'unknown:'")
        a = p1_argument()
        a["claims"][0]["power"]["literature_effect"] = "(TBD)"
        self.assert_finding(a, "C27", "ERROR", "literature_effect is (TBD)")

    def test_render_shows_the_derivation(self):
        (self.gd / "argument.json").write_text(json.dumps(p1_argument()))
        ok("argument-render", self.gd)
        md = (self.gd / "argument.md").read_text()
        self.assertIn("form **share**", md)
        self.assertIn("| R2 | bias | main |", md)

    def test_hypo_check_and_the_note(self):
        (self.gd / "argument.json").write_text(json.dumps(p1_argument()))
        out = ok("hypo-check", self.gd)
        self.assertIn("C25-C27 0 error(s)", out)
        code, out = run("argument-check", self.gd, "--no-idea", "--json", tool=TOOLS)
        res = json.loads(out[out.index("{"): out.rindex("}") + 1])
        self.assertTrue([n for n in res["notes"] if n["check"] == "C25" and "no finding" in n["text"]], res["notes"])
        a = p1_argument()
        del a["claims"][0]["derivation"]
        (self.gd / "argument.json").write_text(json.dumps(a))
        code, out = run("hypo-check", self.gd, tool=TOOLS)
        self.assertEqual(code, 1, out)

    def test_unrecorded_main_rival_warns(self):
        qp = self.gd / "question.json"
        keep = qp.read_text()
        try:
            q = json.loads(keep)
            q["rival_accounts"].append({"id": "RA2", "account": "block order", "basis": [], "unrecorded": "own design"})
            qp.write_text(json.dumps(q))
            a = p1_argument()
            rv = a["claims"][0]["rivals"]
            rv[1]["account"], rv[0]["account"] = "RA2", "RA1"
            self.assert_finding(a, "C26", "WARN", "no record holds")
        finally:
            qp.write_text(keep)

    def test_older_generation_is_not_checked(self):
        gd = self.rd / "gen_9"
        gd.mkdir()
        a = base_argument()
        (gd / "argument.json").write_text(json.dumps(a))
        code, out = run("argument-check", gd, "--no-idea", "--json", tool=TOOLS)
        res = json.loads(out[out.index("{"): out.rindex("}") + 1])
        self.assertFalse([f for k in ("errors", "warnings") for f in res[k] if f["check"] in P1_CHECKS], res)
        self.assertIsNone(it_plan.context(gd))


class Suggestion(unittest.TestCase):
    def test_deferred_and_unrecorded_accounts_are_not_suggested(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            rd = build_good(tmp)
            ok("question-take", rd, "Q_001")
            gd = rd / "gen_1"
            q = json.loads((gd / "question.json").read_text())
            q["rival_accounts"] = [
                {"id": "RA1", "account": "the anchor differs (left to Q_003)", "basis": ["X0001", "X0002"]},
                {"id": "RA2", "account": "a hedge", "basis": ["X0001"], "axis": "claim-strength"},
                {"id": "RA3", "account": "block order", "basis": [], "unrecorded": "own design"}]
            (gd / "question.json").write_text(json.dumps(q))
            ok("hypo-prefill", gd)
            p = json.loads((gd / "p1_prefill.json").read_text())
            self.assertEqual(p["suggested_main"], "RA2")
            self.assertEqual([r["account"] for r in p["rival_candidates"]], ["RA2", "RA1", "RA3"])
            self.assertEqual(p["varies"], ["measure-definition"], "varies reaches question.json")
        finally:
            shutil.rmtree(tmp)


class Forms(unittest.TestCase):
    def test_default_forms(self):
        f = it_plan.default_form
        self.assertEqual(f({"result": "conflict", "axes_differ": ["time-anchor"]}), "moderation")
        self.assertEqual(f({"result": "conflict", "axes_differ": ["none"]}), "adjudication")
        self.assertEqual(f({"result": "boundary"}), "interaction")
        self.assertEqual(f({"result": "untested-shared"}), "premise-test")
        self.assertEqual(f({"result": "assumption-at-stake"}), "premise-test")
        self.assertEqual(f({"result": "assumption-challenged"}), "share")
        self.assertEqual(f({"result": "criterion-unmet"}), "evaluation")
        self.assertEqual(f({"result": "extends"}), "increment")
        self.assertEqual(f({"result": "convention-vs-lens"}), "non-inferiority")
        self.assertEqual(f(None), "estimate")


if __name__ == "__main__":
    unittest.main(verbosity=1)
