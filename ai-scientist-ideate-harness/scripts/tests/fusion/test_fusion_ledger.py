#!/usr/bin/env python3
"""Tests for the fusion block on the ledger (it_ledger: FUSION, unit-begin / unit-done, fusion caveats, STATUS.md;
it_trace: collisions, gaps, questions, a paper's fusion steps), offline. Builds on the A7.R fixture
(test_a7r_recon.build_good) and closes the Units the model writes with unit-done.

Interrupt (armour condition 8): IDEATE_FAIL_AFTER_WRITES=k stops the k+1-th write of a fusion command. Afterwards the
ledger holds no `done` for the Unit after the interrupted call, every file it owns still parses, and a second run
gives what an uninterrupted run gives. A Unit the model writes is interrupted by a session that stops after unit-begin:
it shows as running, `next` names it, and unit-done closes it.

  python3 .claude/skills/ai-scientist-ideate/scripts/tests/fusion/test_fusion_ledger.py
"""

from __future__ import annotations

import json
import os
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
import it_collide  # noqa: E402
import it_ledger  # noqa: E402
import it_trace  # noqa: E402
from test_a7d_decon import TOOLS  # noqa: E402
from test_a7r_recon import build_good as build_recon  # noqa: E402

A7A = SCRIPTS / "tests" / "fixtures" / "fusion" / "a7a" / "good"
A7X = SCRIPTS / "tests" / "fixtures" / "fusion" / "a7x" / "good"
VOLATILE = {"at", "history", "vocab_at", "coords_at", "generated_at"}


def run(*args, fail_after=None):
    env = {**os.environ}
    env.pop("IDEATE_FAIL_AFTER_WRITES", None)
    if fail_after is not None:
        env["IDEATE_FAIL_AFTER_WRITES"] = str(fail_after)
    p = subprocess.run([sys.executable, str(TOOLS), *map(str, args)], capture_output=True, text=True, env=env)
    return p.returncode, p.stdout + p.stderr


def ok(*args):
    code, out = run(*args)
    assert code == 0, out
    return out


def build(tmp: Path) -> Path:
    """The A7.R fixture set the lens before the A7.X fixture revised the records: B1 runs again on the same lens (kept
    unchanged), the commands downstream run again, and the Units the model writes are closed."""
    rd = build_recon(tmp)
    lens = json.loads((rd / "lens.json").read_text())
    (tmp / "lens_in.json").write_text(json.dumps({k: lens[k] for k in ("persona", "on_coords", "own_data")}))
    ok("lens-set", rd, tmp / "lens_in.json")
    ok("collide-candidates", rd)
    ok("collide-plan", rd)                       # every candidate judged: the plan closes A7.X2
    ok("collide-plan", rd, "--lens")             # no lens candidate in the fixture: the plan closes B3.c
    ok("gaps-set", rd, A7X / "gaps.json")
    for u in it_ledger.MODEL_UNITS:
        ok("unit-done", rd, u)
    ok("questions-index", rd)
    return rd


def st(rd: Path) -> dict:
    return {u: s["state"] for u, s in it_ledger.states(rd, "fusion").items()}


def strip(x):
    if isinstance(x, dict):
        return {k: strip(v) for k, v in x.items() if k not in VOLATILE}
    if isinstance(x, list):
        return [strip(v) for v in x]
    return x


def owned(rd: Path, unit: str) -> dict:
    """Every file a Unit owns, parsed (a half-written file raises here), with timestamps removed."""
    out = {}
    for s in it_ledger.io(unit)["owns"]:
        if "step0" in s:
            continue
        files = sorted(rd.glob(s["glob"])) if "glob" in s else [rd / s["file"]]
        for f in files:
            if not f.exists():
                continue
            t = f.read_text(encoding="utf-8")
            if f.suffix == ".json":
                v = strip(json.loads(t))
            elif f.suffix == ".jsonl":
                v = [strip(json.loads(l)) for l in t.splitlines() if l.strip()]
            else:
                v = t
            out[f.relative_to(rd).as_posix()] = it_ledger._part(v, s["part"]) if s.get("part") else v
    return out


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.rd = build(cls.tmp / "base")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def copy(self) -> Path:
        d = Path(tempfile.mkdtemp(dir=self.tmp))
        shutil.copytree(self.rd.parent, d, dirs_exist_ok=True)
        return d / self.rd.name


