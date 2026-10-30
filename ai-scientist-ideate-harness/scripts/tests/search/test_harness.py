#!/usr/bin/env python3
"""The test bench of the literature search (armour condition 9): offline replay of every networked Unit, and an
interrupt at each Unit's writes.

Replay: a networked Unit runs once on fakes behind the real recording path (it_common.recorded / http_json), then once
more on a copy of the same state with IDEATE_REPLAY=1 and fakes that refuse to be called - the outputs must match.
Interrupt: IDEATE_FAIL_AFTER_WRITES=k stops the k+1-th write between its temporary file and the rename. Afterwards the
ledger holds no `done` for the Unit, every file it owns still parses, and a second run gives what an uninterrupted
run gives.

  python3 .claude/skills/ai-scientist-ideate/scripts/tests/search/test_harness.py
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

SCRIPTS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import it_common  # noqa: E402
import it_export  # noqa: E402
import it_frame  # noqa: E402
import it_ledger  # noqa: E402
import it_screen  # noqa: E402
import it_search  # noqa: E402
import it_snowball  # noqa: E402
from test_a1_frame import FIX as A1FIX, FakeProbeServer, run as run_cli  # noqa: E402
from test_a2_search import GOOD_VERDICTS, FakeServer, fake_fetch as a2_fetch  # noqa: E402
from test_a3_screen import FakeVenues, fake_subagent  # noqa: E402
from test_a4_export import crossref_fetch  # noqa: E402
from test_a5_snowball import FakeS2, graph_fetch  # noqa: E402

VOLATILE = {"at", "search_timestamp", "written_at", "timestamp", "basis", "raw_sha", "sha", "strategy_sha", "history",
            "screening_timestamp"}       # the archived engine's stamp of the shortlist (it_legacy), set at its first write
MAIL = "x@example.com"
STAMP = __import__("re").compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d")


async def nosleep(_):
    return None


def strip(x):
    if isinstance(x, dict):
        return {k: strip(v) for k, v in x.items() if k not in VOLATILE}
    if isinstance(x, list):
        return [strip(v) for v in x]
    return x


def outputs(rd: Path, unit: str) -> dict:
    """What the Unit owns, comparable across runs (timestamps and basis hashes removed)."""
    out = {}
    cfg = json.loads((rd / "step0_session_config.json").read_text()) if (rd / "step0_session_config.json").exists() else {}
    for spec in it_ledger.io(unit)["owns"]:
        if "step0" in spec:              # a wall-clock key (A1.p's `timestamp`) is volatile at the top level too
            out[spec["step0"]] = None if spec["step0"] in VOLATILE else strip(cfg.get(spec["step0"]))
        elif "glob" in spec:
            out[spec["glob"]] = sorted(json.dumps(strip(json.loads(f.read_text())), sort_keys=True) for f in rd.glob(spec["glob"]))
        else:
            f = rd / spec["file"]
            if not f.exists():
                out[spec["file"]] = None
            elif f.suffix == ".json":
                out[spec["file"]] = strip(json.loads(f.read_text()))
            elif f.suffix == ".jsonl":
                out[spec["file"]] = [strip(json.loads(l)) for l in f.read_text().splitlines() if l.strip()]
            else:
                out[spec["file"]] = [STAMP.sub("<t>", l) for l in f.read_text().splitlines()
                                     if not l.startswith(("% ", "<!--")) and "Generated" not in l]
    return out


def ns(rd, **kw):
    return SimpleNamespace(research_dir=str(rd), **kw)


def cfg_of(rd):
    return json.loads((Path(rd) / "step0_session_config.json").read_text())


# ------------------------------------------------------------------------------------------- fakes behind the recorder
class Recorded:
    """A fake server behind the same record / replay path the bridge's Server uses."""

    def __init__(self, fake, rd):
        self.fake, self.rd = fake, rd

    async def call(self, tool, params):
        return await it_common.recorded_async(self.rd, "scholar", {"tool": tool, "params": params},
                                              lambda: self.fake.call(tool, params))


