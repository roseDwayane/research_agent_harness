#!/usr/bin/env python3
"""The Stage A pieces that let a local model (the harness's Ollama worker) do the model Units: code settles what
follows from the inputs - quotes copied exactly, ids, structure, the empty fields of a schema-decoded answer - and the
schemas bound the answer. Pure functions; no network, no model.

  python3 -m pytest scripts/tests/test_local_worker.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import it_common  # noqa: E402
import it_decon  # noqa: E402
import it_recon  # noqa: E402
import it_screen  # noqa: E402
import it_search  # noqa: E402

ABSTRACT = ("Sleep stage classification is essential. We propose a self-supervised learning (SSL) framework that "
            "integrates the Superlet Transform (SLT), a high-resolution time-frequency representation, with a Masked "
            "Autoencoder (MAE) architecture for robust staging.")


class TestQuoteRepair(unittest.TestCase):
    def test_a_near_copy_becomes_the_source_words(self):
        self.assertEqual(it_common.repair_quote("a self-supervised learning (SSL) framework that integrates t", ABSTRACT),
                         "a self-supervised learning (SSL) framework that integrates the")

    def test_an_ellipsis_keeps_its_longest_exact_part(self):
        got = it_common.repair_quote("We propose a self-supervised learning (SSL) framework that integrates the "
                                     "Superlet Transform (SLT) ... with a Masked Autoencoder", ABSTRACT)
        self.assertTrue(got and got.startswith("We propose a self-supervised") and got in ABSTRACT.replace("\n", " "))

    def test_nothing_is_invented(self):
        self.assertIsNone(it_common.repair_quote("deep reinforcement learning for robot arms", ABSTRACT))
        self.assertIsNone(it_common.repair_quote("two words", ABSTRACT))


class TestScreeningAnswer(unittest.TestCase):
    def test_schema_asks_one_entry_per_paper_and_no_rare_fields(self):
        s = it_screen.answer_schema(["paper_001", "paper_002"], ["EX1", "IN1"])
        sc = s["properties"]["scores"]
        self.assertEqual((sc["minItems"], sc["maxItems"]), (2, 2))
        props = sc["items"]["properties"]
        self.assertEqual(props["id"]["enum"], ["paper_001", "paper_002"])
        self.assertNotIn("duplicate_of", props)               # a schema-decoded answer fills every field it is given
        self.assertNotIn("other_reading", props)              # only when the protocol has soft criteria
        self.assertIn("other_reading", it_screen.answer_schema(["p"], ["IN1"], ["IN1"])["properties"]["scores"]
                      ["items"]["properties"])

    def test_soft_criteria_and_one_word_quotes_are_settled_by_code(self):
        paper = {"title": "Cross-subject emotion recognition", "abstract": "We evaluate on the SEED dataset."}
        e = {"id": "p1", "evidence": {"problem": "Cross-subject emotion recognition", "method": "evaluate on the",
                                      "data": "SEED", "code": "not stated"}, "rel": 4, "qual": 3,
             "decision": "exclude", "violates": ["EX2"], "rationale": "r", "other_reading": ""}
        kept = it_screen._normal(e, paper, {"EX2"})             # no reason the other reading excludes it: kept
        self.assertNotIn("violates", kept)
        self.assertIn("EX2", kept["soft_violates"])
        self.assertEqual(kept["evidence"]["data"], "not stated")      # optional evidence, no phrase: not recorded
        self.assertEqual(it_screen.evidence_problems(kept, paper), [])
        out = it_screen._normal({**e, "other_reading": "fails it too"}, paper, {"EX2"})
        self.assertEqual((out["violates"], out["both_readings"]), (["EX2"], {"EX2": "fails it too"}))

    def test_decision_settles_violates_and_quotes_are_repaired(self):
        paper = {"title": "Superlet-MAE", "abstract": ABSTRACT}
        e = {"id": "paper_002", "decision": "include", "violates": ["IN1"], "rel": 5, "qual": 4, "rationale": "x",
             "evidence": {"problem": "Sleep stage classification is essential", "method": "a self-supervised learning "
                          "(SSL) framework that integrates t", "data": "not stated", "code": "not stated"}}
        n = it_screen._normal(e, paper)
        self.assertNotIn("violates", n)                        # an included paper's violates is ignored
        self.assertEqual(it_screen.evidence_problems(n, paper), [])
        x = it_screen._normal({**e, "decision": "exclude"}, paper)
        self.assertEqual(x["violates"], ["IN1"])
        self.assertNotIn("rel", x)                             # an excluded paper is not scored


class TestDeconstruct(unittest.TestCase):
    def test_reading_text_leaves_the_reference_list_out(self):
        text = "Intro " * 400 + "\nResults hold.\n\nReferences\n[1] A. Author. Old paper. 2001.\n"
        r = it_decon.reading_text(text)
        self.assertIn("Results hold.", r)
        self.assertNotIn("[1] A. Author", r)
        self.assertEqual(it_decon.reading_text("Short. References are discussed here."),
                         "Short. References are discussed here.")    # no heading in the second half: unchanged

    def test_record_schema_by_basis(self):
        ab = it_decon.record_schema("abstract", ["IN1"])
        self.assertEqual(ab["properties"]["eligibility"]["properties"]["verdict"]["enum"], ["abstract-only"])
        self.assertEqual(ab["properties"]["experiments"]["maxItems"], 1)
        self.assertNotIn("not-done", ab["properties"]["units"]["items"]["properties"]["kind"]["enum"])
        ft = it_decon.record_schema("full-text", ["IN1"])
        self.assertIn("ineligible", ft["properties"]["eligibility"]["properties"]["verdict"]["enum"])

    def test_complete_settles_ids_structure_and_empties(self):
        ans = {"eligibility": {"verdict": "abstract-only", "reason": "no full text", "criteria": ["none"]},
               "summary": {k: "(TBD)" for k in it_decon.SUMMARY_KEYS},
               "units": [{"kind": "claim", "text": "t", "strength": "shows", "scope": {"population": "(TBD)",
                          "data": "EEG", "conditions": "(TBD)"}, "where": "abstract",
                          "quote": "We propose a self-supervised framework that integrates the Superlet Transform"},
                         {"kind": "claim", "text": "u", "strength": "may", "scope": {"population": "x", "data": "y",
                          "conditions": "z"}, "where": "abstract", "quote": "Sleep stage classification is essential"}],
               "experiments": [{"role": "proposes-method", "method_family": ["mae"], "split": "(TBD)",
                                "data": [{"name": "Sleep-EDF", "n": "(TBD)", "modality": "EEG", "preproc": "(TBD)"}],
                                "baselines": ["(TBD)"], "metrics": ["(TBD)"], "stats": "", "headline": "(TBD)",
                                "not_done": ["(TBD)"], "where": "abstract"}],
               "terms": [{"term": "MAE", "kind": "method", "definition": "", "where": "abstract"}]}
        rec = it_decon.complete(ans, "chaetal2025", "abstract", f"Superlet-MAE\n{ABSTRACT}")
        self.assertEqual([u["id"] for u in rec["units"]], ["chaetal2025#C1", "chaetal2025#C2"])
        self.assertEqual(rec["experiments"][0]["exp_id"], "chaetal2025#E1")
        self.assertEqual((rec["experiments"][0]["evidence"], rec["experiments"][0]["citation_key"]),
                         ("abstract", "chaetal2025"))
        self.assertNotIn("stats", rec["experiments"][0])        # "" is absent
        self.assertNotIn("criteria", rec["eligibility"])        # only an ineligible verdict names criteria
        self.assertNotIn("definition", rec["terms"][0])
        q = rec["units"][0]["quote"]                           # a dropped word: the source's own words instead
        self.assertTrue(q.startswith("We propose a self-supervised learning (SSL) framework"), q)
        self.assertIsNone(it_decon.quote_problem(q, it_decon.squash(ABSTRACT)))


class TestRelevanceVerdicts(unittest.TestCase):
    def test_allowed_verdicts_follow_the_rules(self):
        q = {"status": "active", "papers": 10, "on_anchor_share": 0.9, "anchor_terms_found": {}, "strategy": "primary"}
        sig = {"queries": {"Q1": q, "Q2": {**q, "papers": 0}, "Q3": {**q, "status": "retired"}},
               "new_share_latest_round": None}
        a = it_search.allowed_verdicts(sig, 0)
        self.assertEqual(a, {"Q1": ["ok", "replan", "accept-weak"], "Q2": ["replan", "accept-weak"]})
        self.assertNotIn("replan", it_search.allowed_verdicts(sig, it_search.MAX_ROUNDS - 1)["Q1"])
        rnd = it_search._normal_round({"verdicts": {"Q1": {"verdict": "ok", "reason": "r"}}})
        self.assertEqual(rnd["verdicts"], [{"query": "Q1", "verdict": "ok", "reason": "r"}])


class TestQuestionsAttach(unittest.TestCase):
    def test_section_9_is_replaced_or_appended(self):
        with tempfile.TemporaryDirectory() as t:
            rd = Path(t)
            (rd / "questions").mkdir()
            (rd / it_recon.B35).mkdir(parents=True)
            (rd / "questions" / "Q_001.md").write_text("---\nquestion: Q_001\n---\n# Problem\n\n## 8. Definitions\nx\n")
            (rd / it_recon.B35 / "s9_Q_001.md").write_text('```json\n{"targets": []}\n```\n')
            it_recon.cmd_questions_attach(type("A", (), {"research_dir": str(rd)})())
            text = (rd / "questions" / "Q_001.md").read_text()
            self.assertIn("## 8. Definitions", text)
            self.assertEqual(text.count("## " + it_recon.HANDOVER), 1)
            self.assertEqual(it_recon.handover_of(text), {"targets": []})
            (rd / it_recon.B35 / "s9_Q_001.md").write_text("## 9. For the planning block\n```json\n{\"targets\": [1]}\n```")
            it_recon.cmd_questions_attach(type("A", (), {"research_dir": str(rd)})())
            text = (rd / "questions" / "Q_001.md").read_text()
            self.assertEqual(text.count("## " + it_recon.HANDOVER), 1)
            self.assertEqual(it_recon.handover_of(text), {"targets": [1]})
            # an answer under a heading of its own, or the schema's bare object: under the section's heading, once
            (rd / it_recon.B35 / "s9_Q_001.md").unlink()
            (rd / it_recon.B35 / "s9_Q_001.json").write_text('{"targets": [2]}')
            it_recon.cmd_questions_attach(type("A", (), {"research_dir": str(rd)})())
            text = (rd / "questions" / "Q_001.md").read_text()
            self.assertEqual(text.count("## 9. "), 1)
            self.assertEqual(it_recon.handover_of(text), {"targets": [2]})
            (rd / it_recon.B35 / "s9_Q_001.json").unlink()
            (rd / it_recon.B35 / "s9_Q_001.md").write_text('## 9. Candidate evidence\n\n```json\n{"targets": [3]}\n```')
            it_recon.cmd_questions_attach(type("A", (), {"research_dir": str(rd)})())
            text = (rd / "questions" / "Q_001.md").read_text()
            self.assertEqual(text.count("## 9. "), 1)
            self.assertEqual(it_recon.handover_of(text), {"targets": [3]})


if __name__ == "__main__":
    unittest.main()


class TestCardsMerge(unittest.TestCase):
    """A Unit writes only its part of knowledge_cards.json; the others' cards are never echoed back by a model."""

    def run_tool(self, *args):
        import subprocess
        p = subprocess.run([sys.executable, str(SCRIPTS / "ideate_tools.py"), *map(str, args)], capture_output=True,
                           text=True)
        return p.returncode, p.stdout + p.stderr

    def test_an_origin_and_the_planes_are_replaced_the_rest_kept(self):
        with tempfile.TemporaryDirectory() as t:
            rd = Path(t) / "x_research"
            rd.mkdir()
            (rd / "knowledge_cards.json").write_text(json.dumps({
                "points": [{"slug": "A", "origin": "align"}, {"slug": "B", "origin": "collide"}],
                "planes": [{"n": 1, "slug": "Old"}], "methodology": {"k1": "review"}}))
            part = Path(t) / "part.json"
            part.write_text(json.dumps({"points": [{"slug": "C"}], "methodology": {"k2": "computational"}}))
            code, out = self.run_tool("cards-merge", rd, part, "--origin", "align")
            self.assertEqual(code, 0, out)
            c = json.loads((rd / "knowledge_cards.json").read_text())
            self.assertEqual(sorted((p["slug"], p["origin"]) for p in c["points"]), [("B", "collide"), ("C", "align")])
            self.assertEqual(c["methodology"], {"k1": "review", "k2": "computational"})
            part.write_text(json.dumps({"planes": [{"n": 1, "slug": "New"}]}))
            code, out = self.run_tool("cards-merge", rd, part, "--planes")
            self.assertEqual(code, 0, out)
            c = json.loads((rd / "knowledge_cards.json").read_text())
            self.assertEqual([p["slug"] for p in c["planes"]], ["New"])
            self.assertEqual(len(c["points"]), 2)
            part.write_text(json.dumps({"points": [], "extra": 1}))
            code, out = self.run_tool("cards-merge", rd, part, "--origin", "align")
            self.assertEqual(code, 2, out)
            self.assertIn("extra", out)


