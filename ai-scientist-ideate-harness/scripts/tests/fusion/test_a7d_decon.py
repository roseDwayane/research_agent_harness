#!/usr/bin/env python3
"""Tests for A7.D deconstruct (it_decon.py; rules references/fusion/F1-deconstruct.md), offline. The fixture topic
(tests/fixtures/fusion/a7d/good) has three shortlisted papers: one full text that is eligible, one full text that turns
out ineligible (MEG only), one abstract-only. One counter-example per check lives in tests/fixtures/fusion/a7d/neg/.

  python3 .claude/skills/ai-scientist-ideate/scripts/tests/fusion/test_a7d_decon.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2]
TOOLS = SCRIPTS / "ideate_tools.py"
DECON = SCRIPTS / "it_decon.py"
FIX = SCRIPTS / "tests" / "fixtures" / "fusion" / "a7d"
sys.path.insert(0, str(SCRIPTS))
import it_decon  # noqa: E402


def _registered() -> bool:
    p = subprocess.run([sys.executable, str(TOOLS), "decon-check", "-h"], capture_output=True, text=True)
    return p.returncode == 0


CLI = TOOLS if _registered() else DECON


def run(*args, tool=None):
    p = subprocess.run([sys.executable, str(tool or CLI), *map(str, args)], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def make_topic(tmp: Path) -> Path:
    rd = tmp / "fx_research"
    (rd / "step5_full_text").mkdir(parents=True)
    for f in ("step0_session_config.json", "step3_shortlist.json"):
        shutil.copy(FIX / "good" / f, rd / f)
    for f in (FIX / "good" / "full_text").glob("*.md"):
        shutil.copy(f, rd / "step5_full_text" / f.name)
    return rd


def answers_into(rd: Path, only=None) -> Path:
    ad = rd / it_decon.WORK / "answers"
    ad.mkdir(parents=True, exist_ok=True)
    for f in (FIX / "good" / "answers").glob("*.json"):
        if only is None or f.stem in only:
            shutil.copy(f, ad / f.name)
    return ad


def build_good(tmp: Path) -> Path:
    rd = make_topic(tmp)
    code, out = run("decon-plan", rd)
    assert code == 0, out
    answers_into(rd)
    code, out = run("decon-merge", rd)
    assert code == 0, out
    return rd


def _walk(obj, path):
    parts = path.split(".")
    for p in parts[:-1]:
        obj = obj[int(p)] if isinstance(obj, list) else obj[p]
    last = parts[-1]
    return obj, (int(last) if isinstance(obj, list) else last)


def apply_ops(data, ops):
    for o in ops:
        parent, k = _walk(data, o["path"])
        if o["op"] == "set":
            parent[k] = o["value"]
        elif o["op"] == "del":
            del parent[k]
        elif o["op"] == "append":
            parent[k].append(o["value"])
        else:
            raise ValueError(o["op"])
    return data


def apply_case(rd: Path, case: dict) -> list[str]:
    """Apply a counter-example; return the decon-check arguments that must report it."""
    kind, _, key = case["target"].partition(":")
    if kind == "answer":
        f = FIX / "good" / "answers" / f"{key}.json"
        out = rd / "neg_answer.json"
        out.write_text(json.dumps(apply_ops(json.loads(f.read_text()), case["ops"])))
        return ["--answer", str(out)]
    if kind == "record":
        f = it_decon.decon_dir(rd) / f"{key}.json"
        f.write_text(json.dumps(apply_ops(json.loads(f.read_text()), case["ops"])))
    elif kind in ("note", "fulltext"):
        f = (it_decon.notes_dir(rd) if kind == "note" else rd / "step5_full_text") / f"{key}.md"
        f.write_text(f.read_text() + "".join(o["value"] for o in case["ops"]))
    elif kind == "remove":
        (it_decon.decon_dir(rd) / f"{key}.json").unlink()
    else:
        raise ValueError(case["target"])
    return []


class Good(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.rd = build_good(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_check_passes(self):
        code, out = run("decon-check", self.rd)
        self.assertEqual(code, 0, out)

    def test_records_and_views(self):
        recs = it_decon.records(self.rd)
        self.assertEqual(set(recs), {"smithetal2020", "leeetal2021", "parketal2019"})
        self.assertEqual(recs["parketal2019"]["basis"], "abstract")
        self.assertTrue(all(r["source_sha"] and r["at"] for r in recs.values()))
        notes = sorted(f.stem for f in it_decon.notes_dir(self.rd).glob("*.md"))
        self.assertEqual(notes, ["smithetal2020"], "a note only for an eligible full text")
        note = (it_decon.notes_dir(self.rd) / "smithetal2020.md").read_text()
        for label in ("Claim scope:", "Assumes:", "Disagrees with: (TBD)", "Not done:", "- Future work:"):
            self.assertIn(label, note)
        self.assertEqual(sum(l.startswith("Not done:") for l in note.splitlines()), 1)

    def test_one_note_line_per_unit(self):
        ad = self.rd / it_decon.WORK / "answers"
        a = json.loads((ad / "smithetal2020.json").read_text())
        a["units"] += [{"id": f"smithetal2020#N{i}", "kind": "not-done", "text": f"item {i} " + "x" * 300} for i in (2, 3)]
        (ad / "smithetal2020.json").write_text(json.dumps(a))
        self.assertEqual(run("decon-merge", self.rd, "--revise", "more not-done items")[0], 0)
        run("concept-index", self.rd, tool=TOOLS)
        ci = json.loads((self.rd / "knowledge" / "concept_index.json").read_text())
        nd = [x for x in ci["signals"]["not_done_and_future_work"] if x["kind"] == "not done"]
        self.assertEqual(len(nd), 3, "every not-done unit reaches the index on its own line")

    def test_concept_index_reads_the_view(self):
        code, out = run("concept-index", self.rd, tool=TOOLS)
        self.assertEqual(code, 0, out)
        ci = json.loads((self.rd / "knowledge" / "concept_index.json").read_text())
        self.assertEqual(ci["notes_with_claim_fields"], "1/1")
        self.assertEqual([a["paper"] for a in ci["signals"]["assumptions"]], ["smithetal2020"])
        self.assertEqual(ci["signals"]["disagreements"], [])
        kinds = sorted(x["kind"] for x in ci["signals"]["not_done_and_future_work"])
        self.assertEqual(kinds, ["future work", "not done"])

    def test_build_methods_from_records(self):
        mi = self.rd / "knowledge" / "methods_matrix_input.json"
        mi.write_text(json.dumps({"vocab": {"method_family": {"artifact-rejection": "a", "ica": "b"}}, "aliases": {}}))
        code, out = run("build-methods", self.rd, mi, *sorted(it_decon.decon_dir(self.rd).glob("*.json")), tool=TOOLS)
        self.assertEqual(code, 0, out)
        mm = json.loads((self.rd / "knowledge" / "methods_matrix.json").read_text())
        self.assertEqual(sorted(r["exp_id"] for r in mm["experiments"]), ["parketal2019#E1", "smithetal2020#E1"])
        self.assertEqual(mm["aggregates"]["counts"]["full_text_experiments"], 1)

    def test_resume_plans_nothing(self):
        code, out = run("decon-plan", self.rd)
        self.assertEqual(code, 0, out)
        plan = json.loads((self.rd / it_decon.WORK / "plan.json").read_text())
        self.assertEqual((plan["missing"], plan["stale"], plan["batches"]), ([], [], []))

    def test_merge_again_is_idempotent(self):
        code, out = run("decon-merge", self.rd)
        self.assertEqual(code, 0, out)
        self.assertIn("0 written, 3 unchanged", out)

    def test_stale_full_text_is_planned_and_rewritten(self):
        ft = self.rd / "step5_full_text" / "smithetal2020.md"
        ft.write_text(ft.read_text() + "\nAddendum.\n")
        run("decon-plan", self.rd)
        plan = json.loads((self.rd / it_decon.WORK / "plan.json").read_text())
        self.assertEqual(plan["stale"], ["smithetal2020"])
        ad = self.rd / it_decon.WORK / "answers"
        self.assertFalse((ad / "smithetal2020.json").exists(), "the answer read from the old text is moved away")
        self.assertTrue(list(ad.glob("_superseded_*/smithetal2020.json")))
        answers_into(self.rd, only={"smithetal2020"})               # the re-read of the new text
        code, out = run("decon-merge", self.rd)
        self.assertEqual(code, 0, out)
        rec = it_decon.records(self.rd)["smithetal2020"]
        self.assertEqual(len(rec["history"]), 1)
        self.assertEqual(run("decon-check", self.rd)[0], 0)

    def test_revision_needs_a_reason(self):
        ad = self.rd / it_decon.WORK / "answers"
        a = json.loads((ad / "smithetal2020.json").read_text())
        a["units"][0]["strength"] = "suggests"
        (ad / "smithetal2020.json").write_text(json.dumps(a))
        code, out = run("decon-merge", self.rd)
        self.assertEqual(code, 1, out)
        self.assertIn("revision", out)
        code, out = run("decon-merge", self.rd, "--revise", "B3 source check: the paper hedges in Sec. 5")
        self.assertEqual(code, 0, out)
        rec = it_decon.records(self.rd)["smithetal2020"]
        self.assertEqual(rec["units"][0]["strength"], "suggests")
        self.assertEqual(rec["history"][0]["reason"], "B3 source check: the paper hedges in Sec. 5")
        self.assertIn("(suggests;", (it_decon.notes_dir(self.rd) / "smithetal2020.md").read_text())
        self.assertEqual(run("decon-check", self.rd)[0], 0)

    def test_record_turning_ineligible_drops_its_view(self):
        ad = self.rd / it_decon.WORK / "answers"
        a = json.loads((ad / "smithetal2020.json").read_text())
        a.update(eligibility={"verdict": "ineligible", "criteria": ["IN1"], "reason": "x"}, units=[], experiments=[])
        (ad / "smithetal2020.json").write_text(json.dumps(a))
        code, out = run("decon-merge", self.rd, "--revise", "read again: no automated method")
        self.assertEqual(code, 0, out)
        self.assertFalse((it_decon.notes_dir(self.rd) / "smithetal2020.md").exists())
        self.assertEqual(run("decon-check", self.rd)[0], 0)


    def test_paper_leaving_the_shortlist_is_withdrawn_and_restored(self):
        sp = self.rd / "step3_shortlist.json"
        orig = sp.read_text()
        data = json.loads(orig)
        rows = data["papers"] if isinstance(data, dict) else data
        rows[:] = [p for p in rows if p.get("citation_key") != "smithetal2020"]
        sp.write_text(json.dumps(data))
        self.assertNotEqual(run("decon-check", self.rd)[0], 0, "a record of a paper off the shortlist is refused (D01)")
        code, out = run("decon-plan", self.rd)
        self.assertEqual(code, 0, out)
        self.assertIn("moved to knowledge/decon/_withdrawn/", out)
        self.assertTrue((it_decon.decon_dir(self.rd) / "_withdrawn" / "smithetal2020.json").exists())
        self.assertFalse((it_decon.notes_dir(self.rd) / "smithetal2020.md").exists(), "its view goes with it")
        self.assertEqual(run("decon-check", self.rd)[0], 0)
        sp.write_text(orig)                                    # back on the shortlist: the same record returns
        run("decon-plan", self.rd)
        self.assertTrue((it_decon.decon_dir(self.rd) / "smithetal2020.json").exists())
        self.assertEqual(run("decon-render", self.rd)[0], 0)
        self.assertEqual(run("decon-check", self.rd)[0], 0)


class Plan(unittest.TestCase):
    def test_batches_split_by_basis(self):
        with tempfile.TemporaryDirectory() as t:
            rd = make_topic(Path(t))
            code, out = run("decon-plan", rd, "--ft-size", "1")
            self.assertEqual(code, 0, out)
            plan = json.loads((rd / it_decon.WORK / "plan.json").read_text())
            self.assertEqual([b["basis"] for b in plan["batches"]], ["full-text", "full-text", "abstract"])
            b1 = json.loads((rd / it_decon.WORK / "batch_001.json").read_text())
            self.assertEqual(b1["rules"], it_decon.RULES)
            self.assertIn("criteria", b1["context"])
            self.assertTrue((SCRIPTS.parent / b1["rules"]).exists())
            b3 = json.loads((rd / it_decon.WORK / "batch_003.json").read_text())
            self.assertIn("abstract", b3["papers"][0])

    def test_refused_answers_are_not_written(self):
        with tempfile.TemporaryDirectory() as t:
            rd = make_topic(Path(t))
            ad = answers_into(rd)
            a = json.loads((ad / "smithetal2020.json").read_text())
            a["units"][0]["quote"] = "a sentence the paper never wrote at all"
            (ad / "smithetal2020.json").write_text(json.dumps(a))
            code, out = run("decon-merge", rd)
            self.assertEqual(code, 1, out)
            self.assertIn("REFUSED smithetal2020", out)
            self.assertEqual(sorted(it_decon.records(rd)), ["leeetal2021", "parketal2019"])

    def test_legacy_knowledge_base_is_frozen(self):
        with tempfile.TemporaryDirectory() as t:
            rd = make_topic(Path(t))
            (rd / "knowledge" / "_notes").mkdir(parents=True)
            (rd / "knowledge" / "_notes" / "smithetal2020.md").write_text("# hand-written note\nNot done: x\n")
            answers_into(rd)
            code, out = run("decon-merge", rd)
            self.assertEqual(code, 2, out)
            self.assertIn("frozen", out)
            self.assertEqual((rd / "knowledge" / "_notes" / "smithetal2020.md").read_text(),
                             "# hand-written note\nNot done: x\n")


class PicoTopic(unittest.TestCase):
    def test_ineligible_names_a_pico_slot(self):
        cfg = {"pico": {"population": "golfers", "intervention": "EEG"}}
        self.assertEqual(it_decon._criteria_ids(cfg), {"population", "intervention"})


class Squash(unittest.TestCase):
    def test_line_breaks_hyphens_ligatures(self):
        text = it_decon.squash("automated artifact rejec-\ntion improves deﬁned **accuracy**")
        self.assertIn(it_decon.squash("artifact rejection improves defined accuracy"), text)
        self.assertIsNone(it_decon.quote_problem("artifact rejection improves defined accuracy", text))
        self.assertIn("too short", it_decon.quote_problem("rejection improves", text))
        self.assertIn("not found", it_decon.quote_problem("artifact removal improves defined accuracy", text))

    def test_a_source_shorter_than_the_minimum_is_quoted_whole(self):
        """A record with a three-word title and no abstract: the whole title is the only possible quote."""
        text = it_decon.squash("Wireless ear-eeg sensor\n")
        self.assertIsNone(it_decon.quote_problem("Wireless ear-eeg sensor", text))
        self.assertIn("too short", it_decon.quote_problem("ear-eeg sensor", text))


class Negative(unittest.TestCase):
    def test_every_counter_example_fails_with_its_code(self):
        cases = sorted((FIX / "neg").glob("*.json"))
        self.assertTrue(cases)
        for f in cases:
            case = json.loads(f.read_text())
            with self.subTest(f.stem), tempfile.TemporaryDirectory() as t:
                rd = build_good(Path(t))
                extra = apply_case(rd, case)
                code, out = run("decon-check", rd, *extra, "--json")
                fs = json.loads(out[: out.rindex("]") + 1])
                hits = [x for x in fs if x["code"] == case["expect"] and x["level"] == case["level"]]
                self.assertTrue(hits, f"{f.stem}: expected {case['level']} {case['expect']}, got {fs}")
                if case["level"] == "ERROR":
                    self.assertEqual(code, 1, f.stem)

    def test_every_emitted_code_has_a_counter_example(self):
        import re
        emitted = set(re.findall(r'F\("(?:ERROR|WARN)", "(D\d\d)"', DECON.read_text()))
        covered = {json.loads(f.read_text())["expect"] for f in (FIX / "neg").glob("*.json")}
        self.assertEqual(emitted - covered, set())


if __name__ == "__main__":
    unittest.main(verbosity=1)