class Refuse:
    async def call(self, tool, params):
        raise AssertionError(f"a replayed run called the server ({tool})")


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def urlopen_from(fake):
    def urlopen(req, timeout=30):
        return Resp(json.dumps(fake(req.full_url)).encode())
    return urlopen


def refuse_urlopen(req, timeout=30):
    raise AssertionError(f"a replayed run went to the network: {req.full_url[:80]}")


# ================================================================================================= the stage states
def stage_states(tmp: Path) -> dict:
    """One research-dir copy after each step of the fixture topic, in run order (name -> topic_research path)."""
    st = {}
    work = tmp / "work"
    work.mkdir()
    shutil.copy(A1FIX / "good" / "topic.md", work / "topic.md")
    rd = work / "topic_research"
    rd.mkdir()

    def keep(name):
        d = tmp / name
        shutil.copytree(work, d)
        st[name] = d / "topic_research"
    keep("empty")
    assert run_cli("frame", "set-protocol", rd, A1FIX / "good" / "protocol.json")[0] == 0
    keep("protocol")
    assert run_cli("frame", "set-strategy", rd, A1FIX / "good" / "strategy.json")[0] == 0
    keep("strategy")
    asyncio.run(it_frame.run_probe(FakeProbeServer(), cfg_of(rd), rd, MAIL, fetch=lambda u, r=None: {"meta": {"count": 2140}},
                                   sleep=nosleep))
    keep("probed")
    assert run_cli("frame", "set-context", rd, A1FIX / "good" / "context.json")[0] == 0
    assert run_cli("frame", "eval-brief", rd)[0] == 0
    keep("briefed")
    assert run_cli("frame", "set-evaluation", rd, A1FIX / "good" / "evaluation.json")[0] == 0
    keep("framed")
    asyncio.run(it_search.run_search(FakeServer(), cfg_of(rd), rd, sleep=nosleep))
    keep("searched")
    asyncio.run(it_search.run_merge(FakeServer(), cfg_of(rd), rd, MAIL, fetch=a2_fetch, embedder=None))
    keep("merged")
    v = tmp / "verdicts.json"
    v.write_text(json.dumps(GOOD_VERDICTS))
    assert run_cli("search-check", rd)[0] == 0
    keep("signals")
    assert run_cli("relevance-set", rd, v)[0] == 0
    keep("judged")
    asyncio.run(it_screen.run_bibliometrics(FakeVenues(), cfg_of(rd), rd, MAIL, fetch=graph_fetch))
    keep("measured")
    assert run_cli("screen-gate", rd)[0] == 0
    keep("gated")
    assert run_cli("screen-plan", rd, "--size", "4")[0] == 0
    fan = rd / "_state/fanout/A3"
    for f in sorted(fan.glob("batch_*.in.json")):
        b = json.loads(f.read_text())
        (fan / b["out"]).write_text(json.dumps(fake_subagent(b)))
    assert run_cli("screen-merge", rd)[0] == 0
    keep("scored")
    assert run_cli("screen-build", rd, rd / "screening_scores.json")[0] == 0
    keep("screened")
    asyncio.run(it_snowball.run_snowball(FakeS2(), cfg_of(rd), rd, MAIL, fetch=graph_fetch, embedder=None))
    keep("snowballed")
    asyncio.run(it_screen.run_bibliometrics(FakeVenues(), cfg_of(rd), rd, MAIL, fetch=graph_fetch))
    assert run_cli("screen-gate", rd)[0] == 0
    assert run_cli("screen-plan", rd, "--size", "4")[0] == 0
    for f in sorted(fan.glob("batch_*.in.json")):
        b = json.loads(f.read_text())
        if not (fan / b["out"]).exists():
            (fan / b["out"]).write_text(json.dumps(fake_subagent(b)))
    assert run_cli("screen-merge", rd)[0] == 0
    assert run_cli("screen-build", rd, rd / "screening_scores.json")[0] == 0
    keep("rescreened")
    assert run_cli("export", rd)[0] == 0
    keep("keyed")
    it_export.build_bibliography(cfg_of(rd), rd, MAIL, fetch=crossref_fetch)
    keep("done")
    return st


