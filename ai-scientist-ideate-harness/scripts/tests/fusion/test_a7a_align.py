#!/usr/bin/env python3
"""Tests for A7.A align and B1 lens (it_align.py; rules references/fusion/F2-align.md), offline. Builds on the A7.D
fixture topic (test_a7d_decon.build_good): vocabulary from tests/fixtures/fusion/a7a/good/vocab.json, coordinates by
--auto, a probe of a temporary data root, the lens from good/lens.json. One counter-example per check in
tests/fixtures/fusion/a7a/neg/.

  python3 .claude/skills/ai-scientist-ideate/scripts/tests/fusion/test_a7a_align.py
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
FIX = SCRIPTS / "tests" / "fixtures" / "fusion" / "a7a"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))
import it_align  # noqa: E402
from test_a7d_decon import TOOLS, apply_ops, run  # noqa: E402
from test_a7d_decon import build_good as build_decon  # noqa: E402


def build_good(tmp: Path) -> Path:
    rd = build_decon(tmp)
    code, out = run("align-terms", rd, tool=TOOLS)
    assert code == 0, out
    code, out = run("align-set", rd, FIX / "good" / "vocab.json", tool=TOOLS)
    assert code == 0, out
    code, out = run("align-coords", rd, "--auto", tool=TOOLS)
    assert code == 0, out
    code, out = run("align-coords", rd, "--apply", FIX / "good" / "coords.json", tool=TOOLS)
    assert code == 0, out
    (tmp / "data" / "BNCI").mkdir(parents=True)
    code, out = run("env-probe", rd, "--write", "--roots", tmp / "data", "--packages", "json", tool=TOOLS)
    assert code == 0, out
    code, out = run("lens-set", rd, FIX / "good" / "lens.json", tool=TOOLS)
    assert code == 0, out
    return rd


def check(rd, *extra):
    code, out = run("align-check", rd, "--json", *extra, tool=TOOLS)
    return code, json.loads(out[: out.rindex("]") + 1])


def edit_json(path: Path, ops):
    path.write_text(json.dumps(apply_ops(json.loads(path.read_text()), ops)))


def apply_case(rd: Path, case: dict) -> None:
    kind, _, key = case["target"].partition(":")
    files = {"alignment": it_align.alignment_path(rd), "lens": it_align.lens_path(rd),
             "matrix_input": it_align.matrix_input_path(rd), "step0": rd / "step0_session_config.json",
             "decon": rd / "knowledge" / "decon" / f"{key}.json"}
    if kind == "cards":
        p = rd / "knowledge_cards.json"
        p.write_text(json.dumps(apply_ops({"points": []}, case["ops"])))
        return
    edit_json(files[kind], case["ops"])


class Good(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.rd = build_good(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_check_passes(self):
        code, fs = check(self.rd)
        self.assertEqual(code, 0, fs)

    def test_worklist(self):
        wl = json.loads((self.rd / it_align.WORK / "terms.json").read_text())
        strings = {i["string"] for i in wl["items"]}
        self.assertIn("SNR", strings)
        self.assertIn("own MI EEG", strings, "row names are on the worklist too")
        self.assertNotIn("No EEG was recorded in this study", strings, "an ineligible paper's words are not evidence")

    def test_a_changed_unit_is_named_and_re_placed(self):
        rec_p = self.rd / "knowledge" / "decon" / "smithetal2020.json"
        rec = json.loads(rec_p.read_text())
        next(u for u in rec["units"] if u["id"] == "smithetal2020#A1")["text"] = "expert labels are taken as ground truth"
        rec_p.write_text(json.dumps(rec))
        code, fs = check(self.rd)
        a11 = [f for f in fs if f["code"] == "A11"]
        self.assertTrue(a11 and "smithetal2020#A1" in a11[0]["msg"] and "parketal2019#C1" not in a11[0]["msg"], fs)
        al = json.loads(it_align.alignment_path(self.rd).read_text())
        p = self.tmp / "re.json"
        p.write_text(json.dumps({"smithetal2020#A1": {"axes": al["coords"]["smithetal2020#A1"]["axes"], "note": "re-placed"}}))
        code, out = run("align-coords", self.rd, "--apply", p, tool=TOOLS)
        self.assertEqual(code, 0, out)
        self.assertFalse([f for f in check(self.rd)[1] if f["code"] == "A11"])

    def test_auto_coordinates(self):
        al = json.loads(it_align.alignment_path(self.rd).read_text())
        c1 = al["coords"]["smithetal2020#C1"]
        self.assertEqual(c1["by"], "auto")
        self.assertEqual(c1["axes"]["method_family"], "method-family:artifact-rejection")
        self.assertEqual(c1["axes"]["measure"], "measure:accuracy", "longest spelling wins: 'decoding accuracy'")
        self.assertEqual(c1["axes"]["data"], "dataset:own-mi-eeg")
        self.assertEqual(c1["from"]["data"], "row")
        p1 = al["coords"]["parketal2019#C1"]["axes"]
        self.assertEqual(p1["construct"], "construct:class-correlated-artifacts")
        self.assertEqual(p1["data"], "dataset:bnci-2a")
        self.assertEqual(set(al["coords"]), {"smithetal2020#C1", "smithetal2020#A1", "parketal2019#C1"})
        self.assertEqual(al["coords"]["smithetal2020#A1"]["by"], "model", "nothing to collide on: never set by --auto")
        self.assertEqual(al["coords"]["smithetal2020#A1"]["axes"]["split"], "n/a")

    def test_apply_overrides_auto(self):
        ans = self.tmp / "coords.json"
        axes = {a: "unstated" for a in it_align.AXES}
        axes.update(construct="construct:class-correlated-artifacts", measure="measure:accuracy")
        ans.write_text(json.dumps({"smithetal2020#A1": {"axes": axes, "note": "labels decide which artifacts count"}}))
        code, out = run("align-coords", self.rd, "--apply", ans, tool=TOOLS)
        self.assertEqual(code, 0, out)
        al = json.loads(it_align.alignment_path(self.rd).read_text())
        self.assertEqual(al["coords"]["smithetal2020#A1"]["by"], "model")
        bad = self.tmp / "bad.json"
        bad.write_text(json.dumps({"smithetal2020#A1": {"axes": {**axes, "measure": "dataset:own-mi-eeg"}}}))
        code, out = run("align-coords", self.rd, "--apply", bad, tool=TOOLS)
        self.assertEqual(code, 1, out)

    def test_coordinate_batches_ask_only_what_the_tool_cannot_settle(self):
        """The harness's local worker: units --auto left, each asking only its unsettled axes; the answers joined to
        the settled ones; an answer naming a concept of the wrong kind leaves its unit for the next pass."""
        p = it_align.alignment_path(self.rd)
        al = json.loads(p.read_text())
        al["coords"].pop("smithetal2020#A1")
        p.write_text(json.dumps(al))
        code, out = run("align-coords", self.rd, "--batches", "--max-chars", "20000", tool=TOOLS)
        self.assertEqual(code, 0, out)
        wd = self.rd / it_align.WORK
        b = json.loads((wd / "coord_batch_001.json").read_text())
        self.assertEqual([u["id"] for u in b["units"]], ["smithetal2020#A1"])
        u = b["units"][0]
        self.assertEqual(u["ask"], {"construct": ["*"], "measure": ["*"]})        # nothing suggested: any concept
        self.assertIn("choices", b)
        schema = json.loads((wd / "schemas" / "coord_batch_001.json").read_text())
        self.assertIn("construct:class-correlated-artifacts",
                      schema["properties"]["smithetal2020#A1"]["properties"]["construct"]["items"]["enum"])
        ans = self.rd / b["answer"]
        ans.parent.mkdir(parents=True, exist_ok=True)
        ans.write_text(json.dumps({"smithetal2020#A1": {"construct": ["construct:class-correlated-artifacts"],
                                                        "measure": ["dataset:own-mi-eeg"]}}))     # wrong kind
        code, out = run("align-coords", self.rd, "--apply-answers", tool=TOOLS)
        self.assertNotIn("smithetal2020#A1", json.loads(p.read_text())["coords"])
        ans.write_text(json.dumps({"smithetal2020#A1": {"construct": ["construct:class-correlated-artifacts"],
                                                        "measure": ["measure:accuracy"]}}))
        code, out = run("align-coords", self.rd, "--apply-answers", tool=TOOLS)
        self.assertEqual(code, 0, out)
        c = json.loads(p.read_text())["coords"]["smithetal2020#A1"]
        self.assertEqual((c["by"], c["axes"]["construct"], c["axes"]["measure"]),
                         ("model", "construct:class-correlated-artifacts", "measure:accuracy"))
        self.assertEqual(set(c["axes"]), set(it_align.AXES))                   # the fixed axes joined in

    def test_vocabulary_in_batches(self):
        """The harness's local worker: the words in batches, each answered with a concept, the vocabulary built by
        code - here every word answered as the fixture's good vocabulary places it, which align-set must take."""
        good = it_align.Vocab(json.loads((FIX / "good" / "vocab.json").read_text()))
        al = json.loads(it_align.alignment_path(self.rd).read_text())
        al.pop("vocab")
        it_align.alignment_path(self.rd).write_text(json.dumps(al))
        code, out = run("align-terms", self.rd, "--batches", "--max-chars", "700", tool=TOOLS)
        self.assertEqual(code, 0, out)
        wd = self.rd / it_align.WORK
        batches = sorted(wd.glob("vbatch_*.json"))
        self.assertGreater(len(batches), 1)                    # the budget splits them
        for bf in batches:
            b = json.loads(bf.read_text())
            ans = {}
            for it in b["items"]:
                cid = good.resolve("", it["word"])
                c = good.concepts[cid]
                ans[it["key"]] = {"kind": c["kind"], "slug": cid.partition(":")[2], "name": c["name"],
                                  "definition": c["definition"]}
                if it.get("definitions"):
                    ans[it["key"]].update(same_measure=True, because="both define the same quantity")
            (self.rd / b["answer"]).parent.mkdir(parents=True, exist_ok=True)
            (self.rd / b["answer"]).write_text(json.dumps(ans))
        code, out = run("align-terms", self.rd, "--merge-answers", tool=TOOLS)
        self.assertEqual(code, 0, out)
        code, out = run("align-set", self.rd, wd / "vocab.json", tool=TOOLS)
        self.assertEqual(code, 0, out)
        code, out = run("align-terms", self.rd, "--batches", tool=TOOLS)    # every word placed: nothing left to ask
        self.assertIn("0 word(s) to place", out)

    def test_a_word_whose_roles_share_no_kind_is_asked_per_role(self):
        """'own MI EEG' a dataset in one paper and a population term in another: one item per role, each answer placed
        for its papers and role only - not as a spelling, which would put the other role on the wrong kind (A04)."""
        dp = self.rd / "knowledge" / "decon" / "parketal2019.json"
        r = json.loads(dp.read_text())
        r["terms"].append({"term": "own MI EEG", "kind": "population"})
        dp.write_text(json.dumps(r))
        al = json.loads(it_align.alignment_path(self.rd).read_text())
        al.pop("vocab")
        it_align.alignment_path(self.rd).write_text(json.dumps(al))
        run("align-terms", self.rd, tool=TOOLS)
        bs = it_align.vocab_batches(self.rd)
        roles = [it for b in bs for it in b if it["word"] == "own MI EEG"]
        self.assertEqual(sorted((it["kinds"], it["uses"]) for it in roles),
                         [(["dataset"], [["smithetal2020", "row:data"]]), (["population"], [["parketal2019", "term:population"]])])
        good = it_align.Vocab(json.loads((FIX / "good" / "vocab.json").read_text()))
        wd = self.rd / it_align.WORK
        code, out = run("align-terms", self.rd, "--batches", tool=TOOLS)
        for bf in sorted(wd.glob("vbatch_*.json")):
            b = json.loads(bf.read_text())
            ans = {}
            for it in b["items"]:
                if it.get("uses"):
                    kind = it["kinds"][0]
                    ans[it["key"]] = {"kind": kind, "slug": "own-mi-eeg", "name": "own MI EEG", "definition": f"as a {kind}"}
                    continue
                c = good.concepts[good.resolve("", it["word"])]
                ans[it["key"]] = {"kind": c["kind"], "slug": c["id"].partition(":")[2], "name": c["name"],
                                  "definition": c["definition"], "same_measure": True, "because": "the same quantity"}
            (self.rd / b["answer"]).parent.mkdir(parents=True, exist_ok=True)
            (self.rd / b["answer"]).write_text(json.dumps(ans))
        code, out = run("align-terms", self.rd, "--merge-answers", tool=TOOLS)
        self.assertEqual(code, 0, out)
        code, out = run("align-set", self.rd, wd / "vocab.json", tool=TOOLS)
        self.assertEqual(code, 0, out)
        V = it_align.Vocab(json.loads(it_align.alignment_path(self.rd).read_text())["vocab"])
        self.assertEqual(V.kind(V.resolve("smithetal2020", "own MI EEG", "row:data")), "dataset")
        self.assertEqual(V.kind(V.resolve("parketal2019", "own MI EEG", "term:population")), "population")

    def test_a_measure_two_papers_define_under_two_spellings_is_asked_once_more(self):
        """'SNR' (smithetal2020) and 'signal-to-noise ratio' (parketal2019), each defined by its paper and placed on one
        measure by two answers: nobody read the two definitions together (A05). The next pass asks, side by side; 'not
        the same' gives the second paper a measure of its own."""
        dp = self.rd / "knowledge" / "decon" / "parketal2019.json"
        r = json.loads(dp.read_text())
        r["terms"].append({"term": "signal-to-noise ratio", "kind": "measure", "where": "abstract",
                           "definition": "the power of the signal over the power of the noise"})
        dp.write_text(json.dumps(r))
        al = json.loads(it_align.alignment_path(self.rd).read_text())
        al.pop("vocab")
        it_align.alignment_path(self.rd).write_text(json.dumps(al))
        good = it_align.Vocab(json.loads((FIX / "good" / "vocab.json").read_text()))
        snr, wd = good.resolve("", "SNR"), self.rd / it_align.WORK

        def answer_all(same):
            asked = []
            for bf in sorted(wd.glob("vbatch_*.json")):
                b = json.loads(bf.read_text())
                ans = {}
                for it in b["items"]:
                    asked.append(it)
                    cid = snr if it.get("concept") or it["word"] == "signal-to-noise ratio" else good.resolve("", it["word"])
                    c = good.concepts[cid]
                    ans[it["key"]] = {"kind": c["kind"], "slug": cid.partition(":")[2], "name": c["name"],
                                      "definition": c["definition"]}
                    if it.get("definitions"):
                        ans[it["key"]].update(same_measure=same, because="the same quantity" if same else "")
                (self.rd / b["answer"]).parent.mkdir(parents=True, exist_ok=True)
                (self.rd / b["answer"]).write_text(json.dumps(ans))
            self.assertEqual(run("align-terms", self.rd, "--merge-answers", tool=TOOLS)[0], 0)
            return asked

        run("align-terms", self.rd, tool=TOOLS)
        run("align-terms", self.rd, "--batches", tool=TOOLS)
        answer_all(True)
        code, out = run("align-set", self.rd, wd / "vocab.json", tool=TOOLS)
        self.assertIn("A05", out)                                             # placed, but never read together
        run("align-terms", self.rd, "--batches", tool=TOOLS)
        [q] = answer_all(False)
        self.assertEqual((q["concept"], sorted(q["definitions"])), (snr, ["parketal2019", "smithetal2020"]))
        code, out = run("align-set", self.rd, wd / "vocab.json", tool=TOOLS)
        self.assertEqual(code, 0, out)
        V = it_align.Vocab(json.loads(it_align.alignment_path(self.rd).read_text())["vocab"])
        self.assertNotEqual(V.resolve("parketal2019", "signal-to-noise ratio"), V.resolve("smithetal2020", "SNR"))

    def test_lens_brief_lists_what_needs_a_verdict(self):
        code, out = run("lens-brief", self.rd, tool=TOOLS)
        self.assertEqual(code, 0, out)
        wd = self.rd / "knowledge" / "_work" / "B1"
        schema = json.loads((wd / "lens.schema.json").read_text())
        need = schema["properties"]["on_coords"]["required"]
        self.assertIn("method-family:artifact-rejection", need)
        brief = (wd / "brief.md").read_text()
        self.assertIn("method-family:artifact-rejection", brief)
        # what each verdict means sits beside the list: a package not installed, or data not here, is not a no
        self.assertIn("a missing package alone is never no", brief)
        self.assertIn("no data root here is a reason for not yes, never for no", brief)

    def test_point_candidates(self):
        code, out = run("align-points", self.rd, tool=TOOLS)
        self.assertEqual(code, 0, out)
        cands = json.loads((self.rd / it_align.WORK / "point_candidates.json").read_text())
        self.assertEqual([c["concept"] for c in cands], ["measure:accuracy"], "only accuracy is reached by both papers")
        cards = {"points": [{"slug": "Decoding_Accuracy", "name": "decoding accuracy", "origin": "align",
                             "concept": "measure:accuracy", "unit_refs": ["smithetal2020#C1"]}]}
        (self.rd / "knowledge_cards.json").write_text(json.dumps(cards))
        code, out = run("build-cards", self.rd, self.rd / "knowledge_cards.json", tool=TOOLS)
        self.assertEqual(code, 0, out)
        card = (self.rd / "knowledge" / "points" / "P_draft_Decoding_Accuracy.md").read_text()
        self.assertIn("origin: align", card)
        self.assertIn("concept: measure:accuracy", card)
        self.assertEqual(check(self.rd)[0], 0)

    def test_points_in_batches_are_built_by_code_from_the_decision(self):
        """The model answers keep + the text under a schema; slug, source, also_in, unit_refs and source_files are
        the candidate's, and an empty text field is (TBD)."""
        code, out = run("align-points", self.rd, "--batches", tool=TOOLS)
        self.assertEqual(code, 0, out)
        wd = self.rd / it_align.WORK
        b = json.loads((wd / "point_batch_001.json").read_text())
        schema = json.loads((wd / "schemas" / "point_batch_001.json").read_text())
        self.assertEqual(schema["required"], ["measure:accuracy"])
        self.assertTrue(b["candidates"][0]["definition"])                     # the vocabulary's, for a word-only one
        ans = {"measure:accuracy": {"keep": True, "claim_type": "empirical", "description": "decoding accuracy",
                                    "purpose": "how well a classifier decodes", "core_claim": "", "expanded": "",
                                    "method": "", "findings": "smithetal2020#C1"}}
        (self.rd / b["answer"]).parent.mkdir(parents=True, exist_ok=True)
        (self.rd / b["answer"]).write_text(json.dumps(ans))
        code, out = run("align-points", self.rd, "--merge-answers", tool=TOOLS)
        self.assertEqual(code, 0, out)
        p = json.loads((wd / "points_part.json").read_text())["points"][0]
        self.assertEqual((p["slug"], p["origin"], p["concept"], p["core_claim"]),
                         ("Decoding_Accuracy", "align", "measure:accuracy", "(TBD)"))
        self.assertEqual(sorted([p["source"], *p["also_in"]]), ["parketal2019", "smithetal2020"])
        self.assertEqual(p["source_files"], [f"knowledge/decon/{k}.json" for k in [p["source"], *p["also_in"]]])
        code, out = run("cards-merge", self.rd, wd / "points_part.json", "--origin", "align", tool=TOOLS)
        self.assertEqual(code, 0, out)
        code, out = run("build-cards", self.rd, self.rd / "knowledge_cards.json", tool=TOOLS)
        self.assertEqual(code, 0, out)
        self.assertEqual(check(self.rd, "--unit", "A7.A3")[0], 0)

    def test_projection_feeds_build_methods(self):
        mi = json.loads(it_align.matrix_input_path(self.rd).read_text())
        self.assertEqual(sorted(mi["vocab"]["method_family"]), ["artifact-rejection", "ica"])
        self.assertIn("ICA-based cleaning", mi["aliases"]["method_family"]["ica"])
        self.assertEqual(mi["not_shared_datasets"], ["own MI EEG"])
        self.assertTrue(mi["affordable"]["ica"].startswith("yes"))
        decon = sorted((self.rd / "knowledge" / "decon").glob("*.json"))
        code, out = run("build-methods", self.rd, it_align.matrix_input_path(self.rd), *decon, tool=TOOLS)
        self.assertEqual(code, 0, out)
        self.assertNotIn("not in vocab", out)
        rows = {r["exp_id"]: r for r in json.loads((self.rd / "knowledge" / "methods_matrix.json").read_text())["experiments"]}
        self.assertEqual(rows["smithetal2020#E1"]["metrics"], ["decoding accuracy"])
        self.assertEqual(rows["smithetal2020#E1"]["split"], "k-fold CV over trials")
        self.assertTrue(rows["parketal2019#E1"]["affordable_here"].endswith("(lens)"))

    def test_revising_the_vocabulary_keeps_history(self):
        code, out = run("align-set", self.rd, FIX / "good" / "vocab.json", "--reason", "incommensurable X_001", tool=TOOLS)
        self.assertEqual(code, 0, out)
        al = json.loads(it_align.alignment_path(self.rd).read_text())
        self.assertEqual(al["history"][-1]["reason"], "incommensurable X_001")

    def test_refused_vocabulary_is_not_written(self):
        v = json.loads((FIX / "good" / "vocab.json").read_text())
        v["concepts"][5]["variants"].append("SNR")
        bad = self.tmp / "v.json"
        bad.write_text(json.dumps(v))
        before = it_align.alignment_path(self.rd).read_text()
        code, out = run("align-set", self.rd, bad, tool=TOOLS)
        self.assertEqual(code, 1, out)
        self.assertEqual(it_align.alignment_path(self.rd).read_text(), before)

    def test_a_withdrawn_paper_leaves_the_vocabulary_and_the_coordinates(self):
        sp = self.rd / "step3_shortlist.json"
        data = json.loads(sp.read_text())
        rows = data["papers"] if isinstance(data, dict) else data
        rows[:] = [r for r in rows if r.get("citation_key") != "parketal2019"]
        sp.write_text(json.dumps(data))
        self.assertEqual(run("decon-plan", self.rd, tool=TOOLS)[0], 0)        # F1: the record is withdrawn
        v = json.loads((FIX / "good" / "vocab.json").read_text())
        v.setdefault("overrides", {})["parketal2019"] = {"BNCI 2a": "dataset:bnci-2a"}
        v.setdefault("unaligned", []).append({"paper": "parketal2019", "string": "whatever", "reason": "x"})
        vp = self.tmp / "v.json"
        vp.write_text(json.dumps(v))
        code, out = run("align-set", self.rd, vp, "--reason", "parketal2019 withdrawn", tool=TOOLS)
        self.assertEqual(code, 0, out)
        self.assertIn("per-paper entr(y/ies) of papers no longer among the records dropped", out)
        al = json.loads(it_align.alignment_path(self.rd).read_text())
        self.assertNotIn("parketal2019", al["vocab"]["overrides"])
        empty = self.tmp / "none.json"
        empty.write_text("{}")
        code, out = run("align-coords", self.rd, "--apply", empty, tool=TOOLS)
        self.assertEqual(code, 0, out)
        self.assertIn("1 coordinate(s) of units no longer in any record dropped", out)
        al = json.loads(it_align.alignment_path(self.rd).read_text())
        self.assertNotIn("parketal2019#C1", al["coords"])
        self.assertFalse([f for f in check(self.rd)[1] if f["code"] in ("A06", "A07", "A09") and f["level"] == "ERROR"])


