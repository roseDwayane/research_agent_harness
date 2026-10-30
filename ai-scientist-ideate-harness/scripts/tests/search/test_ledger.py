#!/usr/bin/env python3
"""Tests for the search block's ledger, views, overrides, trace and preflight (it_ledger, it_overrides, it_trace):
on the fixture topic taken through A1 -> A5 -> A4 (test_a4_export.build_good).

  python3 .claude/skills/ai-scientist-ideate/scripts/tests/search/test_ledger.py
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2]
TOOLS = SCRIPTS / "ideate_tools.py"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import it_ledger  # noqa: E402
import it_search  # noqa: E402
import it_snowball  # noqa: E402
import it_trace  # noqa: E402
from test_a4_export import build_good  # noqa: E402


def run(*args):
    p = subprocess.run([sys.executable, str(TOOLS), *map(str, args)], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def overrides(rd: Path, *entries):
    (rd / "_human").mkdir(exist_ok=True)
    (rd / "_human" / "search_overrides.json").write_text(json.dumps({"entries": list(entries)}))


class TestLedger(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.rd = build_good(cls.tmp / "a")
        cls.n = 0

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def copy(self) -> Path:
        type(self).n += 1
        d = self.tmp / f"c{self.n}"
        shutil.copytree(self.rd.parent, d)
        return d / "topic_research"

    def st(self, rd):
        return {u: s["state"] for u, s in it_ledger.states(rd).items()}

    def test_every_unit_done_and_next(self):
        self.assertEqual(set(self.st(self.rd).values()), {"done"})
        self.assertIsNone(it_ledger.next_unit(self.rd)[0])
        code, out = run("next", self.rd)
        self.assertEqual(code, 0, out)
        self.assertIn("complete", out)
        status = (self.rd / "STATUS.md").read_text()
        for u in it_ledger.ORDER:
            self.assertIn(f"| {u} | ✔ done", status)
        cav = json.loads((self.rd / "search_caveats.json").read_text())
        self.assertEqual(cav["schema"], "ideate-search-caveats/1")

    def test_done_records_inputs_outputs_counts(self):
        evs = it_ledger._events(self.rd)
        for u in it_ledger.ORDER:
            d = [e for e in evs if e["unit"] == u and e["ev"] == "done"][-1]
            want_in = {it_ledger.spec_id(s) for s in it_ledger.io(u)["reads"]}
            self.assertEqual(set(d["inputs"]), want_in, u)
            self.assertEqual(set(d["outputs"]), {it_ledger.spec_id(s) for s in it_ledger.io(u)["owns"]}, u)
            self.assertTrue(d["counts"] and "error" not in d["counts"], u)
            self.assertTrue(d["tool"], u)

    def test_hand_edit_makes_stale_downstream(self):
        rd = self.copy()
        g = json.loads((rd / "step3_gate.json").read_text())
        g["excluded"] = g["excluded"][1:]
        (rd / "step3_gate.json").write_text(json.dumps(g))
        st = it_ledger.states(rd)
        self.assertEqual(st["A3.g"]["state"], "stale")
        self.assertIn("output changed", st["A3.g"]["why"])
        self.assertEqual((st["A3"]["state"], st["A4.k"]["state"]), ("stale", "stale"))
        self.assertEqual(st["A2.m"]["state"], "done")                    # upstream untouched
        self.assertEqual(it_ledger.next_unit(rd)[0], "A3.g")

    def test_unchanged_rerun_keeps_downstream(self):
        rd = self.copy()
        before = (rd / "step3_gate.json").read_bytes()
        code, out = run("screen-gate", rd)
        self.assertEqual(code, 0, out)
        self.assertEqual((rd / "step3_gate.json").read_bytes(), before)  # same decisions: the file is kept
        st = self.st(rd)
        self.assertEqual((st["A3.g"], st["A3"], st["A4.b"]), ("done", "done", "done"))

    def test_retired_term_stales_the_search_only(self):
        rd = self.copy()
        f = rd.parent / "retire.json"
        f.write_text(json.dumps({"axis": "C2", "terms": ["artifact detection"], "reason": "brings in seismic detection",
                                 "round": 1}))
        code, out = run("frame", "retire-terms", rd, f)
        self.assertEqual(code, 0, out)
        st = self.st(rd)
        self.assertEqual((st["A1.p"], st["A1.q"], st["A1.e"]), ("done", "done", "done"))   # a declared revision
        self.assertEqual(st["A2.s"], "stale")
        self.assertEqual(it_ledger.next_unit(rd)[0], "A2.s")

    def test_revised_anchors_stale_the_merge(self):
        """§15 G2: anchors-revise is a declared revision of A1.q; A2.m reads anchor_terms, so the merge is next."""
        rd = self.copy()
        cfg = json.loads((rd / "step0_session_config.json").read_text())
        f = rd.parent / "anchors.json"
        f.write_text(json.dumps({"anchor_terms": list(cfg["anchor_terms"][:2]) + ["eeg"],
                                 "reason": "the revised protocol's reading"}))
        code, out = run("frame", "anchors-revise", rd, f)
        self.assertEqual(code, 0, out)
        st = self.st(rd)
        self.assertEqual((st["A1.q"], st["A1.e"], st["A2.s"]), ("done", "done", "done"))   # a declared revision
        self.assertEqual(st["A2.m"], "stale")
        self.assertEqual(it_ledger.next_unit(rd)[0], "A2.m")

    def test_foreign_write_refused(self):
        rd = self.copy()
        it_ledger.begin(rd, "A3.g")
        raw = json.loads((rd / "step2_raw_papers.json").read_text())
        raw["papers"][0]["title"] = "edited by hand"
        (rd / "step2_raw_papers.json").write_text(json.dumps(raw))
        with self.assertRaises(SystemExit) as cm:
            it_ledger.done(rd, "A3.g")
        self.assertEqual(cm.exception.code, 3)
        self.assertEqual(it_ledger._events(rd)[-1]["ev"], "fail")
        self.assertIn("step2_raw_papers.json", it_ledger._events(rd)[-1]["why"])

    def test_foreign_step0_key_refused_scratch_allowed(self):
        rd = self.copy()
        it_ledger.begin(rd, "A3")
        (rd / "_state/fanout/A3/note.txt").write_text("scratch")       # declared scratch
        cfg = json.loads((rd / "step0_session_config.json").read_text())
        cfg["sources"] = ["arxiv"]                                      # A1.q's key
        (rd / "step0_session_config.json").write_text(json.dumps(cfg))
        self.assertEqual(it_ledger.violations(rd, "A3"), ["step0:sources"])

    def test_human_exclude_and_include(self):
        rd = self.copy()
        sl = json.loads((rd / "step3_shortlist.json").read_text())
        out_id = sl["papers"][0]["id"]
        sc = json.loads((rd / "screening_scores.json").read_text())
        inc = {q["id"] for q in sl["papers"]}
        back_id = next(e["id"] for e in sc["scores"] if e["id"] not in inc and "rel" in e)
        overrides(rd, {"kind": "exclude", "id": out_id, "reason": "not about scalp EEG", "by": "kyc"},
                  {"kind": "include", "id": back_id, "reason": "the toolbox every study here uses", "by": "kyc"})
        st = it_ledger.states(rd)
        self.assertEqual(st["A3"]["state"], "stale")
        self.assertIn("search_overrides", st["A3"]["why"])
        self.assertEqual(run("a3-check", rd)[0], 1)                     # C14: not applied yet
        code, out = run("screen-build", rd, rd / "screening_scores.json")
        self.assertEqual(code, 0, out)
        sl = json.loads((rd / "step3_shortlist.json").read_text())
        ids = {q["id"]: q for q in sl["papers"]}
        self.assertNotIn(out_id, ids)
        self.assertEqual(ids[back_id]["screening"]["decided_by"], "human")
        self.assertEqual(sl["summary"]["excluded_by_reason"].get("HUMAN"), 1)
        self.assertEqual(run("a3-check", rd)[0], 0)
        st = it_ledger.states(rd)
        self.assertEqual((st["A3"]["state"], st["A4.k"]["state"]), ("done", "stale"))
        tr = it_trace.trace(rd, back_id)
        self.assertTrue(any("decided by kyc" in s["text"] for s in tr["steps"]))

    def test_human_reread_becomes_rescue(self):
        rd = self.copy()
        sc = json.loads((rd / "screening_scores.json").read_text())
        inc = {q["id"] for q in json.loads((rd / "step3_shortlist.json").read_text())["papers"]}
        pid = next(e["id"] for e in sc["scores"] if e["id"] not in inc and "rel" in e)
        overrides(rd, {"kind": "reread", "id": pid, "reason": "it reports the outcome O2", "by": "kyc"})
        for _ in range(2):                                              # a second plan does not dispatch it again
            code, out = run("screen-plan", rd)
            self.assertEqual(code, 0, out)
        fan = rd / "_state/fanout/A3"
        resc = [json.loads(f.read_text()) for f in fan.glob("batch_*.in.json") if json.loads(f.read_text()).get("rescue")]
        self.assertEqual([(b["ids"], b["rescue"]["by"]) for b in resc], [([pid], "kyc")])

    def test_seed_override(self):
        rd = self.copy()
        sl = json.loads((rd / "step3_shortlist.json").read_text())
        rule, _ = it_snowball.forward_seeds(rd, sl)
        drop = rule[0]["id"]
        overrides(rd, {"kind": "seed", "id": drop, "action": "remove", "reason": "a review, not a method"})
        seeds, applied = it_snowball.forward_seeds(rd, sl)
        self.assertNotIn(drop, [p["id"] for p in seeds])
        self.assertEqual(applied, [{"id": drop, "action": "remove", "reason": "a review, not a method"}])
        self.assertEqual(it_ledger.states(rd)["A5"]["state"], "stale")

    def test_known_item_override(self):
        rd = self.copy()
        overrides(rd, {"kind": "known_item", "title": "A paper nobody indexed about EEG quality", "reason": "my lab's"})
        sig = it_search.signals(json.loads((rd / "step0_session_config.json").read_text()), rd)
        self.assertIn("A paper nobody indexed about EEG quality", [k["ref"] for k in sig["known_items"] if not k["resolved"]])
        self.assertEqual(it_ledger.states(rd)["A2.c"]["state"], "stale")

    def test_trace_paper_key_query(self):
        key = json.loads((self.rd / "step4_citation_keys.jsonl").read_text().splitlines()[0])
        tr = it_trace.trace(self.rd, key["key"])
        units = {s["unit"] for s in tr["steps"]}
        self.assertTrue({"A2.s", "A2.m", "A3.b", "A3", "A4.k", "A4.b"} <= units, units)
        self.assertTrue(any(c.strip().startswith("comment on relevance") for c in tr["comments"]))
        q = it_trace.trace(self.rd, "Q1")
        self.assertTrue({"A1.q", "A2.s", "A2.m", "A2.c"} <= {s["unit"] for s in q["steps"]})
        sb = json.loads((self.rd / "step2b_snowball_papers.json").read_text())["papers"][0]
        self.assertEqual(it_trace.trace(self.rd, sb["id"])["steps"][0]["unit"], "A5")
        code, out = run("trace", self.rd, "Q1")
        self.assertEqual(code, 0, out)

    def test_trace_covers_every_unit(self):
        sl = json.loads((self.rd / "step3_shortlist.json").read_text())["papers"]
        gated = json.loads((self.rd / "step3_gate.json").read_text())["excluded"][0]["id"]
        snow = json.loads((self.rd / "step2b_snowball_papers.json").read_text())["papers"][0]["id"]
        units = set()
        for item in ("protocol", sl[0]["id"], gated, snow, "Q1"):
            units |= {s["unit"] for s in it_trace.trace(self.rd, item)["steps"]}
        self.assertEqual(units, set(it_ledger.ORDER))

    def test_preflight_degrades_dense(self):
        rd = self.copy()
        (rd / "_state").mkdir(exist_ok=True)
        (rd / "_state" / "preflight.json").write_text(json.dumps({
            "at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "services": {"semantic_scholar": {"ok": False, "detail": "429 rate limit"}}}))

        class NoCall:
            async def call(self, tool, params):
                raise AssertionError("the preflight said Semantic Scholar is down")
        cfg = json.loads((rd / "step0_session_config.json").read_text())
        rec = asyncio.run(it_search.run_dense(NoCall(), cfg, rd))
        att = rec["per_source"]["semantic_scholar"]["attempts"][-1]
        self.assertIn("preflight", att["skipped"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