# Each Unit: (state it starts from, how to run it in-process). `live` runs on fakes behind the recorder (network Units).
UNITS = {
    "A1.p": ("empty", lambda rd: it_frame.cmd_set_protocol(ns(rd, input_json=str(A1FIX / "good" / "protocol.json"), note=""))),
    "A1.q": ("protocol", lambda rd: (it_frame.cmd_set_strategy(ns(rd, input_json=str(A1FIX / "good" / "strategy.json"), note="")),
                                     asyncio.run(it_frame.run_probe(Recorded(FakeProbeServer(), rd), cfg_of(rd), rd, MAIL,
                                                                    fetch=it_common.http_json, sleep=nosleep)))),
    "A1.v": ("probed", lambda rd: it_frame.cmd_set_context(ns(rd, input_json=str(A1FIX / "good" / "context.json"), note=""))),
    "A1.e": ("briefed", lambda rd: it_frame.cmd_set_evaluation(ns(rd, input_json=str(A1FIX / "good" / "evaluation.json"), note=""))),
    "A2.s": ("framed", lambda rd: asyncio.run(it_search.run_search(Recorded(FakeServer(), rd), cfg_of(rd), rd, sleep=nosleep))),
    "A2.m": ("searched", lambda rd: asyncio.run(it_search.run_merge(Recorded(FakeServer(), rd), cfg_of(rd), rd, MAIL,
                                                                    fetch=it_common.http_json, embedder=None))),
    "A2.c": ("signals", lambda rd: it_search.cmd_relevance_set(ns(rd, input_json=str(Path(rd).parent.parent / "verdicts.json")))),
    "A3.b": ("judged", lambda rd: asyncio.run(it_screen.run_bibliometrics(Recorded(FakeVenues(), rd), cfg_of(rd), rd, MAIL,
                                                                          fetch=it_common.http_json))),
    "A3.g": ("measured", lambda rd: it_screen.cmd_gate(ns(rd))),
    "A3": ("scored", lambda rd: it_screen.cmd_build(ns(rd, scores_json=str(Path(rd) / "screening_scores.json")))),
    "A5": ("screened", lambda rd: asyncio.run(it_snowball.run_snowball(Recorded(FakeS2(), rd), cfg_of(rd), rd, MAIL,
                                                                       fetch=it_common.http_json, embedder=None))),
    "A4.k": ("rescreened", lambda rd: it_export.cmd_export(ns(rd, no_snowball=None))),
    "A4.b": ("keyed", lambda rd: it_export.build_bibliography(cfg_of(rd), rd, MAIL, fetch=it_common.http_json)),
}
NETWORK = {"A1.q": lambda u: {"meta": {"count": 2140}}, "A2.m": a2_fetch, "A3.b": graph_fetch, "A5": graph_fetch,
           "A4.b": crossref_fetch, "A2.s": None}