class Matching(unittest.TestCase):
    def test_hyphen_equals_space(self):
        self.assertEqual(it_align.norm("Temporal-Autocorrelation"), it_align.norm("temporal autocorrelation"))
        V = it_align.Vocab({"concepts": [{"id": "construct:temporal-autocorrelation", "kind": "construct"}]})
        self.assertEqual(V.resolve("p", "temporal autocorrelation"), "construct:temporal-autocorrelation", "slug spelled out")

    def test_kinds_do_not_hide_each_other(self):
        V = it_align.Vocab({"concepts": [
            {"id": "method-family:mrcp", "kind": "method-family", "variants": ["readiness potential"]},
            {"id": "measure:rp-amplitude", "kind": "measure", "variants": ["readiness potential amplitude"]},
            {"id": "measure:amplitude", "kind": "measure", "variants": ["amplitude"]}]})
        recs = {"p": {"units": [{"id": "p#C1", "kind": "claim", "text": "readiness potential amplitude is larger for misses",
                                 "scope": {}}], "experiments": []}}
        s = it_align.suggest(None, recs, V)["p#C1"]["candidates"]
        self.assertEqual(s["measure"], ["measure:rp-amplitude"], "longest within the kind wins")
        self.assertEqual(s["method_family"], ["method-family:mrcp"], "a measure does not hide the family")

    def test_set_aside_wins_for_that_paper_only(self):
        V = it_align.Vocab({"concepts": [{"id": "population:novices", "kind": "population"}],
                            "unaligned": [{"paper": "a", "string": "novices", "reason": "a contrast condition here"}]})
        self.assertIsNone(V.resolve("a", "novices"))
        self.assertEqual(V.resolve("b", "novices"), "population:novices")


