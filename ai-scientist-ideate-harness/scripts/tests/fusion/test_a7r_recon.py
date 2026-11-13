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

    def test_batched_a7r1_makes_points_cards_and_patches(self):
        """recon-batches settles what the rules settle; each answer (under its schema) becomes a findings Point, a Line
        card or a patch line by recon-merge, and the A7.R1 checks pass on the result."""
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        with tempfile.TemporaryDirectory() as t:
            rd = Path(t) / self.rd.name
            shutil.copytree(self.rd, rd)
            ok("recon-candidates", rd)
            ok("recon-batches", rd)
            wd = rd / it_recon.WORK
            kinds = {}
            for f in sorted(wd.glob("r1_batch_*.json")):
                b = json.loads(f.read_text())
                kinds[b["kind"]] = b
                if b["kind"] == "point":
                    ans = {"name": "cleaning gains on BNCI", "claim_type": "empirical",
                           **{k: f"{k} from {b['collisions'][0]['id']}" for k in it_recon.POINT_FIELDS}}
                else:
                    secs = it_recon.LINE_KINDS[b["kind"]][1]
                    ans = {"card": {"title": "Does cleaning remove class-related contamination?", "endpoints": [],
                                    "sections": {h: "smithetal2020#C1 vs parketal2019#C1 (X0001)" for h in secs}}}
                jsonschema.validate(ans, json.loads((wd / "schemas" / f.name).read_text()))
                (rd / b["answer"]).parent.mkdir(parents=True, exist_ok=True)
                (rd / b["answer"]).write_text(json.dumps(ans))
            self.assertEqual(sorted(kinds), ["debate", "point"])       # the two-paper extends: a patch, by code
            out = ok("recon-merge", rd)
            self.assertIn("1 findings Point(s)", out)
            ok("cards-merge", rd, wd / "points_collide.json", "--origin", "collide")
            W = it_recon.World(rd)
            pt = W.points["P_draft_Cleaning_Gains_On_BNCI"]
            self.assertEqual((pt["origin"], pt["collisions"]), ("collide", ["X0003"]))
            self.assertEqual(W.lines["D_draft_Does_Cleaning_Remove_Class_Related_Contamination"]["fm"]["collisions"],
                             ["X0001"])
            patches = (rd / it_recon.PATCHES).read_text()
            self.assertIn("X0004", patches)                            # the two-paper chain
            self.assertIn("`smithetal2020#A1` ← assumption-challenged ←", patches)   # a premise no card holds (J04)
            self.assertEqual([f for f in it_recon.r1_problems(W) if f["level"] == "ERROR"], [])
            ok("recon-merge", rd)                                      # again: the same cards under the same ids
            self.assertEqual(sorted(it_recon.World(rd).lines), sorted(W.lines))
            self.assertEqual(json.loads((wd / "points_collide.json").read_text())["points"][0]["slug"], "Cleaning_Gains_On_BNCI")

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

    def test_a_planes_part_is_normalised_before_the_check(self):
        """Q1..Q5 keys become q1..q5; a paper named twice stays in its first Plane; a key that is no evidence paper
        goes; a paper in no Plane is left for the check to name."""
        import ideate_tools
        out = ideate_tools.normal_planes(self.rd, [
            {"n": 1, "name": "a", "member_papers": ["smithetal2020", "nosuchpaper2020"], "Q3": "X0002", "Q5": "(TBD)"},
            {"n": 2, "name": "b", "member_papers": ["smithetal2020"], "q3": "(TBD)"}])
        self.assertEqual([p["member_papers"] for p in out], [["smithetal2020"], []])
        self.assertEqual((out[0]["q3"], out[0]["q5"]), ("X0002", "(TBD)"))
        self.assertNotIn("Q3", out[0])

    def test_planes_take_their_members_from_assign(self):
        """A7.R2 under its schema: every evidence paper's Plane in `assign` (each one required), the members by code."""
        import ideate_tools
        schema = it_recon.planes_schema(it_recon.World(self.rd))
        self.assertEqual(schema["properties"]["assign"]["required"], ["parketal2019", "smithetal2020"])
        out = ideate_tools.normal_planes(self.rd, [{"n": 1, "name": "a", "slug": "Theme A", "adjacent_planes": [2, 1]},
                                                   {"n": 2, "name": "b", "slug": "Theme B"}],
                                         {"parketal2019": 1, "smithetal2020": 1})
        self.assertEqual([p["member_papers"] for p in out], [["parketal2019", "smithetal2020"], []])
        self.assertEqual(out[0]["adjacent_planes"], ["F_draft_T2_Theme_B"])          # by number -> the Plane's id
        self.assertEqual(out[0]["source_files"], ["knowledge/decon/parketal2019.json", "knowledge/decon/smithetal2020.json"])

    def test_planes_q3_and_q5_are_chosen_ids(self):
        """Q3 and Q5 under the schema are lists of the ids that count there (an independent collision is no open
        problem, a collision that does not exist is none at all); code joins them into the card's line of ids."""
        import ideate_tools
        q = it_recon.planes_schema(it_recon.World(self.rd))["properties"]["planes"]["items"]["properties"]
        self.assertIn("X0003", q["q3"]["items"]["enum"])                # an agree collision: Q3 may cite it
        self.assertNotIn("X0003", q["q5"]["items"]["enum"])             # ... but it is no open problem
        self.assertIn("X0001", q["q5"]["items"]["enum"])                # a conflict is
        out = ideate_tools.normal_planes(self.rd, [{"n": 1, "name": "a", "q3": ["X0001", "X0003"], "q5": []}])
        self.assertEqual((out[0]["q3"], out[0]["q5"]), ("X0001, X0003", "(TBD)"))

    def test_sota_tables_are_written_by_code(self):
        """B2's legend and mapping from the Planes and the cards' methodology map; a model-written mapping is replaced
        and does not make a paper cited."""
        text = (self.rd / it_recon.SOTA).read_text() + "\n## Paper-Theme Mapping\n\n| `nosuchpaper2020` | T9 | x | — |\n"
        cards = json.loads((self.rd / "knowledge_cards.json").read_text())
        out = it_recon.sota_tables(self.rd, text)
        self.assertNotIn("nosuchpaper2020", out)
        self.assertLess(out.index("## Methodology legend"), out.index("## Theme "))
        self.assertIn("| `parketal2019` | T1 | (TBD) | — |", out)
        (self.rd / "knowledge_cards.json").write_text(json.dumps({**cards, "methodology": {"parketal2019": "experimental"}}))
        try:
            out = it_recon.sota_tables(self.rd, text)
        finally:
            (self.rd / "knowledge_cards.json").write_text(json.dumps(cards))
        self.assertIn("| `parketal2019` | T1 | experimental | — |", out)
        self.assertIn("| 🔴 Red | experimental | 1 |", out)

    def test_an_id_in_another_case_is_spelled_as_its_own(self):
        W = it_recon.World(self.rd)
        pid = sorted(W.points)[0]
        out = it_recon.id_case(W, f"see {pid.upper().replace('P_DRAFT_', 'P_draft_')} and P_draft_Nosuch")
        self.assertEqual(out, f"see {pid} and P_draft_Nosuch")                 # an unknown id is left for the check

    def test_the_digest_names_what_the_corpus_has_none_of(self):
        """A quick run has no agree, conflict or extends collision: the sections that would cite them say (TBD)."""
        W = it_recon.World(self.rd)
        self.assertNotIn("Consensus", " ".join(it_recon.absent(W)))           # the fixture has a findings source
        W.cur, W.points, W.lines = {}, {}, {}
        self.assertEqual(len(it_recon.absent(W)), 3)
        self.assertIn("## None in this corpus", it_recon.digest(W, "B2"))

    def test_the_b3_digest_lists_what_w10_asks_for(self):
        import it_collide
        W = it_recon.World(self.rd)
        must = it_collide.must_account(W.cur)
        self.assertTrue(must)
        self.assertIn(f"(W10): {', '.join(must)}", it_recon.digest(W, "B3"))

    def test_the_b2_digest_lists_what_each_theme_may_cite(self):
        W = it_recon.World(self.rd)
        d = it_recon.digest(W, "B2")
        self.assertIn("## What each Theme's Consensus and Debates may cite", d)
        for pl in W.planes.values():
            for head, ids in it_recon.theme_sources(W, pl).items():
                self.assertTrue(all(it_recon.counts_for(W, head, i) for i in ids))
                self.assertIn(f"  - {head}: {', '.join(ids) or it_recon.TBD}", d)

    def test_section_9_copies_are_written_by_code(self):
        """The model picks units, collisions and accounts; papers, strength, evidence level, the weakness's type and
        axes, and the ids come from the records - a wrong copy is put right, a right one left as it is."""
        W = it_recon.World(self.rd)
        H = it_recon.handover_of((self.rd / "questions" / "Q_001.md").read_text())
        bad = json.loads(json.dumps(H))
        for t in bad["targets"]:
            t.update(id="T9", papers=[], strength="causes", evidence_level="?")
            t["weakness"].update(type="agree", axes=[])
        bad["rival_accounts"][0]["id"] = "RA7"
        self.assertEqual(it_recon.settle_handover(W, bad), H)

    def test_the_section_9_schema_takes_the_choices_of_a_good_one(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        W = it_recon.World(self.rd)
        H = it_recon.handover_of((self.rd / "questions" / "Q_001.md").read_text())
        # the schema's form: a collision and the unit on its losing or untested side (+ `also`), no copies, no ids
        mine = {**H, "targets": [{"collision": t["weakness"]["collision"], "unit": t["claim_units"][0],
                                  "also": t["claim_units"][1:], "holds": t["holds"]} for t in H["targets"]],
                "rival_accounts": [{k: v for k, v in r.items() if k != "id"} for r in H["rival_accounts"]]}
        schema = it_recon.handover_schema(W, it_recon.handover_candidates(W, "Q_001"), "GAP_001")
        jsonschema.validate(mine, schema)
        self.assertEqual(it_recon.settle_handover(W, mine), H)          # attach turns it into the rules' form
        for bad in ({"collision": "X9999"},                               # a collision the question does not reach
                    {"unit": "parketal2019#C1"}):                          # the evidence against T1's premise
            m = json.loads(json.dumps(mine))
            m["targets"][0].update(bad)
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(m, schema)
        m = json.loads(json.dumps(mine))
        m["targets"][0]["holds"] = "x" * 400                               # a text without end is cut off
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(m, schema)

    def test_a_rival_on_the_varied_axis_keeps_no_axis(self):
        """Y12: the axis the question varies is no rival's - attach leaves it out (the form Y12 names) instead of a
        revision that cannot see which `varies` the answer will choose."""
        W = it_recon.World(self.rd)
        H = it_recon.handover_of((self.rd / "questions" / "Q_001.md").read_text())
        m = json.loads(json.dumps(H))
        m["rival_accounts"][0]["axis"] = m["varies"][0]
        out = it_recon.settle_handover(W, m)
        self.assertNotIn("axis", out["rival_accounts"][0])

    def test_no_target_candidate_means_an_empty_target_list(self):
        """A question whose collisions hold no claim or assumption on a losing or untested side, and no overreach (a
        development question on matrix rows): its schema takes only `targets: []`, and Y11 WARNs instead of failing a
        list no answer could fill."""
        W = it_recon.World(self.rd)
        cand = it_recon.handover_candidates(W, "Q_001")
        none = {**cand, "targets": [], "claims_without_collision": []}
        self.assertEqual(it_recon.target_choices(none), ({}, []))
        schema = it_recon.handover_schema(W, none, "GAP_001")
        self.assertEqual(schema["properties"]["targets"]["maxItems"], 0)
        self.assertTrue(any(it_recon.target_choices(cand)))
        self.assertEqual(it_recon.handover_schema(W, cand, "GAP_001")["properties"]["targets"]["minItems"], 1)

    def test_the_b3_digest_quotes_a_full_text_side_whole_and_marks_a_row(self):
        """B3 copies a source check from the digest (W05: verbatim from the full text): a full-text side's quote is
        whole, and a matrix row's headline - a summary - is marked, with its paper's verified claim quotes."""
        W = it_recon.World(self.rd)
        cid, r = next((c, r) for c, r in sorted(W.cur.items())
                      if any(x.get("paper") and (W.records.get(x["paper"]) or {}).get("basis") == "full-text"
                             for x in r.get("sides") or []))
        side = next(x for x in r["sides"] if x.get("paper") and W.records[x["paper"]].get("basis") == "full-text")
        long = "one two three four five six seven eight nine ten " * 14
        side.update(quote=long, kind=side.get("kind"))
        d = it_recon.digest(W, "B3")
        if side.get("kind") != "row":
            self.assertIn(f'"{long.strip()}"', d)
        side["kind"] = "row"
        d = it_recon.digest(W, "B3")
        self.assertIn(f"{side['id']} · {side['paper']} · row summary (not verbatim):", d)


    def test_a_refused_question_is_asked_again_with_why(self):
        with tempfile.TemporaryDirectory() as t:
            rd = Path(t) / self.rd.name
            shutil.copytree(self.rd, rd)
            q = rd / "questions" / "Q_001.md"
            text = q.read_text()
            body = it_recon.section(text, "1. Common ground")
            q.write_text(text.replace(body, "\nThe field agrees on little.\n\n"))      # Y03: no common ground cited
            ok("questions-plan", rd)
            b = json.loads((rd / it_recon.B35 / "q_batch_Q_001.json").read_text())
            self.assertTrue(any(r.startswith("Y03") for r in b["refused_before"]), b["refused_before"])
            self.assertEqual(b["previous"], f"{it_recon.B35}/previous/Q_001.md")
            self.assertIn("1. Common ground", " ".join(b["must_cite"]))
            self.assertFalse(q.exists())                        # moved: the fan-out writes it again
            ok("questions-plan", rd)          # the rewrite never came: the question comes back, and is asked again
            self.assertEqual(sorted(f.name for f in (rd / it_recon.B35).glob("q_batch_*.json")), ["q_batch_Q_001.json"])
            self.assertTrue((rd / it_recon.B35 / "previous" / "Q_001.md").exists())

    def test_a_screen_result_is_its_first_word(self):
        """`yes (partial)` is a yes, `partly: tested only in ...` a partly - the qualifier after the word is the basis's."""
        t = ("## 6. Screens\n| Screen | Result | Basis |\n|---|---|---|\n"
             "| Is the answer already settled in the literature? | partly: tested only in rest | x |\n"
             "| Could data on this machine settle it? | yes (partial) | lens:dataset:x |\n\n## 7. Key terms\n")
        sc = it_recon.parse_question(t)["screens"]
        self.assertEqual((sc["settled"]["result"], sc["data"]["result"]), ("partly", "yes"))

    def test_frontmatter_takes_a_block_list(self):
        """`collisions:` with `- X0006` below it is the same list as `collisions: [X0006]` (a model writes either)."""
        fm = it_recon.frontmatter("---\nquestion: Q_005\naxes:\n- measure-definition\n- method-config\n"
                                  "collisions:\n  - X0006\nstatus: ready\nnote:\n---\n")
        self.assertEqual((fm["axes"], fm["collisions"], fm["status"], fm["note"]),
                         (["measure-definition", "method-config"], ["X0006"], "ready", ""))

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