class Bench(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.states = stage_states(cls.tmp)
        cls.n = 0

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def setUp(self):
        self._open = it_common._ur.urlopen
        self._env = {k: os.environ.get(k) for k in ("IDEATE_REPLAY", "IDEATE_FAIL_AFTER_WRITES")}

    def tearDown(self):
        it_common._ur.urlopen = self._open
        for k, v in self._env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        it_common._REPLAY_SEEN.clear()

    def copy(self, state: str) -> Path:
        type(self).n += 1
        d = self.tmp / f"case{self.n}"
        shutil.copytree(self.states[state].parent, d)
        return d / "topic_research"

    def run_unit(self, unit, rd, fake_fetch=None):
        start, fn = UNITS[unit]
        it_common._ur.urlopen = urlopen_from(fake_fetch) if fake_fetch else self._open
        try:
            fn(rd)
        finally:
            it_common._ur.urlopen = self._open

    def state(self, rd, unit):
        return it_ledger.unit_state(rd, unit)["state"]


class TestReplay(Bench):
    """Every networked Unit gives the same outputs when replayed from its recordings, without any network."""

    def check_replay(self, unit):
        start = UNITS[unit][0]
        live = self.copy(start)
        self.run_unit(unit, live, NETWORK.get(unit))
        self.assertEqual(self.state(live, unit), "done")
        rep = self.copy(start)
        shutil.rmtree(rep / "_state" / "net", ignore_errors=True)
        shutil.copytree(live / "_state" / "net", rep / "_state" / "net")
        os.environ["IDEATE_REPLAY"] = "1"
        it_common._REPLAY_SEEN.clear()
        it_common._ur.urlopen = refuse_urlopen
        start_, fn = UNITS[unit]
        orig = Recorded.call

        async def replay_only(self_, tool, params):            # the fake must never be reached
            self_.fake = Refuse()
            return await orig(self_, tool, params)
        Recorded.call = replay_only
        try:
            fn(rep)
        finally:
            Recorded.call = orig
            os.environ.pop("IDEATE_REPLAY", None)
        self.assertEqual(self.state(rep, unit), "done")
        self.assertEqual(outputs(rep, unit), outputs(live, unit))

    def test_replay_a1q_probe(self):
        self.check_replay("A1.q")

    def test_replay_a2s(self):
        self.check_replay("A2.s")

    def test_replay_a2m(self):
        self.check_replay("A2.m")

    def test_replay_a3b(self):
        self.check_replay("A3.b")

    def test_replay_a5(self):
        self.check_replay("A5")

    def test_replay_a4b(self):
        self.check_replay("A4.b")


class TestInterrupt(Bench):
    """An interrupted Unit leaves no `done`, no half-written file, and a rerun gives the uninterrupted result."""

    def check_interrupt(self, unit, ks=(0, 1)):
        start = UNITS[unit][0]
        ref = self.copy(start)
        self.run_unit(unit, ref, NETWORK.get(unit))
        self.assertEqual(self.state(ref, unit), "done", unit)
        hit = 0
        for k in ks:
            rd = self.copy(start)
            os.environ["IDEATE_FAIL_AFTER_WRITES"] = str(k)
            it_common._WRITES[0] = 0
            try:
                self.run_unit(unit, rd, NETWORK.get(unit))
                stopped = False
            except (it_common.InjectedFailure, SystemExit):
                stopped = True
            finally:
                os.environ.pop("IDEATE_FAIL_AFTER_WRITES", None)
            if not stopped:                                       # the Unit wrote fewer than k+1 files
                continue
            hit += 1
            self.assertIn(self.state(rd, unit), ("failed", "running"), f"{unit} k={k}")
            for f in list(rd.rglob("*.json")):
                if "_state/net" not in str(f) and not f.name.endswith(".tmp"):
                    json.loads(f.read_text())                    # every file parses: nothing half-written
            self.run_unit(unit, rd, NETWORK.get(unit))
            self.assertEqual(self.state(rd, unit), "done", f"{unit} k={k}")
            self.assertEqual(outputs(rd, unit), outputs(ref, unit), f"{unit} k={k}")
        self.assertGreater(hit, 0, f"{unit}: no write was interrupted")

    def test_interrupt_a1p(self):
        self.check_interrupt("A1.p")

    def test_interrupt_a1q(self):
        self.check_interrupt("A1.q")

    def test_interrupt_a1v(self):
        self.check_interrupt("A1.v")

    def test_interrupt_a1e(self):
        self.check_interrupt("A1.e")

    def test_interrupt_a2s(self):
        self.check_interrupt("A2.s")

    def test_interrupt_a2m(self):
        self.check_interrupt("A2.m")

    def test_interrupt_a2c(self):
        self.check_interrupt("A2.c")

    def test_interrupt_a3b(self):
        self.check_interrupt("A3.b")

    def test_interrupt_a3g(self):
        self.check_interrupt("A3.g")

    def test_interrupt_a3(self):
        self.check_interrupt("A3")

    def test_interrupt_a5(self):
        self.check_interrupt("A5")

    def test_interrupt_a4k(self):
        self.check_interrupt("A4.k")

    def test_interrupt_a4b(self):
        self.check_interrupt("A4.b")


if __name__ == "__main__":
    unittest.main(verbosity=2)