class States(Fixture):
    def test_every_unit_done_and_next(self):
        self.assertEqual(set(st(self.rd).values()), {"done"}, st(self.rd))
        self.assertEqual(it_ledger.current_block(self.rd), "fusion")
        out = ok("next", self.rd)
        self.assertIn("fusion block is complete", out)
        status = (self.rd / "STATUS.md").read_text()
        self.assertNotIn("## Literature search", status, "the search never ran on the ledger here")
        for u in it_ledger.FUSION:
            self.assertIn(f"| {u} | ✔ done", status)
        cav = json.loads((self.rd / "fusion_caveats.json").read_text())
        self.assertEqual(cav["schema"], "ideate-fusion-caveats/1")
        self.assertEqual([c["code"] for c in cav["must_disclose"]], ["questions-short"])

    def test_done_records_inputs_outputs_counts(self):
        evs = it_ledger._events(self.rd)
        for u in it_ledger.FUSION:
            d = [e for e in evs if e["unit"] == u and e["ev"] == "done"][-1]
            self.assertEqual(set(d["inputs"]), {it_ledger.spec_id(s) for s in it_ledger.io(u)["reads"]}, u)
            self.assertEqual(set(d["outputs"]), {it_ledger.spec_id(s) for s in it_ledger.io(u)["owns"]}, u)
            self.assertTrue(d["counts"] and "error" not in d["counts"], u)
            self.assertTrue(it_ledger.status_line(u, d["counts"]), u)
        b35 = [e for e in evs if e["unit"] == "B3.5" and e["ev"] == "done"][-1]
        self.assertEqual(b35["degraded"], ["questions-short"])

    def test_unchanged_rerun_keeps_downstream(self):
        rd = self.copy()
        lens = json.loads((rd / "lens.json").read_text())
        (rd.parent / "lens_in.json").write_text(json.dumps({k: lens[k] for k in ("persona", "on_coords", "own_data")}))
        gaps = json.loads((rd / it_collide.GAPS).read_text())
        (rd.parent / "gaps_in.json").write_text(json.dumps({k: v for k, v in gaps.items()
                                                            if k not in ("ranked", "composites", "retired", "at")}))
        ok("lens-set", rd, rd.parent / "lens_in.json")
        ok("collide-candidates", rd)
        ok("collide-plan", rd)
        ok("gaps-set", rd, rd.parent / "gaps_in.json")
        ok("questions-index", rd)
        self.assertEqual(set(st(rd).values()), {"done"}, st(rd))

    def test_revision_makes_downstream_stale(self):
        rd = self.copy()
        coords = json.loads((A7X / "coords.json").read_text())
        uid = next(iter(coords))
        coords[uid]["axes"]["split"] = "unstated"                 # was split:trial-kfold
        (rd.parent / "coords.json").write_text(json.dumps(coords))
        ok("align-coords", rd, "--apply", rd.parent / "coords.json")
        s = it_ledger.states(rd, "fusion")
        self.assertEqual(s["A7.A2"]["state"], "done")
        self.assertEqual(s["A7.D"]["state"], "done", "upstream untouched")
        self.assertEqual(s["A7.X1"]["state"], "stale")
        self.assertIn("alignment.json part=coords", s["A7.X1"]["why"])
        self.assertEqual(s["B1"]["state"], "done", "the lens reads the vocabulary, not the coordinates")
        self.assertEqual(s["F.9"]["state"], "stale")
        self.assertEqual(it_ledger.next_unit(rd, "fusion")[0], "A7.A3")

    def test_unit_done_pending_when_checks_fail(self):
        rd = self.copy()
        p = rd / "step6_sota_review.md"
        p.write_text(p.read_text().replace("## Theme", "## Topic"))
        code, out = run("unit-done", rd, "B2")
        self.assertEqual(code, 1, out)
        s = it_ledger.unit_state(rd, "B2")
        self.assertEqual(s["state"], "waiting")
        self.assertIn("J08", s["why"])

    def test_write_outside_declared_files_fails(self):
        rd = self.copy()
        ok("unit-begin", rd, "A7.R3")
        p = rd / it_collide.GAPS
        p.write_text(p.read_text().replace("Expert artifact labels", "Expert labels"))
        run("unit-done", rd, "A7.R3")
        s = it_ledger.unit_state(rd, "A7.R3")
        self.assertEqual(s["state"], "failed")
        self.assertIn("step7_gaps.json", s["why"])

    def test_write_to_another_units_part_fails(self):
        rd = self.copy()
        ok("unit-begin", rd, "A7.R1")              # R1 owns the findings Points of knowledge_cards.json, not the Planes
        p = rd / "knowledge_cards.json"
        cards = json.loads(p.read_text())
        cards["planes"][0]["name"] = "renamed by the wrong Unit"
        p.write_text(json.dumps(cards))
        run("unit-done", rd, "A7.R1")
        s = it_ledger.unit_state(rd, "A7.R1")
        self.assertEqual(s["state"], "failed")
        self.assertIn("knowledge_cards.json part=planes", s["why"])

    def test_search_block_counts_once_on_the_ledger(self):
        rd = self.copy()
        self.assertEqual(it_ledger.unit_state(rd, "A7.D")["state"], "done", "the search ran before the ledger")
        it_ledger.begin(rd, "A4.b")
        s = it_ledger.unit_state(rd, "A7.D")
        self.assertEqual((s["state"], s["why"]), ("stale", "upstream A4.b is running"))

    def test_current_block_before_fusion(self):
        rd = self.copy()
        shutil.rmtree(rd / "knowledge" / "decon")
        (rd / it_ledger.LEDGER).unlink()
        self.assertEqual(it_ledger.current_block(rd), "search")
        self.assertIn("next: A1.p", ok("next", rd))

    def test_adopt_a_topic_fused_before_the_ledger(self):
        rd = self.copy()
        (rd / it_ledger.LEDGER).unlink()
        self.assertEqual(set(st(rd).values()), {"todo"})
        ok("adopt", rd)
        self.assertEqual(set(st(rd).values()), {"done"}, st(rd))
        self.assertEqual(len([e for e in it_ledger._events(rd) if e["ev"] == "adopt"]), len(it_ledger.FUSION))

    def test_adopt_stops_at_the_first_failing_unit(self):
        rd = self.copy()
        (rd / it_ledger.LEDGER).unlink()
        p = rd / "step6_sota_review.md"
        p.write_text(p.read_text().replace("## Theme", "## Topic"))
        code, out = run("adopt", rd)
        self.assertEqual(code, 1, out)
        s = st(rd)
        self.assertEqual((s["A7.R3"], s["B2"], s["B3.5"]), ("done", "waiting", "todo"))

    def test_one_command_closing_two_units(self):
        """collide-merge opens A7.X2 and B3.c together; each may write its own part of collisions.jsonl."""
        rd = self.copy()
        it_ledger.begin(rd, "A7.X2")
        it_ledger.begin(rd, "B3.c")
        p = rd / it_collide.LOG
        recs = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
        recs.append({**recs[0], "collision_id": "X0099", "candidate": "Kx", "type": "same-coords"})
        p.write_text("".join(json.dumps(r) + "\n" for r in recs))
        self.assertEqual(it_ledger.violations(rd, "B3.c"), [], "A7.X2 is open: its part may change")
        self.assertEqual(it_ledger.violations(rd, "A7.X2"), [])

    def test_side_by_side_units(self):
        """B3.5 open while A7.R1 runs and closes: the questions B3.5 writes meanwhile are not A7.R1's violation."""
        rd = self.copy()
        ok("unit-begin", rd, "B3.5")
        ok("unit-begin", rd, "A7.R1")
        q = rd / "questions" / "Q_001.md"
        q.write_text(q.read_text() + "\n")
        self.assertEqual(it_ledger.violations(rd, "A7.R1"), [])
        ok("unit-done", rd, "A7.R1")
        self.assertEqual(it_ledger.unit_state(rd, "A7.R1")["state"], "done")

    def test_planes_in_the_matrix_keep_the_collisions_current(self):
        """A7.R2 re-runs build-methods; the rows gain a `theme`, which the collision Units do not read."""
        rd = self.copy()
        m = rd / "knowledge" / "methods_matrix.json"
        d = json.loads(m.read_text())
        for r in d["experiments"]:
            r["theme"] = "T9"
        d["generated_at"] = "2099-01-01"
        m.write_text(json.dumps(d))
        s = it_ledger.states(rd, "fusion")
        self.assertEqual((s["A7.X1"]["state"], s["A7.X2"]["state"]), ("done", "done"))

    def test_r1_attaches_collisions_to_a_concept_point(self):
        rd = self.copy()
        ok("unit-begin", rd, "A7.R1")
        p = rd / "knowledge_cards.json"
        cards = json.loads(p.read_text())
        pt = next(x for x in cards["points"] if x.get("origin") == "align")
        pt["collisions"] = ["X0003"]
        p.write_text(json.dumps(cards))
        self.assertEqual(it_ledger.violations(rd, "A7.R1"), [])
        ok("unit-done", rd, "A7.R1")
        self.assertEqual(it_ledger.unit_state(rd, "A7.A3")["state"], "done", "the concept Point itself did not change")

    def test_merge_units(self):
        rd = self.copy()
        ans = rd / it_collide.WORK / "answers"
        ans.mkdir(parents=True, exist_ok=True)
        self.assertEqual(it_collide.merge_units(rd), ["A7.X2"], "nothing new: the paper Unit by default")
        (ans / "lens_batch_001.json").write_text(json.dumps({"judgements": [{"candidate": "Knew", "relations": []}]}))
        self.assertEqual(it_collide.merge_units(rd), ["B3.c"])