class Overrides(unittest.TestCase):
    def test_one_word_two_roles(self):
        V = it_align.Vocab({"concepts": [{"id": "measure:mse", "kind": "measure"}, {"id": "method-family:entropy", "kind": "method-family"}],
                            "overrides": {"p": {"multiscale entropy": {"term:measure": "measure:mse", "row:method_family": "method-family:entropy"}}}})
        self.assertEqual(V.resolve("p", "multiscale entropy", "term:measure"), "measure:mse")
        self.assertEqual(V.resolve("p", "multiscale entropy", "row:method_family"), "method-family:entropy")
        self.assertIsNone(V.resolve("p", "multiscale entropy", "row:metrics"))


class Negative(unittest.TestCase):
    def test_every_counter_example_fails_with_its_code(self):
        cases = sorted((FIX / "neg").glob("*.json"))
        self.assertTrue(cases)
        for f in cases:
            case = json.loads(f.read_text())
            with self.subTest(f.stem), tempfile.TemporaryDirectory() as t:
                rd = build_good(Path(t))
                apply_case(rd, case)
                code, fs = check(rd)
                hits = [x for x in fs if x["code"] == case["expect"] and x["level"] == case["level"]]
                self.assertTrue(hits, f"{f.stem}: expected {case['level']} {case['expect']}, got {fs}")
                if case["level"] == "ERROR":
                    self.assertEqual(code, 1, f.stem)

    def test_every_emitted_code_has_a_counter_example(self):
        import re
        emitted = set(re.findall(r'F\("(?:ERROR|WARN)", "([AT]\d\d)"', (SCRIPTS / "it_align.py").read_text()))
        covered = {json.loads(f.read_text())["expect"] for f in (FIX / "neg").glob("*.json")}
        self.assertEqual(emitted - covered, set())


if __name__ == "__main__":
    unittest.main(verbosity=1)