class TestReplan(unittest.TestCase):
    """A2.c's re-plan for a worker without commands: the tool lists what to revise, the model picks new words, the
    tool writes the revision and names the new id for `search --only`."""

    def test_brief_apply_and_a_revision_that_changes_nothing(self):
        sys.path.insert(0, str(SCRIPTS / "tests" / "search"))
        from test_a1_frame import build_good, run
        with tempfile.TemporaryDirectory() as t:
            rd = build_good(Path(t))
            (rd / "step2_relevance_check.json").write_text(json.dumps({"rounds": [{"verdicts": [
                {"query": "Q1", "verdict": "replan", "reason": "few on-topic hits"}]}]}))
            code, out = run("frame", "replan-brief", rd)
            self.assertEqual(code, 0, out)
            schema = json.loads((rd / "_state" / "A2c" / "replan.schema.json").read_text())
            self.assertEqual(schema["required"], ["Q1"])
            ans = Path(t) / "replan.json"
            cfg = json.loads((rd / "step0_session_config.json").read_text())
            old = next(q for q in cfg["queries"] if q["id"] == "Q1")["flat_query"].split()
            ans.write_text(json.dumps({"Q1": {"flat": old, "terms": {}, "reason": "same again"}}))
            code, out = run("frame", "replan-apply", rd, ans)
            self.assertEqual(code, 2, out)
            self.assertIn("repeats the query it retires", out)
            ans.write_text(json.dumps({"Q1": {"flat": ["EEG", "artefact", "removal"], "terms": {}, "reason": "r"}}))
            code, out = run("frame", "replan-apply", rd, ans)
            self.assertEqual(code, 0, out)
            new = out.split("replan-ids: ")[1].split()[0]
            cfg = json.loads((rd / "step0_session_config.json").read_text())
            q = {x["id"]: x for x in cfg["queries"]}
            self.assertEqual((q["Q1"]["status"], q["Q1"]["retired_by"]), ("retired", new))
            self.assertEqual(q[new]["flat_query"], "EEG artefact removal")