class Trace(Fixture):
    def test_items(self):
        self.assertIn("B3", {s["unit"] for s in it_trace.trace(self.rd, "X0002")["steps"]})
        gap = it_trace.trace(self.rd, "GAP_001")
        self.assertIn("Q_001", " ".join(s["text"] for s in gap["steps"]))
        q = it_trace.trace(self.rd, "Q_001")
        self.assertEqual(q["steps"][0]["unit"], "B3")
        code, out = run("trace", self.rd, "X9999")
        self.assertEqual(code, 2, out)

    def test_paper_covers_the_block(self):
        units = set()
        for item in ("smithetal2020", "parketal2019", "X0001", "GAP_001", "Q_001"):
            tr = it_trace.trace(self.rd, item)
            units |= {s["unit"] for s in tr["steps"]}
            units |= {line.split("-> ")[1].split(":")[0] for line in tr["comments"]}
        missing = set(it_ledger.FUSION) - units
        self.assertEqual(missing, set(), "every fusion Unit is reachable from some item")


# ============================================================================================================ interrupt
class TestInterrupt(Fixture):
    def interrupt(self, unit: str, prepare, cmd):
        """prepare(rd) sets up a state in which cmd(rd) writes; each write is interrupted in turn."""
        ref = self.copy()
        prepare(ref)
        ok(*cmd(ref))
        want = owned(ref, unit)
        k = 0
        while True:
            rd = self.copy()
            prepare(rd)
            n0 = len(it_ledger._events(rd))
            code, out = run(*cmd(rd), fail_after=k)
            if "injected failure" not in out:
                self.assertEqual(code, 0, out)
                break
            evs = it_ledger._events(rd)[n0:]
            self.assertFalse([e for e in evs if e["unit"] == unit and e["ev"] == "done"], f"{unit} k={k}")
            self.assertEqual(it_ledger.unit_state(rd, unit)["state"], "failed", f"{unit} k={k}")
            owned(rd, unit)                       # every owned file still parses
            ok(*cmd(rd))
            self.assertEqual(owned(rd, unit), want, f"{unit} k={k}")
            self.assertEqual(it_ledger.unit_state(rd, unit)["state"], "done", f"{unit} k={k}")
            k += 1
        self.assertGreaterEqual(k, 1, f"{unit}: the command wrote nothing")

    def model_unit(self, unit: str, close):
        rd = self.copy()
        if unit in it_ledger.MODEL_UNITS:
            ok("unit-begin", rd, unit)
        else:                                    # a session that stopped inside the command's boundary
            it_ledger.begin(rd, unit)
        s = it_ledger.unit_state(rd, unit)
        self.assertEqual(s["state"], "running")
        self.assertEqual(it_ledger.next_unit(rd, "fusion")[0], unit)
        ok(*close(rd))
        self.assertEqual(it_ledger.unit_state(rd, unit)["state"], "done")

    def test_interrupt_a7d(self):
        def prepare(rd):
            for k in ("parketal2019", "leeetal2021"):
                (rd / "knowledge" / "decon" / f"{k}.json").unlink()
        self.interrupt("A7.D", prepare, lambda rd: ("decon-merge", rd))

    def test_interrupt_a7a1(self):
        self.interrupt("A7.A1", lambda rd: None, lambda rd: ("align-set", rd, A7A / "vocab.json", "--reason", "test"))

    def test_interrupt_a7a2(self):
        def prepare(rd):
            p = rd / "knowledge" / "alignment.json"
            al = json.loads(p.read_text())
            al["coords"].pop(next(iter(json.loads((A7X / "coords.json").read_text()))))
            p.write_text(json.dumps(al))
        self.interrupt("A7.A2", prepare, lambda rd: ("align-coords", rd, "--apply", A7X / "coords.json"))

    def test_interrupt_a7a3(self):
        self.model_unit("A7.A3", lambda rd: ("unit-done", rd, "A7.A3"))

    def test_interrupt_b1(self):
        def prepare(rd):
            lens = json.loads((rd / "lens.json").read_text())
            lens = {k: lens[k] for k in ("persona", "on_coords", "own_data")}
            lens["persona"] = {**lens["persona"], "note": "revised for the test"}
            (rd.parent / "lens_in.json").write_text(json.dumps(lens))
        self.interrupt("B1", prepare, lambda rd: ("lens-set", rd, rd.parent / "lens_in.json", "--reason", "test"))

    def test_interrupt_a7x1(self):
        self.interrupt("A7.X1", lambda rd: (rd / it_collide.CANDS).unlink(), lambda rd: ("collide-candidates", rd))

    def test_interrupt_a7x2(self):
        def prepare(rd):
            (rd / it_collide.LOG).unlink()
            ok("collide-plan", rd)
            batch = json.loads((rd / it_collide.WORK / "batch_001.json").read_text())
            by_type = json.loads((A7X / "judgements_by_type.json").read_text())
            ans = {"model": "claude-opus-5-5",
                   "judgements": [{"candidate": c["id"], "relations": by_type[c["type"]]} for c in batch["candidates"]]}
            (rd / it_collide.WORK / "answers" / "batch_001.json").write_text(json.dumps(ans))
        self.interrupt("A7.X2", prepare, lambda rd: ("collide-merge", rd))

    def test_interrupt_b3c(self):
        self.model_unit("B3.c", lambda rd: ("collide-plan", rd, "--lens"))

    def test_interrupt_b3(self):
        def prepare(rd):
            (rd / it_collide.GAPS).unlink()
            (rd / it_collide.GAPS_MD).unlink()
        self.interrupt("B3", prepare, lambda rd: ("gaps-set", rd, A7X / "gaps.json"))

    def test_interrupt_a7r1(self):
        self.model_unit("A7.R1", lambda rd: ("unit-done", rd, "A7.R1"))

    def test_interrupt_a7r2(self):
        self.model_unit("A7.R2", lambda rd: ("unit-done", rd, "A7.R2"))

    def test_interrupt_a7r3(self):
        self.model_unit("A7.R3", lambda rd: ("unit-done", rd, "A7.R3"))

    def test_interrupt_b2(self):
        self.model_unit("B2", lambda rd: ("unit-done", rd, "B2"))

    def test_interrupt_b35(self):
        self.model_unit("B3.5", lambda rd: ("unit-done", rd, "B3.5"))

    def test_interrupt_f9(self):
        def prepare(rd):
            (rd / "questions" / "index.json").unlink()
            (rd / "knowledge" / "fusion_map.md").unlink()
        self.interrupt("F.9", prepare, lambda rd: ("questions-index", rd))


if __name__ == "__main__":
    unittest.main(verbosity=1)
